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
    RETRY_DELAY,
)
from formatter import Formatter
from valorant_client import (
    COUNTDOWN_PATTERN,
    EVENT_SLUG_PATTERN,
    MATCH_URL_PATTERN,
    CircuitBreakerOpen,
    Match,
)

logger = logging.getLogger("valorant_matches")

# Maximum backoff delay in seconds
MAX_BACKOFF_DELAY = 30

# Circuit breaker settings
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_RESET_TIME = 60


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


class AsyncValorantClient:
    """Async client for fetching and processing Valorant match data."""

    def __init__(self, cache_enabled: bool = True):
        self.formatter = Formatter()
        self.cache = MatchCache(enabled=cache_enabled)
        self._cache_enabled = cache_enabled
        self._failure_count = 0
        self._circuit_open_time: float | None = None
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

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = RETRY_DELAY * (2**attempt)
        jitter = delay * 0.25 * (time.time() % 1)
        return min(delay + jitter, MAX_BACKOFF_DELAY)

    def _check_circuit_breaker(self) -> None:
        """Check if circuit breaker allows requests."""
        if self._circuit_open_time is not None:
            elapsed = time.time() - self._circuit_open_time
            if elapsed < CIRCUIT_BREAKER_RESET_TIME:
                raise CircuitBreakerOpen(
                    f"Circuit breaker open. Retry in {CIRCUIT_BREAKER_RESET_TIME - elapsed:.0f}s"
                )
            logger.info("Circuit breaker attempting reset...")
            self._circuit_open_time = None
            self._failure_count = 0

    def _record_success(self) -> None:
        """Record a successful request."""
        self._failure_count = 0
        self._circuit_open_time = None

    def _record_failure(self) -> None:
        """Record a failed request."""
        self._failure_count += 1
        if self._failure_count >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open_time = time.time()
            logger.error(
                f"Circuit breaker tripped after {self._failure_count} failures"
            )

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
                    return BeautifulSoup(text, "lxml")

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
    ) -> str | None:
        """Process a single match asynchronously."""
        match_url = urljoin(BASE_URL, link["href"])
        logger.debug(f"Processing match: {match_url}")

        try:
            if not upcoming_only and self._cache_enabled:
                cached_data = self.cache.get(match_url)
                if cached_data:
                    cached_match = Match(**cached_data)
                    if not cached_match.is_live and not cached_match.is_upcoming:
                        return self._format_match_output(cached_match)

            soup = await self._make_request(match_url)
            if not soup:
                return None

            teams, score, is_live = self._extract_match_data(soup)
            if "TBD" in teams:
                return None

            match_date, match_time = self._extract_date_time(soup)

            is_upcoming = score.lower().startswith("match has not started") or bool(
                COUNTDOWN_PATTERN.match(score)
            )

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

            return self._format_match_output(match)

        except Exception as e:
            logger.error(f"Error processing match {match_url}: {e}")
            return None

    def _extract_match_data(
        self, soup: BeautifulSoup
    ) -> tuple[list[str], str, bool | None]:
        """Extract team names, score, and live status from match page."""
        teams = self._extract_teams(soup)
        score = self._extract_score(soup)
        is_live = self._extract_live_status(soup)
        return teams, score, is_live

    def _extract_teams(self, soup: BeautifulSoup) -> list[str]:
        """Extract team names with fallback selectors."""
        team_selectors = [
            ("div", "wf-title-med"),
            ("div", "match-header-link-name"),
            ("a", "match-header-link"),
        ]

        for tag, class_name in team_selectors:
            elements = soup.find_all(tag, class_=class_name)
            if elements and len(elements) >= 2:
                teams = [el.text.strip() for el in elements][:2]
                teams = [team.split("(")[0].strip() for team in teams]
                if all(teams):
                    return teams

        return ["Unknown Team 1", "Unknown Team 2"]

    def _extract_score(self, soup: BeautifulSoup) -> str:
        """Extract match score with fallback selectors."""
        # First, check for upcoming match countdown (e.g., "0h 38m", "1d 5h")
        upcoming_elem = soup.find("span", class_="match-header-vs-note mod-upcoming")
        if upcoming_elem:
            countdown = upcoming_elem.text.strip()
            countdown = " ".join(countdown.split())
            if countdown:
                return countdown

        # Then check for completed/live match scores
        score_selectors = [
            ("div", "js-spoiler"),
            ("div", "match-header-vs-score"),
            ("span", "match-header-vs-score-winner"),
        ]

        for tag, class_name in score_selectors:
            score_elem = soup.find(tag, class_=class_name)
            if score_elem:
                score = score_elem.text.strip()
                score = " ".join(score.split())
                if score:
                    return score

        return "Match has not started yet."

    def _extract_live_status(self, soup: BeautifulSoup) -> bool:
        """Extract live status with fallback selectors."""
        live_selectors = [
            ("span", "match-header-vs-note mod-live"),
            ("span", "mod-live"),
            ("div", "match-header-vs-note mod-live"),
        ]

        for tag, class_name in live_selectors:
            if soup.find(tag, class_=class_name):
                return True

        header = soup.find("div", class_="match-header-vs")
        return bool(header and "live" in header.text.lower())

    def _extract_date_time(self, soup: BeautifulSoup) -> tuple[str, str]:
        """Extract match date and time with fallback selectors."""
        # Use specific selectors in order of preference (avoid broad container matches)
        date_selectors = [
            ("div", "moment-tz-convert"),
            ("span", "moment-tz-convert"),
        ]

        for tag, class_name in date_selectors:
            date_elem = soup.find(tag, class_=class_name)
            if date_elem:
                match_date = date_elem.text.strip()
                time_elem = date_elem.find_next("div", class_="moment-tz-convert")
                if not time_elem:
                    time_elem = date_elem.find_next("div")
                match_time = time_elem.text.strip() if time_elem else "Unknown time"
                if match_date and match_date != "Unknown date":
                    return match_date, match_time

        return "Unknown date", "Unknown time"

    def _format_eta(self, score: str) -> str:
        """Format ETA for upcoming matches from score field.

        The score field for upcoming matches contains countdown text like
        "0h 42m", "1d 5h", or "Match has not started yet."
        This extracts and formats the time until the match starts.
        """
        # Check if score contains a countdown pattern (e.g., "0h 42m", "1d 5h")
        if COUNTDOWN_PATTERN.match(score):
            return f"in {score}"
        # Fallback for matches without countdown info
        return "UPCOMING"

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
            # Display time until match starts if available (e.g., "1h 30m", "2d 5h")
            eta = self._format_eta(match.score)
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
) -> list[tuple]:
    """Process matches concurrently using asyncio."""
    results = []
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
        # item is now guaranteed to be tuple[dict, str | None]
        link, result = item
        if result is not None:
            if results_only and "UPCOMING" in result:
                continue
            results.append((link, result))

    # Sort by original order
    return sorted(results, key=lambda x: match_links.index(x[0]))
