# Tests for async_client.py

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from async_client import (
    AsyncRateLimiter,
    AsyncValorantClient,
    process_matches_async,
)
from match_extractor import Match


class TestAsyncRateLimiter:
    """Tests for AsyncRateLimiter."""

    @pytest.mark.asyncio
    async def test_first_request_no_delay(self):
        """First request should not be delayed."""
        limiter = AsyncRateLimiter(delay=1.0)
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.1  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_subsequent_requests_delayed(self):
        """Subsequent requests should be delayed by the configured delay."""
        limiter = AsyncRateLimiter(delay=0.2)
        await limiter.acquire()

        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        # Should be delayed by at least the delay time
        assert elapsed >= 0.15  # Some tolerance

    @pytest.mark.asyncio
    async def test_concurrent_requests_serialized(self):
        """Concurrent requests should be serialized by the lock."""
        limiter = AsyncRateLimiter(delay=0.1)
        results = []

        async def acquire_and_record(n: int):
            await limiter.acquire()
            results.append(n)

        # Launch multiple concurrent requests
        await asyncio.gather(
            acquire_and_record(1),
            acquire_and_record(2),
            acquire_and_record(3),
        )

        # All should complete
        assert len(results) == 3


class TestAsyncValorantClientContextManager:
    """Tests for AsyncValorantClient context manager."""

    @pytest.mark.asyncio
    async def test_enter_creates_session(self):
        """Entering context should create an aiohttp session."""
        async with AsyncValorantClient(cache_enabled=False) as client:
            assert client._session is not None
            assert not client._session.closed

    @pytest.mark.asyncio
    async def test_exit_closes_session(self):
        """Exiting context should close the session."""
        async with AsyncValorantClient(cache_enabled=False) as client:
            session = client._session

        assert session is not None
        assert session.closed

    @pytest.mark.asyncio
    async def test_session_not_initialized_error(self):
        """Using client without context should raise RuntimeError."""
        client = AsyncValorantClient(cache_enabled=False)
        with pytest.raises(RuntimeError, match="Client not initialized"):
            await client._make_request("https://example.com")


class TestAsyncValorantClientMakeRequest:
    """Tests for _make_request method."""

    @pytest.mark.asyncio
    async def test_successful_request(self):
        """Test successful HTTP request returns BeautifulSoup."""
        html = "<html><body><h1>Test</h1></body></html>"

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=html)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()
            )
        )

        async with AsyncValorantClient(cache_enabled=False) as client:
            client._session = mock_session
            client._rate_limiter = AsyncMock()
            client._rate_limiter.acquire = AsyncMock()

            result = await client._make_request("https://vlr.gg/test")

            assert result is not None
            assert isinstance(result, BeautifulSoup)

    @pytest.mark.asyncio
    async def test_retryable_status_codes(self):
        """Test that 5xx and 429 status codes trigger retry."""
        client = AsyncValorantClient(cache_enabled=False)

        assert client._is_retryable_status(500) is True
        assert client._is_retryable_status(502) is True
        assert client._is_retryable_status(503) is True
        assert client._is_retryable_status(429) is True
        assert client._is_retryable_status(404) is False
        assert client._is_retryable_status(400) is False

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """Test that HTTP errors return None after retries."""
        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()
            )
        )

        async with AsyncValorantClient(cache_enabled=False) as client:
            client._session = mock_session
            client._rate_limiter = AsyncMock()
            client._rate_limiter.acquire = AsyncMock()

            result = await client._make_request("https://vlr.gg/test", retries=1)

            assert result is None


class TestAsyncValorantClientSlugPattern:
    """Tests for slug pattern caching."""

    def test_slug_pattern_caching(self):
        """Test that slug patterns are cached."""
        client = AsyncValorantClient(cache_enabled=False)

        pattern1 = client._get_slug_pattern("americas-kickoff")
        pattern2 = client._get_slug_pattern("americas-kickoff")

        assert pattern1 is pattern2  # Same object (cached)

    def test_slug_pattern_matches(self):
        """Test that slug patterns match correctly."""
        client = AsyncValorantClient(cache_enabled=False)

        pattern = client._get_slug_pattern("americas")
        assert pattern.search("vct-2026-americas-kickoff") is not None
        assert pattern.search("vct-2026-emea-kickoff") is None


class TestProcessMatchesAsync:
    """Tests for process_matches_async function."""

    @pytest.mark.asyncio
    async def test_empty_match_links(self):
        """Test with empty match links list."""
        async with AsyncValorantClient(cache_enabled=False) as client:
            results, tbd_count = await process_matches_async(client, [])
            assert results == []
            assert tbd_count == 0

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        """Test that progress callback is called for each match."""
        callback_count = 0

        def progress_callback():
            nonlocal callback_count
            callback_count += 1

        mock_links = [
            {"href": "/123/match1"},
            {"href": "/456/match2"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            # Mock process_match to return None (simulating failed matches)
            client.process_match = AsyncMock(return_value=None)

            await process_matches_async(
                client, mock_links, progress_callback=progress_callback
            )

            assert callback_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_processing(self):
        """Test that matches are processed concurrently."""
        processing_times = []
        start_time = asyncio.get_event_loop().time()

        async def mock_process_match(link, upcoming_only=False):
            processing_times.append(asyncio.get_event_loop().time() - start_time)
            await asyncio.sleep(0.1)  # Simulate network delay
            return Match(
                date="Dec 23",
                time="3:00 PM",
                team1="Team A",
                team2="Team B",
                score="2-1",
                is_live=False,
                url=f"https://vlr.gg{link['href']}",
                is_upcoming=False,
            )

        mock_links = [
            {"href": "/1/match1"},
            {"href": "/2/match2"},
            {"href": "/3/match3"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            results, tbd_count = await process_matches_async(client, mock_links)

            # All should start at roughly the same time (concurrent)
            assert len(processing_times) == 3
            # All start times should be close together (within 0.05s)
            assert max(processing_times) - min(processing_times) < 0.05

            # Should have results for all matches
            assert len(results) == 3
            assert tbd_count == 0

    @pytest.mark.asyncio
    async def test_results_sorted_by_original_order(self):
        """Test that results maintain original order despite concurrent processing."""
        delays = {"/1/match1": 0.15, "/2/match2": 0.05, "/3/match3": 0.1}

        async def mock_process_match(link, upcoming_only=False):
            await asyncio.sleep(delays[link["href"]])
            return Match(
                date="Dec 23",
                time="3:00 PM",
                team1="Team A",
                team2="Team B",
                score="2-1",
                is_live=False,
                url=f"https://vlr.gg{link['href']}",
                is_upcoming=False,
            )

        mock_links = [
            {"href": "/1/match1"},
            {"href": "/2/match2"},
            {"href": "/3/match3"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            results, _tbd_count = await process_matches_async(client, mock_links)

            # Results should be in original order, not completion order
            assert results[0][0]["href"] == "/1/match1"
            assert results[1][0]["href"] == "/2/match2"
            assert results[2][0]["href"] == "/3/match3"

    @pytest.mark.asyncio
    async def test_view_mode_results_filters_upcoming(self):
        """Test that view_mode='results' filters out upcoming matches."""

        async def mock_process_match(link, upcoming_only=False):
            if "upcoming" in link["href"]:
                return Match(
                    date="Dec 23",
                    time="3:00 PM",
                    team1="Team A",
                    team2="Team B",
                    score="in 2h",
                    is_live=False,
                    url="https://vlr.gg/1",
                    is_upcoming=True,
                )
            return Match(
                date="Dec 23",
                time="3:00 PM",
                team1="Team A",
                team2="Team B",
                score="2-1",
                is_live=False,
                url="https://vlr.gg/2",
                is_upcoming=False,
            )

        mock_links = [
            {"href": "/1/upcoming-match"},
            {"href": "/2/completed-match"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            results, _tbd_count = await process_matches_async(
                client, mock_links, view_mode="results"
            )

            # Only completed match should be in results
            assert len(results) == 1
            assert "completed" in results[0][0]["href"]

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test that exceptions are caught and logged."""

        async def mock_process_match(link, upcoming_only=False):
            if "error" in link["href"]:
                raise ValueError("Test error")
            return Match(
                date="Dec 23",
                time="3:00 PM",
                team1="Team A",
                team2="Team B",
                score="2-1",
                is_live=False,
                url=f"https://vlr.gg{link['href']}",
                is_upcoming=False,
            )

        mock_links = [
            {"href": "/1/error-match"},
            {"href": "/2/good-match"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            # Should not raise, exceptions are caught
            results, _tbd_count = await process_matches_async(client, mock_links)

            # Only the successful match should be in results
            assert len(results) == 1
            assert "good" in results[0][0]["href"]

    @pytest.mark.asyncio
    async def test_tbd_matches_counted_separately(self):
        """Test that TBD matches are counted separately from failures."""

        async def mock_process_match(link, upcoming_only=False):
            if "tbd" in link["href"]:
                return "TBD"  # Sentinel value for TBD matches
            if "error" in link["href"]:
                return None  # Actual failure
            return Match(
                date="Dec 23",
                time="3:00 PM",
                team1="Team A",
                team2="Team B",
                score="2-1",
                is_live=False,
                url=f"https://vlr.gg{link['href']}",
                is_upcoming=False,
            )

        mock_links = [
            {"href": "/1/tbd-match"},
            {"href": "/2/tbd-match"},
            {"href": "/3/error-match"},
            {"href": "/4/good-match"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            results, tbd_count = await process_matches_async(client, mock_links)

            # Should have 1 successful match
            assert len(results) == 1
            # Should have counted 2 TBD matches
            assert tbd_count == 2


class TestCircuitBreaker:
    """Tests for circuit breaker functionality in AsyncValorantClient."""

    def test_circuit_breaker_initialization(self):
        """Test that circuit breaker is properly initialized."""
        client = AsyncValorantClient(cache_enabled=False)

        assert hasattr(client, "_failure_count")
        assert hasattr(client, "_circuit_open_time")
        assert client._failure_count == 0
        assert client._circuit_open_time is None
