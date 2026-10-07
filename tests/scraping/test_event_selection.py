# Tests for event selection.

from unittest.mock import Mock

from valorant_matches.scraping.discovery import DiscoveredEvent
from valorant_matches.scraping.event_selection import (
    get_event_for_region,
    select_events,
)


def make_event(event_id: str, status: str, region: str = "americas") -> DiscoveredEvent:
    """Create a discovered event test object."""
    return DiscoveredEvent(
        name=f"Event {event_id}",
        url=f"https://vlr.gg/event/matches/{event_id}/event-{event_id}/",
        event_id=event_id,
        slug=f"event-{event_id}",
        status=status,
        dates="",
        region=region,
    )


class TestGetEventForRegion:
    """Tests for view-mode aware event selection."""

    def test_prefers_ongoing_for_results_mode(self):
        """Results mode should prefer ongoing events first."""
        discovery = Mock()
        discovery.get_events_by_region.return_value = [
            make_event("101", "upcoming"),
            make_event("102", "ongoing"),
            make_event("103", "completed"),
        ]

        selected = get_event_for_region("americas", discovery, view_mode="results")

        assert selected is not None
        assert selected.status == "ongoing"
        assert selected.event_id == "102"

    def test_prefers_latest_completed_when_no_ongoing_for_results(self):
        """Results mode should use the most recent completed event over upcoming."""
        discovery = Mock()
        discovery.get_events_by_region.return_value = [
            make_event("101", "completed"),
            make_event("104", "upcoming"),
            make_event("103", "completed"),
        ]

        selected = get_event_for_region("americas", discovery, view_mode="results")

        assert selected is not None
        assert selected.status == "completed"
        assert selected.event_id == "103"

    def test_prefers_latest_completed_when_no_ongoing_for_default_mode(self):
        """Default mode should not pick an empty upcoming event over results."""
        discovery = Mock()
        discovery.get_events_by_region.return_value = [
            make_event("101", "completed", region="emea"),
            make_event("104", "upcoming", region="emea"),
            make_event("103", "completed", region="emea"),
        ]

        selected = get_event_for_region("emea", discovery)

        assert selected is not None
        assert selected.status == "completed"
        assert selected.event_id == "103"

    def test_prefers_upcoming_for_upcoming_mode(self):
        """Upcoming mode should prioritize upcoming events."""
        discovery = Mock()
        discovery.get_events_by_region.return_value = [
            make_event("100", "completed"),
            make_event("101", "ongoing"),
            make_event("102", "upcoming"),
        ]

        selected = get_event_for_region("americas", discovery, view_mode="upcoming")

        assert selected is not None
        assert selected.status == "upcoming"
        assert selected.event_id == "102"


class TestSelectEvents:
    """Tests for choosing which events a CLI run fetches."""

    def _discovery(self) -> Mock:
        discovery = Mock()
        events = {
            "americas": [
                make_event("10", "completed"),
                make_event("11", "ongoing"),
                make_event("12", "upcoming"),
            ],
            "emea": [make_event("20", "ongoing", region="emea")],
        }
        discovery.get_events_by_region.side_effect = (
            lambda region, force_refresh=False: events.get(region, [])
        )
        discovery.list_regions.return_value = ["americas", "emea", "other"]
        return discovery

    def test_event_id_wins(self) -> None:
        """An explicit event ID bypasses regional ranking."""
        discovery = self._discovery()
        discovery.get_event_by_id.return_value = make_event("42", "ongoing")
        events = select_events(discovery, event_id="42", force_refresh=True)
        assert [event.event_id for event in events] == ["42"]
        discovery.get_event_by_id.assert_called_once_with("42", force_refresh=True)

    def test_unknown_event_id(self) -> None:
        """A missing event ID selects nothing."""
        discovery = self._discovery()
        discovery.get_event_by_id.return_value = None
        assert select_events(discovery, event_id="1") == []

    def test_region_picks_best_event(self) -> None:
        """A region outside upcoming view fetches its single best event."""
        events = select_events(self._discovery(), region="americas")
        assert [event.event_id for event in events] == ["11"]

    def test_upcoming_combines_active_events(self) -> None:
        """Upcoming view fetches every active event, future first."""
        events = select_events(
            self._discovery(), region="americas", view_mode="upcoming"
        )
        assert [event.event_id for event in events] == ["12", "11"]

    def test_favorites_span_vct_regions(self) -> None:
        """Favorites without a region cover each VCT region, skipping others."""
        events = select_events(self._discovery(), favorites_only=True)
        assert [event.event_id for event in events] == ["11", "20"]

    def test_nothing_selected(self) -> None:
        """No target selects no events."""
        assert select_events(self._discovery()) == []
