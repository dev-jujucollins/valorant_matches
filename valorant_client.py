"""Core functionality for fetching and processing Valorant match data."""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from rich.progress import Progress

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
    """Represents a Valorant match."""

    date: str
    time: str
    team1: str
    team2: str
    score: str
    is_live: bool
    url: str


class ValorantClient:
    """Client for fetching and processing Valorant match data."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.formatter = Formatter()

    def _make_request(
        self, url: str, retries: int = MAX_RETRIES
    ) -> Optional[BeautifulSoup]:
        """Make an HTTP request with retry logic."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.content, "html.parser")
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
        """Get the URL for the selected event."""
        if choice in EVENTS:
            return EVENTS[choice].url
        elif choice == "5":
            logger.info("User chose to exit")
            return None
        logger.warning(f"Invalid event choice: {choice}")
        return None

    def fetch_event_matches(self, event_url: str) -> List[Dict]:
        """Fetch all matches for an event."""
        logger.info(f"Fetching matches for event: {event_url}")
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

    def process_match(self, link: Dict) -> Optional[str]:
        """Process a single match and return formatted output."""
        match_url = urljoin(BASE_URL, link["href"])
        logger.debug(f"Processing match: {match_url}")

        try:
            soup = self._make_request(match_url)
            if not soup:
                return None

            teams, score, is_live = self._extract_match_data(soup)
            if "TBD" in teams:
                return None

            match_date, match_time = self._extract_date_time(soup)
            match = Match(
                date=match_date,
                time=match_time,
                team1=teams[0],
                team2=teams[1],
                score=score,
                is_live=bool(is_live),
                url=match_url,
            )
            return self._format_match_output(match)

        except Exception as e:
            logger.error(f"Error processing match {match_url}: {str(e)}")
            return None

    def _extract_match_data(
        self, soup: BeautifulSoup
    ) -> Tuple[List[str], str, Optional[bool]]:
        """Extract team names, score, and live status from match page."""
        teams = [
            team.text.strip() for team in soup.find_all("div", class_="wf-title-med")
        ][:2]
        teams = [team.split("(")[0].strip() for team in teams]

        try:
            score = soup.find("div", class_="js-spoiler").text.strip()
            score = " ".join(score.split())
        except AttributeError:
            score = "Match has not started yet."

        is_live = bool(soup.find("span", class_="match-header-vs-note mod-live"))
        return teams, score, is_live

    def _extract_date_time(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract match date and time."""
        date_elem = soup.find("div", class_="moment-tz-convert")
        match_date = date_elem.text.strip()
        match_time = date_elem.find_next("div").text.strip()
        return match_date, match_time

    def _format_match_output(self, match: Match) -> str:
        """Format match data for display."""
        status = "In Progress" if match.is_live else ""
        return f"{self.formatter.format(f"{match.date}  {match.time}", "white")} | {self.formatter.format(f"{match.team1} vs {match.team2}", "white")} | Score: {self.formatter.format(f"{match.score}", "green")} {self.formatter.format(status, "red")}\n{self.formatter.format(f"Stats: {match.url}", "cyan")}\n{'-' * 100}\n"

    def display_menu(self) -> str:
        """Display the event selection menu."""
        print("\nRegions:")
        for key, event in EVENTS.items():
            print(f"{key}. {event.name}")
        print("5. Exit\n")
        return input("\nWhich matches would you like to see results for: ").strip()
