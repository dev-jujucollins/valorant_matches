# Auto-discovery of VCT events from vlr.gg.

import logging
import re
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)

from config import BASE_URL, HEADERS, MAX_RETRIES, REQUEST_TIMEOUT, RETRY_DELAY

logger = logging.getLogger("valorant_matches")

# Cache TTL for discovered events (24 hours)
EVENT_CACHE_TTL = 86400

# VCT series ID for current year (2026)
VCT_SERIES_ID = "86"

# Region mappings for CLI aliases
REGION_ALIASES: dict[str, list[str]] = {
    "americas": ["americas", "am"],
    "emea": ["emea", "eu"],
    "pacific": ["pacific", "apac"],
    "china": ["china", "cn"],
    "champions": ["champions"],
    "masters": ["masters"],
}

# Pre-compiled regex patterns for performance
VCT_SLUG_PATTERN = re.compile(r"vct-(\d{4})-([^-]+)-(.+)")
CHAMPIONS_SLUG_PATTERN = re.compile(r"valorant-(champions|masters)-(\d{4})")
MASTERS_CITY_PATTERN = re.compile(r"valorant-masters-([^-]+)-(\d{4})")
EVENT_ID_PATTERN = re.compile(r"/event/(\d+)/([^/]+)")
EVENT_LINK_PATTERN = re.compile(r"^/event/\d+/")
EVENT_NAME_PATTERN = re.compile(
    r"((?:VCT \d{4}:|Valorant (?:Champions|Masters))[^$\d]+)"
)


@dataclass
class DiscoveredEvent:
    """Represents a discovered VCT event."""

    name: str
    url: str
    event_id: str
    slug: str
    status: str  # "upcoming", "ongoing", "completed"
    dates: str
    region: str


class EventDiscovery:
    """Discovers VCT events from vlr.gg."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        # Configure connection pooling for better performance
        adapter = HTTPAdapter(
            pool_connections=5,
            pool_maxsize=10,
            max_retries=0,  # We handle retries ourselves
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._cache: TTLCache = TTLCache(maxsize=10, ttl=EVENT_CACHE_TTL)

    def _is_retryable_error(
        self, error: Exception, response: requests.Response | None = None
    ) -> bool:
        """Determine if an error is transient and worth retrying."""
        if isinstance(error, (ConnectionError, Timeout)):
            return True
        if isinstance(error, HTTPError) and response is not None:
            return response.status_code >= 500 or response.status_code == 429
        return False

    def _make_request(self, url: str) -> BeautifulSoup | None:
        """Make an HTTP request with smart retry logic."""
        for attempt in range(MAX_RETRIES):
            response = None
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return BeautifulSoup(response.text, "lxml")
            except RequestException as e:
                is_retryable = self._is_retryable_error(e, response)

                if is_retryable and attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"Transient error (attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                    )
                    time.sleep(RETRY_DELAY * (2**attempt))
                elif not is_retryable:
                    logger.warning(f"Permanent error, not retrying: {e}")
                    return None
                else:
                    logger.error(f"Failed after {MAX_RETRIES} attempts: {e}")
                    return None
        return None

    def _slug_to_name(self, slug: str) -> str | None:
        """Convert event slug to human-readable name."""
        # Pattern: vct-2026-americas-kickoff -> VCT 2026: Americas Kickoff
        vct_match = VCT_SLUG_PATTERN.match(slug)
        if vct_match:
            year, region, stage = vct_match.groups()
            region = region.capitalize()
            stage = stage.replace("-", " ").title()
            return f"VCT {year}: {region} {stage}"

        # Pattern: valorant-champions-2026 -> Valorant Champions 2026
        champ_match = CHAMPIONS_SLUG_PATTERN.match(slug)
        if champ_match:
            event_type, year = champ_match.groups()
            return f"Valorant {event_type.capitalize()} {year}"

        # Pattern: valorant-masters-city-2026 -> Valorant Masters City 2026
        masters_match = MASTERS_CITY_PATTERN.match(slug)
        if masters_match:
            city, year = masters_match.groups()
            return f"Valorant Masters {city.capitalize()} {year}"

        return None

    def _parse_region(self, event_name: str) -> str:
        """Extract region from event name."""
        name_lower = event_name.lower()
        if "americas" in name_lower:
            return "americas"
        elif "emea" in name_lower:
            return "emea"
        elif "pacific" in name_lower:
            return "pacific"
        elif "china" in name_lower:
            return "china"
        elif "champions" in name_lower:
            return "champions"
        elif "masters" in name_lower:
            return "masters"
        return "other"

    def _extract_event_id(self, href: str) -> tuple[str, str] | None:
        """Extract event ID and slug from href like /event/2682/vct-2026-americas-kickoff."""
        match = EVENT_ID_PATTERN.match(href)
        if match:
            return match.group(1), match.group(2)
        return None

    def discover_events(self, force_refresh: bool = False) -> list[DiscoveredEvent]:
        """Discover current VCT events from vlr.gg."""
        cache_key = "vct_events"

        # Check cache (TTLCache auto-expires entries)
        if not force_refresh and cache_key in self._cache:
            logger.debug("Using cached event list")
            return self._cache[cache_key]

        logger.info("Discovering VCT events from vlr.gg")
        events = []

        # Fetch VCT events page
        url = f"{BASE_URL}/events/?series_id={VCT_SERIES_ID}"
        soup = self._make_request(url)
        if not soup:
            logger.warning("Failed to fetch events page, using cache if available")
            if cache_key in self._cache:
                return self._cache[cache_key]
            return []

        # Find all event cards - they're in anchor tags with /event/ hrefs
        event_links = soup.find_all("a", href=EVENT_LINK_PATTERN)

        seen_ids: set[str] = set()
        for link in event_links:
            href = link.get("href", "")
            extracted = self._extract_event_id(href)
            if not extracted:
                continue

            event_id, slug = extracted

            # Skip duplicates
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            # Get event name - try to extract clean name from slug first
            name = self._slug_to_name(slug)
            if not name:
                # Fallback to parsing link text
                raw_name = link.get_text(strip=True)
                # Try to extract just the event name (before status/dates/etc)
                name_match = EVENT_NAME_PATTERN.match(raw_name)
                name = name_match.group(1).strip() if name_match else raw_name[:50]

            if not name or len(name) < 5:
                continue

            # Filter for VCT events only (not Challengers, Game Changers, etc.)
            if not self._is_vct_international(name):
                continue

            # Determine status from link text content
            # vlr.gg format: "Event Name|ongoing|Status|Prize|..."
            link_text = link.get_text(separator="|", strip=True).lower()
            if "|ongoing|" in link_text:
                status = "ongoing"
            elif "|completed|" in link_text:
                status = "completed"
            else:
                status = "upcoming"

            # Extract dates if available
            dates = ""
            date_elem = link.find(class_=re.compile(r"date"))
            if date_elem:
                dates = date_elem.get_text(strip=True)

            event = DiscoveredEvent(
                name=name,
                url=f"{BASE_URL}/event/matches/{event_id}/{slug}/",
                event_id=event_id,
                slug=slug,
                status=status,
                dates=dates,
                region=self._parse_region(name),
            )
            events.append(event)
            logger.debug(f"Discovered event: {name} ({event_id})")

        # Sort by event_id (roughly chronological)
        events.sort(key=lambda e: int(e.event_id))

        # Cache results (TTLCache handles expiration automatically)
        self._cache[cache_key] = events
        logger.info(f"Discovered {len(events)} VCT events")

        return events

    def _is_vct_international(self, name: str) -> bool:
        """Check if event is a VCT international event (not Challengers/GC)."""
        name_lower = name.lower()
        # Include VCT Kickoff, Stage, Masters, Champions
        if "vct" in name_lower or "champions" in name_lower or "masters" in name_lower:
            # Exclude Challengers and Game Changers
            return "challengers" not in name_lower and "game changers" not in name_lower
        return False

    def get_events_by_region(
        self, region: str, force_refresh: bool = False
    ) -> list[DiscoveredEvent]:
        """Get events filtered by region."""
        events = self.discover_events(force_refresh=force_refresh)

        # Normalize region input
        region_lower = region.lower()
        target_region = None

        for canonical, aliases in REGION_ALIASES.items():
            if region_lower in aliases:
                target_region = canonical
                break

        if not target_region:
            logger.warning(f"Unknown region: {region}")
            return []

        return [e for e in events if e.region == target_region]

    def get_event_by_id(
        self, event_id: str, force_refresh: bool = False
    ) -> DiscoveredEvent | None:
        """Get a specific event by ID."""
        events = self.discover_events(force_refresh=force_refresh)
        for event in events:
            if event.event_id == event_id:
                return event
        return None

    def list_regions(self) -> list[str]:
        """List available regions from discovered events."""
        events = self.discover_events()
        regions = sorted(set(e.region for e in events))
        return regions
