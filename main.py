#!/usr/bin/python3

import argparse
import asyncio
import logging
import logging.config
import sys

from rich.progress import Progress

from async_client import AsyncValorantClient, process_matches_async
from cli_mode import run_cli_mode
from config import EVENTS, LOGGING_CONFIG
from event_discovery import REGION_ALIASES, DiscoveredEvent, EventDiscovery
from formatter import Formatter
from interactive import run_interactive_mode
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


async def process_matches_with_progress(
    client: AsyncValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> list[tuple]:
    """Process matches asynchronously with progress display."""
    task_label = {
        "all": "Fetching all matches...",
        "results": "Fetching match results...",
        "upcoming": "Fetching upcoming matches...",
    }.get(view_mode, "Fetching matches...")

    with Progress() as progress:
        task = progress.add_task(
            f"[bright_magenta] {task_label}",
            total=len(match_links),
        )

        def update_progress():
            progress.update(task, advance=1)

        results = await process_matches_async(
            client, match_links, view_mode, progress_callback=update_progress
        )

    print("")
    return results


def process_matches(
    client: ValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> list[tuple]:
    """Process matches using async client (sync wrapper for backward compatibility)."""

    async def _run():
        async with AsyncValorantClient(
            cache_enabled=client._cache_enabled
        ) as async_client:
            return await process_matches_with_progress(
                async_client, match_links, view_mode
            )

    return asyncio.run(_run())


def _run_interactive(formatter: Formatter, discovery: EventDiscovery) -> int:
    """Wrapper for run_interactive_mode that injects process_matches."""
    return run_interactive_mode(formatter, discovery, process_matches)


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
        exit_code = run_cli_mode(
            args, formatter, discovery, process_matches, _run_interactive
        )
    else:
        # Interactive mode
        exit_code = _run_interactive(formatter, discovery)

    logger.info("Application shutdown complete")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
