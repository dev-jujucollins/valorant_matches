#!/usr/bin/python3

import argparse
import logging
import logging.config
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress

from config import EVENTS, LOGGING_CONFIG, MAX_WORKERS
from formatter import Formatter
from valorant_client import ValorantClient

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")

# Region name mappings for CLI
REGION_ALIASES = {
    "americas": "1",
    "am": "1",
    "emea": "2",
    "eu": "2",
    "apac": "3",
    "pacific": "3",
    "china": "4",
    "cn": "4",
    "champions": "5",
    "champs": "5",
}


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

Available regions:
  americas (am)    - VCT Americas Kickoff
  emea (eu)        - VCT EMEA Kickoff
  apac (pacific)   - VCT Pacific Kickoff
  china (cn)       - VCT China Kickoff
  champions        - VCT Champions Playoffs
        """,
    )
    parser.add_argument(
        "-r",
        "--region",
        type=str,
        choices=list(REGION_ALIASES.keys()),
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
                result = future.result()
                if result is not None:
                    # For results_only mode, skip upcoming matches
                    if results_only and "UPCOMING" in result:
                        pass
                    else:
                        results.append((futures_to_link[future], result))
                progress.update(task, advance=1)
                time.sleep(0.5)  # Rate limiting

        print("")
    return sorted(results, key=lambda x: match_links.index(x[0]))


def run_cli_mode(args: argparse.Namespace, formatter: Formatter) -> int:
    """Run in CLI mode with command line arguments."""
    cache_enabled = not args.no_cache
    client = ValorantClient(cache_enabled=cache_enabled)

    if args.no_cache:
        logger.info("Cache disabled via --no-cache flag")

    # Get event URL from region
    event_key = REGION_ALIASES.get(args.region)
    if not event_key or event_key not in EVENTS:
        print(f"\n{formatter.error(f'Invalid region: {args.region}')}\n")
        return 1

    event = EVENTS[event_key]
    print(f"\n{formatter.info(f'Fetching matches for: {event.name}', bold=True)}\n")

    match_links = client.fetch_event_matches(event.url)
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


def run_interactive_mode(formatter: Formatter) -> int:
    """Run in interactive mode with menus."""
    client = ValorantClient()

    while True:
        try:
            selected_option = client.display_menu()
            if selected_option == "6":
                logger.info("User chose to exit")
                print(
                    f"\n{formatter.success('Thank you for using the Valorant Match Tracker!')}"
                )
                break

            event_url = client.get_event_url(selected_option)
            if not event_url:
                logger.warning("Invalid event selection")
                print(f"\n{formatter.error('Invalid choice. Please try again.')}\n")
                continue

            match_links = client.fetch_event_matches(event_url)
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
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
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

    if args.list_regions:
        print(f"\n{formatter.info('Available regions:', bold=True)}\n")
        for key, event in EVENTS.items():
            # Find aliases for this key
            aliases = [alias for alias, k in REGION_ALIASES.items() if k == key]
            alias_str = ", ".join(aliases) if aliases else ""
            print(f"  {formatter.primary(alias_str, bold=True)}: {event.name}")
        print()
        sys.exit(0)

    print(
        f"\n{formatter.format('Valorant Champions Tour 2025', 'bright_cyan', bold=True)}"
    )
    print(f"{formatter.format('=' * 40, 'bright_magenta')}\n")

    # Determine mode based on arguments
    if args.region:
        # CLI mode
        exit_code = run_cli_mode(args, formatter)
    else:
        # Interactive mode
        exit_code = run_interactive_mode(formatter)

    logger.info("Application shutdown complete")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
