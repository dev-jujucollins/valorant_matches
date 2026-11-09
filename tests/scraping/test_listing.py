"""Tests for reading an event listing and using it instead of match pages."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from valorant_matches.cache import MatchCache
from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import parse_event_listing

FIXTURES = Path(__file__).parents[1] / "fixtures" / "vlr"
EVENT_URL = "https://vlr.gg/event/matches/2766/valorant-champions-2026/"
SLUG = re.compile(r"(^|-)(valorant-champions-2026)(-|$)")


def soup_for(name: str) -> BeautifulSoup:
    """Parse a saved fixture."""
    return BeautifulSoup((FIXTURES / f"{name}.html").read_text("utf-8"), "lxml")


def test_listing_rows_carry_teams_score_and_status() -> None:
    """Each row yields what the listing shows, in page order."""
    rows = parse_event_listing(soup_for("event-listing"), SLUG)
    assert [row.url.rsplit("-", 1)[-1] for row in rows] == [
        "c",
        "gf",
        "live",
        "upcoming",
        "tbd",
        "plain",
    ]
    opener, final, live, upcoming, tbd, plain = rows

    assert (opener.team1, opener.team2) == ("Team Liquid", "Paper Rex")
    assert (opener.status, opener.score, opener.countdown) == (
        "completed",
        "1 : 2",
        None,
    )
    assert (final.team1, final.score) == ("LOUD", "3 : 1")
    assert (live.status, live.score) == ("live", "1 : 0")
    assert (upcoming.status, upcoming.score, upcoming.countdown) == (
        "upcoming",
        None,
        "2h 5m",
    )
    assert tbd.is_tbd and tbd.has_details
    assert not plain.has_details and not plain.is_tbd


def test_listing_schedule_ignores_today_tag() -> None:
    """The reschedule fingerprint is the date heading plus the clock text."""
    opener, final, *_ = parse_event_listing(soup_for("event-listing"), SLUG)
    assert opener.schedule == "Thu, September 24, 2026 | 2:00 AM"
    assert final.schedule == "Sat, October 17, 2026 | 11:00 PM"


async def test_second_run_needs_only_the_listing(tmp_path: Path) -> None:
    """Match pages are fetched once; later runs reuse their start times."""
    pages = {EVENT_URL: soup_for("event-listing")}
    requested: list[str] = []

    async def fake_fetch(self: HttpFetcher, url: str, retries: int = 3):
        requested.append(url)
        # Every match page in this run is the saved completed page.
        return pages.get(url) or soup_for("completed")

    async def run_once(view_mode: str = "all"):
        client = AsyncValorantClient(cache_enabled=False)
        client.cache = MatchCache(cache_dir=tmp_path, enabled=True)
        rows = await client.fetch_event_listing(EVENT_URL)
        return await process_matches_async(client, rows, view_mode)

    with patch.object(HttpFetcher, "fetch", fake_fetch):
        first = await run_once()
        # Listing + five match pages (the TBD row needs none).
        assert len(requested) == 6
        assert first.tbd_count == 1 and first.cache_hits == 0

        requested.clear()
        second = await run_once()
        assert requested == [EVENT_URL]
        # The plain link has no listing row, but its page was a finished match.
        assert second.cache_hits == 5

    statuses = [match.status for match in second.results]
    assert statuses == ["completed", "completed", "live", "upcoming", "completed"]
    live = second.results[2]
    # Status and score follow the listing; the start time came from the page.
    assert live.score == "1 : 0"
    assert live.starts_at is not None
    assert live.starts_at.isoformat() == "2025-12-09T09:00:00+00:00"
    assert second.results[3].countdown == "2h 5m"


async def test_unwanted_rows_cost_no_requests() -> None:
    """The results view never opens pages the listing marks as not finished."""
    client = AsyncValorantClient(cache_enabled=False)
    rows = parse_event_listing(soup_for("event-listing"), SLUG)
    with patch.object(
        HttpFetcher, "fetch", new_callable=AsyncMock, return_value=soup_for("completed")
    ) as fetch:
        processed = await process_matches_async(client, rows, "results")
    # Two listed results plus the plain link, which has to be opened to know.
    assert fetch.await_count == 3
    assert processed.skipped_count == 2 and processed.tbd_count == 1
