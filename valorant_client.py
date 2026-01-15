# Core functionality for fetching and processing Valorant match data.

import logging
import logging.config
import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

from cache import MatchCache
from config import (
    BASE_URL,
    EVENTS,
    HEADERS,
    LOGGING_CONFIG,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)
from formatter import Formatter

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")

# Maximum backoff delay in seconds
MAX_BACKOFF_DELAY = 30

# Circuit breaker settings
CIRCUIT_BREAKER_THRESHOLD = 5  # Number of consecutive failures to trip
CIRCUIT_BREAKER_RESET_TIME = 60  # Seconds before attempting to reset


@dataclass
class Match:
    # Represents a Valorant match

    date: str
    time: str
    team1: str
    team2: str
    score: str
    is_live: bool
    url: str
    is_upcoming: bool = False


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and requests are blocked."""

    pass


class ValorantClient:
    # Client for fetching and processing Valorant match data

    def __init__(self, cache_enabled: bool = True):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.formatter = Formatter()
        self.cache = MatchCache(enabled=cache_enabled)
        self._cache_enabled = cache_enabled
        # Circuit breaker state
        self._failure_count = 0
        self._circuit_open_time: float | None = None

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = RETRY_DELAY * (2**attempt)
        # Add some jitter (0-25% of delay)
        jitter = delay * 0.25 * (time.time() % 1)
        return min(delay + jitter, MAX_BACKOFF_DELAY)

    def _check_circuit_breaker(self) -> None:
        """Check if circuit breaker allows requests. Raises CircuitBreakerOpen if not."""
        if self._circuit_open_time is not None:
            elapsed = time.time() - self._circuit_open_time
            if elapsed < CIRCUIT_BREAKER_RESET_TIME:
                raise CircuitBreakerOpen(
                    f"Circuit breaker open. Retry in {CIRCUIT_BREAKER_RESET_TIME - elapsed:.0f}s"
                )
            # Try to reset the circuit breaker
            logger.info("Circuit breaker attempting reset...")
            self._circuit_open_time = None
            self._failure_count = 0

    def _record_success(self) -> None:
        """Record a successful request, resetting failure count."""
        self._failure_count = 0
        self._circuit_open_time = None

    def _record_failure(self) -> None:
        """Record a failed request, potentially tripping the circuit breaker."""
        self._failure_count += 1
        if self._failure_count >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open_time = time.time()
            logger.error(
                f"Circuit breaker tripped after {self._failure_count} consecutive failures. "
                f"Blocking requests for {CIRCUIT_BREAKER_RESET_TIME}s"
            )

    def _make_request(
        self, url: str, retries: int = MAX_RETRIES
    ) -> BeautifulSoup | None:
        # Make an HTTP request with exponential backoff retry logic and circuit breaker
        try:
            self._check_circuit_breaker()
        except CircuitBreakerOpen as e:
            logger.warning(str(e))
            return None

        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                self._record_success()
                return BeautifulSoup(response.text, "html.parser")
            except RequestException as e:
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{retries}): {str(e)}"
                )
                if attempt < retries - 1:
                    backoff_delay = self._calculate_backoff(attempt)
                    logger.debug(f"Retrying in {backoff_delay:.2f}s...")
                    time.sleep(backoff_delay)
                else:
                    logger.error(
                        f"Failed to fetch data from {url} after {retries} attempts"
                    )
                    self._record_failure()
                    return None
        return None

    def get_event_url(self, choice: str) -> str | None:
        # Get the URL for the selected event
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

        # Extract event slug from URL if not provided
        if not event_slug:
            slug_match = re.search(r"/event/matches/\d+/([^/]+)", event_url)
            if slug_match:
                event_slug = slug_match.group(1)

        # Match pattern: links starting with /<number>/ that contain the event slug
        # Example: /596399/envy-vs-evil-geniuses-vct-2026-americas-kickoff-ur1
        match_pattern = re.compile(r"^/\d+/")

        # Create slug pattern with word boundaries (using hyphen as delimiter)
        # This prevents "vct" from matching "valorant-challengers-vct"
        slug_pattern = None
        if event_slug:
            # Escape special regex characters and match as a complete segment
            escaped_slug = re.escape(event_slug.lower())
            slug_pattern = re.compile(rf"(^|-)({escaped_slug})(-|$)")

        match_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Must start with /<number>/
            if not match_pattern.match(href):
                continue
            # If we have a slug, verify it matches as a complete segment
            if slug_pattern and not slug_pattern.search(href.lower()):
                continue
            match_links.append(link)

        logger.info(f"Found {len(match_links)} matches")
        return match_links

    def process_match(self, link: dict, upcoming_only: bool = False) -> str | None:
        # Process a single match and return formatted output
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

            teams, score, is_live = self._extract_match_data(soup)
            if "TBD" in teams:
                return None

            match_date, match_time = self._extract_date_time(soup)

            # Determine if this is an upcoming match
            # Check for "match has not started" or countdown timers like "19h 37m", "1d 5h"
            is_upcoming = (
                score.lower().startswith("match has not started")
                or bool(
                    re.match(r"^\d+[dhm]\s", score)
                )  # Countdown: "19h 37m", "1d 5h"
            )

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

    def _extract_match_data(
        self, soup: BeautifulSoup
    ) -> tuple[list[str], str, bool | None]:
        # Extract team names, score, and live status from match page
        # Uses fallback selectors for resilience against HTML changes
        teams = self._extract_teams(soup)
        score = self._extract_score(soup)
        is_live = self._extract_live_status(soup)
        return teams, score, is_live

    def _extract_teams(self, soup: BeautifulSoup) -> list[str]:
        """Extract team names with fallback selectors."""
        # Primary selector
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

        logger.warning("Could not extract team names with any selector")
        return ["Unknown Team 1", "Unknown Team 2"]

    def _extract_score(self, soup: BeautifulSoup) -> str:
        """Extract match score with fallback selectors."""
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

        # Also check for "LIVE" text in the header area
        header = soup.find("div", class_="match-header-vs")
        return bool(header and "live" in header.text.lower())

    def _extract_date_time(self, soup: BeautifulSoup) -> tuple[str, str]:
        """Extract match date and time with fallback selectors."""
        date_selectors = [
            ("div", "moment-tz-convert"),
            ("div", "match-header-date"),
            ("span", "moment-tz-convert"),
        ]

        for tag, class_name in date_selectors:
            date_elem = soup.find(tag, class_=class_name)
            if date_elem:
                match_date = date_elem.text.strip()
                time_elem = date_elem.find_next("div")
                match_time = time_elem.text.strip() if time_elem else "Unknown time"
                if match_date and match_date != "Unknown date":
                    return match_date, match_time

        logger.debug("Could not extract date/time with any selector")
        return "Unknown date", "Unknown time"

    def _format_match_output(self, match: Match) -> str:
        # Format match data for display
        separator = "─" * 100
        date_time = self.formatter.date_time(f"{match.date}  {match.time}")
        teams = self.formatter.team_name(f"{match.team1} vs {match.team2}")
        stats_link = self.formatter.stats_link(f"Stats: {match.url}")

        # Determine status and score display
        if match.is_live:
            status = self.formatter.live_status("LIVE")
            score = self.formatter.score(match.score)
            return f"{date_time} | {teams} | Score: {score} {status}\n{stats_link}\n{self.formatter.muted(separator)}\n"
        elif match.is_upcoming:
            status = self.formatter.warning("UPCOMING")
            return f"{date_time} | {teams} | {status}\n{stats_link}\n{self.formatter.muted(separator)}\n"
        else:
            score = self.formatter.score(match.score)
            return f"{date_time} | {teams} | Score: {score}\n{stats_link}\n{self.formatter.muted(separator)}\n"

    def display_menu(self) -> str:
        # Display the event selection menu
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
        # Display the view mode selection menu
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
