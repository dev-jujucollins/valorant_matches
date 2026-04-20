# Event management and region-to-event mapping.

import logging

from config import EVENTS, REGION_FALLBACK_KEYS
from event_discovery import REGION_ALIASES, DiscoveredEvent, EventDiscovery

logger = logging.getLogger("valorant_matches")


def get_event_for_region(
    region: str,
    discovery: EventDiscovery,
    force_refresh: bool = False,
    view_mode: str = "all",
) -> DiscoveredEvent | None:
    """Get the best matching event for a region using auto-discovery with fallback."""
    # Try auto-discovery first
    events = discovery.get_events_by_region(region, force_refresh=force_refresh)

    if events:
        if view_mode == "results":
            status_priority = {"ongoing": 0, "completed": 1, "upcoming": 2}
        elif view_mode == "upcoming":
            status_priority = {"upcoming": 0, "ongoing": 1, "completed": 2}
        else:
            status_priority = {"ongoing": 0, "upcoming": 1, "completed": 2}

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
        return ranked[0]

    # Fallback to hardcoded config
    logger.warning(f"No discovered events for {region}, falling back to config")

    # Normalize region and find fallback event
    for canonical, aliases in REGION_ALIASES.items():
        if region.lower() in aliases:
            key = REGION_FALLBACK_KEYS.get(canonical)
            if key and key in EVENTS:
                fallback = EVENTS[key]
                return DiscoveredEvent(
                    name=fallback.name,
                    url=fallback.url,
                    event_id=fallback.series_id,
                    slug="",
                    status="unknown",
                    dates="",
                    region=canonical,
                )
            break

    return None
