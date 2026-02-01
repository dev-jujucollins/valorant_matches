# Shared match extraction logic used by both sync and async clients.

import logging
import re
import time
from dataclasses import dataclass

from bs4 import BeautifulSoup

from config import RETRY_DELAY

logger = logging.getLogger("valorant_matches")

# Pre-compiled regex patterns for performance
MATCH_URL_PATTERN = re.compile(r"^/\d+/")
EVENT_SLUG_PATTERN = re.compile(r"/event/matches/\d+/([^/]+)")
COUNTDOWN_PATTERN = re.compile(r"^\d+[dhm]\s")

# Maximum backoff delay in seconds
MAX_BACKOFF_DELAY = 30

# Circuit breaker settings
CIRCUIT_BREAKER_THRESHOLD = 5  # Number of consecutive failures to trip
CIRCUIT_BREAKER_RESET_TIME = 60  # Seconds before attempting to reset

# CSS selectors for extracting match data (fallback strategies)
TEAM_SELECTORS = [
    ("div", "wf-title-med"),
    ("div", "match-header-link-name"),
    ("a", "match-header-link"),
]

SCORE_SELECTORS = [
    ("div", "js-spoiler"),
    ("div", "match-header-vs-score"),
    ("span", "match-header-vs-score-winner"),
]

LIVE_SELECTORS = [
    ("span", "match-header-vs-note mod-live"),
    ("span", "mod-live"),
    ("div", "match-header-vs-note mod-live"),
]

DATE_SELECTORS = [
    ("div", "moment-tz-convert"),
    ("span", "moment-tz-convert"),
]


@dataclass
class Match:
    """Represents a Valorant match."""

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


class CircuitBreakerMixin:
    """Mixin providing circuit breaker functionality for HTTP clients."""

    _failure_count: int
    _circuit_open_time: float | None

    def _init_circuit_breaker(self) -> None:
        """Initialize circuit breaker state. Call in __init__."""
        self._failure_count = 0
        self._circuit_open_time = None

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


def extract_teams(soup: BeautifulSoup) -> list[str]:
    """Extract team names with fallback selectors."""
    for tag, class_name in TEAM_SELECTORS:
        elements = soup.find_all(tag, class_=class_name)
        if elements and len(elements) >= 2:
            teams = [el.text.strip() for el in elements][:2]
            teams = [team.split("(")[0].strip() for team in teams]
            if all(teams):
                return teams

    logger.warning("Could not extract team names with any selector")
    return ["Unknown Team 1", "Unknown Team 2"]


def extract_score(soup: BeautifulSoup) -> str:
    """Extract match score with fallback selectors."""
    # First, check for upcoming match countdown (e.g., "0h 38m", "1d 5h")
    upcoming_elem = soup.find("span", class_="match-header-vs-note mod-upcoming")
    if upcoming_elem:
        countdown = upcoming_elem.text.strip()
        countdown = " ".join(countdown.split())
        if countdown:
            return countdown

    # Then check for completed/live match scores
    for tag, class_name in SCORE_SELECTORS:
        score_elem = soup.find(tag, class_=class_name)
        if score_elem:
            score = score_elem.text.strip()
            score = " ".join(score.split())
            if score:
                return score

    return "Match has not started yet."


def extract_live_status(soup: BeautifulSoup) -> bool:
    """Extract live status with fallback selectors."""
    for tag, class_name in LIVE_SELECTORS:
        if soup.find(tag, class_=class_name):
            return True

    header = soup.find("div", class_="match-header-vs")
    return bool(header and "live" in header.text.lower())


def extract_date_time(soup: BeautifulSoup) -> tuple[str, str]:
    """Extract match date and time with fallback selectors."""
    for tag, class_name in DATE_SELECTORS:
        date_elem = soup.find(tag, class_=class_name)
        if date_elem:
            match_date = date_elem.text.strip()
            time_elem = date_elem.find_next("div", class_="moment-tz-convert")
            if not time_elem:
                time_elem = date_elem.find_next("div")
            match_time = time_elem.text.strip() if time_elem else "Unknown time"
            if match_date and match_date != "Unknown date":
                return match_date, match_time

    logger.debug("Could not extract date/time with any selector")
    return "Unknown date", "Unknown time"


def extract_match_data(soup: BeautifulSoup) -> tuple[list[str], str, bool]:
    """Extract team names, score, and live status from match page."""
    teams = extract_teams(soup)
    score = extract_score(soup)
    is_live = extract_live_status(soup)
    return teams, score, is_live


def format_eta(score: str) -> str:
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


def is_upcoming_match(score: str) -> bool:
    """Determine if a match is upcoming based on its score text."""
    return score.lower().startswith("match has not started") or bool(
        COUNTDOWN_PATTERN.match(score)
    )
