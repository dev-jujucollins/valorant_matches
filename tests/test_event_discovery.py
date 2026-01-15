# Tests for the event_discovery module.
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from event_discovery import (
    REGION_ALIASES,
    DiscoveredEvent,
    EventDiscovery,
)


class TestDiscoveredEvent:
    def test_dataclass_fields(self):
        """Test DiscoveredEvent has all required fields."""
        event = DiscoveredEvent(
            name="VCT 2026: Americas Kickoff",
            url="https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/",
            event_id="2682",
            slug="vct-2026-americas-kickoff",
            status="upcoming",
            dates="Jan 15—Feb 15",
            region="americas",
        )

        assert event.name == "VCT 2026: Americas Kickoff"
        assert event.event_id == "2682"
        assert event.slug == "vct-2026-americas-kickoff"
        assert event.status == "upcoming"
        assert event.region == "americas"


class TestRegionAliases:
    def test_americas_aliases(self):
        """Test Americas region aliases."""
        assert "americas" in REGION_ALIASES
        assert "am" in REGION_ALIASES["americas"]
        assert "americas" in REGION_ALIASES["americas"]

    def test_emea_aliases(self):
        """Test EMEA region aliases."""
        assert "emea" in REGION_ALIASES
        assert "eu" in REGION_ALIASES["emea"]
        assert "emea" in REGION_ALIASES["emea"]

    def test_pacific_aliases(self):
        """Test Pacific region aliases."""
        assert "pacific" in REGION_ALIASES
        assert "apac" in REGION_ALIASES["pacific"]
        assert "pacific" in REGION_ALIASES["pacific"]

    def test_china_aliases(self):
        """Test China region aliases."""
        assert "china" in REGION_ALIASES
        assert "cn" in REGION_ALIASES["china"]
        assert "china" in REGION_ALIASES["china"]


class TestEventDiscovery:
    @pytest.fixture
    def discovery(self):
        """Create an EventDiscovery instance."""
        return EventDiscovery()

    def test_parse_region_americas(self, discovery):
        """Test region parsing for Americas."""
        assert discovery._parse_region("VCT 2026: Americas Kickoff") == "americas"

    def test_parse_region_emea(self, discovery):
        """Test region parsing for EMEA."""
        assert discovery._parse_region("VCT 2026: EMEA Kickoff") == "emea"

    def test_parse_region_pacific(self, discovery):
        """Test region parsing for Pacific."""
        assert discovery._parse_region("VCT 2026: Pacific Kickoff") == "pacific"

    def test_parse_region_china(self, discovery):
        """Test region parsing for China."""
        assert discovery._parse_region("VCT 2026: China Kickoff") == "china"

    def test_parse_region_champions(self, discovery):
        """Test region parsing for Champions."""
        assert discovery._parse_region("Valorant Champions 2026") == "champions"

    def test_parse_region_masters(self, discovery):
        """Test region parsing for Masters."""
        assert discovery._parse_region("Valorant Masters Santiago 2026") == "masters"

    def test_parse_region_unknown(self, discovery):
        """Test region parsing for unknown region."""
        assert discovery._parse_region("Some Random Tournament") == "other"

    def test_extract_event_id_valid(self, discovery):
        """Test event ID extraction from valid href."""
        result = discovery._extract_event_id("/event/2682/vct-2026-americas-kickoff")
        assert result == ("2682", "vct-2026-americas-kickoff")

    def test_extract_event_id_invalid(self, discovery):
        """Test event ID extraction from invalid href."""
        result = discovery._extract_event_id("/other/path")
        assert result is None

    def test_is_vct_international_kickoff(self, discovery):
        """Test VCT international check for Kickoff events."""
        assert discovery._is_vct_international("VCT 2026: Americas Kickoff") is True

    def test_is_vct_international_champions(self, discovery):
        """Test VCT international check for Champions."""
        assert discovery._is_vct_international("Valorant Champions 2026") is True

    def test_is_vct_international_masters(self, discovery):
        """Test VCT international check for Masters."""
        assert discovery._is_vct_international("Valorant Masters London 2026") is True

    def test_is_vct_international_challengers_excluded(self, discovery):
        """Test Challengers events are excluded."""
        assert discovery._is_vct_international("VCT Challengers NA") is False

    def test_is_vct_international_game_changers_excluded(self, discovery):
        """Test Game Changers events are excluded."""
        assert discovery._is_vct_international("VCT Game Changers NA") is False

    def test_is_vct_international_random_excluded(self, discovery):
        """Test random tournaments are excluded."""
        assert discovery._is_vct_international("Random Tournament 2026") is False

    @patch.object(EventDiscovery, "_make_request")
    def test_discover_events_parses_html(self, mock_request, discovery):
        """Test event discovery parses HTML correctly."""
        mock_html = """
        <html>
        <body>
            <a href="/event/2682/vct-2026-americas-kickoff">VCT 2026: Americas Kickoff</a>
            <a href="/event/2684/vct-2026-emea-kickoff">VCT 2026: EMEA Kickoff</a>
            <a href="/event/9999/challengers-na">Challengers NA</a>
        </body>
        </html>
        """
        mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

        events = discovery.discover_events(force_refresh=True)

        # Should find 2 VCT events (Challengers excluded)
        assert len(events) == 2
        assert events[0].event_id == "2682"
        assert events[1].event_id == "2684"

    @patch.object(EventDiscovery, "_make_request")
    def test_discover_events_request_fails(self, mock_request, discovery):
        """Test event discovery when request fails."""
        mock_request.return_value = None

        events = discovery.discover_events(force_refresh=True)

        assert events == []

    @patch.object(EventDiscovery, "_make_request")
    def test_discover_events_uses_cache(self, mock_request, discovery):
        """Test event discovery uses cache on subsequent calls."""
        mock_html = """
        <html><body>
            <a href="/event/2682/vct-2026-americas-kickoff">VCT 2026: Americas Kickoff</a>
        </body></html>
        """
        mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

        # First call
        events1 = discovery.discover_events(force_refresh=True)
        # Second call should use cache
        events2 = discovery.discover_events()

        # Request should only be made once
        assert mock_request.call_count == 1
        assert events1 == events2

    @patch.object(EventDiscovery, "discover_events")
    def test_get_events_by_region(self, mock_discover, discovery):
        """Test filtering events by region."""
        mock_discover.return_value = [
            DiscoveredEvent(
                name="VCT 2026: Americas Kickoff",
                url="https://vlr.gg/event/matches/2682/vct-2026-americas-kickoff/",
                event_id="2682",
                slug="vct-2026-americas-kickoff",
                status="upcoming",
                dates="",
                region="americas",
            ),
            DiscoveredEvent(
                name="VCT 2026: EMEA Kickoff",
                url="https://vlr.gg/event/matches/2684/vct-2026-emea-kickoff/",
                event_id="2684",
                slug="vct-2026-emea-kickoff",
                status="upcoming",
                dates="",
                region="emea",
            ),
        ]

        americas_events = discovery.get_events_by_region("americas")
        assert len(americas_events) == 1
        assert americas_events[0].region == "americas"

        # Test alias
        am_events = discovery.get_events_by_region("am")
        assert len(am_events) == 1

    @patch.object(EventDiscovery, "discover_events")
    def test_get_events_by_region_unknown(self, mock_discover, discovery):
        """Test filtering by unknown region returns empty list."""
        mock_discover.return_value = []

        events = discovery.get_events_by_region("unknown_region")
        assert events == []

    @patch.object(EventDiscovery, "discover_events")
    def test_list_regions(self, mock_discover, discovery):
        """Test listing available regions."""
        mock_discover.return_value = [
            DiscoveredEvent(
                name="VCT 2026: Americas Kickoff",
                url="",
                event_id="1",
                slug="",
                status="",
                dates="",
                region="americas",
            ),
            DiscoveredEvent(
                name="VCT 2026: EMEA Kickoff",
                url="",
                event_id="2",
                slug="",
                status="",
                dates="",
                region="emea",
            ),
        ]

        regions = discovery.list_regions()
        assert "americas" in regions
        assert "emea" in regions
