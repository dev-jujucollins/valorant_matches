# Async HTTP client for high-performance match fetching.

import asyncio
import logging
import re
import time
from dataclasses import asdict
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from cache import MatchCache
from config import (
    BASE_URL,
    HEADERS,
    MAX_RETRIES,
    RATE_LIMIT_DELAY,
    REQUEST_TIMEOUT,
)
from formatter import Formatter
from match_extractor import (
    EVENT_SLUG_PATTERN,
    MATCH_URL_PATTERN,
    CircuitBreakerMixin,
    CircuitBreakerOpen,
    Match,
    extract_date_time,
    extract_match_data,
    format_eta,
    is_upcoming_match,
)

logger = logging.getLogger("valorant_matches")


class AsyncRateLimiter:
    """Async-compatible rate limiter."""

    def __init__(self, delay: float = RATE_LIMIT_DELAY):
        self._delay = delay
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for rate limit before proceeding."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)
            self._last_request = time.time()


class AsyncValorantClient(CircuitBreakerMixin):
    """Async client for fetching and processing Valorant match data."""

    def __init__(self, cache_enabled: bool = True):
        self.formatter = Formatter()
        self.cache = MatchCache(enabled=cache_enabled)
        self._cache_enabled = cache_enabled
        self._init_circuit_breaker()
        self._slug_pattern_cache: dict[str, re.Pattern] = {}
        self._rate_limiter = AsyncRateLimiter()
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "AsyncValorantClient":
        """Async context manager entry."""
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(
            limit=20,  # Max concurrent connections
            limit_per_host=10,  # Per-host limit
        )
        self._session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=timeout,
            connector=connector,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._session:
            await self._session.close()

    def _get_slug_pattern(self, slug: str) -> re.Pattern:
        """Get or create a compiled slug pattern (cached)."""
        if slug not in self._slug_pattern_cache:
            escaped_slug = re.escape(slug.lower())
            self._slug_pattern_cache[slug] = re.compile(rf"(^|-)({escaped_slug})(-|$)")
        return self._slug_pattern_cache[slug]

    def _is_retryable_status(self, status: int) -> bool:
        """Check if HTTP status code is retryable."""
        return status >= 500 or status == 429

    async def _make_request(
        self, url: str, retries: int = MAX_RETRIES
    ) -> BeautifulSoup | None:
        """Make an async HTTP request with retry logic."""
        if not self._session:
            raise RuntimeError("Client not initialized. Use async with context.")

        try:
            self._check_circuit_breaker()
        except CircuitBreakerOpen as e:
            logger.warning(str(e))
            return None

        for attempt in range(retries):
            try:
                await self._rate_limiter.acquire()
                async with self._session.get(url) as response:
                    if response.status >= 400:
                        if (
                            self._is_retryable_status(response.status)
                            and attempt < retries - 1
                        ):
                            logger.warning(
                                f"Retryable status {response.status} (attempt {attempt + 1})"
                            )
                            await asyncio.sleep(self._calculate_backoff(attempt))
                            continue
                        else:
                            logger.warning(f"HTTP error {response.status} for {url}")
                            self._record_failure()
                            return None

                    text = await response.text()
                    self._record_success()
                    # Run BeautifulSoup parsing in thread pool to avoid blocking
                    soup = await asyncio.to_thread(BeautifulSoup, text, "lxml")
                    return soup

            except TimeoutError:
                if attempt < retries - 1:
                    logger.warning(f"Timeout (attempt {attempt + 1}/{retries})")
                    await asyncio.sleep(self._calculate_backoff(attempt))
                else:
                    logger.error(f"Timeout after {retries} attempts for {url}")
                    self._record_failure()
                    return None

            except aiohttp.ClientError as e:
                if attempt < retries - 1:
                    logger.warning(f"Client error (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(self._calculate_backoff(attempt))
                else:
                    logger.error(f"Failed after {retries} attempts: {e}")
                    self._record_failure()
                    return None

        return None

    async def fetch_event_matches(
        self, event_url: str, event_slug: str | None = None
    ) -> list[dict]:
        """Fetch all matches for an event asynchronously."""
        logger.info(f"Fetching matches for event:\n{event_url}\n")
        soup = await self._make_request(event_url)
        if not soup:
            return []

        if not event_slug:
            slug_match = EVENT_SLUG_PATTERN.search(event_url)
            if slug_match:
                event_slug = slug_match.group(1)

        slug_pattern = self._get_slug_pattern(event_slug) if event_slug else None

        match_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not MATCH_URL_PATTERN.match(href):
                continue
            if slug_pattern and not slug_pattern.search(href.lower()):
                continue
            match_links.append(link)

        logger.info(f"Found {len(match_links)} match links")
        return match_links

    async def process_match(
        self, link: dict, upcoming_only: bool = False
    ) -> Match | str | None:
        """Process a single match asynchronously.

        Returns:
            Match object if successful, "TBD" if teams not announced, None on failure.
        """
        match_url = urljoin(BASE_URL, link["href"])
        logger.debug(f"Processing match: {match_url}")

        try:
            if not upcoming_only and self._cache_enabled:
                cached_data = self.cache.get(match_url)
                if cached_data:
                    cached_match = Match(**cached_data)
                    if not cached_match.is_live and not cached_match.is_upcoming:
                        return cached_match

            soup = await self._make_request(match_url)
            if not soup:
                return None

            teams, score, is_live = extract_match_data(soup)
            if "TBD" in teams:
                return "TBD"  # Sentinel value for TBD matches

            match_date, match_time = extract_date_time(soup)

            is_upcoming = is_upcoming_match(score)

            if upcoming_only and not is_upcoming and not is_live:
                return None

            match = Match(
                date=match_date,
                time=match_time,
                team1=teams[0],
                team2=teams[1],
                score=score,
                is_live=bool(is_live),
                url=match_url,
                is_upcoming=is_upcoming,
            )

            if self._cache_enabled and not match.is_live and not match.is_upcoming:
                self.cache.set(match_url, asdict(match))
            elif self._cache_enabled:
                self.cache.invalidate(match_url)

            return match

        except Exception as e:
            logger.error(f"Error processing match {match_url}: {e}")
            return None

    def _format_match_output(self, match: Match) -> str:
        """Format match data for display."""
        separator = "─" * 100
        date_time = self.formatter.date_time(f"{match.date}  {match.time}")
        teams = self.formatter.team_name(f"{match.team1} vs {match.team2}")
        stats_link = self.formatter.stats_link(f"Stats: {match.url}")

        if match.is_live:
            status = self.formatter.live_status("LIVE")
            score = self.formatter.score(match.score)
            return f"{date_time} | {teams} | Score: {score} {status}\n{stats_link}\n{self.formatter.muted(separator)}\n"
        elif match.is_upcoming:
            eta = format_eta(match.score)
            status = self.formatter.warning(eta)
            return f"{date_time} | {teams} | {status}\n{stats_link}\n{self.formatter.muted(separator)}\n"
        else:
            score = self.formatter.score(match.score)
            return f"{date_time} | {teams} | Score: {score}\n{stats_link}\n{self.formatter.muted(separator)}\n"


async def process_matches_async(
    client: AsyncValorantClient,
    match_links: list[dict],
    view_mode: str = "all",
    progress_callback=None,
) -> tuple[list[tuple[dict, Match]], int]:
    """Process matches concurrently using asyncio.

    Returns:
        Tuple of (results, tbd_count) where results is list of (link_dict, Match) tuples.
    """
    results: list[tuple[dict, Match]] = []
    tbd_count = 0
    upcoming_only = view_mode == "upcoming"
    results_only = view_mode == "results"

    # Create tasks for all matches
    async def process_single(link):
        result = await client.process_match(link, upcoming_only)
        if progress_callback:
            progress_callback()
        return (link, result)

    # Process all matches concurrently
    tasks = [process_single(link) for link in match_links]
    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for item in completed:
        if isinstance(item, BaseException):
            logger.warning(f"Failed to process match: {item}")
            continue
        # item is now guaranteed to be tuple[dict, Match | str | None]
        link, match = item
        if match == "TBD":
            tbd_count += 1
        elif isinstance(match, Match):
            if results_only and match.is_upcoming:
                continue
            results.append((link, match))

    # Sort by original order
    sorted_results = sorted(results, key=lambda x: match_links.index(x[0]))
    return (sorted_results, tbd_count)
