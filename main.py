#!/usr/bin/python3

import argparse
import asyncio
import logging
import logging.config
import shutil
import sys
import tempfile
from pathlib import Path

from rich.progress import Progress

from async_client import AsyncValorantClient, process_matches_async
from cli_mode import run_cli_mode
from config import CACHE_DIR, EVENTS, LOGGING_CONFIG
from config_profile import UserProfile, config_manager
from event_discovery import REGION_ALIASES, DiscoveredEvent, EventDiscovery
from formatter import Formatter
from interactive import run_interactive_mode
from match_extractor import ProcessedMatches
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
  {CLI_COMMAND} --interactive -r americas # Fetch region, then open interactive mode
  {CLI_COMMAND} config set default-region americas
  {CLI_COMMAND} completion install zsh

Available regions:
  americas (am)    - VCT Americas
  emea (eu)        - VCT EMEA
  pacific (apac)   - VCT Pacific
  china (cn)       - VCT China
  champions        - Valorant Champions
  masters          - Valorant Masters
        """,
    )
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config", help="Manage saved defaults")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_subparsers.required = True

    config_set = config_subparsers.add_parser("set", help="Set a saved default")
    config_set.add_argument(
        "key",
        choices=[
            "default-region",
            "default-view",
            "compact",
            "sort",
            "group-by",
            "cache",
        ],
    )
    config_set.add_argument("value")

    config_get = config_subparsers.add_parser("get", help="Show saved config")
    config_get.add_argument("key", nargs="?")

    config_favorites = config_subparsers.add_parser(
        "favorite", help="Manage favorite teams"
    )
    config_favorites.add_argument("action", choices=["add", "remove", "list"])
    config_favorites.add_argument("team", nargs="?")

    config_subparsers.add_parser("reset", help="Reset saved config")

    completion_parser = subparsers.add_parser(
        "completion", help="Print or install shell completion"
    )
    completion_subparsers = completion_parser.add_subparsers(dest="completion_command")
    completion_subparsers.required = True
    completion_print = completion_subparsers.add_parser(
        "print", help="Print completion script"
    )
    completion_print.add_argument("shell", choices=["bash", "zsh", "fish"])
    completion_install = completion_subparsers.add_parser(
        "install", help="Install completion script"
    )
    completion_install.add_argument("shell", choices=["bash", "zsh", "fish"])

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
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enter interactive mode after CLI results",
    )
    return parser.parse_args()


def get_completion_script(shell: str) -> str:
    """Generate shell completion script for supported shells."""
    options = [
        "config",
        "completion",
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
        "--interactive",
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


def _parse_bool(value: str) -> bool:
    """Parse a user-facing boolean config value."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected one of: true, false, yes, no, on, off")


def _format_profile(profile: UserProfile) -> str:
    """Format saved profile for display."""
    favorites = ", ".join(profile.favorite_teams) or "(none)"
    return "\n".join(
        [
            f"default-region: {profile.default_region or '(none)'}",
            f"default-view: {profile.default_view_mode}",
            f"compact: {profile.compact_mode}",
            f"sort: {profile.default_sort or '(none)'}",
            f"group-by: {profile.default_group_by or '(none)'}",
            f"cache: {profile.cache_enabled}",
            f"favorite-teams: {favorites}",
        ]
    )


CONFIG_KEY_TO_FIELD = {
    "default-region": "default_region",
    "default-view": "default_view_mode",
    "compact": "compact_mode",
    "sort": "default_sort",
    "group-by": "default_group_by",
    "cache": "cache_enabled",
}


def run_config_command(args: argparse.Namespace, formatter: Formatter) -> int:
    """Run config subcommands."""
    profile = config_manager.load()

    if args.config_command == "get":
        if args.key:
            requested_key = str(args.key)
            key = CONFIG_KEY_TO_FIELD.get(
                requested_key, requested_key.replace("-", "_")
            )
            if not hasattr(profile, key):
                print(f"{formatter.error(f'Unknown config key: {args.key}')}")
                return 1
            print(getattr(profile, key))
        else:
            print(_format_profile(profile))
        return 0

    if args.config_command == "reset":
        config_manager.reset()
        print(f"{formatter.success('Config reset.')}")
        return 0

    if args.config_command == "favorite":
        if args.action == "list":
            print(", ".join(profile.favorite_teams) or "(none)")
            return 0
        if not args.team:
            print(f"{formatter.error('Team name required.')}")
            return 1
        if args.action == "add":
            profile.add_favorite_team(args.team)
            config_manager.save(profile)
            print(f"{formatter.success(f'Added favorite team: {args.team}')}")
            return 0
        removed = profile.remove_favorite_team(args.team)
        config_manager.save(profile)
        if removed:
            print(f"{formatter.success(f'Removed favorite team: {args.team}')}")
        else:
            print(f"{formatter.warning(f'Favorite team not found: {args.team}')}")
        return 0

    key = args.key
    value = args.value
    try:
        if key == "default-region":
            if value not in REGION_CHOICES:
                print(f"{formatter.error(f'Unknown region: {value}')}")
                print(f"{formatter.muted('Run --list-regions to see valid choices.')}")
                return 1
            profile.default_region = value
        elif key == "default-view":
            if value not in {"all", "upcoming", "results"}:
                print(
                    f"{formatter.error('default-view must be all, upcoming, or results')}"
                )
                return 1
            profile.default_view_mode = value
        elif key == "compact":
            profile.compact_mode = _parse_bool(value)
        elif key == "sort":
            profile.default_sort = None if value == "none" else value
            if profile.default_sort not in {None, "date", "team"}:
                print(f"{formatter.error('sort must be date, team, or none')}")
                return 1
        elif key == "group-by":
            profile.default_group_by = None if value == "none" else value
            if profile.default_group_by not in {None, "date", "status"}:
                print(f"{formatter.error('group-by must be date, status, or none')}")
                return 1
        elif key == "cache":
            profile.cache_enabled = _parse_bool(value)
    except ValueError as e:
        print(f"{formatter.error(str(e))}")
        return 1

    config_manager.save(profile)
    print(f"{formatter.success(f'Set {key} = {value}')}")
    return 0


def _completion_install_path(shell: str) -> Path:
    """Return install path for a shell completion script."""
    if shell == "zsh":
        return Path.home() / ".zfunc" / f"_{CLI_COMMAND}"
    if shell == "fish":
        return Path.home() / ".config" / "fish" / "completions" / f"{CLI_COMMAND}.fish"
    return (
        Path.home()
        / ".local"
        / "share"
        / "bash-completion"
        / "completions"
        / CLI_COMMAND
    )


def install_completion(shell: str) -> Path:
    """Install shell completion and return written path."""
    path = _completion_install_path(shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(get_completion_script(shell), encoding="utf-8")
    return path


def run_completion_command(args: argparse.Namespace, formatter: Formatter) -> int:
    """Run completion subcommands."""
    if args.completion_command == "print":
        print(get_completion_script(args.shell))
        return 0
    if not shutil.which(args.shell):
        print(
            f"{formatter.warning(f'{args.shell} not found on PATH; installing anyway.')}"
        )
    path = install_completion(args.shell)
    print(f"{formatter.success(f'Installed {args.shell} completion: {path}')}")
    if args.shell == "zsh":
        print(f"{formatter.muted('Ensure ~/.zfunc is in fpath, then restart shell.')}")
    return 0


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
) -> ProcessedMatches:
    """Process matches asynchronously with progress display.

    Returns:
        ProcessedMatches with result metadata.
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

        processed = await process_matches_async(
            client, match_links, view_mode, progress_callback=update_progress
        )

    print("")
    return processed


def process_matches(
    client: ValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
) -> ProcessedMatches:
    """Process matches using async client (sync wrapper for backward compatibility).

    Returns:
        Tuple of (results, tbd_count, cache_hits).
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


def apply_profile_defaults(args: argparse.Namespace, profile: UserProfile) -> None:
    """Apply saved defaults when equivalent CLI flags are absent."""
    if not args.region and profile.default_region:
        args.region = profile.default_region

    if not args.upcoming and not args.results:
        if profile.default_view_mode == "upcoming":
            args.upcoming = True
        elif profile.default_view_mode == "results":
            args.results = True

    if not getattr(args, "compact", False):
        args.compact = profile.compact_mode

    if getattr(args, "sort", None) is None:
        args.sort = profile.default_sort

    if getattr(args, "group_by", None) is None:
        args.group_by = profile.default_group_by

    if not getattr(args, "no_cache", False):
        args.no_cache = not profile.cache_enabled


def main() -> None:
    logger.info("Starting Valorant Matches application")
    args = parse_args()

    # Create a formatter instance for main application
    formatter = Formatter()

    if args.command == "config":
        sys.exit(run_config_command(args, formatter))

    if args.command == "completion":
        sys.exit(run_completion_command(args, formatter))

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
    profile = config_manager.load()
    apply_profile_defaults(args, profile)

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
