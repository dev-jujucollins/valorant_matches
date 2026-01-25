# Integration tests for new functionality.
import time
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

from match_extractor import (
    CIRCUIT_BREAKER_RESET_TIME,
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreakerOpen,
)
from valorant_client import ValorantClient


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_circuit_breaker_trips_after_threshold_failures(self):
        """Test that circuit breaker trips after consecutive failures."""
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            # Simulate failures up to threshold
            for _ in range(CIRCUIT_BREAKER_THRESHOLD):
                client._record_failure()

            # Circuit should be open now
            assert client._circuit_open_time is not None
            assert client._failure_count == CIRCUIT_BREAKER_THRESHOLD

    def test_circuit_breaker_blocks_requests_when_open(self):
        """Test that circuit breaker blocks requests when open."""
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            # Trip the circuit breaker
            client._circuit_open_time = time.time()
            client._failure_count = CIRCUIT_BREAKER_THRESHOLD

            # Should raise CircuitBreakerOpen
            with pytest.raises(CircuitBreakerOpen):
                client._check_circuit_breaker()

    def test_circuit_breaker_resets_after_timeout(self):
        """Test that circuit breaker resets after timeout period."""
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            # Set circuit breaker to have opened in the past
            client._circuit_open_time = time.time() - CIRCUIT_BREAKER_RESET_TIME - 1
            client._failure_count = CIRCUIT_BREAKER_THRESHOLD

            # Should not raise - circuit should reset
            client._check_circuit_breaker()

            assert client._circuit_open_time is None
            assert client._failure_count == 0

    def test_success_resets_failure_count(self):
        """Test that successful request resets failure count."""
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            # Accumulate some failures
            client._failure_count = 3

            # Record success
            client._record_success()

            assert client._failure_count == 0
            assert client._circuit_open_time is None

    @patch("valorant_client.requests.Session.get")
    def test_make_request_records_failure_on_exhausted_retries(self, mock_get):
        """Test that _make_request records failure when all retries exhausted."""
        mock_get.side_effect = RequestException("Connection failed")

        with (
            patch("valorant_client.MatchCache"),
            patch("valorant_client.time.sleep"),
        ):
            client = ValorantClient()
            client._make_request("https://vlr.gg/test", retries=2)

            assert client._failure_count == 1

    @patch("valorant_client.requests.Session.get")
    def test_make_request_resets_on_success(self, mock_get):
        """Test that _make_request resets failure count on success."""
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with patch("valorant_client.MatchCache"):
            client = ValorantClient()
            client._failure_count = 3  # Simulate previous failures

            client._make_request("https://vlr.gg/test")

            assert client._failure_count == 0


class TestSlugMatching:
    """Tests for improved slug matching with regex word boundaries."""

    def test_slug_exact_match(self):
        """Test that slug matches exactly as a segment."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1">Match 1</a>
            <a href="/595002/team-c-vs-team-d-vct-2026-americas-kickoff-ur1">Match 2</a>
        </body>
        </html>
        """
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

                matches = client.fetch_event_matches(
                    "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
                )

                assert len(matches) == 2

    def test_slug_no_false_positives(self):
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
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

                matches = client.fetch_event_matches(
                    "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
                )

                # Only the first match should be included
                assert len(matches) == 1
                assert "vct-2026-americas-kickoff" in matches[0]["href"]

    def test_slug_case_insensitive(self):
        """Test that slug matching is case insensitive."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-VCT-2026-Americas-Kickoff-ur1">Match 1</a>
        </body>
        </html>
        """
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            with patch.object(client, "_make_request") as mock_request:
                mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

                matches = client.fetch_event_matches(
                    "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"
                )

                assert len(matches) == 1


class TestRegionFallbackMapping:
    """Tests for consolidated region fallback mapping."""

    def test_region_fallback_keys_completeness(self):
        """Test that all regions in REGION_ALIASES have fallback keys."""
        from config import REGION_FALLBACK_KEYS
        from event_discovery import REGION_ALIASES

        for region in REGION_ALIASES:
            assert region in REGION_FALLBACK_KEYS, f"Missing fallback key for {region}"

    def test_region_fallback_keys_valid_events(self):
        """Test that all fallback keys point to valid events."""
        from config import EVENTS, REGION_FALLBACK_KEYS

        for region, key in REGION_FALLBACK_KEYS.items():
            assert key in EVENTS, f"Invalid event key '{key}' for region '{region}'"

    def test_masters_has_fallback(self):
        """Test that masters region has a fallback event."""
        from config import EVENTS, REGION_FALLBACK_KEYS

        assert "masters" in REGION_FALLBACK_KEYS
        masters_key = REGION_FALLBACK_KEYS["masters"]
        assert masters_key in EVENTS
        assert "masters" in EVENTS[masters_key].name.lower()


class TestConcurrentProcessing:
    """Tests for concurrent processing with exception handling."""

    def test_process_matches_handles_exceptions(self):
        """Test that process_matches continues despite individual match failures."""

        from main import process_matches

        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

        # Create mock links
        mock_links = [
            {"href": "/123/match-1"},
            {"href": "/456/match-2"},
            {"href": "/789/match-3"},
        ]

        # Mock process_match to fail on second call
        call_count = [0]

        async def mock_process_match(link, upcoming_only=False):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ValueError("Simulated failure")
            return f"Result for {link['href']}"

        # Patch the AsyncValorantClient's process_match method since process_matches uses async
        with patch(
            "async_client.AsyncValorantClient.process_match",
            side_effect=mock_process_match,
        ):
            # This should not raise despite the exception
            results = process_matches(client, mock_links, "all")

            # Should have 2 results (first and third succeeded)
            assert len(results) == 2


class TestCacheHashAlgorithm:
    """Tests for SHA-256 cache key generation."""

    def test_cache_key_is_sha256(self):
        """Test that cache keys are generated using SHA-256."""
        import hashlib

        from cache import MatchCache

        cache = MatchCache(enabled=True)
        url = "https://vlr.gg/match/12345"

        expected_key = hashlib.sha256(url.encode()).hexdigest()
        actual_key = cache._get_cache_key(url)

        assert actual_key == expected_key
        # SHA-256 produces 64 character hex strings
        assert len(actual_key) == 64

    def test_cache_key_not_md5(self):
        """Test that cache keys are NOT MD5 (32 chars)."""
        from cache import MatchCache

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
        from config import RATE_LIMIT_DELAY

        assert isinstance(RATE_LIMIT_DELAY, float)
        assert RATE_LIMIT_DELAY > 0

    def test_rate_limit_delay_default_value(self):
        """Test default rate limit delay value."""
        from config import RATE_LIMIT_DELAY

        # Default should be 0.5 seconds
        assert RATE_LIMIT_DELAY == 0.5


class TestExceptionHandling:
    """Tests for specific exception handling in valorant_client."""

    @patch("valorant_client.requests.Session.get")
    def test_process_match_handles_request_exception(self, mock_get):
        """Test that process_match handles RequestException gracefully."""
        mock_get.side_effect = RequestException("Network error")

        with (
            patch("valorant_client.MatchCache") as mock_cache,
            patch("valorant_client.time.sleep"),
        ):
            mock_cache_instance = Mock()
            mock_cache_instance.get.return_value = None
            mock_cache.return_value = mock_cache_instance

            client = ValorantClient()
            result = client.process_match({"href": "/123/test-match"})

            # Should return None, not raise
            assert result is None

    def test_process_match_handles_attribute_error(self):
        """Test that process_match handles AttributeError from malformed HTML."""
        with patch("valorant_client.MatchCache") as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get.return_value = None
            mock_cache.return_value = mock_cache_instance

            client = ValorantClient()

            # Mock _make_request to return soup that causes AttributeError
            with patch.object(client, "_make_request") as mock_request:
                mock_soup = Mock()
                mock_soup.find_all.side_effect = AttributeError("No attribute")
                mock_request.return_value = mock_soup

                result = client.process_match({"href": "/123/test-match"})

                # Should return None, not raise
                assert result is None
