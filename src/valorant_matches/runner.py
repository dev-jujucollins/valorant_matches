# Synchronous entry point that drives the async client for one event fetch.

import asyncio
import logging
from dataclasses import dataclass, field

from rich.progress import Progress

from valorant_matches.async_client import AsyncValorantClient, process_matches_async
from valorant_matches.match_extractor import ProcessedMatches

logger = logging.getLogger("valorant_matches")

PROGRESS_LABELS = {
    "all": "Fetching all matches...",
    "results": "Fetching match results...",
    "upcoming": "Fetching upcoming matches...",
}


@dataclass
class EventFetchResult:
    """Outcome of fetching and processing one event's matches."""

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
        match_links = await client.fetch_event_matches(event_url, event_slug)
        if not match_links:
            return EventFetchResult()

        if show_progress:
            task_label = PROGRESS_LABELS.get(view_mode, "Fetching matches...")
            with Progress() as progress:
                task = progress.add_task(
                    f"[bright_magenta] {task_label}",
                    total=len(match_links),
                )
                processed = await process_matches_async(
                    client,
                    match_links,
                    view_mode,
                    progress_callback=lambda: progress.update(task, advance=1),
                )
            print("")
        else:
            processed = await process_matches_async(client, match_links, view_mode)

        return EventFetchResult(total_links=len(match_links), processed=processed)


def fetch_event_data(
    event_url: str,
    event_slug: str | None = None,
    view_mode: str = "all",
    cache_enabled: bool = True,
    show_progress: bool = True,
) -> EventFetchResult:
    """Fetch an event's match links and process them in one async session."""
    return asyncio.run(
        _fetch_event_data(
            event_url, event_slug, view_mode, cache_enabled, show_progress
        )
    )
