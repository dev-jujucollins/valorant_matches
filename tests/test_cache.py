# Tests for the cache module.
import time

import pytest

from cache import MatchCache


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory for testing."""
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def cache(temp_cache_dir):
    """Create a MatchCache instance with a temporary directory."""
    return MatchCache(cache_dir=temp_cache_dir, ttl_seconds=60, enabled=True)


@pytest.fixture
def disabled_cache(temp_cache_dir):
    """Create a disabled MatchCache instance."""
    return MatchCache(cache_dir=temp_cache_dir, ttl_seconds=60, enabled=False)


class TestMatchCache:
    def test_cache_set_and_get(self, cache):
        """Test basic set and get operations."""
        url = "https://vlr.gg/match/12345"
        data = {"team1": "Sentinels", "team2": "Cloud9", "score": "2 - 1"}

        cache.set(url, data)
        result = cache.get(url)

        assert result == data

    def test_cache_miss(self, cache):
        """Test that cache returns None for missing URLs."""
        result = cache.get("https://vlr.gg/match/nonexistent")
        assert result is None

    def test_cache_expiration(self, temp_cache_dir):
        """Test that expired cache entries are not returned."""
        cache = MatchCache(cache_dir=temp_cache_dir, ttl_seconds=1, enabled=True)
        url = "https://vlr.gg/match/12345"
        data = {"team1": "Sentinels", "team2": "Cloud9"}

        cache.set(url, data)

        # Wait for cache to expire
        time.sleep(1.1)

        result = cache.get(url)
        assert result is None

    def test_cache_disabled(self, disabled_cache):
        """Test that disabled cache returns None and doesn't store."""
        url = "https://vlr.gg/match/12345"
        data = {"team1": "Sentinels"}

        disabled_cache.set(url, data)
        result = disabled_cache.get(url)

        assert result is None

    def test_cache_clear(self, cache, temp_cache_dir):
        """Test clearing all cache entries."""
        urls = [
            "https://vlr.gg/match/1",
            "https://vlr.gg/match/2",
            "https://vlr.gg/match/3",
        ]
        for url in urls:
            cache.set(url, {"url": url})

        count = cache.clear()

        assert count == 3
        for url in urls:
            assert cache.get(url) is None

    def test_cache_clear_expired(self, temp_cache_dir):
        """Test clearing only expired cache entries."""
        cache = MatchCache(cache_dir=temp_cache_dir, ttl_seconds=1, enabled=True)

        # Set one entry that will expire
        cache.set("https://vlr.gg/match/old", {"old": True})

        # Wait for it to expire
        time.sleep(1.1)

        # Set another entry that won't expire
        cache.set("https://vlr.gg/match/new", {"new": True})

        count = cache.clear_expired()

        assert count == 1
        assert cache.get("https://vlr.gg/match/old") is None
        assert cache.get("https://vlr.gg/match/new") == {"new": True}

    def test_cache_stats(self, cache, temp_cache_dir):
        """Test getting cache statistics."""
        cache.set("https://vlr.gg/match/1", {"data": 1})
        cache.set("https://vlr.gg/match/2", {"data": 2})

        stats = cache.get_stats()

        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2
        assert stats["expired_entries"] == 0

    def test_cache_handles_invalid_json(self, cache, temp_cache_dir):
        """Test that cache handles corrupted cache files gracefully."""
        url = "https://vlr.gg/match/12345"
        key = cache._get_cache_key(url)
        cache_path = temp_cache_dir / f"{key}.json"

        # Write invalid JSON
        cache_path.write_text("not valid json {{{")

        result = cache.get(url)

        assert result is None
        # File should be deleted
        assert not cache_path.exists()

    def test_cache_key_generation(self, cache):
        """Test that cache keys are consistent."""
        url = "https://vlr.gg/match/12345"

        key1 = cache._get_cache_key(url)
        key2 = cache._get_cache_key(url)

        assert key1 == key2
        assert len(key1) == 32  # MD5 hex digest length

    def test_cache_invalidate(self, cache):
        """Test invalidating a cached entry."""
        url = "https://vlr.gg/match/12345"
        data = {"team1": "Sentinels", "team2": "Cloud9"}

        cache.set(url, data)
        assert cache.get(url) == data

        result = cache.invalidate(url)

        assert result is True
        assert cache.get(url) is None

    def test_cache_invalidate_nonexistent(self, cache):
        """Test invalidating a non-existent entry returns False."""
        result = cache.invalidate("https://vlr.gg/match/nonexistent")
        assert result is False

    def test_cache_invalidate_disabled(self, disabled_cache):
        """Test that invalidate returns False when cache is disabled."""
        result = disabled_cache.invalidate("https://vlr.gg/match/12345")
        assert result is False
