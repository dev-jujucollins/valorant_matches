# Async match client: event listings, cached match pages, and batching.

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from types import TracebackType

from valorant_matches.cache import MatchCache
from valorant_matches.config import CACHE_ENABLED
from valorant_matches.scraping.http import HttpFetcher
from valorant_matches.scraping.matches import (
    FetchError,
    ListingRow,
    Match,
    ProcessedMatches,
    ProcessMatchResult,
    build_match_from_soup,
    extract_event_slug,
    parse_event_listing,
    should_use_cached_match,
)

logger = logging.getLogger("valorant_matches")

# Status a match must have to be shown in each view; None keeps everything.
VIEW_MODE_STATUS = {"all": None, "results": "completed", "upcoming": "upcoming"}


class AsyncValorantClient:
    """Fetch event and match pages, reading and writing the match cache.

    The event listing supplies teams, score, and status for every match. A
    match page is only fetched for what the listing lacks, the start time, and
    the result is cached until the listing shows the match was rescheduled.
    """

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

    async def fetch_event_listing(
        self, event_url: str, event_slug: str | None = None
    ) -> list[ListingRow]:
        """Fetch the match rows listed on an event's matches page.

        Args:
            event_url: Event matches page URL.
            event_slug: Slug that match links must contain; derived when omitted.

        Returns:
            Listing rows in page order, or an empty list when the page failed.
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
        rows = parse_event_listing(soup, slug_pattern)
        detailed = sum(row.has_details for row in rows)
        logger.info(f"Found {len(rows)} match links ({detailed} with listing details)")
        if rows and not detailed:
            logger.debug("Listing rows unreadable; falling back to match pages")
        return rows

    def _cached_match(self, row: ListingRow) -> Match | None:
        """Return the cached match, refreshed from the listing row, if usable."""
        entry = self.cache.get(row.url)
        if entry is None:
            return None
        try:
            cached = Match.from_dict(entry["match"])
            schedule = entry["schedule"]
        except (TypeError, ValueError, KeyError):
            logger.warning(f"Discarding malformed cached match for {row.url}")
            self.cache.invalidate(row.url)
            return None

        status = row.status
        listing_is_enough = row.has_details and not (
            status == "completed" and row.score is None
        )
        if status is None or not listing_is_enough:
            # Nothing to refresh the cached copy with: trust finished matches only.
            return cached if should_use_cached_match(cached) else None
        if schedule != row.schedule:
            logger.debug(f"Listed schedule changed for {row.url}; refetching")
            return None
        return replace(cached, status=status, score=row.score, countdown=row.countdown)

    async def process_match(self, target: ListingRow | str) -> ProcessMatchResult:
        """Load one match from the listing and cache, or from its page.

        Args:
            target: A listing row, or a bare match URL when no row is known.

        Returns:
            The match with cache, TBD, or error metadata.
        """
        row = ListingRow(url=target) if isinstance(target, str) else target
        logger.debug(f"Processing match: {row.url}")

        try:
            if row.is_tbd:
                return ProcessMatchResult(is_tbd=True)

            cached = self._cached_match(row)
            if cached is not None:
                return ProcessMatchResult(match=cached, cache_hit=True)

            soup = await self.http.fetch(row.url)
            if not soup:
                return ProcessMatchResult(
                    error=self.http.errors.get(row.url)
                    or FetchError(row.url, "fetch", "Could not fetch match page")
                )

            result = build_match_from_soup(soup, row.url)
            match = result.match
            if match is None:
                return result

            # With a listing row, later runs can refresh status and score, so
            # any match is safe to cache. Without one, only finished matches are.
            if row.has_details or match.status == "completed":
                self.cache.set(
                    row.url, {"match": match.to_dict(), "schedule": row.schedule}
                )
            else:
                self.cache.invalidate(row.url)
            return result

        except (ValueError, TypeError, KeyError, OSError) as e:
            logger.error(f"Error processing match {row.url}: {e}", exc_info=True)
            return ProcessMatchResult(error=FetchError(row.url, "processing", str(e)))


def _target_url(target: ListingRow | str) -> str:
    """Return the match URL of a listing row or bare URL."""
    return target if isinstance(target, str) else target.url


async def process_matches_async(
    client: AsyncValorantClient,
    targets: Sequence[ListingRow | str],
    view_mode: str = "all",
    progress_callback: Callable[[], None] | None = None,
) -> ProcessedMatches:
    """Process matches concurrently and keep the event page's order.

    Args:
        client: An open client.
        targets: Listing rows, or bare match URLs when no rows are known.
        view_mode: "all", "results", or "upcoming"; other statuses are skipped.
        progress_callback: Called once per finished match.

    Returns:
        Matches plus TBD, cache, skip, and failure counts.
    """
    wanted_status = VIEW_MODE_STATUS.get(view_mode)
    processed = ProcessedMatches(results=[])

    async def process_single(target: ListingRow | str) -> ProcessMatchResult:
        listed = None if isinstance(target, str) else target
        if (
            wanted_status
            and listed is not None
            and listed.has_details
            and not listed.is_tbd
            and listed.status != wanted_status
        ):
            # The listing already says this match is not wanted: no request.
            result = ProcessMatchResult(skipped=True)
        else:
            result = await client.process_match(target)
        if progress_callback:
            progress_callback()
        return result

    # gather() returns in task order, so results stay in original link order
    completed = await asyncio.gather(
        *(process_single(target) for target in targets), return_exceptions=True
    )

    for target, item in zip(targets, completed, strict=True):
        match_url = _target_url(target)
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
