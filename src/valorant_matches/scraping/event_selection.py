# Event management and region-to-event mapping.

import logging

from valorant_matches.scraping.discovery import (
    DiscoveredEvent,
    EventDiscovery,
)

logger = logging.getLogger("valorant_matches")


def get_events_for_region(
    region: str,
    discovery: EventDiscovery,
    force_refresh: bool = False,
    view_mode: str = "all",
) -> list[DiscoveredEvent]:
    """Rank discovered events for a region and view mode."""
    events = discovery.get_events_by_region(region, force_refresh=force_refresh)

    if events:
        if view_mode == "results":
            status_priority = {"ongoing": 0, "completed": 1, "upcoming": 2}
        elif view_mode == "upcoming":
            status_priority = {"upcoming": 0, "ongoing": 1, "completed": 2}
        else:
            status_priority = {"ongoing": 0, "completed": 1, "upcoming": 2}

        def event_id_key(event: DiscoveredEvent) -> int:
            try:
                return int(event.event_id)
            except ValueError:
                return 0

        ranked = sorted(
            events,
            key=lambda event: (
                status_priority.get(event.status, 3),
                -event_id_key(event),
            ),
        )
        return ranked
    logger.warning("No discovered events for region %s", region)
    return []


def get_event_for_region(
    region: str,
    discovery: EventDiscovery,
    force_refresh: bool = False,
    view_mode: str = "all",
) -> DiscoveredEvent | None:
    """Get one preferred event for existing single-event workflows."""
    events = get_events_for_region(region, discovery, force_refresh, view_mode)
    return events[0] if events else None
