# Synchronous entry points that drive the async client.

import asyncio
import logging
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import Progress

from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import (
    FetchError,
    ProcessedMatches,
    build_match_from_soup,
)

logger = logging.getLogger("valorant_matches")

PROGRESS_LABELS = {
    "all": "Fetching all matches...",
    "results": "Fetching match results...",
    "upcoming": "Fetching upcoming matches...",
}


@dataclass
class EventFetchResult:
    """Outcome of fetching and processing one event's matches."""

    error: FetchError | None = None
    total_links: int = 0
    processed: ProcessedMatches = field(
        default_factory=lambda: ProcessedMatches(results=[])
    )


async def _fetch_event_data(
    event_url: str,
    event_slug: str | None,
    view_mode: str,
    cache_enabled: bool,
    show_progress: bool,
    console: Console | None = None,
) -> EventFetchResult:
    async with AsyncValorantClient(cache_enabled=cache_enabled) as client:
        rows = await client.fetch_event_listing(event_url, event_slug)
        if not rows:
            return EventFetchResult(error=client.http.errors.get(event_url))

        if show_progress:
            task_label = PROGRESS_LABELS.get(view_mode, "Fetching matches...")
            # transient: the bar is progress, not output, so it clears itself.
            with Progress(console=console, transient=True) as progress:
                task = progress.add_task(
                    f"[bright_magenta] {task_label}",
                    total=len(rows),
                )
                processed = await process_matches_async(
                    client,
                    rows,
                    view_mode,
                    progress_callback=lambda: progress.update(task, advance=1),
                )
        else:
            processed = await process_matches_async(client, rows, view_mode)

        return EventFetchResult(total_links=len(rows), processed=processed)


def fetch_event_data(
    event_url: str,
    event_slug: str | None = None,
    view_mode: str = "all",
    cache_enabled: bool = True,
    show_progress: bool = True,
    console: Console | None = None,
) -> EventFetchResult:
    """Fetch an event's match listing and process it in one async session.

    Args:
        event_url: Event matches page URL.
        event_slug: Slug that match links must contain; derived when omitted.
        view_mode: "all", "results", or "upcoming".
        cache_enabled: Read and write the match cache.
        show_progress: Show a Rich progress bar while matches load.
        console: Console for the progress bar; Rich's default when omitted.

    Returns:
        The event-level error, or processed matches with counts.
    """
    return asyncio.run(
        _fetch_event_data(
            event_url, event_slug, view_mode, cache_enabled, show_progress, console
        )
    )


@dataclass
class ParserCheck:
    """What a live parsing check found on one event.

    Attributes:
        rows: Match links found on the event listing.
        detailed: Rows whose teams and status could be read from the listing.
        sample_url: Match page fetched to check page parsing, if any.
        problems: Human-readable failures; empty when everything parsed.
    """

    rows: int = 0
    detailed: int = 0
    sample_url: str | None = None
    problems: list[str] = field(default_factory=list)


async def _check_event_parsing(event_url: str, event_slug: str | None) -> ParserCheck:
    check = ParserCheck()
    # One listing and one match page: no need to space the two requests out.
    http = HttpFetcher(rate_limit_delay=0)
    async with AsyncValorantClient(cache_enabled=False, http=http) as client:
        rows = await client.fetch_event_listing(event_url, event_slug)
        check.rows = len(rows)
        check.detailed = sum(row.has_details for row in rows)
        if not rows:
            error = client.http.errors.get(event_url)
            check.problems.append(
                f"Event listing failed: {error.message}"
                if error
                else "Event listing has no match links"
            )
            return check
        if not check.detailed:
            check.problems.append(
                "Listing rows could not be read (teams/status markup changed?)"
            )

        decided = [row for row in rows if not row.is_tbd]
        if not decided:
            return check  # Every team is undecided: no match page to verify yet.
        sample = decided[0]
        check.sample_url = sample.url
        soup = await client.http.fetch(sample.url)
        if not soup:
            error = client.http.errors.get(sample.url)
            reason = error.message if error else "no response"
            check.problems.append(f"Match page failed: {reason}")
            return check
        result = build_match_from_soup(soup, sample.url)
        match = result.match
        if result.error:
            check.problems.append(f"Match page: {result.error.message}")
        elif match and match.starts_at is None and "TBD" not in match.time_label:
            check.problems.append("Match page has no readable start time")
        if (
            match
            and sample.has_details
            and (match.team1, match.team2) != (sample.team1, sample.team2)
        ):
            check.problems.append(
                "Listing and match page disagree on team names: "
                f"{sample.team1} / {sample.team2} vs {match.team1} / {match.team2}"
            )
    return check


def check_event_parsing(event_url: str, event_slug: str | None = None) -> ParserCheck:
    """Fetch one event listing and one match page to verify live parsing.

    Args:
        event_url: Event matches page URL.
        event_slug: Slug that match links must contain; derived when omitted.

    Returns:
        Counts plus any problems found. Never reads or writes the cache.
    """
    return asyncio.run(_check_event_parsing(event_url, event_slug))
