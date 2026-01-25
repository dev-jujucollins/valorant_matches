# CLI mode functionality for command-line usage.

import argparse
import logging

from event_discovery import EventDiscovery
from event_manager import get_event_for_region
from formatter import Formatter
from valorant_client import ValorantClient

logger = logging.getLogger("valorant_matches")


def get_view_mode(args: argparse.Namespace) -> str:
    """Determine view mode from CLI arguments."""
    if args.upcoming:
        return "upcoming"
    elif args.results:
        return "results"
    return "all"


def run_cli_mode(
    args: argparse.Namespace,
    formatter: Formatter,
    discovery: EventDiscovery,
    process_matches_func,
    run_interactive_func,
) -> int:
    """Run in CLI mode with command line arguments, then transition to interactive.

    Args:
        args: Parsed command line arguments
        formatter: Formatter instance for output styling
        discovery: EventDiscovery instance
        process_matches_func: Function to process matches (injected to avoid circular import)
        run_interactive_func: Function to run interactive mode (injected to avoid circular import)
    """
    cache_enabled = not args.no_cache
    client = ValorantClient(cache_enabled=cache_enabled)

    if args.no_cache:
        logger.info("Cache disabled via --no-cache flag")

    # Get event using auto-discovery
    event = get_event_for_region(
        args.region, discovery, force_refresh=getattr(args, "refresh", False)
    )
    if not event:
        print(f"\n{formatter.error(f'No events found for region: {args.region}')}\n")
        return 1

    status_str = f" ({event.status})" if event.status != "unknown" else ""
    print(
        f"\n{formatter.info(f'Fetching matches for: {event.name}{status_str}', bold=True)}\n"
    )

    match_links = client.fetch_event_matches(event.url, event.slug)
    if not match_links:
        print(f"\n{formatter.warning('No matches found for the selected event')}\n")
        return 0

    view_mode = get_view_mode(args)
    results = process_matches_func(client, match_links, view_mode)

    # Log the actual number of matches being displayed
    match_type = {"upcoming": "upcoming", "results": "completed", "all": ""}
    type_str = f" {match_type[view_mode]}" if match_type[view_mode] else ""
    logger.info(f"Displaying {len(results)}{type_str} matches")
    print()

    if not results:
        if view_mode == "upcoming":
            print(
                f"\n{formatter.warning('No upcoming matches found for this event.')}\n"
            )
        elif view_mode == "results":
            print(
                f"\n{formatter.warning('No completed matches found for this event.')}\n"
            )
        else:
            print(f"\n{formatter.warning('No matches found.')}\n")
    else:
        for _, result in results:
            print(result)

    # Transition to interactive mode
    print(f"\n{formatter.muted('─' * 40)}")
    print(f"{formatter.info('Entering interactive mode...', bold=True)}\n")
    return run_interactive_func(formatter, discovery)
