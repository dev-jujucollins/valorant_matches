#!/usr/bin/python3

import argparse
import logging
import logging.config
import shutil
import sys
import tempfile
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from valorant_matches.cli.display import run_cli_mode, saved_discovery_notice
from valorant_matches.cli.interactive import run_interactive_mode
from valorant_matches.config import APP_DIR, CACHE_DIR, build_logging_config
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile, config_manager
from valorant_matches.scraping.discovery import (
    REGION_ALIASES,
    DiscoveredEvent,
    EventDiscovery,
)

logger = logging.getLogger("valorant_matches")

# Flatten region aliases for argparse choices
REGION_CHOICES = [alias for aliases in REGION_ALIASES.values() for alias in aliases]

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
    parser.add_argument("--all", action="store_true", help="Override saved view mode")
    parser.add_argument(
        "--cache", dest="no_cache", action="store_false", help="Use cache for this run"
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Disable cache and fetch fresh data",
    )
    parser.set_defaults(no_cache=None)
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
        dest="compact",
        action="store_true",
        help="Display matches in compact single-line format",
    )
    parser.add_argument(
        "--no-compact",
        dest="compact",
        action="store_false",
        help="Use full match display for this run",
    )
    parser.set_defaults(compact=None)
    parser.add_argument(
        "--group-by",
        choices=["date", "status", "none"],
        help="Group matches by date or status",
    )
    parser.add_argument(
        "--sort",
        choices=["date", "team", "none"],
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
        "--favorites",
        action="store_true",
        help="Show saved favorite teams across regions",
    )
    parser.add_argument("--event", help="Fetch a discovered event by numeric ID")
    parser.add_argument(
        "--season", type=int, help="VCT season to discover (default: current year)"
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
    parser.add_argument(
        "--today",
        action="store_true",
        help="Only matches starting today in the selected timezone",
    )
    parser.add_argument("--timezone", help="IANA timezone (default: local timezone)")
    parser.add_argument(
        "--watch", action="store_true", help="Refresh matches until Ctrl+C"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between watch refreshes (minimum 10, default 60)",
    )
    args = parser.parse_args()
    if sum((args.upcoming, args.results, args.all)) > 1:
        parser.error("--all, --upcoming, and --results cannot be combined")
    if args.event and not args.event.isdigit():
        parser.error("--event requires a numeric event ID")
    if args.season is not None and not 2020 <= args.season <= 2100:
        parser.error("--season must be between 2020 and 2100")
    if args.event and args.region:
        parser.error("--event and --region cannot be combined")
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")
    if args.watch and (args.export or args.interactive):
        parser.error("--watch cannot be combined with --export or --interactive")
    if args.timezone:
        try:
            ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            parser.error(f"Unknown timezone: {args.timezone}")
    return args


def get_completion_script(shell: str) -> str:
    """Generate shell completion script for supported shells."""
    options = [
        "config",
        "completion",
        "-r",
        "--region",
        "--upcoming",
        "--results",
        "--all",
        "--cache",
        "--no-cache",
        "--clear-cache",
        "--list-regions",
        "--refresh",
        "--compact",
        "--no-compact",
        "--group-by",
        "--sort",
        "--export",
        "--output",
        "--team",
        "--favorites",
        "--event",
        "--season",
        "--doctor",
        "--quickstart",
        "--print-completion",
        "--interactive",
        "--help",
        "--today",
        "--timezone",
        "--watch",
        "--interval",
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
            sort_value = None if value == "none" else value
            if sort_value not in {None, "date", "team"}:
                print(f"{formatter.error('sort must be date, team, or none')}")
                return 1
            profile.default_sort = sort_value
        elif key == "group-by":
            group_value = None if value == "none" else value
            if group_value not in {None, "date", "status"}:
                print(f"{formatter.error('group-by must be date, status, or none')}")
                return 1
            profile.default_group_by = group_value
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


def apply_profile_defaults(args: argparse.Namespace, profile: UserProfile) -> None:
    """Apply saved defaults when equivalent CLI flags are absent."""
    if (
        not args.region
        and getattr(args, "favorites", False) is not True
        and not isinstance(getattr(args, "event", None), str)
        and profile.default_region
    ):
        args.region = profile.default_region

    if (
        not args.upcoming
        and not args.results
        and getattr(args, "all", False) is not True
    ):
        if profile.default_view_mode == "upcoming":
            args.upcoming = True
        elif profile.default_view_mode == "results":
            args.results = True

    if getattr(args, "compact", None) is None:
        args.compact = profile.compact_mode

    if getattr(args, "sort", None) is None:
        args.sort = profile.default_sort
    elif args.sort == "none":
        args.sort = None
        args.sort_explicit_none = True

    if getattr(args, "group_by", None) is None:
        args.group_by = profile.default_group_by
    elif args.group_by == "none":
        args.group_by = None

    if getattr(args, "no_cache", None) is None:
        args.no_cache = not profile.cache_enabled


def main() -> None:
    # Configure logging once, here — library modules only get loggers.
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(build_logging_config())

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
        from valorant_matches.cache import MatchCache

        cache = MatchCache()
        count = cache.clear()
        print(f"{formatter.success(f'Cleared {count} cache entries.')}")
        sys.exit(0)

    # Initialize event discovery
    discovery = EventDiscovery(season=args.season)
    force_refresh = getattr(args, "refresh", False)
    profile = config_manager.load()
    apply_profile_defaults(args, profile)
    args.favorite_teams = profile.favorite_teams
    formatter.set_favorite_teams(profile.favorite_teams)

    if args.favorites and not profile.favorite_teams:
        print(
            formatter.error(
                "No favorite teams saved. Add one with config favorite add."
            )
        )
        sys.exit(2)

    if (args.watch or args.today or args.timezone) and not (
        args.region or args.event or args.favorites
    ):
        print(
            formatter.error(
                "--watch, --today, and --timezone require --region or a saved default-region."
            )
        )
        sys.exit(2)

    if args.doctor:
        exit_code = run_doctor(formatter, discovery)
        sys.exit(exit_code)

    if args.list_regions:
        print(f"\n{formatter.info('Discovering VCT events...', bold=True)}\n")
        events = discovery.discover_events(force_refresh=force_refresh)
        notice = saved_discovery_notice(discovery)
        if notice:
            print(formatter.warning(notice))

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
                    print(
                        f"    - {event.event_id}: {event.name}{formatter.muted(status)}"
                    )
                print()
        else:
            print(f"{formatter.warning('No events found for selected season.')}\n")
            sys.exit(1)
        sys.exit(0)

    print(f"\n{formatter.format('Valorant Champions Tour', 'bright_cyan', bold=True)}")
    print(f"{formatter.format('=' * 40, 'bright_magenta')}\n")

    # Determine mode based on arguments
    if args.region or args.event or args.favorites:
        # CLI mode
        interactive_func = partial(
            run_interactive_mode,
            profile=profile,
            cache_enabled=not args.no_cache,
            timezone=args.timezone,
        )
        exit_code = run_cli_mode(args, formatter, discovery, interactive_func)
    else:
        # Interactive mode
        exit_code = run_interactive_mode(
            formatter,
            discovery,
            profile=profile,
            cache_enabled=not args.no_cache,
            timezone=args.timezone,
        )

    logger.info("Application shutdown complete")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
