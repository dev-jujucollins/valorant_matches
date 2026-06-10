# Integration tests for cross-module behavior.
import time
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.async_client import AsyncValorantClient, process_matches_async
from valorant_matches.match_extractor import (
    CIRCUIT_BREAKER_RESET_TIME,
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreakerOpen,
    Match,
    ProcessMatchResult,
)


class TestCircuitBreaker:
    """Tests for circuit breaker functionality on the async client."""

    def test_circuit_breaker_trips_after_threshold_failures(self):
        """Test that circuit breaker trips after consecutive failures."""
        client = AsyncValorantClient(cache_enabled=False)

        # Simulate failures up to threshold
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            client._record_failure()

        # Circuit should be open now
        assert client._circuit_open_time is not None
        assert client._failure_count == CIRCUIT_BREAKER_THRESHOLD

    def test_circuit_breaker_blocks_requests_when_open(self):
        """Test that circuit breaker blocks requests when open."""
        client = AsyncValorantClient(cache_enabled=False)

        # Trip the circuit breaker
        client._circuit_open_time = time.time()
        client._failure_count = CIRCUIT_BREAKER_THRESHOLD

        # Should raise CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen):
            client._check_circuit_breaker()

    def test_circuit_breaker_resets_after_timeout(self):
        """Test that circuit breaker resets after timeout period."""
        client = AsyncValorantClient(cache_enabled=False)

        # Set circuit breaker to have opened in the past
        client._circuit_open_time = time.time() - CIRCUIT_BREAKER_RESET_TIME - 1
        client._failure_count = CIRCUIT_BREAKER_THRESHOLD

        # Should not raise - circuit should reset
        client._check_circuit_breaker()

        assert client._circuit_open_time is None
        assert client._failure_count == 0

    def test_success_resets_failure_count(self):
        """Test that successful request resets failure count."""
        client = AsyncValorantClient(cache_enabled=False)

        # Accumulate some failures
        client._failure_count = 3

        # Record success
        client._record_success()

        assert client._failure_count == 0
        assert client._circuit_open_time is None


class TestSlugMatching:
    """Tests for slug matching with regex word boundaries."""

    @pytest.mark.asyncio
    async def test_slug_exact_match(self):
        """Test that slug matches exactly as a segment."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1">Match 1</a>
            <a href="/595002/team-c-vs-team-d-vct-2026-americas-kickoff-ur1">Match 2</a>
        </body>
        </html>
        """
        client = AsyncValorantClient(cache_enabled=False)
        with patch.object(
            client,
            "_make_request",
            AsyncMock(return_value=BeautifulSoup(mock_html, "html.parser")),
        ):
            matches = await client.fetch_event_matches(
                "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
            )

        assert len(matches) == 2

    @pytest.mark.asyncio
    async def test_slug_no_false_positives(self):
        """Test that substring matches are not included (prevents 'vct' matching 'valorant-challengers-vct')."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1">Correct Match</a>
            <a href="/595002/team-c-vs-team-d-valorant-challengers-vct-2026">Wrong - challengers</a>
            <a href="/596003/team-e-vs-team-f-vct-americas-different-event">Wrong - different</a>
        </body>
        </html>
        """
        client = AsyncValorantClient(cache_enabled=False)
        with patch.object(
            client,
            "_make_request",
            AsyncMock(return_value=BeautifulSoup(mock_html, "html.parser")),
        ):
            matches = await client.fetch_event_matches(
                "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
            )

        # Only the first match should be included
        assert len(matches) == 1
        assert "vct-2026-americas-kickoff" in matches[0]["href"]

    @pytest.mark.asyncio
    async def test_slug_case_insensitive(self):
        """Test that slug matching is case insensitive."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-VCT-2026-Americas-Kickoff-ur1">Match 1</a>
        </body>
        </html>
        """
        client = AsyncValorantClient(cache_enabled=False)
        with patch.object(
            client,
            "_make_request",
            AsyncMock(return_value=BeautifulSoup(mock_html, "html.parser")),
        ):
            matches = await client.fetch_event_matches(
                "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
            )

        assert len(matches) == 1


class TestRegionFallbackMapping:
    """Tests for consolidated region fallback mapping."""

    def test_region_fallback_keys_completeness(self):
        """Test that all regions in REGION_ALIASES have fallback keys."""
        from valorant_matches.config import REGION_FALLBACK_KEYS
        from valorant_matches.event_discovery import REGION_ALIASES

        for region in REGION_ALIASES:
            assert region in REGION_FALLBACK_KEYS, f"Missing fallback key for {region}"

    def test_region_fallback_keys_valid_events(self):
        """Test that all fallback keys point to valid events."""
        from valorant_matches.config import EVENTS, REGION_FALLBACK_KEYS

        for region, key in REGION_FALLBACK_KEYS.items():
            assert key in EVENTS, f"Invalid event key '{key}' for region '{region}'"

    def test_masters_has_fallback(self):
        """Test that masters region has a fallback event."""
        from valorant_matches.config import EVENTS, REGION_FALLBACK_KEYS

        assert "masters" in REGION_FALLBACK_KEYS
        masters_key = REGION_FALLBACK_KEYS["masters"]
        assert masters_key in EVENTS
        assert "masters" in EVENTS[masters_key].name.lower()


class TestConcurrentProcessing:
    """Tests for concurrent processing with exception handling."""

    @pytest.mark.asyncio
    async def test_process_matches_handles_exceptions(self):
        """Test that processing continues despite individual match failures."""
        mock_links = [
            {"href": "/123/match-1"},
            {"href": "/456/match-2"},
            {"href": "/789/match-3"},
        ]

        call_count = [0]

        async def mock_process_match(link, upcoming_only=False):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ValueError("Simulated failure")
            return ProcessMatchResult(
                match=Match(
                    date="Jan 1",
                    time="12:00",
                    team1="Team A",
                    team2="Team B",
                    score="2-0",
                    is_live=False,
                    url=f"https://vlr.gg{link['href']}",
                )
            )

        client = AsyncValorantClient(cache_enabled=False)
        with patch.object(client, "process_match", side_effect=mock_process_match):
            # This should not raise despite the exception
            processed = await process_matches_async(client, mock_links, "all")

        # Should have 2 results (first and third succeeded)
        assert len(processed.results) == 2
        assert processed.failed_count == 1


class TestCacheHashAlgorithm:
    """Tests for SHA-256 cache key generation."""

    def test_cache_key_is_sha256(self):
        """Test that cache keys are generated using SHA-256."""
        import hashlib

        from valorant_matches.cache import MatchCache

        cache = MatchCache(enabled=True)
        url = "https://vlr.gg/match/12345"

        expected_key = hashlib.sha256(url.encode()).hexdigest()
        actual_key = cache._get_cache_key(url)

        assert actual_key == expected_key
        # SHA-256 produces 64 character hex strings
        assert len(actual_key) == 64

    def test_cache_key_not_md5(self):
        """Test that cache keys are NOT MD5 (32 chars)."""
        from valorant_matches.cache import MatchCache

        cache = MatchCache(enabled=True)
        url = "https://vlr.gg/match/12345"

        key = cache._get_cache_key(url)

        # MD5 produces 32 character hex strings, SHA-256 produces 64
        assert len(key) != 32
        assert len(key) == 64


class TestRateLimitingConfig:
    """Tests for configurable rate limiting."""

    def test_rate_limit_delay_in_config(self):
        """Test that RATE_LIMIT_DELAY is defined in config."""
        from valorant_matches.config import RATE_LIMIT_DELAY

        assert isinstance(RATE_LIMIT_DELAY, float)
        assert RATE_LIMIT_DELAY > 0

    def test_rate_limit_delay_default_value(self):
        """Test default rate limit delay value."""
        from valorant_matches.config import RATE_LIMIT_DELAY

        # Default should be 0.5 seconds
        assert RATE_LIMIT_DELAY == 0.5
