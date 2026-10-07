# CLI match workflow plus match-list helpers shared with interactive mode.

import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo

from valorant_matches.cli.options import ExportFormat, GroupKey, RunOptions, SortKey
from valorant_matches.output.exporters import export_matches
from valorant_matches.output.formatter import Formatter
from valorant_matches.scraping.discovery import DiscoveredEvent, EventDiscovery
from valorant_matches.scraping.event_selection import select_events
from valorant_matches.scraping.matches import FetchError, Match
from valorant_matches.scraping.runner import EventFetchResult, fetch_event_data

logger = logging.getLogger("valorant_matches")

# Errors listed individually before the summary collapses the rest
MAX_LISTED_ERRORS = 5

STATUS_GROUP_LABELS = {
    "live": ("LIVE MATCHES", "live"),
    "upcoming": ("UPCOMING MATCHES", "warning"),
    "completed": ("COMPLETED MATCHES", "success"),
}

# Follow-up hints for an empty listing, phrased for each mode's controls.
CLI_HINTS = {
    "team": "Try a shorter team name with --team, or remove the filter.",
    "upcoming": "Try removing --upcoming to view all matches.",
    "results": "Try --upcoming to view scheduled matches instead.",
    "all": "Try --refresh, --list-regions, or another region alias.",
}
INTERACTIVE_HINTS = {
    "team": "Press f to change or clear the team filter.",
    "upcoming": "Try all matches mode or refresh events with r.",
    "results": "Try upcoming mode to see scheduled matches.",
    "all": "Press r to refresh events or pick another event.",
}


def saved_discovery_notice(discovery: EventDiscovery) -> str | None:
    """Describe the saved event list when live discovery failed.

    Args:
        discovery: Event discovery service.

    Returns:
        A warning naming the snapshot time, or None when discovery is live.
    """
    if getattr(discovery, "is_stale", False) is not True:
        return None
    updated = discovery.last_updated
    timestamp = (
        datetime.fromtimestamp(updated).astimezone().isoformat()
        if isinstance(updated, (int, float))
        else "unknown"
    )
    return f"Using saved event list from {timestamp}; refresh failed."


@dataclass
class MatchStats:
    """Counts gathered while fetching one or more events."""

    total: int = 0
    cache_hits: int = 0
    failed: int = 0
    tbd_count: int = 0
    skipped_count: int = 0
    errors: list[FetchError] = field(default_factory=list)

    def add_fetch(self, result: EventFetchResult) -> None:
        """Add one event's fetch outcome.

        Args:
            result: Fetch result for a single event.
        """
        if result.error:
            self.errors.append(result.error)
            self.failed += 1
            return
        processed = result.processed
        self.total += result.total_links
        self.cache_hits += processed.cache_hits
        self.failed += processed.failed_count
        self.tbd_count += processed.tbd_count
        self.skipped_count += processed.skipped_count
        self.errors.extend(processed.errors)


def print_error_summary(formatter: Formatter, errors: list[FetchError]) -> None:
    """Print the first few errors with their URLs.

    Args:
        formatter: Output formatter.
        errors: Errors collected during fetching.
    """
    if not errors:
        return

    formatter.blank()
    formatter.warning(f"Errors encountered ({len(errors)}):")
    for error in errors[:MAX_LISTED_ERRORS]:
        formatter.print(f"  - {error.error_type}: {error.message}")
        formatter.muted(f"    {error.url}")

    if len(errors) > MAX_LISTED_ERRORS:
        formatter.muted(f"  ... and {len(errors) - MAX_LISTED_ERRORS} more errors")


def fetch_matches(
    events: list[DiscoveredEvent],
    formatter: Formatter,
    *,
    view_mode: str,
    cache_enabled: bool,
    stats: MatchStats,
) -> list[Match]:
    """Fetch every event's matches, reporting progress and event failures.

    Args:
        events: Events to fetch, in order.
        formatter: Output formatter.
        view_mode: "all", "results", or "upcoming".
        cache_enabled: Read and write the completed-match cache.
        stats: Counts updated in place.

    Returns:
        Matches across all events, unique by URL.
    """
    fetched: dict[str, Match] = {}
    for event in events:
        status = f" ({event.status})" if event.status != "unknown" else ""
        formatter.blank()
        formatter.info(f"Fetching matches for: {event.name}{status}", bold=True)
        formatter.blank()
        result = fetch_event_data(
            event.url, event.slug, view_mode=view_mode, cache_enabled=cache_enabled
        )
        stats.add_fetch(result)
        if result.error:
            error = result.error
            formatter.error(f"Fetch failed: {error.message} ({error.url})")
            continue
        for match in result.processed.results:
            fetched.setdefault(match.url, match)
    return list(fetched.values())


def _parse_date(date_str: str) -> datetime:
    """Parse a date label to a datetime for sorting.

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
        has_year = "%Y" in fmt
        try:
            parsed = datetime.strptime(
                date_str if has_year else f"{date_str} 2000",
                fmt if has_year else f"{fmt} %Y",
            )
        except ValueError:
            continue
        if not has_year:
            # No year in the source: pick the year that puts the date closest
            # to today, so a Jan match listed in December sorts as next year.
            today = datetime.now()
            candidates = []
            for offset in range(-4, 5):
                try:
                    candidates.append(parsed.replace(year=today.year + offset))
                except ValueError:
                    continue
            parsed = min(candidates, key=lambda d: abs(d - today))
        return parsed
    return datetime.max


def _match_sort_key(match: Match) -> datetime:
    """Prefer source timestamps; keep label-only dates sortable."""
    if match.starts_at:
        return match.starts_at.astimezone(UTC)
    date = _parse_date(match.date_label)
    for pattern in ("%I:%M %p", "%H:%M"):
        try:
            clock = datetime.strptime(match.time_label, pattern)
            date = date.replace(hour=clock.hour, minute=clock.minute)
            break
        except ValueError:
            continue
    return date.replace(tzinfo=UTC)


def filter_today(matches: list[Match], zone: tzinfo | None) -> list[Match]:
    """Keep matches whose known start falls on today's date in a timezone.

    Args:
        matches: Matches to filter.
        zone: Timezone that defines "today"; None means local.

    Returns:
        Matches starting today; matches without a start time are dropped.
    """
    today = datetime.now().astimezone(zone).date()
    return [
        match
        for match in matches
        if match.starts_at and match.starts_at.astimezone(zone).date() == today
    ]


def filter_matches_by_team(matches: list[Match], team_name: str | None) -> list[Match]:
    """Keep matches where either team contains a name, ignoring case.

    Args:
        matches: Matches to filter.
        team_name: Partial team name; None keeps everything.
    """
    if not team_name:
        return matches
    team_lower = team_name.lower()
    return [
        match
        for match in matches
        if team_lower in match.team1.lower() or team_lower in match.team2.lower()
    ]


def filter_matches_by_favorites(
    matches: list[Match], favorite_teams: Iterable[str]
) -> list[Match]:
    """Keep matches with at least one saved favorite team.

    Args:
        matches: Matches to filter.
        favorite_teams: Exact team names, compared case-insensitively.
    """
    favorites = {team.casefold() for team in favorite_teams}
    return [
        match
        for match in matches
        if match.team1.casefold() in favorites or match.team2.casefold() in favorites
    ]


def sort_matches(matches: list[Match], sort_by: SortKey | None) -> list[Match]:
    """Sort matches by start time or first team name.

    Args:
        matches: Matches to sort.
        sort_by: "date", "team", or None to keep source order.
    """
    if sort_by == "date":
        return sorted(matches, key=_match_sort_key)
    if sort_by == "team":
        return sorted(matches, key=lambda match: match.team1.lower())
    return matches


def group_matches(
    matches: list[Match], group_by: GroupKey | None, zone: tzinfo | None = None
) -> dict[str, list[Match]]:
    """Group matches by display date or status.

    Args:
        matches: Matches to group, already in display order.
        group_by: "date", "status", or None for a single "all" group.
        zone: Timezone used for date labels.

    Returns:
        Groups in first-seen order.
    """
    if not group_by:
        return {"all": matches}

    grouped: dict[str, list[Match]] = defaultdict(list)
    for match in matches:
        key = match.local_date_time(zone)[0] if group_by == "date" else match.status
        grouped[key].append(match)
    return dict(grouped)


def prepare_matches(
    matches: list[Match],
    *,
    zone: tzinfo | None = None,
    today_only: bool = False,
    team: str | None = None,
    favorite_teams: Iterable[str] = (),
    favorites_only: bool = False,
    sort_by: SortKey | None = None,
) -> list[Match]:
    """Apply the shared filters and sorting used by both CLI modes.

    Args:
        matches: Fetched matches.
        zone: Timezone that defines "today".
        today_only: Keep only matches starting today.
        team: Partial team-name filter.
        favorite_teams: Saved favorite team names.
        favorites_only: Keep only matches with a favorite team.
        sort_by: "date", "team", or None.

    Returns:
        Matches ready to display or export.
    """
    prepared = filter_today(matches, zone) if today_only else matches
    prepared = filter_matches_by_team(prepared, team)
    if favorites_only:
        prepared = filter_matches_by_favorites(prepared, favorite_teams)
    return sort_matches(prepared, sort_by)


def display_results(
    matches: list[Match],
    formatter: Formatter,
    *,
    compact: bool = False,
    group_by: GroupKey | None = None,
    zone: tzinfo | None = None,
) -> None:
    """Print matches, optionally under group headers.

    Args:
        matches: Matches in display order.
        formatter: Output formatter.
        compact: Use single-line match entries.
        group_by: "date", "status", or None.
        zone: Display timezone.
    """
    for group_key, group in group_matches(matches, group_by, zone).items():
        if group_by:
            label, style = STATUS_GROUP_LABELS.get(group_key, (group_key, "info"))
            formatter.blank()
            formatter.print(label if group_by == "status" else group_key, style, True)
            formatter.rule(30)
        for match in group:
            formatter.print_match(match, zone, compact)


def print_empty_results(
    formatter: Formatter,
    *,
    view_mode: str,
    team: str | None = None,
    today_only: bool = False,
    favorites_only: bool = False,
    interactive: bool = False,
) -> None:
    """Explain why nothing was shown and suggest a next step.

    Args:
        formatter: Output formatter.
        view_mode: "all", "results", or "upcoming".
        team: Active team filter, if any.
        today_only: Whether the --today filter was active.
        favorites_only: Whether the favorites filter was active.
        interactive: Phrase hints for interactive mode instead of CLI flags.
    """
    hints = INTERACTIVE_HINTS if interactive else CLI_HINTS
    if today_only:
        formatter.warning("No matches with known start times today.")
        return
    if favorites_only:
        formatter.warning("No matches found for saved favorite teams.")
        return

    if team:
        message, hint = f"No matches found for team filter: {team}", hints["team"]
    elif view_mode == "upcoming":
        message = "No upcoming matches are scheduled right now for this event."
        hint = hints["upcoming"]
    elif view_mode == "results":
        message = "No completed matches are available for this event yet."
        hint = hints["results"]
    else:
        message, hint = "No matches available to display right now.", hints["all"]
    formatter.blank()
    formatter.warning(message)
    formatter.muted(hint)


@dataclass
class WatchState:
    """Keep the previous successful match values across refreshes."""

    previous: dict[str, tuple[str, str]] = field(default_factory=dict)
    last_success: str | None = None

    def report(self, matches: list[Match], formatter: Formatter) -> None:
        """Print score/status changes without losing unseen previous values.

        Args:
            matches: Matches from the latest refresh.
            formatter: Output formatter.
        """
        for match in matches:
            current = (match.score or "–", match.status)
            before = self.previous.get(match.url)
            if before is not None and before != current:
                formatter.print(
                    f"Changed: {match.team1} vs {match.team2}: "
                    f"{before[0]} ({before[1]}) → {current[0]} ({current[1]})"
                )
            self.previous[match.url] = current


def run_cli_mode(
    opts: RunOptions, formatter: Formatter, discovery: EventDiscovery
) -> int:
    """Show matches once, or refresh until Ctrl+C in watch mode.

    Args:
        opts: Resolved run options.
        formatter: Output formatter.
        discovery: Event discovery service.

    Returns:
        Process exit code: 0 success, 1 failure, 130 when watch is interrupted.
    """
    formatter.set_favorite_teams(opts.favorite_teams)
    if not opts.watch:
        return _run_cli_once(opts, formatter, discovery)

    state = WatchState()
    formatter.print("Watching matches. Press Ctrl+C to stop.")
    try:
        while True:
            if _run_cli_once(opts, formatter, discovery, state) == 0:
                state.last_success = (
                    datetime.now().astimezone().isoformat(timespec="seconds")
                )
            else:
                formatter.print("Refresh incomplete; retrying after the interval.")
            formatter.print(
                f"Last successful update: {state.last_success or 'none yet'}"
            )
            time.sleep(opts.interval)
    except KeyboardInterrupt:
        formatter.print("Watch stopped.")
        return 130


def _report_no_events(
    opts: RunOptions, formatter: Formatter, discovery: EventDiscovery
) -> int:
    """Explain an empty event selection and return the exit code."""
    if (
        opts.view_mode == "upcoming"
        and not opts.event_id
        and discovery.discover_events()
    ):
        formatter.warning("No upcoming VCT events are scheduled for this selection.")
        return 0
    target = opts.event_id or opts.region or "favorite teams"
    formatter.blank()
    formatter.error(f"No events found for: {target}")
    formatter.muted(
        "Try --list-regions to see discovered options, "
        "or run with --refresh to force discovery."
    )
    formatter.blank()
    return 1


def _export(
    export_format: ExportFormat,
    opts: RunOptions,
    matches: list[Match],
    formatter: Formatter,
    stats: MatchStats,
) -> int:
    """Write the export file and return the exit code."""
    path = opts.output or f"matches.{export_format}"
    try:
        count = export_matches(matches, export_format, path, zone=opts.zone)
    except OSError as error:
        formatter.error(f"Export failed: {error}")
        return 1
    print_error_summary(formatter, stats.errors)
    formatter.success(f"Exported {count} matches to {path}")
    formatter.blank()
    return 1 if stats.failed else 0  # Partial exports are not complete success


def _run_cli_once(
    opts: RunOptions,
    formatter: Formatter,
    discovery: EventDiscovery,
    watch_state: WatchState | None = None,
) -> int:
    """Select events, fetch, filter, and display or export one time.

    Args:
        opts: Resolved run options.
        formatter: Output formatter.
        discovery: Event discovery service.
        watch_state: Previous values to compare against in watch mode.

    Returns:
        0 on success (including an empty schedule), 1 on any failure.
    """
    start_time = time.monotonic()
    stats = MatchStats()
    if not opts.cache_enabled:
        logger.info("Cache disabled for this run")

    events = select_events(
        discovery,
        region=opts.region,
        event_id=opts.event_id,
        favorites_only=opts.favorites_only,
        view_mode=opts.view_mode,
        force_refresh=opts.refresh,
    )
    if not events:
        return _report_no_events(opts, formatter, discovery)
    notice = saved_discovery_notice(discovery)
    if notice:
        formatter.warning(notice)

    fetched = fetch_matches(
        events,
        formatter,
        view_mode=opts.view_mode,
        cache_enabled=opts.cache_enabled,
        stats=stats,
    )
    if not stats.total and not opts.export and not stats.failed:
        formatter.blank()
        formatter.warning("No matches found for the selected event page.")
        formatter.muted(
            "The event may not have posted matches yet. "
            "Try --refresh or check another region."
        )
        formatter.blank()
        return 0
    if stats.failed and not fetched:
        formatter.error("Match retrieval incomplete; no usable matches returned.")
        print_error_summary(formatter, stats.errors)
        return 1

    sort_by = opts.sort_by
    if sort_by is None and opts.auto_sort and len(events) > 1:
        sort_by = "date"
    matches = prepare_matches(
        fetched,
        zone=opts.zone,
        today_only=opts.today,
        team=opts.team,
        favorite_teams=opts.favorite_teams,
        favorites_only=opts.favorites_only,
        sort_by=sort_by,
    )
    if watch_state is not None:
        watch_state.report(matches, formatter)
    logger.info(f"Displaying {len(matches)} matches")
    formatter.blank()

    if opts.export:
        return _export(opts.export, opts, matches, formatter, stats)

    if matches:
        display_results(
            matches,
            formatter,
            compact=opts.compact,
            group_by=opts.group_by,
            zone=opts.zone,
        )
    else:
        print_empty_results(
            formatter,
            view_mode=opts.view_mode,
            team=opts.team,
            today_only=opts.today,
            favorites_only=opts.favorites_only,
        )

    formatter.blank()
    formatter.print_stats_footer(
        displayed=len(matches),
        cache_hits=stats.cache_hits,
        failed=stats.failed,
        tbd_count=stats.tbd_count,
        fetch_time=time.monotonic() - start_time,
        live_count=sum(match.status == "live" for match in matches),
        skipped_count=stats.skipped_count,
    )
    print_error_summary(formatter, stats.errors)
    return 1 if stats.failed else 0
