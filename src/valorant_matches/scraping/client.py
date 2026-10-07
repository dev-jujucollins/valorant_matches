# Async match client: event match lists, cached match pages, and batching.

import asyncio
import logging
import re
from collections.abc import Callable
from types import TracebackType

from valorant_matches.cache import MatchCache
from valorant_matches.config import CACHE_ENABLED
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import (
    FetchError,
    Match,
    ProcessedMatches,
    ProcessMatchResult,
    build_match_from_soup,
    extract_event_slug,
    find_event_match_urls,
    should_use_cached_match,
)

logger = logging.getLogger("valorant_matches")

# Status a match must have to be shown in each view; None keeps everything.
VIEW_MODE_STATUS = {"all": None, "results": "completed", "upcoming": "upcoming"}


class AsyncValorantClient:
    """Fetch event and match pages, reading and writing the match cache."""

    def __init__(
        self, cache_enabled: bool | None = None, http: HttpFetcher | None = None
    ) -> None:
        self.cache = MatchCache(
            enabled=CACHE_ENABLED if cache_enabled is None else cache_enabled
        )
        self.http = http or HttpFetcher()

    async def __aenter__(self) -> "AsyncValorantClient":
        """Open the underlying HTTP session."""
        await self.http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP session."""
        await self.http.__aexit__(exc_type, exc_val, exc_tb)

    async def fetch_event_match_urls(
        self, event_url: str, event_slug: str | None = None
    ) -> list[str]:
        """Fetch the match URLs listed on an event's matches page.

        Args:
            event_url: Event matches page URL.
            event_slug: Slug that match links must contain; derived when omitted.

        Returns:
            Absolute match URLs, or an empty list when the page failed.
        """
        logger.info(f"Fetching matches for event: {event_url}")
        soup = await self.http.fetch(event_url)
        if not soup:
            return []

        event_slug = event_slug or extract_event_slug(event_url)
        slug_pattern = (
            re.compile(rf"(^|-)({re.escape(event_slug.lower())})(-|$)")
            if event_slug
            else None
        )
        match_urls = find_event_match_urls(soup, slug_pattern)
        logger.info(f"Found {len(match_urls)} match links")
        return match_urls

    async def process_match(
        self, match_url: str, upcoming_only: bool = False
    ) -> ProcessMatchResult:
        """Load one match from the cache or its page.

        Args:
            match_url: Absolute match page URL.
            upcoming_only: Mark non-upcoming matches as skipped.

        Returns:
            The match with cache, TBD, skip, or error metadata.
        """
        logger.debug(f"Processing match: {match_url}")

        try:
            cached_data = self.cache.get(match_url)
            if cached_data is not None:
                try:
                    cached = Match.from_dict(cached_data)
                except (TypeError, ValueError):
                    logger.warning(f"Discarding malformed cached match for {match_url}")
                    self.cache.invalidate(match_url)
                else:
                    if should_use_cached_match(cached):
                        if upcoming_only:
                            return ProcessMatchResult(skipped=True, cache_hit=True)
                        return ProcessMatchResult(match=cached, cache_hit=True)

            soup = await self.http.fetch(match_url)
            if not soup:
                return ProcessMatchResult(
                    error=self.http.errors.get(match_url)
                    or FetchError(match_url, "fetch", "Could not fetch match page")
                )

            result = build_match_from_soup(soup, match_url)
            match = result.match
            if match is None:
                return result

            # Only finished matches are stable enough to cache.
            if match.status == "completed":
                self.cache.set(match_url, match.to_dict())
            else:
                self.cache.invalidate(match_url)

            if upcoming_only and match.status != "upcoming":
                return ProcessMatchResult(skipped=True)
            return result

        except (ValueError, TypeError, KeyError, OSError) as e:
            logger.error(f"Error processing match {match_url}: {e}", exc_info=True)
            return ProcessMatchResult(error=FetchError(match_url, "processing", str(e)))


async def process_matches_async(
    client: AsyncValorantClient,
    match_urls: list[str],
    view_mode: str = "all",
    progress_callback: Callable[[], None] | None = None,
) -> ProcessedMatches:
    """Process matches concurrently and keep the event page's order.

    Args:
        client: An open client.
        match_urls: Absolute match URLs.
        view_mode: "all", "results", or "upcoming"; other statuses are skipped.
        progress_callback: Called once per finished match.

    Returns:
        Matches plus TBD, cache, skip, and failure counts.
    """
    wanted_status = VIEW_MODE_STATUS.get(view_mode)
    processed = ProcessedMatches(results=[])

    async def process_single(match_url: str) -> ProcessMatchResult:
        result = await client.process_match(match_url, wanted_status == "upcoming")
        if progress_callback:
            progress_callback()
        return result

    # gather() returns in task order, so results stay in original link order
    completed = await asyncio.gather(
        *(process_single(url) for url in match_urls), return_exceptions=True
    )

    for match_url, item in zip(match_urls, completed, strict=True):
        if isinstance(item, BaseException):
            logger.warning(f"Failed to process match: {item}")
            processed.failed_count += 1
            processed.errors.append(FetchError(match_url, "processing", str(item)))
            continue
        if item.cache_hit:
            processed.cache_hits += 1
        if item.skipped:
            processed.skipped_count += 1
        elif item.is_tbd:
            processed.tbd_count += 1
        elif item.match:
            if wanted_status and item.match.status != wanted_status:
                processed.skipped_count += 1
            else:
                processed.results.append(item.match)
        else:
            processed.failed_count += 1
            processed.errors.append(
                item.error
                or FetchError(match_url, "processing", "No match data returned")
            )

    return processed
