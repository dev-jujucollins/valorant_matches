# Synchronous entry point that drives the async client for one event fetch.

import asyncio
import logging
from dataclasses import dataclass, field

from rich.progress import Progress

from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.matches import FetchError, ProcessedMatches

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
) -> EventFetchResult:
    async with AsyncValorantClient(cache_enabled=cache_enabled) as client:
        match_urls = await client.fetch_event_match_urls(event_url, event_slug)
        if not match_urls:
            return EventFetchResult(error=client.http.errors.get(event_url))

        if show_progress:
            task_label = PROGRESS_LABELS.get(view_mode, "Fetching matches...")
            with Progress() as progress:
                task = progress.add_task(
                    f"[bright_magenta] {task_label}",
                    total=len(match_urls),
                )
                processed = await process_matches_async(
                    client,
                    match_urls,
                    view_mode,
                    progress_callback=lambda: progress.update(task, advance=1),
                )
            print("")
        else:
            processed = await process_matches_async(client, match_urls, view_mode)

        return EventFetchResult(total_links=len(match_urls), processed=processed)


def fetch_event_data(
    event_url: str,
    event_slug: str | None = None,
    view_mode: str = "all",
    cache_enabled: bool = True,
    show_progress: bool = True,
) -> EventFetchResult:
    """Fetch an event's match links and process them in one async session.

    Args:
        event_url: Event matches page URL.
        event_slug: Slug that match links must contain; derived when omitted.
        view_mode: "all", "results", or "upcoming".
        cache_enabled: Read and write the completed-match cache.
        show_progress: Show a Rich progress bar while matches load.

    Returns:
        The event-level error, or processed matches with counts.
    """
    return asyncio.run(
        _fetch_event_data(
            event_url, event_slug, view_mode, cache_enabled, show_progress
        )
    )
