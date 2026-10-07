# Event management and region-to-event mapping.

import logging

from valorant_matches.scraping.discovery import (
    REGION_ALIASES,
    DiscoveredEvent,
    EventDiscovery,
)

logger = logging.getLogger("valorant_matches")

# Events that can still produce scheduled matches.
ACTIVE_STATUSES = {"ongoing", "upcoming"}


def get_events_for_region(
    region: str,
    discovery: EventDiscovery,
    force_refresh: bool = False,
    view_mode: str = "all",
) -> list[DiscoveredEvent]:
    """Rank discovered events for a region and view mode.

    Args:
        region: Region name or alias.
        discovery: Event discovery service.
        force_refresh: Bypass the in-process discovery cache.
        view_mode: "all", "results", or "upcoming".

    Returns:
        Events ordered by status preference, newest first within a status.
    """
    events = discovery.get_events_by_region(region, force_refresh=force_refresh)
    if not events:
        logger.warning("No discovered events for region %s", region)
        return []

    if view_mode == "upcoming":
        status_priority = {"upcoming": 0, "ongoing": 1, "completed": 2}
    else:
        status_priority = {"ongoing": 0, "completed": 1, "upcoming": 2}

    def event_id_key(event: DiscoveredEvent) -> int:
        try:
            return int(event.event_id)
        except ValueError:
            return 0

    return sorted(
        events,
        key=lambda event: (status_priority.get(event.status, 3), -event_id_key(event)),
    )


def get_event_for_region(
    region: str,
    discovery: EventDiscovery,
    force_refresh: bool = False,
    view_mode: str = "all",
) -> DiscoveredEvent | None:
    """Get the preferred event for a region.

    Args:
        region: Region name or alias.
        discovery: Event discovery service.
        force_refresh: Bypass the in-process discovery cache.
        view_mode: "all", "results", or "upcoming".

    Returns:
        The best-ranked event, or None when the region has none.
    """
    events = get_events_for_region(region, discovery, force_refresh, view_mode)
    return events[0] if events else None


def _events_for(
    region: str, discovery: EventDiscovery, view_mode: str, force_refresh: bool
) -> list[DiscoveredEvent]:
    """Pick one region's events: all active ones for upcoming, else the best one."""
    if view_mode == "upcoming":
        return [
            event
            for event in get_events_for_region(
                region, discovery, force_refresh=force_refresh, view_mode=view_mode
            )
            if event.status in ACTIVE_STATUSES
        ]
    event = get_event_for_region(
        region, discovery, force_refresh=force_refresh, view_mode=view_mode
    )
    return [event] if event else []


def select_events(
    discovery: EventDiscovery,
    *,
    region: str | None = None,
    event_id: str | None = None,
    favorites_only: bool = False,
    view_mode: str = "all",
    force_refresh: bool = False,
) -> list[DiscoveredEvent]:
    """Choose which events a CLI run fetches.

    An explicit event ID wins. Favorites without a region span every VCT
    region. Upcoming views combine every active event in a region so fixtures
    from an ongoing event and a future one are both shown.

    Args:
        discovery: Event discovery service.
        region: Region name or alias.
        event_id: Discovered numeric event ID.
        favorites_only: Collect favorite-team matches across regions.
        view_mode: "all", "results", or "upcoming".
        force_refresh: Bypass the in-process discovery cache.

    Returns:
        Unique events in fetch order.
    """
    if event_id:
        event = discovery.get_event_by_id(event_id, force_refresh=force_refresh)
        events = [event] if event else []
    elif region:
        events = _events_for(region, discovery, view_mode, force_refresh)
    elif favorites_only:
        events = [
            event
            for name in discovery.list_regions()
            if name in REGION_ALIASES
            for event in _events_for(name, discovery, view_mode, force_refresh=False)
        ]
    else:
        events = []
    return list({event.event_id: event for event in events}.values())
