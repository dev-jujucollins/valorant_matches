# Two-tier (memory + disk) cache for completed match data.
import hashlib
import json
import logging
import math
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from valorant_matches.config import CACHE_DIR, CACHE_ENABLED, CACHE_TTL_SECONDS

logger = logging.getLogger("valorant_matches")

# Default in-memory cache size (number of entries)
MEMORY_CACHE_SIZE = 100

# Bump when the cached Match payload shape changes; mismatched entries are
# discarded instead of failing to rebuild a Match.
CACHE_SCHEMA_VERSION = 2


class MatchCache:
    """Two-tier cache with an in-memory LRU and file-based persistence.

    The cache is used from a single asyncio thread, so it takes no locks.
    """

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        enabled: bool = CACHE_ENABLED,
        memory_size: int = MEMORY_CACHE_SIZE,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._memory_size = memory_size

        # In-memory LRU cache: {key: (timestamp, data)}, oldest first
        self._memory_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = (
            OrderedDict()
        )

        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _memory_get(self, key: str) -> dict[str, Any] | None:
        """Get from memory, or None when missing or expired."""
        entry = self._memory_cache.get(key)
        if entry is None:
            return None
        timestamp, data = entry
        if time.time() - timestamp > self.ttl_seconds:
            del self._memory_cache[key]
            return None
        self._memory_cache.move_to_end(key)
        return data

    def _memory_set(self, key: str, data: dict[str, Any]) -> None:
        """Store in memory, evicting the least recently used entry when full."""
        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
        else:
            while len(self._memory_cache) >= self._memory_size:
                self._memory_cache.popitem(last=False)
        self._memory_cache[key] = (time.time(), data)

    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from a URL using SHA-256."""
        return hashlib.sha256(url.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{key}.json"

    def get(self, url: str) -> dict[str, Any] | None:
        """Get cached data for a URL, checking memory before disk.

        Args:
            url: Match page URL.

        Returns:
            The cached data, or None on a miss, expiry, or damaged entry.
        """
        if not self.enabled:
            return None

        key = self._get_cache_key(url)

        data = self._memory_get(key)
        if data is not None:
            logger.debug(f"Memory cache hit for {url}")
            return data

        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)

            if not isinstance(cached, dict):
                raise ValueError("cache entry must be an object")
            if cached.get("version") != CACHE_SCHEMA_VERSION:
                logger.debug(f"Cache schema mismatch for {url}, discarding")
                cache_path.unlink(missing_ok=True)
                return None

            timestamp = cached["timestamp"]
            if (
                not isinstance(timestamp, (int, float))
                or isinstance(timestamp, bool)
                or not math.isfinite(timestamp)
            ):
                raise ValueError("cache timestamp is invalid")
            if time.time() - timestamp > self.ttl_seconds:
                logger.debug(f"Cache expired for {url}")
                cache_path.unlink(missing_ok=True)
                return None

            data = cached["data"]
            if not isinstance(data, dict):
                raise ValueError("cache data must be an object")
            # Promote to memory cache for faster subsequent access
            self._memory_set(key, data)
            logger.debug(f"Disk cache hit for {url}")
            return data

        except (json.JSONDecodeError, KeyError, OSError, ValueError) as e:
            logger.warning(f"Failed to read cache for {url}: {e}")
            cache_path.unlink(missing_ok=True)
            return None

    def set(self, url: str, data: dict[str, Any]) -> None:
        """Cache data for a URL in memory and, atomically, on disk.

        Args:
            url: Match page URL.
            data: JSON-serializable match data.
        """
        if not self.enabled:
            return

        key = self._get_cache_key(url)
        self._memory_set(key, data)

        # Write to a temp file, then rename, so readers never see partial JSON.
        cache_path = self._get_cache_path(key)
        try:
            cache_entry = {
                "version": CACHE_SCHEMA_VERSION,
                "url": url,
                "timestamp": time.time(),
                "data": data,
            }
            fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    json.dump(cache_entry, f, ensure_ascii=False, indent=2)
                Path(tmp_path).replace(cache_path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
            logger.debug(f"Cached data for {url}")

        except OSError as e:
            logger.warning(f"Failed to write cache for {url}: {e}")

    def invalidate(self, url: str) -> bool:
        """Remove cached data for a URL.

        Args:
            url: Match page URL.

        Returns:
            True when a disk entry was removed.
        """
        if not self.enabled:
            return False

        key = self._get_cache_key(url)
        self._memory_cache.pop(key, None)

        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return False
        try:
            cache_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to invalidate cache for {url}: {e}")
            return False
        logger.debug(f"Invalidated cache for {url}")
        return True

    def clear(self) -> int:
        """Clear all cached data in memory and on disk.

        Returns:
            Number of disk entries removed.
        """
        memory_count = len(self._memory_cache)
        self._memory_cache.clear()

        if not self.cache_dir.exists():
            return 0

        disk_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                disk_count += 1
            except OSError as e:
                logger.warning(f"Failed to remove cache file {cache_file}: {e}")

        logger.info(f"Cleared {disk_count} disk / {memory_count} memory cache entries")
        return disk_count
