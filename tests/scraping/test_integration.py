# Integration tests for cross-module behavior.
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.client import AsyncValorantClient


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
        from valorant_matches.scraping.discovery import REGION_ALIASES

        for region in REGION_ALIASES:
            assert region in REGION_FALLBACK_KEYS, f"Missing fallback key for {region}"

    def test_region_fallback_keys_valid_events(self):
        """Test that all fallback keys point to valid events."""
        from valorant_matches.config import EVENTS, REGION_FALLBACK_KEYS

        for region, key in REGION_FALLBACK_KEYS.items():
            assert key in EVENTS, f"Invalid event key '{key}' for region '{region}'"
