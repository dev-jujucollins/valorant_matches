# Tests for the async match client.

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import (
    FetchError,
    Match,
    MatchStatus,
    ProcessMatchResult,
)


def make_match(url: str, status: MatchStatus = "completed") -> Match:
    """Build a match with the given status."""
    return Match(
        url=url,
        team1="Team A",
        team2="Team B",
        status=status,
        score="2 : 1" if status != "upcoming" else None,
        starts_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_result(url: str, status: MatchStatus = "completed") -> ProcessMatchResult:
    """Build a ProcessMatchResult for a successful match fetch."""
    return ProcessMatchResult(match=make_match(url, status))


URL = "https://vlr.gg/123/match"


class TestClientCacheControl:
    """Tests for cache enable/disable wiring."""

    def test_cache_enabled_by_default(self) -> None:
        """Cache should be enabled unless disabled explicitly."""
        with patch("valorant_matches.scraping.client.MatchCache") as cache:
            AsyncValorantClient()
        cache.assert_called_once_with(enabled=True)

    def test_cache_disabled(self) -> None:
        """Cache can be disabled via constructor."""
        with patch("valorant_matches.scraping.client.MatchCache") as cache:
            AsyncValorantClient(cache_enabled=False)
        cache.assert_called_once_with(enabled=False)

    def test_default_client_honors_environment_cache_setting(self) -> None:
        """Client default passes the configured cache choice to storage."""
        with (
            patch("valorant_matches.scraping.client.CACHE_ENABLED", False),
            patch("valorant_matches.scraping.client.MatchCache") as cache,
        ):
            AsyncValorantClient()
        cache.assert_called_once_with(enabled=False)


class TestProcessMatch:
    """Tests for AsyncValorantClient.process_match."""

    async def test_cached_completed_match_skips_request(self) -> None:
        """A valid cached result is used without a request."""
        cached = make_match(URL)
        with (
            patch("valorant_matches.scraping.client.MatchCache") as cache,
            patch.object(HttpFetcher, "fetch", new_callable=AsyncMock) as fetch,
        ):
            cache.return_value.get.return_value = cached.to_dict()
            result = await AsyncValorantClient().process_match(URL)
        assert result.match == cached
        assert result.cache_hit
        fetch.assert_not_awaited()

    async def test_cached_match_skipped_in_upcoming_view(self) -> None:
        """A cached completed match is known not to be upcoming."""
        with (
            patch("valorant_matches.scraping.client.MatchCache") as cache,
            patch.object(HttpFetcher, "fetch", new_callable=AsyncMock) as fetch,
        ):
            cache.return_value.get.return_value = make_match(URL).to_dict()
            result = await AsyncValorantClient().process_match(URL, upcoming_only=True)
        assert result.skipped and result.cache_hit
        fetch.assert_not_awaited()

    async def test_malformed_cached_match_refetches(self) -> None:
        """An incomplete cached record must not block a fresh result."""
        fresh_match = make_match(URL)
        fresh = ProcessMatchResult(match=fresh_match)
        with (
            patch("valorant_matches.scraping.client.MatchCache") as cache,
            patch.object(
                HttpFetcher,
                "fetch",
                new_callable=AsyncMock,
                return_value=BeautifulSoup("<html></html>", "lxml"),
            ) as fetch,
            patch(
                "valorant_matches.scraping.client.build_match_from_soup",
                return_value=fresh,
            ),
        ):
            cache.return_value.get.return_value = {"team1": "A"}
            result = await AsyncValorantClient().process_match(URL)
        assert result.match == fresh_match
        assert fetch.await_count == 1
        cache.return_value.invalidate.assert_called_once_with(URL)
        cache.return_value.set.assert_called_once_with(URL, fresh_match.to_dict())

    async def test_unfinished_match_is_not_cached(self) -> None:
        """Live and upcoming results clear any cached copy instead."""
        with (
            patch("valorant_matches.scraping.client.MatchCache") as cache,
            patch.object(
                HttpFetcher,
                "fetch",
                new_callable=AsyncMock,
                return_value=BeautifulSoup("<html></html>", "lxml"),
            ),
            patch(
                "valorant_matches.scraping.client.build_match_from_soup",
                return_value=make_result(URL, "live"),
            ),
        ):
            cache.return_value.get.return_value = None
            await AsyncValorantClient().process_match(URL)
        cache.return_value.set.assert_not_called()
        cache.return_value.invalidate.assert_called_once_with(URL)

    async def test_fetch_failure_reports_recorded_error(self) -> None:
        """The fetcher's recorded error is passed through."""
        client = AsyncValorantClient(cache_enabled=False)
        client.http.errors[URL] = FetchError(URL, "http", "HTTP 503")
        with patch.object(HttpFetcher, "fetch", new_callable=AsyncMock) as fetch:
            fetch.return_value = None
            result = await client.process_match(URL)
        assert result.error is not None
        assert result.error.message == "HTTP 503"


class TestProcessMatchesAsync:
    """Tests for process_matches_async."""

    async def test_empty_match_urls(self) -> None:
        """No URLs produce an empty result."""
        processed = await process_matches_async(
            AsyncValorantClient(cache_enabled=False), []
        )
        assert processed.results == []
        assert processed.tbd_count == 0

    async def test_progress_callback_called(self) -> None:
        """The callback runs once per match."""
        calls: list[int] = []
        client = AsyncValorantClient(cache_enabled=False)
        client.process_match = AsyncMock(return_value=ProcessMatchResult())
        await process_matches_async(
            client,
            ["https://vlr.gg/1/a", "https://vlr.gg/2/b"],
            progress_callback=lambda: calls.append(1),
        )
        assert len(calls) == 2

    async def test_concurrent_processing_keeps_page_order(self) -> None:
        """Matches run concurrently but results keep the event page order."""
        delays = {"https://vlr.gg/1": 0.15, "https://vlr.gg/2": 0.05}
        started: list[float] = []

        async def fake_process(url: str, upcoming_only: bool = False):
            started.append(asyncio.get_running_loop().time())
            await asyncio.sleep(delays[url])
            return make_result(url)

        client = AsyncValorantClient(cache_enabled=False)
        client.process_match = fake_process  # type: ignore[method-assign]
        processed = await process_matches_async(client, list(delays))
        assert max(started) - min(started) < 0.05
        assert [match.url for match in processed.results] == list(delays)

    async def test_exception_handling(self) -> None:
        """Unexpected exceptions count as failures with the match URL."""

        async def fake_process(url: str, upcoming_only: bool = False):
            if "error" in url:
                raise ValueError("Test error")
            return make_result(url)

        client = AsyncValorantClient(cache_enabled=False)
        client.process_match = fake_process  # type: ignore[method-assign]
        processed = await process_matches_async(
            client, ["https://vlr.gg/1/error", "https://vlr.gg/2/good"]
        )
        assert [match.url for match in processed.results] == ["https://vlr.gg/2/good"]
        assert processed.failed_count == 1
        assert processed.errors[0].url == "https://vlr.gg/1/error"

    async def test_view_mode_filters_by_status(self) -> None:
        """Results view skips matches that are not completed."""
        results = {
            "https://vlr.gg/1": make_result("https://vlr.gg/1"),
            "https://vlr.gg/2": make_result("https://vlr.gg/2", "upcoming"),
            "https://vlr.gg/3": ProcessMatchResult(is_tbd=True),
        }

        async def fake_process(url: str, upcoming_only: bool = False):
            return results[url]

        client = AsyncValorantClient(cache_enabled=False)
        client.process_match = fake_process  # type: ignore[method-assign]
        processed = await process_matches_async(client, list(results), "results")
        assert [match.url for match in processed.results] == ["https://vlr.gg/1"]
        assert processed.skipped_count == 1
        assert processed.tbd_count == 1
