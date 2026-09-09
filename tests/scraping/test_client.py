# Tests for async scraping client.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.client import (
    AsyncRateLimiter,
    AsyncValorantClient,
    process_matches_async,
)
from valorant_matches.scraping.matches import Match, ProcessMatchResult


def make_result(href: str, is_upcoming: bool = False) -> ProcessMatchResult:
    """Build a ProcessMatchResult for a successful match fetch."""
    return ProcessMatchResult(
        match=Match(
            date="Dec 23",
            time="3:00 PM",
            team1="Team A",
            team2="Team B",
            score="in 2h" if is_upcoming else "2-1",
            is_live=False,
            url=f"https://vlr.gg{href}",
            is_upcoming=is_upcoming,
        )
    )


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


class TestProcessMatchesAsync:
    """Tests for process_matches_async function."""

    @pytest.mark.asyncio
    async def test_empty_match_links(self):
        """Test with empty match links list."""
        async with AsyncValorantClient(cache_enabled=False) as client:
            processed = await process_matches_async(client, [])
            assert processed.results == []
            assert processed.tbd_count == 0

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
            # Mock process_match to return empty results (simulating failed matches)
            client.process_match = AsyncMock(return_value=ProcessMatchResult())

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
            return make_result(link["href"])

        mock_links = [
            {"href": "/1/match1"},
            {"href": "/2/match2"},
            {"href": "/3/match3"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            processed = await process_matches_async(client, mock_links)

            # All should start at roughly the same time (concurrent)
            assert len(processing_times) == 3
            # All start times should be close together (within 0.05s)
            assert max(processing_times) - min(processing_times) < 0.05

            # Should have results for all matches
            assert len(processed.results) == 3
            assert processed.tbd_count == 0

    @pytest.mark.asyncio
    async def test_results_sorted_by_original_order(self):
        """Test that results maintain original order despite concurrent processing."""
        delays = {"/1/match1": 0.15, "/2/match2": 0.05, "/3/match3": 0.1}

        async def mock_process_match(link, upcoming_only=False):
            await asyncio.sleep(delays[link["href"]])
            return make_result(link["href"])

        mock_links = [
            {"href": "/1/match1"},
            {"href": "/2/match2"},
            {"href": "/3/match3"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            processed = await process_matches_async(client, mock_links)

            # Results should be in original order, not completion order
            assert processed.results[0][0]["href"] == "/1/match1"
            assert processed.results[1][0]["href"] == "/2/match2"
            assert processed.results[2][0]["href"] == "/3/match3"

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test that exceptions are caught and logged."""

        async def mock_process_match(link, upcoming_only=False):
            if "error" in link["href"]:
                raise ValueError("Test error")
            return make_result(link["href"])

        mock_links = [
            {"href": "/1/error-match"},
            {"href": "/2/good-match"},
        ]

        async with AsyncValorantClient(cache_enabled=False) as client:
            client.process_match = mock_process_match  # type: ignore[method-assign]

            # Should not raise, exceptions are caught
            processed = await process_matches_async(client, mock_links)

            # Only the successful match should be in results
            assert len(processed.results) == 1
            assert "good" in processed.results[0][0]["href"]
            assert processed.failed_count == 1


class TestClientCacheControl:
    """Tests for cache enable/disable wiring."""

    def test_cache_enabled_by_default(self):
        """Cache should be enabled unless disabled explicitly."""
        with patch("valorant_matches.scraping.client.MatchCache") as mock_cache:
            AsyncValorantClient()
            mock_cache.assert_called_once_with(enabled=True)

    def test_cache_disabled(self):
        """Cache can be disabled via constructor."""
        with patch("valorant_matches.scraping.client.MatchCache") as mock_cache:
            AsyncValorantClient(cache_enabled=False)
            mock_cache.assert_called_once_with(enabled=False)
