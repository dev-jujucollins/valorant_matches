# Core functionality for fetching and processing Valorant match data.

import logging
import logging.config
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict
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
    MATCH_CODES,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)
from formatter import Formatter

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")


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


class ValorantClient:
    # Client for fetching and processing Valorant match data

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.formatter = Formatter()
        self.cache = MatchCache()

    def _make_request(
        self, url: str, retries: int = MAX_RETRIES
    ) -> Optional[BeautifulSoup]:
        # Make an HTTP request with retry logic
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except RequestException as e:
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{retries}): {str(e)}"
                )
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(
                        f"Failed to fetch data from {url} after {retries} attempts"
                    )
                    return None

    def get_event_url(self, choice: str) -> Optional[str]:
        # Get the URL for the selected event
        if choice in EVENTS:
            return EVENTS[choice].url
        elif choice == "6":
            logger.info("User chose to exit")
            return None
        logger.warning(f"Invalid event choice: {choice}")
        return None

    def fetch_event_matches(self, event_url: str) -> List[Dict]:
        # Fetch all matches for an event
        logger.info(f"Fetching matches for event:\n{event_url}\n")
        soup = self._make_request(event_url)
        if not soup:
            return []

        match_links = [
            link
            for link in soup.find_all("a", href=True)
            if any(code in link["href"] for code in MATCH_CODES)
        ]
        logger.info(f"Found {len(match_links)} matches")
        return match_links

    def process_match(self, link: Dict, upcoming_only: bool = False) -> Optional[str]:
        # Process a single match and return formatted output
        match_url = urljoin(BASE_URL, link["href"])
        logger.debug(f"Processing match: {match_url}")

        try:
            # Check cache first (but not for upcoming matches filter)
            if not upcoming_only:
                cached_data = self.cache.get(match_url)
                if cached_data:
                    match = Match(**cached_data)
                    # Don't use cache for live matches (need fresh data)
                    if not match.is_live:
                        return self._format_match_output(match)

            soup = self._make_request(match_url)
            if not soup:
                return None

            teams, score, is_live = self._extract_match_data(soup)
            if "TBD" in teams:
                return None

            match_date, match_time = self._extract_date_time(soup)

            # Determine if this is an upcoming match
            is_upcoming = score.lower().startswith("match has not started")

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

            # Cache the match data (but not live or upcoming matches)
            if not match.is_live and not match.is_upcoming:
                self.cache.set(match_url, asdict(match))

            return self._format_match_output(match)

        except Exception as e:
            logger.error(f"Error processing match {match_url}: {str(e)}")
            return None

    def _extract_match_data(
        self, soup: BeautifulSoup
    ) -> Tuple[List[str], str, Optional[bool]]:
        # Extract team names, score, and live status from match page
        # Uses fallback selectors for resilience against HTML changes
        teams = self._extract_teams(soup)
        score = self._extract_score(soup)
        is_live = self._extract_live_status(soup)
        return teams, score, is_live

    def _extract_teams(self, soup: BeautifulSoup) -> List[str]:
        """Extract team names with fallback selectors."""
        # Primary selector
        team_selectors = [
            ("div", {"class_": "wf-title-med"}),
            ("div", {"class_": "match-header-link-name"}),
            ("a", {"class_": "match-header-link"}),
        ]

        for tag, attrs in team_selectors:
            elements = soup.find_all(tag, **attrs)
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
            ("div", {"class_": "js-spoiler"}),
            ("div", {"class_": "match-header-vs-score"}),
            ("span", {"class_": "match-header-vs-score-winner"}),
        ]

        for tag, attrs in score_selectors:
            score_elem = soup.find(tag, **attrs)
            if score_elem:
                score = score_elem.text.strip()
                score = " ".join(score.split())
                if score:
                    return score

        return "Match has not started yet."

    def _extract_live_status(self, soup: BeautifulSoup) -> bool:
        """Extract live status with fallback selectors."""
        live_selectors = [
            ("span", {"class_": "match-header-vs-note mod-live"}),
            ("span", {"class_": "mod-live"}),
            ("div", {"class_": "match-header-vs-note mod-live"}),
        ]

        for tag, attrs in live_selectors:
            if soup.find(tag, **attrs):
                return True

        # Also check for "LIVE" text in the header area
        header = soup.find("div", class_="match-header-vs")
        if header and "live" in header.text.lower():
            return True

        return False

    def _extract_date_time(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract match date and time with fallback selectors."""
        date_selectors = [
            ("div", {"class_": "moment-tz-convert"}),
            ("div", {"class_": "match-header-date"}),
            ("span", {"class_": "moment-tz-convert"}),
        ]

        for tag, attrs in date_selectors:
            date_elem = soup.find(tag, **attrs)
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
        return input(
            f"{self.formatter.info('Select an event:', bold=True)} "
        ).strip()

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
        return input(
            f"{self.formatter.info('Select view mode:', bold=True)} "
        ).strip()
