#!/usr/bin/python3

import argparse
import json
import logging
import logging.config
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress

from config import (
    EVENTS,
    LOGGING_CONFIG,
    MAX_WORKERS,
    RATE_LIMIT_DELAY,
    REGION_FALLBACK_KEYS,
)
from event_discovery import REGION_ALIASES, DiscoveredEvent, EventDiscovery
from formatter import Formatter
from valorant_client import ValorantClient

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")

# Flatten region aliases for argparse choices
REGION_CHOICES = []
for aliases in REGION_ALIASES.values():
    REGION_CHOICES.extend(aliases)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch and display Valorant Champions Tour (VCT) match results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Interactive mode
  python main.py --region americas        # Show all Americas matches
  python main.py -r emea --upcoming       # Show upcoming EMEA matches
  python main.py -r china --results       # Show completed China matches
  python main.py --region champions --no-cache  # Force fresh data
  python main.py --list-regions           # List available regions (auto-discovered)
  python main.py --refresh                # Force refresh event discovery

Available regions:
  americas (am)    - VCT Americas
  emea (eu)        - VCT EMEA
  pacific (apac)   - VCT Pacific
  china (cn)       - VCT China
  champions        - Valorant Champions
  masters          - Valorant Masters
        """,
    )
    parser.add_argument(
        "-r",
        "--region",
        type=str,
        choices=REGION_CHOICES,
        help="Region/event to fetch matches for",
    )
    parser.add_argument(
        "--upcoming",
        action="store_true",
        help="Show only upcoming/scheduled matches",
    )
    parser.add_argument(
        "--results",
        action="store_true",
        help="Show only completed match results",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache and fetch fresh data",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear all cached data and exit",
    )
    parser.add_argument(
        "--list-regions",
        action="store_true",
        help="List available regions and exit",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh event discovery from vlr.gg",
    )
    return parser.parse_args()


def get_view_mode(args: argparse.Namespace) -> str:
    """Determine view mode from CLI arguments."""
    if args.upcoming:
        return "upcoming"
    elif args.results:
        return "results"
    return "all"


def process_matches(
    client: ValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> list[tuple]:
    # Process matches concurrently and return results.
    # view_mode: "all", "results", or "upcoming"
    results = []
    upcoming_only = view_mode == "upcoming"
    results_only = view_mode == "results"

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures_to_link = {
            executor.submit(client.process_match, link, upcoming_only): link
            for link in match_links
        }

        task_label = {
            "all": "Fetching all matches...",
            "results": "Fetching match results...",
            "upcoming": "Fetching upcoming matches...",
        }.get(view_mode, "Fetching matches...")

        with Progress() as progress:
            task = progress.add_task(
                f"[bright_magenta] {task_label}",
                total=len(futures_to_link),
            )

            for future in as_completed(futures_to_link):
                try:
                    result = future.result()
                    if result is not None:
                        # For results_only mode, skip upcoming matches
                        if results_only and "UPCOMING" in result:
                            pass
                        else:
                            results.append((futures_to_link[future], result))
                except Exception as e:
                    logger.warning(f"Failed to process match: {e}")
                progress.update(task, advance=1)
                time.sleep(RATE_LIMIT_DELAY)

        print("")
    return sorted(results, key=lambda x: match_links.index(x[0]))


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


def run_cli_mode(
    args: argparse.Namespace, formatter: Formatter, discovery: EventDiscovery
) -> int:
    """Run in CLI mode with command line arguments."""
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
    results = process_matches(client, match_links, view_mode)

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

    return 0


def run_interactive_mode(formatter: Formatter, discovery: EventDiscovery) -> int:
    """Run in interactive mode with menus."""
    from requests.exceptions import RequestException

    client = ValorantClient()
    force_refresh = False

    while True:
        try:
            # Discover events and build menu
            events = discovery.discover_events(force_refresh=force_refresh)
            force_refresh = False  # Reset after use

            if not events:
                # Fallback to hardcoded events
                logger.warning("No events discovered, using fallback config")
                events = [
                    DiscoveredEvent(
                        name=e.name,
                        url=e.url,
                        event_id=e.series_id,
                        slug="",
                        status="unknown",
                        dates="",
                        region="",
                    )
                    for e in EVENTS.values()
                ]

            # Display event menu
            print(f"\n{formatter.info(' Available Events:', bold=True)}")
            for i, event in enumerate(events, 1):
                status = f" [{event.status}]" if event.status != "unknown" else ""
                print(
                    f"{formatter.primary(f'{i}.', bold=True)} "
                    f"{formatter.highlight(event.name)}"
                    f"{formatter.muted(status)}"
                )
            print(
                f"{formatter.primary(f'{len(events) + 1}.', bold=True)} "
                f"{formatter.muted('Refresh events')}"
            )
            print(
                f"{formatter.primary(f'{len(events) + 2}.', bold=True)} "
                f"{formatter.muted('Exit')}\n"
            )

            selected = input(
                f"{formatter.info('Select an event:', bold=True)} "
            ).strip()

            # Handle refresh
            if selected == str(len(events) + 1):
                logger.info("User requested event refresh")
                print(f"\n{formatter.info('Refreshing events...')}")
                force_refresh = True
                continue

            # Handle exit
            if selected == str(len(events) + 2):
                logger.info("User chose to exit")
                print(
                    f"\n{formatter.success('Thank you for using the Valorant Match Tracker!')}"
                )
                break

            # Validate selection
            try:
                idx = int(selected) - 1
                if idx < 0 or idx >= len(events):
                    raise ValueError("Index out of range")
                event = events[idx]
            except (ValueError, IndexError):
                logger.warning(f"Invalid event selection: {selected}")
                print(
                    f"\n{formatter.error('Invalid choice. Please enter a number from the menu.')}\n"
                )
                continue

            match_links = client.fetch_event_matches(event.url, event.slug)
            if not match_links:
                logger.warning("No matches found for selected event")
                print(
                    f"\n{formatter.warning('No matches found for the selected event')}\n"
                )
                continue

            # Show view mode menu
            view_mode_option = client.display_view_mode_menu()
            if view_mode_option == "4":
                continue  # Back to events

            view_mode_map = {"1": "all", "2": "results", "3": "upcoming"}
            view_mode = view_mode_map.get(view_mode_option, "all")

            results = process_matches(client, match_links, view_mode)

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

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            print(
                f"\n{formatter.warning('Application interrupted by user. Exiting...')}"
            )
            break
        except RequestException as e:
            logger.error(f"Network error: {e}")
            print(
                f"\n{formatter.error('Network error. Please check your connection and try again.')}\n"
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Data parsing error: {e}", exc_info=True)
            print(
                f"\n{formatter.error('Failed to parse response data. Please try again.')}\n"
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            print(
                f"\n{formatter.error('An unexpected error occurred. Please try again.')}\n"
            )

    return 0


def main() -> None:
    logger.info("Starting Valorant Matches application")
    args = parse_args()

    # Create a formatter instance for main application
    formatter = Formatter()

    # Handle special commands first
    if args.clear_cache:
        from cache import MatchCache

        cache = MatchCache()
        count = cache.clear()
        print(f"{formatter.success(f'Cleared {count} cache entries.')}")
        sys.exit(0)

    # Initialize event discovery
    discovery = EventDiscovery()
    force_refresh = getattr(args, "refresh", False)

    if args.list_regions:
        print(f"\n{formatter.info('Discovering VCT events...', bold=True)}\n")
        events = discovery.discover_events(force_refresh=force_refresh)

        if events:
            print(f"{formatter.info('Available events:', bold=True)}\n")
            # Group by region
            by_region: dict[str, list[DiscoveredEvent]] = {}
            for event in events:
                by_region.setdefault(event.region, []).append(event)

            for region, region_events in sorted(by_region.items()):
                aliases = REGION_ALIASES.get(region, [region])
                alias_str = ", ".join(aliases)
                print(f"  {formatter.primary(alias_str, bold=True)}:")
                for event in region_events:
                    status = f" [{event.status}]" if event.status else ""
                    print(f"    - {event.name}{formatter.muted(status)}")
                print()
        else:
            print(f"{formatter.warning('No events discovered, showing fallback:')}\n")
            for key, event in EVENTS.items():
                print(f"  {formatter.primary(key, bold=True)}: {event.name}")
            print()
        sys.exit(0)

    print(f"\n{formatter.format('Valorant Champions Tour', 'bright_cyan', bold=True)}")
    print(f"{formatter.format('=' * 40, 'bright_magenta')}\n")

    # Determine mode based on arguments
    if args.region:
        # CLI mode
        exit_code = run_cli_mode(args, formatter, discovery)
    else:
        # Interactive mode
        exit_code = run_interactive_mode(formatter, discovery)

    logger.info("Application shutdown complete")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
