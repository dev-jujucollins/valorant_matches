# Tests for event_manager.py

from unittest.mock import Mock

from event_discovery import DiscoveredEvent
from event_manager import get_event_for_region


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
