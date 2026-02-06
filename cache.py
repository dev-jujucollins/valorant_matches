# Caching module for match data with TTL support.
import hashlib
import json
import logging
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from config import CACHE_DIR, CACHE_ENABLED, CACHE_TTL_SECONDS

logger = logging.getLogger("valorant_matches")

# Default in-memory cache size (number of entries)
MEMORY_CACHE_SIZE = 100


class MatchCache:
    """Two-tier cache with in-memory LRU and file-based persistence."""

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        enabled: bool = CACHE_ENABLED,
        memory_size: int = MEMORY_CACHE_SIZE,
    ):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._memory_size = memory_size

        # Thread-safe in-memory LRU cache: {key: (timestamp, data)}
        self._memory_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._memory_lock = threading.Lock()

        if self.enabled:
            self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _memory_get(self, key: str) -> Any | None:
        """Get from memory cache (thread-safe). Returns None if not found or expired."""
        with self._memory_lock:
            if key not in self._memory_cache:
                return None
            timestamp, data = self._memory_cache[key]
            if time.time() - timestamp > self.ttl_seconds:
                del self._memory_cache[key]
                return None
            # Move to end for LRU behavior
            self._memory_cache.move_to_end(key)
            return data

    def _memory_set(self, key: str, data: Any) -> None:
        """Set in memory cache (thread-safe) with LRU eviction."""
        with self._memory_lock:
            # Remove oldest if at capacity
            while len(self._memory_cache) >= self._memory_size:
                self._memory_cache.popitem(last=False)
            self._memory_cache[key] = (time.time(), data)

    def _memory_delete(self, key: str) -> None:
        """Delete from memory cache (thread-safe)."""
        with self._memory_lock:
            self._memory_cache.pop(key, None)

    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from URL using SHA-256."""
        return hashlib.sha256(url.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{key}.json"

    def get(self, url: str) -> Any | None:
        """Get cached data for a URL. Checks memory first, then disk."""
        if not self.enabled:
            return None

        key = self._get_cache_key(url)

        # Check memory cache first (fast path)
        data = self._memory_get(key)
        if data is not None:
            logger.debug(f"Memory cache hit for {url}")
            return data

        # Fall back to disk cache
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)

            # Check if cache has expired
            if time.time() - cached["timestamp"] > self.ttl_seconds:
                logger.debug(f"Cache expired for {url}")
                cache_path.unlink(missing_ok=True)
                return None

            # Promote to memory cache for faster subsequent access
            self._memory_set(key, cached["data"])
            logger.debug(f"Disk cache hit for {url}")
            return cached["data"]

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to read cache for {url}: {e}")
            cache_path.unlink(missing_ok=True)
            return None

    def set(self, url: str, data: Any) -> None:
        """Cache data for a URL in both memory and disk."""
        if not self.enabled:
            return

        key = self._get_cache_key(url)

        # Store in memory cache (fast access)
        self._memory_set(key, data)

        # Persist to disk atomically (write to temp file, then rename)
        cache_path = self._get_cache_path(key)
        try:
            cache_entry = {
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
        """Invalidate (remove) cached data for a URL. Returns True if entry was removed."""
        if not self.enabled:
            return False

        key = self._get_cache_key(url)

        # Remove from memory cache
        self._memory_delete(key)

        # Remove from disk
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            try:
                cache_path.unlink()
                logger.debug(f"Invalidated cache for {url}")
                return True
            except OSError as e:
                logger.warning(f"Failed to invalidate cache for {url}: {e}")
                return False
        return False

    def clear(self) -> int:
        """Clear all cached data (memory and disk). Returns number of entries cleared."""
        # Clear memory cache
        with self._memory_lock:
            memory_count = len(self._memory_cache)
            self._memory_cache.clear()

        if not self.cache_dir.exists():
            return memory_count

        disk_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                disk_count += 1
            except OSError:
                pass

        logger.info(f"Cleared {disk_count} disk / {memory_count} memory cache entries")
        return disk_count

    def clear_expired(self) -> int:
        """Clear only expired cache entries. Returns number of entries cleared."""
        if not self.cache_dir.exists():
            return 0

        count = 0
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cached = json.load(f)

                if current_time - cached["timestamp"] > self.ttl_seconds:
                    cache_file.unlink()
                    count += 1

            except (json.JSONDecodeError, KeyError, OSError):
                cache_file.unlink(missing_ok=True)
                count += 1

        if count > 0:
            logger.info(f"Cleared {count} expired cache entries")
        return count

    def get_stats(self) -> dict:
        """Get cache statistics (memory and disk)."""
        # Memory cache stats
        with self._memory_lock:
            memory_entries = len(self._memory_cache)

        if not self.cache_dir.exists():
            return {
                "memory_entries": memory_entries,
                "disk_total": 0,
                "disk_valid": 0,
                "disk_expired": 0,
            }

        disk_total = 0
        disk_valid = 0
        disk_expired = 0
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            disk_total += 1
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cached = json.load(f)

                if current_time - cached["timestamp"] > self.ttl_seconds:
                    disk_expired += 1
                else:
                    disk_valid += 1
            except (json.JSONDecodeError, KeyError, OSError):
                disk_expired += 1

        return {
            "memory_entries": memory_entries,
            "disk_total": disk_total,
            "disk_valid": disk_valid,
            "disk_expired": disk_expired,
        }
