# Tests for the cache module.
import json
import time

import pytest

from valorant_matches.cache import CACHE_SCHEMA_VERSION, MatchCache


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
    @pytest.mark.parametrize(
        "entry",
        [
            [],
            {"version": CACHE_SCHEMA_VERSION, "timestamp": "bad", "data": {}},
            {"version": CACHE_SCHEMA_VERSION, "timestamp": time.time(), "data": []},
        ],
    )
    def test_malformed_record_is_discarded(
        self, cache: MatchCache, entry: object
    ) -> None:
        """A damaged disk record should become a cache miss."""
        url = "https://vlr.gg/123/match"
        path = cache._get_cache_path(cache._get_cache_key(url))
        path.write_text(json.dumps(entry))

        assert cache.get(url) is None
        assert not path.exists()

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

    def test_cache_discards_mismatched_schema_version(self, cache, temp_cache_dir):
        """Entries written under an old schema version are treated as misses."""
        import json
        import time as time_module

        url = "https://vlr.gg/match/12345"
        key = cache._get_cache_key(url)
        cache_path = temp_cache_dir / f"{key}.json"

        # Simulate an entry from before schema versioning (no "version" key)
        cache_path.write_text(
            json.dumps(
                {"url": url, "timestamp": time_module.time(), "data": {"stale": True}}
            )
        )

        assert cache.get(url) is None
        # Stale file should be deleted
        assert not cache_path.exists()


class TestMemoryLru:
    """Tests for the in-memory LRU tier."""

    def test_updating_key_at_capacity_keeps_other_entries(self, temp_cache_dir):
        """Overwriting a cached URL must not evict an unrelated entry."""
        cache = MatchCache(cache_dir=temp_cache_dir, enabled=True, memory_size=2)
        cache.set("https://vlr.gg/1", {"n": 1})
        cache.set("https://vlr.gg/2", {"n": 2})
        cache.set("https://vlr.gg/1", {"n": 11})
        keys = list(cache._memory_cache)
        assert keys == [
            cache._get_cache_key("https://vlr.gg/2"),
            cache._get_cache_key("https://vlr.gg/1"),
        ]

    def test_least_recently_used_is_evicted(self, temp_cache_dir):
        """Reading an entry protects it from the next eviction."""
        cache = MatchCache(cache_dir=temp_cache_dir, enabled=True, memory_size=2)
        cache.set("https://vlr.gg/1", {"n": 1})
        cache.set("https://vlr.gg/2", {"n": 2})
        cache.get("https://vlr.gg/1")
        cache.set("https://vlr.gg/3", {"n": 3})
        assert cache._get_cache_key("https://vlr.gg/2") not in cache._memory_cache
        assert cache._get_cache_key("https://vlr.gg/1") in cache._memory_cache

    def test_disk_hit_survives_new_instance(self, temp_cache_dir):
        """A new process reads entries written by an earlier one."""
        MatchCache(cache_dir=temp_cache_dir, enabled=True).set(
            "https://vlr.gg/1", {"n": 1}
        )
        fresh = MatchCache(cache_dir=temp_cache_dir, enabled=True)
        assert fresh.get("https://vlr.gg/1") == {"n": 1}
