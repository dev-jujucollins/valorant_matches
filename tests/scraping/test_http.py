# Tests for shared HTTP fetching, retries, and the circuit breaker.

import asyncio
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.http import (
    CIRCUIT_BREAKER_RESET_TIME,
    CIRCUIT_BREAKER_THRESHOLD,
    MAX_BACKOFF_DELAY,
    AsyncRateLimiter,
    CircuitBreaker,
    CircuitBreakerOpen,
    HttpFetcher,
    calculate_backoff,
    fetch_page,
    is_retryable_status,
    retry_delay,
)


def response(status: int, text: str = "<html>ok</html>", headers=None) -> Mock:
    """Wrap a fake aiohttp response in an async context manager."""
    resp = Mock(status=status, headers=headers or {})
    resp.text = AsyncMock(return_value=text)
    return Mock(__aenter__=AsyncMock(return_value=resp), __aexit__=AsyncMock())


class TestBackoff:
    """Tests for backoff and Retry-After handling."""

    def test_calculate_backoff_grows(self) -> None:
        """Delays increase with each attempt."""
        assert calculate_backoff(0) < calculate_backoff(1) < calculate_backoff(2)

    def test_calculate_backoff_max_limit(self) -> None:
        """Delays are capped."""
        assert calculate_backoff(100) <= MAX_BACKOFF_DELAY

    @pytest.mark.parametrize("header", ["nonsense", "-5", None])
    def test_retry_after_fallback(self, header: str | None) -> None:
        """Invalid headers use normal backoff."""
        with patch("valorant_matches.scraping.http.calculate_backoff", return_value=3):
            assert retry_delay(header, 0) == 3

    def test_retry_after_seconds_and_http_date(self) -> None:
        """Delta seconds wait as given; future dates wait; past dates don't."""
        assert retry_delay("12", 0) == 12
        future = format_datetime(datetime.now(UTC) + timedelta(seconds=120), True)
        assert 118 <= retry_delay(future, 0) <= 120
        assert retry_delay("Wed, 01 Jan 2020 00:00:00 GMT", 0) == 0

    def test_retryable_statuses(self) -> None:
        """5xx and 429 retry; other client errors do not."""
        assert all(is_retryable_status(s) for s in (500, 502, 503, 429))
        assert not any(is_retryable_status(s) for s in (400, 403, 404))


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_closed_breaker_allows_requests(self) -> None:
        """A new breaker does not block."""
        CircuitBreaker().check()

    def test_trips_at_threshold(self) -> None:
        """Consecutive failures open the breaker."""
        breaker = CircuitBreaker()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
            breaker.record_failure()
        assert breaker.opened_at is None
        breaker.record_failure()
        assert breaker.opened_at is not None
        with pytest.raises(CircuitBreakerOpen):
            breaker.check()

    def test_resets_after_timeout(self) -> None:
        """The breaker closes again once the reset time passes."""
        breaker = CircuitBreaker()
        breaker.failure_count = CIRCUIT_BREAKER_THRESHOLD
        breaker.opened_at = time.monotonic() - CIRCUIT_BREAKER_RESET_TIME - 1
        breaker.check()
        assert breaker.opened_at is None
        assert breaker.failure_count == 0

    def test_success_resets_count(self) -> None:
        """A success clears earlier failures."""
        breaker = CircuitBreaker()
        breaker.record_failure()
        breaker.record_success()
        assert breaker.failure_count == 0


class TestAsyncRateLimiter:
    """Tests for AsyncRateLimiter."""

    async def test_first_request_no_delay(self) -> None:
        """First request should not be delayed."""
        limiter = AsyncRateLimiter(delay=1.0)
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start < 0.1

    async def test_subsequent_requests_delayed(self) -> None:
        """Subsequent requests wait for the configured delay."""
        limiter = AsyncRateLimiter(delay=0.2)
        await limiter.acquire()
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start >= 0.15

    async def test_concurrent_requests_serialized(self) -> None:
        """Concurrent requests all complete through the lock."""
        limiter = AsyncRateLimiter(delay=0.01)
        await asyncio.gather(*(limiter.acquire() for _ in range(3)))

    async def test_rate_limit_ignores_wall_clock(self) -> None:
        """Wall-clock corrections do not alter rate limiting."""
        limiter = AsyncRateLimiter(delay=1)
        with (
            patch(
                "valorant_matches.scraping.http.time.monotonic",
                side_effect=[100, 100, 100.25, 101],
            ),
            patch(
                "valorant_matches.scraping.http.time.time",
                side_effect=AssertionError("wall clock used"),
            ),
            patch(
                "valorant_matches.scraping.http.asyncio.sleep", new_callable=AsyncMock
            ) as sleep,
        ):
            await limiter.acquire()
            await limiter.acquire()
        sleep.assert_awaited_once_with(0.75)


class TestHttpFetcher:
    """Tests for HttpFetcher.fetch."""

    async def test_exit_closes_session(self) -> None:
        """Leaving the context closes the session."""
        async with HttpFetcher() as fetcher:
            session = fetcher._session
        assert session is not None and session.closed

    async def test_requires_context(self) -> None:
        """Fetching outside async with is a programming error."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await HttpFetcher().fetch("https://vlr.gg/test")

    async def test_successful_request_returns_soup(self) -> None:
        """A 200 response is parsed."""
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            with patch.object(fetcher._session, "get", return_value=response(200)):
                soup = await fetcher.fetch("https://vlr.gg/test")
        assert isinstance(soup, BeautifulSoup)
        assert fetcher.errors == {}

    async def test_http_error_recorded(self) -> None:
        """A non-retryable status is recorded with its URL."""
        url = "https://vlr.gg/test"
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            with patch.object(fetcher._session, "get", return_value=response(404)):
                assert await fetcher.fetch(url) is None
        assert fetcher.errors[url].message == "HTTP 404"
        assert fetcher.breaker.failure_count == 1

    async def test_retry_after_used_by_request(self) -> None:
        """The loop honors the server's delay before retrying."""
        limited = response(429, headers={"Retry-After": "12"})
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            with (
                patch.object(
                    fetcher._session, "get", side_effect=[limited, response(200)]
                ) as get,
                patch(
                    "valorant_matches.scraping.http.asyncio.sleep",
                    new_callable=AsyncMock,
                ) as sleep,
            ):
                assert await fetcher.fetch("https://vlr.gg/test") is not None
        sleep.assert_awaited_once_with(12)
        assert get.call_count == 2

    async def test_circuit_rechecked_after_queue_wait(self) -> None:
        """A request queued before a failure must not bypass an opened circuit."""
        async with HttpFetcher() as fetcher:

            async def open_circuit() -> None:
                fetcher.breaker.opened_at = time.monotonic()

            with (
                patch.object(fetcher.rate_limiter, "acquire", side_effect=open_circuit),
                patch.object(fetcher._session, "get") as get,
            ):
                assert await fetcher.fetch("https://vlr.gg/test") is None
        get.assert_not_called()
        assert fetcher.errors["https://vlr.gg/test"].error_type == "circuit"

    @pytest.mark.parametrize(
        "error, kind",
        [(TimeoutError(), "timeout"), (aiohttp.ClientError("offline"), "network")],
    )
    async def test_request_errors_keep_context(
        self, error: Exception, kind: str
    ) -> None:
        """Exhausted requests retain their URL and failure type."""
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            with patch.object(fetcher._session, "get", side_effect=error):
                assert await fetcher.fetch("https://vlr.gg/test", retries=1) is None
        assert fetcher.errors["https://vlr.gg/test"].error_type == kind

    async def test_transient_errors_retry_then_succeed(self) -> None:
        """A network blip is retried with backoff."""
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            with (
                patch.object(
                    fetcher._session,
                    "get",
                    side_effect=[aiohttp.ClientError("blip"), response(200)],
                ),
                patch(
                    "valorant_matches.scraping.http.asyncio.sleep",
                    new_callable=AsyncMock,
                ),
            ):
                assert await fetcher.fetch("https://vlr.gg/test") is not None


def test_fetch_page_runs_one_request() -> None:
    """The sync helper drives a fetcher to completion."""
    soup = BeautifulSoup("<html></html>", "lxml")
    with patch.object(
        HttpFetcher, "fetch", new_callable=AsyncMock, return_value=soup
    ) as fetch:
        assert fetch_page("https://vlr.gg/") is soup
    fetch.assert_awaited_once_with("https://vlr.gg/")
