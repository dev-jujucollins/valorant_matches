# Entry point: argument parsing, subcommands, and dispatch.

import argparse
import logging
import logging.config
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from valorant_matches.cache import MatchCache
from valorant_matches.cli.display import run_cli_mode, saved_discovery_notice
from valorant_matches.cli.interactive import run_interactive_mode
from valorant_matches.cli.options import (
    EXPORT_FORMATS,
    GROUP_KEYS,
    NONE_CHOICE,
    SORT_KEYS,
    VIEW_MODES,
    RunOptions,
    build_run_options,
)
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
SHELLS = ("bash", "zsh", "fish")


def _region_help() -> str:
    """List region names with their aliases, e.g. "americas (am)"."""
    lines = []
    for region, aliases in REGION_ALIASES.items():
        others = [alias for alias in aliases if alias != region]
        lines.append(f"  {region} ({', '.join(others)})" if others else f"  {region}")
    return "\n".join(lines)


EPILOG = f"""
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
{_region_help()}
"""


def _parse_bool(value: str) -> bool:
    """Parse a user-facing boolean config value.

    Raises:
        ValueError: When the value is not a recognized boolean word.
    """
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected one of: true, false, yes, no, on, off")


def _parse_choice(
    name: str, choices: Sequence[str], allow_none: bool = False
) -> Callable[[str], str | None]:
    """Build a config value parser that accepts only listed choices.

    Args:
        name: Config key, used in the error message.
        choices: Accepted values.
        allow_none: Accept "none" and store None to clear the value.
    """
    accepted = [*choices, NONE_CHOICE] if allow_none else list(choices)

    def parse(value: str) -> str | None:
        if allow_none and value == NONE_CHOICE:
            return None
        if value not in choices:
            raise ValueError(f"{name} must be one of: {', '.join(accepted)}")
        return value

    return parse


# Config key -> (UserProfile field, value parser)
CONFIG_KEYS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "default-region": (
        "default_region",
        _parse_choice("default-region", REGION_CHOICES, allow_none=True),
    ),
    "default-view": ("default_view_mode", _parse_choice("default-view", VIEW_MODES)),
    "compact": ("compact_mode", _parse_bool),
    "sort": ("default_sort", _parse_choice("sort", SORT_KEYS, allow_none=True)),
    "group-by": (
        "default_group_by",
        _parse_choice("group-by", GROUP_KEYS, allow_none=True),
    ),
    "cache": ("cache_enabled", _parse_bool),
}
FAVORITES_KEY = "favorite-teams"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Parser with config and completion subcommands and match flags.
    """
    parser = argparse.ArgumentParser(
        prog=CLI_COMMAND,
        description="Fetch and display Valorant Champions Tour (VCT) match results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config", help="Manage saved defaults")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_subparsers.required = True
    config_set = config_subparsers.add_parser("set", help="Set a saved default")
    config_set.add_argument("key", choices=list(CONFIG_KEYS))
    config_set.add_argument("value")
    config_get = config_subparsers.add_parser("get", help="Show saved config")
    config_get.add_argument("key", nargs="?", choices=[*CONFIG_KEYS, FAVORITES_KEY])
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
    for action, help_text in (
        ("print", "Print completion script"),
        ("install", "Install completion script"),
    ):
        completion_subparsers.add_parser(action, help=help_text).add_argument(
            "shell", choices=SHELLS
        )

    parser.add_argument(
        "-r", "--region", choices=REGION_CHOICES, help="Region/event to fetch"
    )
    parser.add_argument(
        "--upcoming", action="store_true", help="Show only upcoming/scheduled matches"
    )
    parser.add_argument(
        "--results", action="store_true", help="Show only completed match results"
    )
    parser.add_argument("--all", action="store_true", help="Override saved view mode")
    parser.add_argument(
        "--cache",
        dest="cache",
        action="store_true",
        default=None,
        help="Use cache for this run",
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="Disable cache and fetch fresh data",
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear all cached data and exit"
    )
    parser.add_argument(
        "--list-regions", action="store_true", help="List available regions and exit"
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
        default=None,
        help="Display matches in compact single-line format",
    )
    parser.add_argument(
        "--no-compact",
        dest="compact",
        action="store_false",
        help="Use full match display for this run",
    )
    parser.add_argument(
        "--group-by",
        choices=[*GROUP_KEYS, NONE_CHOICE],
        help="Group matches by date or status",
    )
    parser.add_argument(
        "--sort",
        choices=[*SORT_KEYS, NONE_CHOICE],
        help="Sort matches by date or team name",
    )
    parser.add_argument(
        "--export", choices=EXPORT_FORMATS, help="Export matches to JSON or CSV format"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for export (default: matches.{format})",
    )
    parser.add_argument("--team", help="Filter matches by team name (case-insensitive)")
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
        "--quickstart", action="store_true", help="Show a quickstart guide and exit"
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
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Args:
        argv: Arguments without the program name; defaults to sys.argv[1:].

    Returns:
        Parsed arguments. Invalid combinations exit with status 2.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
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


def _completion_words(parser: argparse.ArgumentParser) -> list[str]:
    """List every top-level option string and subcommand name."""
    words: list[str] = []
    # argparse has no public accessor for registered actions.
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            words.extend(action.choices)
        else:
            words.extend(action.option_strings)
    return words


def get_completion_script(shell: str) -> str:
    """Generate a shell completion script from the live parser.

    Args:
        shell: "bash", "zsh", or "fish".

    Returns:
        Script text that completes options, subcommands, and regions.
    """
    words = " ".join(_completion_words(build_parser()))
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


def _display_value(value: object) -> str:
    """Render a profile value for config output."""
    if value is None:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "(none)"
    return str(value)


def _format_profile(profile: UserProfile) -> str:
    """Format the saved profile as "key: value" lines."""
    lines = [
        f"{key}: {_display_value(getattr(profile, field_name))}"
        for key, (field_name, _) in CONFIG_KEYS.items()
    ]
    lines.append(f"{FAVORITES_KEY}: {_display_value(profile.favorite_teams)}")
    return "\n".join(lines)


def _run_favorite_command(
    args: argparse.Namespace, profile: UserProfile, formatter: Formatter
) -> int:
    """Run config favorite add/remove/list."""
    if args.action == "list":
        formatter.print(_display_value(profile.favorite_teams))
        return 0
    if not args.team:
        formatter.error("Team name required.")
        return 1
    if args.action == "add":
        profile.add_favorite_team(args.team)
        config_manager.save(profile)
        formatter.success(f"Added favorite team: {args.team}")
        return 0
    removed = profile.remove_favorite_team(args.team)
    config_manager.save(profile)
    if removed:
        formatter.success(f"Removed favorite team: {args.team}")
    else:
        formatter.warning(f"Favorite team not found: {args.team}")
    return 0


def run_config_command(args: argparse.Namespace, formatter: Formatter) -> int:
    """Run config subcommands.

    Args:
        args: Parsed arguments for the config subcommand.
        formatter: Output formatter.

    Returns:
        Process exit code.
    """
    profile = config_manager.load()

    if args.config_command == "get":
        if args.key == FAVORITES_KEY:
            formatter.print(_display_value(profile.favorite_teams))
        elif args.key:
            field_name, _ = CONFIG_KEYS[args.key]
            formatter.print(_display_value(getattr(profile, field_name)))
        else:
            formatter.print(_format_profile(profile))
        return 0

    if args.config_command == "reset":
        config_manager.reset()
        formatter.success("Config reset.")
        return 0

    if args.config_command == "favorite":
        return _run_favorite_command(args, profile, formatter)

    field_name, parse_value = CONFIG_KEYS[args.key]
    try:
        value = parse_value(args.value)
    except ValueError as e:
        formatter.error(str(e))
        if args.key == "default-region":
            formatter.muted("Run --list-regions to see valid choices.")
        return 1
    setattr(profile, field_name, value)
    config_manager.save(profile)
    formatter.success(f"Set {args.key} = {args.value}")
    return 0


def _completion_install_path(shell: str) -> Path:
    """Return the conventional per-user install path for a shell."""
    if shell == "zsh":
        return Path.home() / ".zfunc" / f"_{CLI_COMMAND}"
    if shell == "fish":
        return Path.home() / ".config" / "fish" / "completions" / f"{CLI_COMMAND}.fish"
    return Path.home() / ".local/share/bash-completion/completions" / CLI_COMMAND


def install_completion(shell: str) -> Path:
    """Install a shell completion script.

    Args:
        shell: "bash", "zsh", or "fish".

    Returns:
        The written path.
    """
    path = _completion_install_path(shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(get_completion_script(shell), encoding="utf-8")
    return path


def run_completion_command(args: argparse.Namespace, formatter: Formatter) -> int:
    """Run completion print/install subcommands.

    Args:
        args: Parsed arguments for the completion subcommand.
        formatter: Output formatter.

    Returns:
        Process exit code.
    """
    if args.completion_command == "print":
        # Plain print: the script is meant to be piped or eval'd.
        print(get_completion_script(args.shell))
        return 0
    if not shutil.which(args.shell):
        formatter.warning(f"{args.shell} not found on PATH; installing anyway.")
    path = install_completion(args.shell)
    formatter.success(f"Installed {args.shell} completion: {path}")
    if args.shell == "zsh":
        formatter.muted("Ensure ~/.zfunc is in fpath, then restart shell.")
    return 0


def print_quickstart(formatter: Formatter) -> None:
    """Print a concise quickstart guide.

    Args:
        formatter: Output formatter.
    """
    steps = [
        ("Interactive mode", CLI_COMMAND),
        ("Region results", f"{CLI_COMMAND} -r americas --results"),
        ("Upcoming only", f"{CLI_COMMAND} -r emea --upcoming"),
        ("Team filter", f"{CLI_COMMAND} -r pacific --team fnatic"),
        ("Troubleshoot", f"{CLI_COMMAND} --doctor"),
    ]
    formatter.blank()
    formatter.info("Quickstart", bold=True)
    for number, (label, command) in enumerate(steps, 1):
        formatter.print(f"{number}) {label}: {command}")
    formatter.blank()


def run_doctor(formatter: Formatter, discovery: EventDiscovery) -> int:
    """Run diagnostics and print actionable results.

    Args:
        formatter: Output formatter.
        discovery: Event discovery service, which shares the request policy.

    Returns:
        0 when every check passed, else 1.
    """
    formatter.blank()
    formatter.info("Running diagnostics...", bold=True)
    failures = 0

    if discovery.can_reach_vlr():
        formatter.success("✓ Network check: vlr.gg reachable")
    else:
        failures += 1
        logger.warning("Doctor network check failed via discovery session")
        formatter.error("✗ Network check failed")
        formatter.muted(
            "  Try again in a minute, or run with --refresh once connectivity returns."
        )

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=CACHE_DIR, delete=True):
            pass
        formatter.success("✓ Cache check: cache directory is writable")
    except OSError as e:
        failures += 1
        logger.warning(f"Doctor cache check failed: {e}")
        formatter.error("✗ Cache check failed")
        formatter.muted(
            f"  Verify filesystem permissions for {CACHE_DIR} or run with --no-cache."
        )

    events = discovery.discover_events(force_refresh=True)
    if events:
        formatter.success(f"✓ Event discovery: found {len(events)} active events")
    else:
        failures += 1
        formatter.warning("! Event discovery returned no live events")
        formatter.muted(
            "  The app will use saved events if available. "
            "You can still run with --region."
        )

    formatter.blank()
    if failures:
        formatter.warning(f"Diagnostics finished with {failures} issue(s).")
        formatter.blank()
        return 1
    formatter.success("Diagnostics passed. You are good to go.")
    formatter.blank()
    return 0


def list_regions(
    formatter: Formatter, discovery: EventDiscovery, force_refresh: bool
) -> int:
    """Print discovered events grouped by region.

    Args:
        formatter: Output formatter.
        discovery: Event discovery service.
        force_refresh: Bypass the in-process discovery cache.

    Returns:
        0 when events were found, else 1.
    """
    formatter.blank()
    formatter.info("Discovering VCT events...", bold=True)
    formatter.blank()
    events = discovery.discover_events(force_refresh=force_refresh)
    notice = saved_discovery_notice(discovery)
    if notice:
        formatter.warning(notice)
    if not events:
        formatter.warning("No events found for selected season.")
        formatter.blank()
        return 1

    formatter.info("Available events:", bold=True)
    formatter.blank()
    by_region: dict[str, list[DiscoveredEvent]] = {}
    for event in events:
        by_region.setdefault(event.region, []).append(event)
    for region, region_events in sorted(by_region.items()):
        aliases = ", ".join(REGION_ALIASES.get(region, [region]))
        formatter.print(f"  {aliases}:", "primary", bold=True)
        for event in region_events:
            status = f" [{event.status}]" if event.status else ""
            formatter.print(f"    - {event.event_id}: {event.name}{status}")
        formatter.blank()
    return 0


def _validate_options(opts: RunOptions, formatter: Formatter) -> int | None:
    """Reject option combinations that need saved state; return an exit code."""
    if opts.favorites_only and not opts.favorite_teams:
        formatter.error("No favorite teams saved. Add one with config favorite add.")
        return 2
    if (opts.watch or opts.today or opts.timezone) and not opts.has_target:
        formatter.error(
            "--watch, --today, and --timezone require --region "
            "or a saved default-region."
        )
        return 2
    return None


def run(args: argparse.Namespace, formatter: Formatter) -> int:
    """Dispatch parsed arguments to the matching command.

    Args:
        args: Parsed arguments.
        formatter: Output formatter.

    Returns:
        Process exit code.
    """
    if args.command == "config":
        return run_config_command(args, formatter)
    if args.command == "completion":
        return run_completion_command(args, formatter)
    if args.quickstart:
        print_quickstart(formatter)
        return 0
    if args.clear_cache:
        count = MatchCache(enabled=True).clear()
        formatter.success(f"Cleared {count} cache entries.")
        return 0

    discovery = EventDiscovery(season=args.season)
    opts = build_run_options(args, config_manager.load())
    error_code = _validate_options(opts, formatter)
    if error_code is not None:
        return error_code
    if args.doctor:
        return run_doctor(formatter, discovery)
    if args.list_regions:
        return list_regions(formatter, discovery, args.refresh)

    formatter.blank()
    formatter.print("Valorant Champions Tour", "bright_cyan", bold=True)
    formatter.rule(style="bright_magenta")
    formatter.blank()

    if not opts.has_target:
        return run_interactive_mode(formatter, discovery, opts)
    exit_code = run_cli_mode(opts, formatter, discovery)
    if opts.interactive:
        formatter.blank()
        formatter.rule()
        formatter.info("Entering interactive mode...", bold=True)
        formatter.blank()
        exit_code = run_interactive_mode(formatter, discovery, opts)
    return exit_code


def main() -> None:
    """Configure logging, run the CLI, and exit with its status code."""
    # Configure logging once, here — library modules only get loggers.
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(build_logging_config())
    logger.info("Starting Valorant Matches application")

    exit_code = run(parse_args(), Formatter())
    logger.info("Application shutdown complete")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
