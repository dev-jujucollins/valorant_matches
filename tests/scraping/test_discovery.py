# Tests for event discovery.
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.discovery import (
    VCT_EVENTS_URL,
    DiscoveredEvent,
    EventDiscovery,
)


class TestEventDiscovery:
    @pytest.fixture
    def discovery(self, tmp_path):
        """Create an EventDiscovery instance."""
        return EventDiscovery(season=2026, snapshot_dir=tmp_path)

    def test_default_season_tracks_calendar_year(self, tmp_path: Path) -> None:
        """Default season rolls over without a source-code edit."""
        assert EventDiscovery(snapshot_dir=tmp_path).season == datetime.now().year

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

    def test_parse_region_college_championship_is_other(self, discovery):
        """Test collegiate championships are not parsed as Champions."""
        assert discovery._parse_region("College VALORANT Championship 2026") == "other"

    def test_parse_region_masters(self, discovery):
        """Test region parsing for Masters."""
        assert discovery._parse_region("Valorant Masters Santiago 2026") == "masters"

    def test_older_champions_tour_names(self, tmp_path: Path) -> None:
        """Historical season option recognizes the older VCT naming scheme."""
        html = BeautifulSoup(
            '<a href="/event/100/champions-tour-2024-americas-stage-2">'
            "Champions Tour 2024: Americas Stage 2</a>"
            '<a href="/event/101/champions-tour-2024-masters-shanghai">'
            "Champions Tour 2024: Masters Shanghai</a>",
            "html.parser",
        )
        older = EventDiscovery(season=2024, snapshot_dir=tmp_path)
        with patch.object(older, "_make_request", return_value=html):
            events = older.discover_events()
        assert [event.region for event in events] == ["americas", "masters"]

    def test_historical_season_uses_older_pages(self, tmp_path: Path) -> None:
        """Explicit older seasons follow VLR's VCT pagination."""
        first = BeautifulSoup(
            '<a href="/event/100/champions-tour-2024-americas-stage-2">'
            "Champions Tour 2024: Americas Stage 2</a>",
            "html.parser",
        )
        second = BeautifulSoup(
            '<a href="/event/90/vct-2023-americas-kickoff">'
            "VCT 2023: Americas Kickoff</a>"
            '<a href="/event/80/vct-2022-americas-kickoff">'
            "VCT 2022: Americas Kickoff</a>",
            "html.parser",
        )
        discovery = EventDiscovery(season=2023, snapshot_dir=tmp_path)
        with patch.object(
            discovery, "_make_request", side_effect=[first, second]
        ) as request:
            events = discovery.discover_events()
        assert [event.event_id for event in events] == ["90"]
        assert request.call_count == 2

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

    def test_is_vct_international_college_championship_excluded(self, discovery):
        """Test collegiate championships are excluded."""
        assert (
            discovery._is_vct_international("College VALORANT Championship 2026")
            is False
        )

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
            <a href="/event/3000/college-valorant-championship-2026">College VALORANT Championship 2026</a>
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
        mock_request.assert_called_once_with(VCT_EVENTS_URL)

    def test_snapshot_recovers_across_processes(self, tmp_path: Path) -> None:
        """A later process uses its season's saved events during an outage."""
        html = BeautifulSoup(
            '<a href="/event/2682/vct-2026-americas-kickoff">VCT 2026: Americas Kickoff</a>',
            "html.parser",
        )
        first = EventDiscovery(season=2026, snapshot_dir=tmp_path)
        with patch.object(first, "_make_request", return_value=html):
            assert len(first.discover_events()) == 1

        later = EventDiscovery(season=2026, snapshot_dir=tmp_path)
        with patch.object(later, "_make_request", return_value=None):
            events = later.discover_events()
        assert [event.event_id for event in events] == ["2682"]
        assert later.is_stale is True
        assert later.last_updated is not None

    def test_selected_season_excludes_other_years(self, tmp_path: Path) -> None:
        """Season selection never silently returns another year's events."""
        html = BeautifulSoup(
            '<a href="/event/1/vct-2025-americas-kickoff">VCT 2025: Americas Kickoff</a>'
            '<a href="/event/2/vct-2026-americas-kickoff">VCT 2026: Americas Kickoff</a>',
            "html.parser",
        )
        discovery = EventDiscovery(season=2025, snapshot_dir=tmp_path)
        with patch.object(discovery, "_make_request", return_value=html):
            events = discovery.discover_events()
        assert [event.event_id for event in events] == ["1"]

    @patch.object(EventDiscovery, "_make_request")
    def test_discover_events_request_fails(self, mock_request, discovery):
        """Test event discovery when request fails."""
        mock_request.return_value = None

        events = discovery.discover_events(force_refresh=True)

        assert events == []

    @patch.object(EventDiscovery, "_make_request")
    def test_can_reach_vlr_uses_shared_request_path(self, mock_request, discovery):
        """Connectivity checks should reuse discovery request settings."""
        mock_request.return_value = BeautifulSoup("<html></html>", "html.parser")

        assert discovery.can_reach_vlr() is True
        mock_request.assert_called_once()

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


def test_discovery_skips_non_string_link_attributes(tmp_path) -> None:
    """Malformed multi-valued hrefs must not break event discovery."""
    soup = BeautifulSoup(
        '<a href="/event/1/vct-2026-americas-kickoff">Event</a>',
        "lxml",
        multi_valued_attributes={"a": ["href"]},
    )
    discovery = EventDiscovery(season=2026, snapshot_dir=tmp_path)
    with patch.object(discovery, "_make_request", return_value=soup):
        assert discovery.discover_events(force_refresh=True) == []
