"""Request scheduling and failure metadata regression tests."""

import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from valorant_matches.scraping.client import AsyncRateLimiter, AsyncValorantClient


@pytest.mark.parametrize("header", ["nonsense", "-5", None])
def test_retry_after_fallback(header: str | None) -> None:
    """Invalid headers use normal backoff."""
    client = AsyncValorantClient(cache_enabled=False)
    with patch.object(client, "_calculate_backoff", return_value=3):
        assert client._retry_delay(header, 0) == 3


def test_retry_after_http_date() -> None:
    """Future HTTP dates wait; past dates allow immediate retry."""
    client = AsyncValorantClient(cache_enabled=False)
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    assert 118 <= client._retry_delay(future, 0) <= 120
    assert client._retry_delay("Wed, 01 Jan 2020 00:00:00 GMT", 0) == 0


async def test_retry_after_used_by_request() -> None:
    """The HTTP loop honors the server's delay before retrying."""
    limited = Mock(status=429, headers={"Retry-After": "12"})
    success = Mock(status=200, text=AsyncMock(return_value="<html>ok</html>"))
    contexts = [
        Mock(__aenter__=AsyncMock(return_value=r), __aexit__=AsyncMock())
        for r in [limited, success]
    ]
    async with AsyncValorantClient(cache_enabled=False) as client:
        with (
            patch.object(client._session, "get", side_effect=contexts) as get,
            patch.object(client._rate_limiter, "acquire", new_callable=AsyncMock),
            patch(
                "valorant_matches.scraping.client.asyncio.sleep", new_callable=AsyncMock
            ) as sleep,
        ):
            assert await client._make_request("https://vlr.gg/test") is not None
    sleep.assert_awaited_once_with(12)
    assert get.call_count == 2


async def test_circuit_rechecked_after_queue_wait() -> None:
    """A request queued before a failure must not bypass an opened circuit."""
    async with AsyncValorantClient(cache_enabled=False) as client:

        async def open_circuit() -> None:
            client._circuit_open_time = time.monotonic()

        with (
            patch.object(client._rate_limiter, "acquire", side_effect=open_circuit),
            patch.object(client._session, "get") as get,
        ):
            assert await client._make_request("https://vlr.gg/test") is None
        get.assert_not_called()
        assert client.request_errors["https://vlr.gg/test"].error_type == "circuit"


@pytest.mark.parametrize(
    "error, kind",
    [(TimeoutError(), "timeout"), (aiohttp.ClientError("offline"), "network")],
)
async def test_request_errors_keep_context(error: Exception, kind: str) -> None:
    """Exhausted requests retain their URL and failure type."""
    async with AsyncValorantClient(cache_enabled=False) as client:
        with patch.object(client._session, "get", side_effect=error):
            assert await client._make_request("https://vlr.gg/test", retries=1) is None
        assert client.request_errors["https://vlr.gg/test"].error_type == kind


async def test_rate_limit_ignores_wall_clock() -> None:
    """Wall-clock corrections do not alter rate limiting."""
    limiter = AsyncRateLimiter(delay=1)
    with (
        patch(
            "valorant_matches.scraping.client.time.monotonic",
            side_effect=[100, 100, 100.25, 101],
        ),
        patch(
            "valorant_matches.scraping.client.time.time",
            side_effect=AssertionError("wall clock used"),
        ),
        patch(
            "valorant_matches.scraping.client.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
    ):
        await limiter.acquire()
        await limiter.acquire()
    sleep.assert_awaited_once_with(0.75)
