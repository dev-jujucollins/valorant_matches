# Tests for the async match client.

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import (
    FetchError,
    ListingRow,
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


def cache_entry(match: Match, schedule: str = "") -> dict:
    """Build a cache record as the client stores it."""
    return {"match": match.to_dict(), "schedule": schedule}


def listed(status: MatchStatus, schedule: str = "Thu, May 1 | 2:00 PM") -> ListingRow:
    """Build a readable listing row for URL."""
    return ListingRow(
        url=URL,
        team1="Team A",
        team2="Team B",
        status=status,
        score=None if status == "upcoming" else "1 : 0",
        countdown="2h 5m" if status == "upcoming" else None,
        schedule=schedule,
    )


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
            cache.return_value.get.return_value = cache_entry(cached)
            result = await AsyncValorantClient().process_match(URL)
        assert result.match == cached
        assert result.cache_hit
        fetch.assert_not_awaited()

    async def test_listing_refreshes_cached_match_without_request(self) -> None:
        """Status and score come from the listing; the start time from cache."""
        row = listed("live")
        cached = make_match(URL, "upcoming")
        with (
            patch("valorant_matches.scraping.client.MatchCache") as cache,
            patch.object(HttpFetcher, "fetch", new_callable=AsyncMock) as fetch,
        ):
            cache.return_value.get.return_value = cache_entry(cached, row.schedule)
            result = await AsyncValorantClient().process_match(row)
        assert result.cache_hit and result.match is not None
        assert (result.match.status, result.match.score) == ("live", "1 : 0")
        assert result.match.starts_at == cached.starts_at
        fetch.assert_not_awaited()

    async def test_rescheduled_match_is_refetched_and_recached(self) -> None:
        """A changed listing date or time means the cached start is stale."""
        row = listed("upcoming", schedule="Fri, May 2 | 4:00 PM")
        fresh = make_result(URL, "upcoming")
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
            cache.return_value.get.return_value = cache_entry(
                make_match(URL, "upcoming"), "Thu, May 1 | 2:00 PM"
            )
            result = await AsyncValorantClient().process_match(row)
        assert not result.cache_hit
        assert fetch.await_count == 1
        assert fresh.match is not None
        cache.return_value.set.assert_called_once_with(
            URL, cache_entry(fresh.match, row.schedule)
        )

    async def test_listed_tbd_match_needs_no_request(self) -> None:
        """Undecided teams are known from the listing alone."""
        row = ListingRow(url=URL, team1="TBD", team2="Team B", status="upcoming")
        with patch.object(HttpFetcher, "fetch", new_callable=AsyncMock) as fetch:
            result = await AsyncValorantClient(cache_enabled=False).process_match(row)
        assert result.is_tbd
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
        cache.return_value.set.assert_called_once_with(URL, cache_entry(fresh_match))

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

    async def test_listing_status_filters_before_any_lookup(self) -> None:
        """A row the view does not want is skipped without cache or request."""
        client = AsyncValorantClient(cache_enabled=False)
        client.process_match = AsyncMock()  # type: ignore[method-assign]
        processed = await process_matches_async(client, [listed("upcoming")], "results")
        assert processed.skipped_count == 1 and processed.results == []
        client.process_match.assert_not_awaited()

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
