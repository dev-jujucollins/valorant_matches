#!/usr/bin/python3

import argparse
import asyncio
import logging
import logging.config
import sys
import tempfile

from rich.progress import Progress

from async_client import AsyncValorantClient, process_matches_async
from cli_mode import run_cli_mode
from config import CACHE_DIR, EVENTS, LOGGING_CONFIG
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

CLI_COMMAND = "valorant-matches"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch and display Valorant Champions Tour (VCT) match results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  {CLI_COMMAND}                          # Interactive mode
  {CLI_COMMAND} --region americas        # Show all Americas matches
  {CLI_COMMAND} -r emea --upcoming       # Show upcoming EMEA matches
  {CLI_COMMAND} -r china --results       # Show completed China matches
  {CLI_COMMAND} --region champions --no-cache  # Force fresh data
  {CLI_COMMAND} --list-regions           # List available regions (auto-discovered)
  {CLI_COMMAND} --refresh                # Force refresh event discovery

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
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Display matches in compact single-line format",
    )
    parser.add_argument(
        "--group-by",
        choices=["date", "status"],
        help="Group matches by date or status",
    )
    parser.add_argument(
        "--sort",
        choices=["date", "team"],
        help="Sort matches by date or team name",
    )
    parser.add_argument(
        "--export",
        choices=["json", "csv"],
        help="Export matches to JSON or CSV format",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path for export (default: matches.{format})",
    )
    parser.add_argument(
        "--team",
        type=str,
        help="Filter matches by team name (case-insensitive)",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run diagnostics for network, cache, and event discovery",
    )
    parser.add_argument(
        "--quickstart",
        action="store_true",
        help="Show a quickstart guide and exit",
    )
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh", "fish"],
        help="Print shell completion script for bash, zsh, or fish",
    )
    return parser.parse_args()


def get_completion_script(shell: str) -> str:
    """Generate shell completion script for supported shells."""
    options = [
        "-r",
        "--region",
        "--upcoming",
        "--results",
        "--no-cache",
        "--clear-cache",
        "--list-regions",
        "--refresh",
        "--compact",
        "--group-by",
        "--sort",
        "--export",
        "--output",
        "--team",
        "--doctor",
        "--quickstart",
        "--print-completion",
        "--help",
    ]
    words = " ".join(options)
    regions = " ".join(REGION_CHOICES)
    if shell == "bash":
        return f"""_valorant_matches_completions() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    if [[ "$prev" == "--region" || "$prev" == "-r" ]]; then
        COMPREPLY=($(compgen -W "{regions}" -- "$cur"))
        return 0
    fi
    COMPREPLY=($(compgen -W "{words}" -- "$cur"))
}}
complete -F _valorant_matches_completions {CLI_COMMAND}
"""
    if shell == "zsh":
        return f"""#compdef {CLI_COMMAND}
_valorant_matches_completions() {{
  local -a opts regions
  opts=({words})
  regions=({regions})
  if [[ $words[CURRENT-1] == "--region" || $words[CURRENT-1] == "-r" ]]; then
    _describe 'regions' regions
    return
  fi
  _describe 'options' opts
}}
compdef _valorant_matches_completions {CLI_COMMAND}
"""
    return f"""function __valorant_matches_complete
    set -l cmd (commandline -opc)
    set -l last (commandline -ct)
    if test (count $cmd) -ge 2
        set -l prev $cmd[-1]
        if test "$prev" = "--region" -o "$prev" = "-r"
            for r in {regions}
                echo $r
            end
            return
        end
    end
    for opt in {words}
        echo $opt
    end
end
complete -c {CLI_COMMAND} -a "(__valorant_matches_complete)"
"""


def print_quickstart(formatter: Formatter) -> None:
    """Print a concise quickstart guide."""
    print(f"\n{formatter.info('Quickstart', bold=True)}")
    print(f"{formatter.muted('1) Interactive mode:')} uv run {CLI_COMMAND}")
    print(
        f"{formatter.muted('2) Region results:')} uv run {CLI_COMMAND} -r americas --results"
    )
    print(
        f"{formatter.muted('3) Upcoming only:')} uv run {CLI_COMMAND} -r emea --upcoming"
    )
    print(
        f"{formatter.muted('4) Team filter:')} uv run {CLI_COMMAND} -r pacific --team fnatic"
    )
    print(f"{formatter.muted('5) Troubleshoot:')} uv run {CLI_COMMAND} --doctor\n")


def run_doctor(formatter: Formatter, discovery: EventDiscovery) -> int:
    """Run diagnostics and print actionable results."""
    print(f"\n{formatter.info('Running diagnostics...', bold=True)}")
    failures = 0

    if discovery.can_reach_vlr():
        print(f"{formatter.success('✓ Network check: vlr.gg reachable')}")
    else:
        failures += 1
        logger.warning("Doctor network check failed via discovery session")
        print(f"{formatter.error('✗ Network check failed')}")
        print(
            f"{formatter.muted('  Try again in a minute, or run with --refresh once connectivity returns.')}"
        )

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=CACHE_DIR, delete=True):
            pass
        print(f"{formatter.success('✓ Cache check: cache directory is writable')}")
    except OSError as e:
        failures += 1
        logger.warning(f"Doctor cache check failed: {e}")
        print(f"{formatter.error('✗ Cache check failed')}")
        print(
            f"{formatter.muted('  Verify filesystem permissions for .cache/ or run with --no-cache.')}"
        )

    events = discovery.discover_events(force_refresh=True)
    if events:
        print(
            f"{formatter.success(f'✓ Event discovery: found {len(events)} active events')}"
        )
    else:
        failures += 1
        print(f"{formatter.warning('! Event discovery returned no live events')}")
        print(
            f"{formatter.muted('  The app will use fallback events. You can still run with --region.')}"
        )

    if failures:
        print(
            f"\n{formatter.warning(f'Diagnostics finished with {failures} issue(s).')}\n"
        )
        return 1
    print(f"\n{formatter.success('Diagnostics passed. You are good to go.')}\n")
    return 0


async def process_matches_with_progress(
    client: AsyncValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> tuple[list[tuple], int]:
    """Process matches asynchronously with progress display.

    Returns:
        Tuple of (results, tbd_count).
    """
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

        results, tbd_count = await process_matches_async(
            client, match_links, view_mode, progress_callback=update_progress
        )

    print("")
    return results, tbd_count


def process_matches(
    client: ValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> tuple[list[tuple], int]:
    """Process matches using async client (sync wrapper for backward compatibility).

    Returns:
        Tuple of (results, tbd_count).
    """

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
    if args.quickstart:
        print_quickstart(formatter)
        sys.exit(0)

    if args.print_completion:
        print(get_completion_script(args.print_completion))
        sys.exit(0)

    if args.clear_cache:
        from cache import MatchCache

        cache = MatchCache()
        count = cache.clear()
        print(f"{formatter.success(f'Cleared {count} cache entries.')}")
        sys.exit(0)

    # Initialize event discovery
    discovery = EventDiscovery()
    force_refresh = getattr(args, "refresh", False)

    if args.doctor:
        exit_code = run_doctor(formatter, discovery)
        sys.exit(exit_code)

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
