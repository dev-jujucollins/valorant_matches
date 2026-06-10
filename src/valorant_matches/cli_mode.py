# CLI mode functionality for command-line usage.

import argparse
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from valorant_matches.event_discovery import EventDiscovery
from valorant_matches.event_manager import get_event_for_region
from valorant_matches.exporters import export_matches
from valorant_matches.formatter import Formatter
from valorant_matches.match_extractor import Match
from valorant_matches.runner import fetch_event_data

logger = logging.getLogger("valorant_matches")


@dataclass
class MatchError:
    """Represents an error during match processing."""

    url: str
    error_type: str
    message: str


@dataclass
class MatchStats:
    """Statistics about match processing."""

    total: int = 0
    displayed: int = 0
    cache_hits: int = 0
    failed: int = 0
    tbd_count: int = 0
    live_count: int = 0
    upcoming_count: int = 0
    completed_count: int = 0
    fetch_time: float = 0.0
    errors: list[MatchError] = field(default_factory=list)

    def increment_cache_hit(self) -> None:
        """Increment cache hit counter."""
        self.cache_hits += 1

    def increment_failed(self) -> None:
        """Increment failed counter."""
        self.failed += 1

    def count_match(self, match: Match) -> None:
        """Count match type from Match object."""
        if match.is_live:
            self.live_count += 1
        elif match.is_upcoming:
            self.upcoming_count += 1
        else:
            self.completed_count += 1

    def add_error(self, url: str, error_type: str, message: str) -> None:
        """Record an error for later reporting."""
        self.errors.append(MatchError(url=url, error_type=error_type, message=message))
        self.failed += 1


def print_error_summary(formatter: Formatter, stats: MatchStats) -> None:
    """Print a summary of errors encountered during processing."""
    if not stats.errors:
        return

    print(f"\n{formatter.warning(f'Errors encountered ({len(stats.errors)}):')}")
    for error in stats.errors[:5]:  # Show first 5 errors
        print(f"  {formatter.muted('-')} {error.error_type}: {error.message}")
        print(f"    {formatter.muted(error.url)}")

    if len(stats.errors) > 5:
        remaining = len(stats.errors) - 5
        print(f"  {formatter.muted(f'... and {remaining} more errors')}")


@dataclass
class DisplayOptions:
    """Options for displaying match results."""

    compact: bool = False
    group_by: str | None = None
    sort_by: str | None = None


def get_match_status(match: Match) -> str:
    """Determine match status from Match object."""
    if match.is_live:
        return "live"
    elif match.is_upcoming:
        return "upcoming"
    return "completed"


def _parse_date(date_str: str) -> datetime:
    """Parse a date string to datetime for sorting.

    Handles formats like "December 23, 2025", "Dec 23, 2025", and "Jan 10".
    Returns datetime.max for unparseable dates so they sort last.
    """
    formats = [
        "%B %d, %Y",  # December 23, 2025
        "%b %d, %Y",  # Dec 23, 2025
        "%B %d",  # December 23 (no year)
        "%b %d",  # Dec 23 (no year)
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            # No year in the source: pick the year that puts the date closest
            # to today, so a Jan match listed in December sorts as next year.
            today = datetime.now()
            candidates = [
                parsed.replace(year=today.year + offset) for offset in (-1, 0, 1)
            ]
            parsed = min(candidates, key=lambda d: abs(d - today))
        return parsed
    return datetime.max


def sort_matches(
    results: list[tuple[dict, Match]], sort_by: str | None
) -> list[tuple[dict, Match]]:
    """Sort matches by the specified criteria."""
    if not sort_by:
        return results

    if sort_by == "date":
        return sorted(results, key=lambda x: _parse_date(x[1].date))
    elif sort_by == "team":
        return sorted(results, key=lambda x: x[1].team1.lower())
    return results


def group_matches(
    results: list[tuple[dict, Match]], group_by: str | None
) -> dict[str, list[tuple[dict, Match]]]:
    """Group matches by the specified criteria."""
    if not group_by:
        return {"all": results}

    grouped: dict[str, list[tuple[dict, Match]]] = defaultdict(list)

    for link, match in results:
        if group_by == "date":
            key = match.date
        elif group_by == "status":
            key = get_match_status(match)
        else:
            key = "all"
        grouped[key].append((link, match))

    return dict(grouped)


def filter_matches_by_team(
    results: list[tuple[dict, Match]], team_name: str | None
) -> list[tuple[dict, Match]]:
    """Filter matches by team name (case-insensitive).

    Args:
        results: List of (link, Match) tuples
        team_name: Team name to filter by (partial match supported)

    Returns:
        Filtered list of matches
    """
    if not team_name:
        return results

    team_lower = team_name.lower()
    filtered = []

    for link, match in results:
        if team_lower in match.team1.lower() or team_lower in match.team2.lower():
            filtered.append((link, match))

    return filtered


def format_match_full(formatter: Formatter, match: Match) -> str:
    """Format match data for full display."""
    return formatter.format_match_full(match)


def get_view_mode(args: argparse.Namespace) -> str:
    """Determine view mode from CLI arguments."""
    if args.upcoming:
        return "upcoming"
    elif args.results:
        return "results"
    return "all"


def get_display_options(args: argparse.Namespace) -> DisplayOptions:
    """Extract display options from CLI arguments."""
    return DisplayOptions(
        compact=getattr(args, "compact", False),
        group_by=getattr(args, "group_by", None),
        sort_by=getattr(args, "sort", None),
    )


def display_results(
    results: list[tuple[dict, Match]],
    formatter: Formatter,
    options: DisplayOptions,
    stats: MatchStats,
) -> None:
    """Display match results with optional grouping and sorting."""
    # Sort if requested
    sorted_results = sort_matches(results, options.sort_by)

    # Group if requested
    grouped = group_matches(sorted_results, options.group_by)

    # Status labels for grouping
    status_labels = {
        "live": formatter.live_status("LIVE MATCHES"),
        "upcoming": formatter.warning("UPCOMING MATCHES"),
        "completed": formatter.success("COMPLETED MATCHES"),
    }

    for group_key, group_results in grouped.items():
        # Print group header if grouping is enabled
        if options.group_by and group_key != "all":
            if options.group_by == "status":
                header = status_labels.get(group_key, group_key.upper())
            else:
                header = formatter.info(group_key, bold=True)
            print(f"\n{header}")
            print(formatter.muted("─" * 30))

        for _, match in group_results:
            # Count match stats
            stats.count_match(match)
            # Format based on compact mode
            if options.compact:
                output = formatter.format_match_compact(
                    date=match.date,
                    team1=match.team1,
                    team2=match.team2,
                    score=match.score,
                    is_live=match.is_live,
                    is_upcoming=match.is_upcoming,
                )
            else:
                output = format_match_full(formatter, match)
            print(output)

    stats.displayed = len(results)


def run_cli_mode(
    args: argparse.Namespace,
    formatter: Formatter,
    discovery: EventDiscovery,
    run_interactive_func,
) -> int:
    """Run in CLI mode with command line arguments.

    Args:
        args: Parsed command line arguments
        formatter: Formatter instance for output styling
        discovery: EventDiscovery instance
        run_interactive_func: Function to run interactive mode if requested
    """
    start_time = time.time()
    stats = MatchStats()

    cache_enabled = not args.no_cache
    if args.no_cache:
        logger.info("Cache disabled via --no-cache flag")

    view_mode = get_view_mode(args)

    # Get event using auto-discovery
    event = get_event_for_region(
        args.region,
        discovery,
        force_refresh=getattr(args, "refresh", False),
        view_mode=view_mode,
    )
    if not event:
        print(f"\n{formatter.error(f'No events found for region: {args.region}')}")
        print(
            f"{formatter.muted('Try --list-regions to see discovered options, or run with --refresh to force discovery.')}\n"
        )
        return 1

    status_str = f" ({event.status})" if event.status != "unknown" else ""
    print(
        f"\n{formatter.info(f'Fetching matches for: {event.name}{status_str}', bold=True)}\n"
    )

    fetch_result = fetch_event_data(
        event.url,
        event.slug,
        view_mode=view_mode,
        cache_enabled=cache_enabled,
    )
    if not fetch_result.total_links:
        print(f"\n{formatter.warning('No matches found for the selected event page.')}")
        print(
            f"{formatter.muted('The event may not have posted matches yet. Try --refresh or check another region.')}\n"
        )
        return 0

    processed = fetch_result.processed
    stats.total = fetch_result.total_links
    stats.tbd_count = processed.tbd_count
    stats.cache_hits = processed.cache_hits
    stats.failed = processed.failed_count
    results = processed.results

    # Apply team filter if specified
    team_filter = getattr(args, "team", None)
    if team_filter:
        results = filter_matches_by_team(results, team_filter)
        logger.info(f"Filtered to {len(results)} matches for team '{team_filter}'")

    # Log the actual number of matches being displayed
    match_type = {"upcoming": "upcoming", "results": "completed", "all": ""}
    type_str = f" {match_type[view_mode]}" if match_type[view_mode] else ""
    logger.info(f"Displaying {len(results)}{type_str} matches")
    print()

    # Handle export if requested
    export_format = getattr(args, "export", None)
    if export_format:
        output_path = getattr(args, "output", None)
        count = export_matches(results, export_format, output_path)
        final_path = output_path or f"matches.{export_format}"
        print(f"{formatter.success(f'Exported {count} matches to {final_path}')}\n")
        return 0  # Exit after export

    if not results:
        if team_filter:
            print(
                f"\n{formatter.warning(f'No matches found for team filter: {team_filter}')}"
            )
            print(
                f"{formatter.muted('Try a shorter team name with --team, or remove the filter.')}\n"
            )
        elif view_mode == "upcoming":
            print(
                f"\n{formatter.warning('No upcoming matches are scheduled right now for this event.')}"
            )
            print(
                f"{formatter.muted('Try removing --upcoming to view all matches.')}\n"
            )
        elif view_mode == "results":
            print(
                f"\n{formatter.warning('No completed matches are available for this event yet.')}"
            )
            print(
                f"{formatter.muted('Try --upcoming to view scheduled matches instead.')}\n"
            )
        else:
            print(
                f"\n{formatter.warning('No matches available to display right now.')}"
            )
            print(
                f"{formatter.muted('Try --refresh, --list-regions, or another region alias.')}\n"
            )
    else:
        options = get_display_options(args)
        display_results(results, formatter, options, stats)

    stats.fetch_time = time.time() - start_time

    print()
    formatter.print_stats_footer(
        displayed=stats.displayed,
        cache_hits=stats.cache_hits,
        failed=stats.failed,
        tbd_count=stats.tbd_count,
        fetch_time=stats.fetch_time,
        live_count=stats.live_count,
    )

    # Print error summary if there were errors
    print_error_summary(formatter, stats)

    if getattr(args, "interactive", False):
        print(f"\n{formatter.muted('─' * 40)}")
        print(f"{formatter.info('Entering interactive mode...', bold=True)}\n")
        return run_interactive_func(formatter, discovery)
    return 0
