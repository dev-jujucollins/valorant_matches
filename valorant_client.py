# Core functionality for fetching and processing Valorant match data.

import logging
import logging.config
import re

# Thread-safe rate limiter
import threading
import time
from dataclasses import asdict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)

from cache import MatchCache
from config import (
    BASE_URL,
    EVENTS,
    HEADERS,
    LOGGING_CONFIG,
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
    is_upcoming_match,
)

_rate_limit_lock = threading.Lock()
_last_request_time = 0.0


def _apply_rate_limit() -> None:
    """Apply thread-safe rate limiting before requests."""
    global _last_request_time
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        _last_request_time = time.time()


# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")


class ValorantClient(CircuitBreakerMixin):
    """Client for fetching and processing Valorant match data."""

    def __init__(self, cache_enabled: bool = True):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        # Configure connection pooling for better performance
        adapter = HTTPAdapter(
            pool_connections=10,  # Number of connection pools
            pool_maxsize=20,  # Max connections per pool
            max_retries=0,  # We handle retries ourselves
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.formatter = Formatter()
        self.cache = MatchCache(enabled=cache_enabled)
        self._cache_enabled = cache_enabled
        # Initialize circuit breaker
        self._init_circuit_breaker()
        # Slug pattern cache for performance
        self._slug_pattern_cache: dict[str, re.Pattern] = {}

    def _get_slug_pattern(self, slug: str) -> re.Pattern:
        """Get or create a compiled slug pattern (cached for performance)."""
        if slug not in self._slug_pattern_cache:
            escaped_slug = re.escape(slug.lower())
            self._slug_pattern_cache[slug] = re.compile(rf"(^|-)({escaped_slug})(-|$)")
        return self._slug_pattern_cache[slug]

    def _is_retryable_error(
        self, error: Exception, response: requests.Response | None = None
    ) -> bool:
        """Determine if an error is transient and worth retrying."""
        # Connection errors and timeouts are always retryable
        if isinstance(error, (ConnectionError, Timeout)):
            return True

        # For HTTP errors, check the status code
        if isinstance(error, HTTPError) and response is not None:
            # 5xx errors are server-side and often transient
            # 429 (Too Many Requests) is also retryable after backoff
            return response.status_code >= 500 or response.status_code == 429

        # Other errors (4xx client errors, etc.) are not retryable
        return False

    def _make_request(
        self, url: str, retries: int = MAX_RETRIES
    ) -> BeautifulSoup | None:
        """Make an HTTP request with exponential backoff retry logic and circuit breaker."""
        try:
            self._check_circuit_breaker()
        except CircuitBreakerOpen as e:
            logger.warning(str(e))
            return None

        for attempt in range(retries):
            response = None
            try:
                # Apply rate limiting before each request attempt
                _apply_rate_limit()
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                self._record_success()
                return BeautifulSoup(response.text, "lxml")
            except RequestException as e:
                # Check if this error is worth retrying
                is_retryable = self._is_retryable_error(e, response)

                if is_retryable and attempt < retries - 1:
                    logger.warning(
                        f"Transient error (attempt {attempt + 1}/{retries}): {str(e)}"
                    )
                    backoff_delay = self._calculate_backoff(attempt)
                    logger.debug(f"Retrying in {backoff_delay:.2f}s...")
                    time.sleep(backoff_delay)
                elif not is_retryable:
                    # Permanent error - don't retry
                    logger.warning(f"Permanent error, not retrying: {str(e)}")
                    self._record_failure()
                    return None
                else:
                    # Exhausted retries
                    logger.error(
                        f"Failed to fetch data from {url} after {retries} attempts"
                    )
                    self._record_failure()
                    return None
        return None

    def get_event_url(self, choice: str) -> str | None:
        """Get the URL for the selected event."""
        if choice in EVENTS:
            return EVENTS[choice].url
        exit_choice = str(len(EVENTS) + 1)
        if choice == exit_choice:
            logger.info("User chose to exit")
            return None
        logger.warning(f"Invalid event choice: {choice}")
        return None

    def fetch_event_matches(
        self, event_url: str, event_slug: str | None = None
    ) -> list[dict]:
        """Fetch all matches for an event.

        Args:
            event_url: The event matches page URL
            event_slug: Optional event slug to filter matches (e.g., 'vct-2026-americas-kickoff')
                       If not provided, extracts from event_url automatically.
        """
        logger.info(f"Fetching matches for event:\n{event_url}\n")
        soup = self._make_request(event_url)
        if not soup:
            return []

        # Extract event slug from URL if not provided (using pre-compiled pattern)
        if not event_slug:
            slug_match = EVENT_SLUG_PATTERN.search(event_url)
            if slug_match:
                event_slug = slug_match.group(1)

        # Get cached slug pattern for word boundary matching
        slug_pattern = self._get_slug_pattern(event_slug) if event_slug else None

        # Find matching links using pre-compiled patterns
        match_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Must start with /<number>/ (using pre-compiled MATCH_URL_PATTERN)
            if not MATCH_URL_PATTERN.match(href):
                continue
            # If we have a slug, verify it matches as a complete segment
            if slug_pattern and not slug_pattern.search(href.lower()):
                continue
            match_links.append(link)

        logger.info(f"Found {len(match_links)} match links")
        return match_links

    def process_match(self, link: dict, upcoming_only: bool = False) -> str | None:
        """Process a single match and return formatted output."""
        match_url = urljoin(BASE_URL, link["href"])
        logger.debug(f"Processing match: {match_url}")

        try:
            # Check cache first (but not for upcoming matches filter)
            if not upcoming_only and self._cache_enabled:
                cached_data = self.cache.get(match_url)
                if cached_data:
                    cached_match = Match(**cached_data)
                    # Don't use cache for live matches (need fresh data)
                    # Also don't use cache for matches that were previously upcoming
                    # (they may have completed since caching)
                    if not cached_match.is_live and not cached_match.is_upcoming:
                        return self._format_match_output(cached_match)

            soup = self._make_request(match_url)
            if not soup:
                return None

            teams, score, is_live = extract_match_data(soup)
            if "TBD" in teams:
                return None

            match_date, match_time = extract_date_time(soup)

            # Determine if this is an upcoming match
            is_upcoming = is_upcoming_match(score)

            # If filtering for upcoming only, skip completed matches
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

            # Cache only completed matches (not live or upcoming)
            # This ensures transitioning matches get fresh data
            if self._cache_enabled and not match.is_live and not match.is_upcoming:
                self.cache.set(match_url, asdict(match))
            elif self._cache_enabled:
                # Invalidate cache for matches that are now live/upcoming
                # (in case they were previously cached as completed incorrectly)
                self.cache.invalidate(match_url)

            return self._format_match_output(match)

        except RequestException as e:
            logger.error(f"Network error processing match {match_url}: {e}")
            return None
        except (AttributeError, TypeError, IndexError) as e:
            logger.error(f"HTML parsing error for match {match_url}: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Data extraction error for match {match_url}: {e}")
            return None
        except Exception as e:
            # Keep a catch-all but log full traceback for debugging
            logger.error(
                f"Unexpected error processing match {match_url}: {e}", exc_info=True
            )
            return None

    def _format_match_output(self, match: Match) -> str:
        """Format match data for display."""
        return self.formatter.format_match_full(match)

    def display_menu(self) -> str:
        """Display the event selection menu."""
        print(f"\n{self.formatter.info(' Available Regions:', bold=True)}")
        for key, event in EVENTS.items():
            print(
                f"{self.formatter.primary(f'{key}.', bold=True)} {self.formatter.highlight(event.name)}"
            )
        print(
            f"{self.formatter.primary('6.', bold=True)} {self.formatter.muted('Exit')}\n"
        )
        return input(f"{self.formatter.info('Select an event:', bold=True)} ").strip()

    def display_view_mode_menu(self) -> str:
        """Display the view mode selection menu."""
        print(f"\n{self.formatter.info(' View Mode:', bold=True)}")
        print(
            f"{self.formatter.primary('1.', bold=True)} {self.formatter.highlight('All Matches')}"
        )
        print(
            f"{self.formatter.primary('2.', bold=True)} {self.formatter.highlight('Results Only')} {self.formatter.muted('(completed matches)')}"
        )
        print(
            f"{self.formatter.primary('3.', bold=True)} {self.formatter.highlight('Upcoming Only')} {self.formatter.muted('(scheduled matches)')}"
        )
        print(
            f"{self.formatter.primary('4.', bold=True)} {self.formatter.muted('Back to Events')}\n"
        )
        return input(f"{self.formatter.info('Select view mode:', bold=True)} ").strip()
