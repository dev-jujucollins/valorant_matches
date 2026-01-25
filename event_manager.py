# Event management and region-to-event mapping.

import logging

from config import EVENTS, REGION_FALLBACK_KEYS
from event_discovery import REGION_ALIASES, DiscoveredEvent, EventDiscovery

logger = logging.getLogger("valorant_matches")


def get_event_for_region(
    region: str, discovery: EventDiscovery, force_refresh: bool = False
) -> DiscoveredEvent | None:
    """Get the best matching event for a region using auto-discovery with fallback."""
    # Try auto-discovery first
    events = discovery.get_events_by_region(region, force_refresh=force_refresh)

    if events:
        # Prefer ongoing events, then upcoming, then most recent
        ongoing = [e for e in events if e.status == "ongoing"]
        if ongoing:
            return ongoing[0]
        upcoming = [e for e in events if e.status == "upcoming"]
        if upcoming:
            return upcoming[0]
        return events[0]

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
