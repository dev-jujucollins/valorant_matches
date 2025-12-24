# Caching module for match data with TTL support.
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from config import CACHE_DIR, CACHE_ENABLED, CACHE_TTL_SECONDS

logger = logging.getLogger("valorant_matches")


class MatchCache:
    """Simple file-based cache with TTL support for match data."""

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        enabled: bool = CACHE_ENABLED,
    ):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled

        if self.enabled:
            self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{key}.json"

    def get(self, url: str) -> Optional[Any]:
        """Get cached data for a URL if it exists and is not expired."""
        if not self.enabled:
            return None

        key = self._get_cache_key(url)
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)

            # Check if cache has expired
            if time.time() - cached["timestamp"] > self.ttl_seconds:
                logger.debug(f"Cache expired for {url}")
                cache_path.unlink(missing_ok=True)
                return None

            logger.debug(f"Cache hit for {url}")
            return cached["data"]

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to read cache for {url}: {e}")
            cache_path.unlink(missing_ok=True)
            return None

    def set(self, url: str, data: Any) -> None:
        """Cache data for a URL."""
        if not self.enabled:
            return

        key = self._get_cache_key(url)
        cache_path = self._get_cache_path(key)

        try:
            cache_entry = {
                "url": url,
                "timestamp": time.time(),
                "data": data,
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_entry, f, ensure_ascii=False, indent=2)
            logger.debug(f"Cached data for {url}")

        except OSError as e:
            logger.warning(f"Failed to write cache for {url}: {e}")

    def clear(self) -> int:
        """Clear all cached data. Returns number of entries cleared."""
        if not self.cache_dir.exists():
            return 0

        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass

        logger.info(f"Cleared {count} cache entries")
        return count

    def clear_expired(self) -> int:
        """Clear only expired cache entries. Returns number of entries cleared."""
        if not self.cache_dir.exists():
            return 0

        count = 0
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
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
        """Get cache statistics."""
        if not self.cache_dir.exists():
            return {"total_entries": 0, "valid_entries": 0, "expired_entries": 0}

        total = 0
        valid = 0
        expired = 0
        current_time = time.time()

        for cache_file in self.cache_dir.glob("*.json"):
            total += 1
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)

                if current_time - cached["timestamp"] > self.ttl_seconds:
                    expired += 1
                else:
                    valid += 1
            except (json.JSONDecodeError, KeyError, OSError):
                expired += 1

        return {
            "total_entries": total,
            "valid_entries": valid,
            "expired_entries": expired,
        }
