# Integration tests for event match-link discovery.
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.client import AsyncValorantClient
from valorant_matches.scraping.http import HttpFetcher

EVENT_URL = "https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/"


async def match_urls_for(html: str) -> list[str]:
    """Run link discovery over an event page."""
    with patch.object(
        HttpFetcher,
        "fetch",
        new_callable=AsyncMock,
        return_value=BeautifulSoup(html, "html.parser"),
    ):
        return await AsyncValorantClient(cache_enabled=False).fetch_event_match_urls(
            EVENT_URL
        )


class TestSlugMatching:
    """Tests for slug matching with regex word boundaries."""

    async def test_slug_exact_match(self) -> None:
        """The slug matches as a whole hyphen-separated segment."""
        urls = await match_urls_for(
            '<a href="/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1">1</a>'
            '<a href="/595002/team-c-vs-team-d-vct-2026-americas-kickoff-ur1">2</a>'
        )
        assert len(urls) == 2

    async def test_slug_no_false_positives(self) -> None:
        """Substring matches from other events are excluded."""
        urls = await match_urls_for(
            '<a href="/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1">ok</a>'
            '<a href="/595002/team-c-vs-team-d-valorant-challengers-vct-2026">no</a>'
            '<a href="/596003/team-e-vs-team-f-vct-americas-different-event">no</a>'
        )
        assert urls == [
            "https://vlr.gg/594001/team-a-vs-team-b-vct-2026-americas-kickoff-ur1"
        ]

    @pytest.mark.parametrize("slug", ["VCT-2026-Americas-Kickoff"])
    async def test_slug_case_insensitive(self, slug: str) -> None:
        """Slug matching ignores case."""
        urls = await match_urls_for(
            f'<a href="/594001/team-a-vs-team-b-{slug}-ur1">1</a>'
        )
        assert len(urls) == 1

    async def test_failed_event_page_returns_no_links(self) -> None:
        """A failed event request yields an empty list."""
        with patch.object(
            HttpFetcher, "fetch", new_callable=AsyncMock, return_value=None
        ):
            client = AsyncValorantClient(cache_enabled=False)
            assert await client.fetch_event_match_urls(EVENT_URL) == []
