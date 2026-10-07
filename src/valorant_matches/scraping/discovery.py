# Auto-discovery of VCT events from vlr.gg.

import json
import logging
import math
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from valorant_matches.config import APP_DIR, BASE_URL
from valorant_matches.scraping.http import fetch_page

logger = logging.getLogger("valorant_matches")

# Cache TTL for discovered events (24 hours)
EVENT_CACHE_TTL = 86400

# VLR's VCT tier covers current and older seasons without a yearly series ID.
VCT_EVENTS_URL = f"{BASE_URL}/events/?tier=60"

# Region mappings for CLI aliases
REGION_ALIASES: dict[str, list[str]] = {
    "americas": ["americas", "am"],
    "emea": ["emea", "eu"],
    "pacific": ["pacific", "apac"],
    "china": ["china", "cn"],
    "champions": ["champions"],
    "masters": ["masters"],
}


def canonical_region(name: str) -> str | None:
    """Map a region name or alias to its canonical region, if known."""
    name = name.lower()
    return next(
        (region for region, aliases in REGION_ALIASES.items() if name in aliases),
        None,
    )


# Pre-compiled regex patterns for performance
VCT_SLUG_PATTERN = re.compile(r"vct-(\d{4})-([^-]+)-(.+)")
TOUR_SLUG_PATTERN = re.compile(r"champions-tour-(\d{4})-([^-]+)-(.+)")
CHAMPIONS_SLUG_PATTERN = re.compile(r"valorant-(champions|masters)-(\d{4})")
MASTERS_CITY_PATTERN = re.compile(r"valorant-masters-([^-]+)-(\d{4})")
EVENT_ID_PATTERN = re.compile(r"/event/(\d+)/([^/]+)")
EVENT_LINK_PATTERN = re.compile(r"^/event/\d+/")
EVENT_NAME_PATTERN = re.compile(
    r"((?:VCT \d{4}:|Champions Tour \d{4}:|Valorant (?:Champions|Masters))[^$\d]+)"
)
OFFICIAL_VCT_NAME_PATTERN = re.compile(
    r"^(?:VCT \d{4}:|Champions Tour \d{4}:|Valorant (?:Champions|Masters)(?:\s+[A-Za-z]+)?\s+\d{4}\b)",
    re.IGNORECASE,
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

    def __init__(self, season: int | None = None, snapshot_dir: Path = APP_DIR) -> None:
        self.season = season or datetime.now().year
        self.snapshot_path = snapshot_dir / f"events-{self.season}.json"
        self.is_stale = False
        self.last_updated: float | None = None
        # In-process copy of the last successful discovery and when it ran.
        self._events: list[DiscoveredEvent] | None = None
        self._events_fetched_at = 0.0

    def _load_snapshot(self) -> list[DiscoveredEvent]:
        """Load last successful discovery for this season."""
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("season") != self.season:
                return []
            timestamp = payload["updated_at"]
            raw_events = payload["events"]
            if (
                not isinstance(timestamp, (int, float))
                or isinstance(timestamp, bool)
                or not math.isfinite(timestamp)
                or not isinstance(raw_events, list)
            ):
                return []
            events = [DiscoveredEvent(**event) for event in raw_events]
            if not all(
                isinstance(event.name, str)
                and isinstance(event.event_id, str)
                and event.event_id.isdigit()
                and isinstance(event.url, str)
                and event.url.startswith(f"{BASE_URL}/event/matches/")
                and isinstance(event.slug, str)
                and isinstance(event.status, str)
                and isinstance(event.dates, str)
                and isinstance(event.region, str)
                and re.search(rf"\b{self.season}\b", event.name)
                for event in events
            ):
                return []
            self.last_updated = timestamp
            return events
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def _save_snapshot(self, events: list[DiscoveredEvent]) -> None:
        """Persist successful discovery atomically."""
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.snapshot_path.parent,
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(
                    {
                        "season": self.season,
                        "updated_at": time.time(),
                        "events": [asdict(event) for event in events],
                    },
                    handle,
                )
            temp_path.replace(self.snapshot_path)
        except OSError as error:
            logger.warning("Could not save event snapshot: %s", error)
            if "temp_path" in locals():
                temp_path.unlink(missing_ok=True)

    def _fetch(self, url: str) -> BeautifulSoup | None:
        """Fetch a page with the shared retry and circuit-breaker policy."""
        return fetch_page(url)

    def _fresh_events(self) -> list[DiscoveredEvent] | None:
        """Return the in-process event list while it is younger than the TTL."""
        if self._events is None:
            return None
        if time.monotonic() - self._events_fetched_at > EVENT_CACHE_TTL:
            return None
        return self._events

    def can_reach_vlr(self) -> bool:
        """Check if vlr.gg is reachable using normal discovery request settings."""
        return self._fetch(BASE_URL) is not None

    def _slug_to_name(self, slug: str) -> str | None:
        """Convert event slug to human-readable name."""
        # Pattern: vct-2026-americas-kickoff -> VCT 2026: Americas Kickoff
        vct_match = VCT_SLUG_PATTERN.match(slug)
        if vct_match:
            year, region, stage = vct_match.groups()
            region = region.capitalize()
            stage = stage.replace("-", " ").title()
            return f"VCT {year}: {region} {stage}"

        tour_match = TOUR_SLUG_PATTERN.match(slug)
        if tour_match:
            year, region, stage = tour_match.groups()
            return f"Champions Tour {year}: {region.capitalize()} {stage.replace('-', ' ').title()}"

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
        elif re.search(r"\bvalorant champions \d{4}\b", name_lower):
            return "champions"
        elif re.search(
            r"\b(?:valorant masters|champions tour \d{4}: masters)\b", name_lower
        ):
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
        cached = None if force_refresh else self._fresh_events()
        if cached is not None:
            logger.debug("Using cached event list")
            return cached

        logger.info("Discovering VCT events from vlr.gg")
        events = []

        # Fetch VCT events page
        soup = self._fetch(VCT_EVENTS_URL)
        if not soup:
            logger.warning("Failed to fetch events page, using saved discovery")
            if self._events is not None:
                self.is_stale = True
                return self._events
            saved = self._load_snapshot()
            self.is_stale = bool(saved)
            return saved

        # Find all event cards - they're in anchor tags with /event/ hrefs
        event_links = soup.find_all("a", href=EVENT_LINK_PATTERN)
        if self.season < datetime.now().year:
            # VLR paginates older seasons. Stop once cards from an earlier
            # season appear, or when pages stop adding new events.
            seen_hrefs = {str(link.get("href")) for link in event_links}
            for page in range(2, 8):
                years = [
                    int(year)
                    for href in seen_hrefs
                    for year in re.findall(r"(?<!\d)20\d{2}(?!\d)", href)
                ]
                if any(year < self.season for year in years):
                    break
                older_page = self._fetch(f"{VCT_EVENTS_URL}&page={page}")
                if not older_page:
                    break
                more_links = older_page.find_all("a", href=EVENT_LINK_PATTERN)
                fresh_links = [
                    link
                    for link in more_links
                    if str(link.get("href")) not in seen_hrefs
                ]
                if not fresh_links:
                    break
                event_links.extend(fresh_links)
                seen_hrefs.update(str(link.get("href")) for link in fresh_links)

        seen_ids: set[str] = set()
        for link in event_links:
            href = link.get("href", "")
            if not isinstance(href, str):
                continue
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
            if not re.search(rf"\b{self.season}\b", name):
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

        if not events:
            saved = self._load_snapshot()
            self.is_stale = bool(saved)
            return saved
        self._events = events
        self._events_fetched_at = time.monotonic()
        self.is_stale = False
        self.last_updated = time.time()
        self._save_snapshot(events)
        logger.info(f"Discovered {len(events)} VCT events")

        return events

    def _is_vct_international(self, name: str) -> bool:
        """Check if event is a VCT international event (not Challengers/GC)."""
        name_lower = name.lower()
        if "challengers" in name_lower or "game changers" in name_lower:
            return False
        return bool(OFFICIAL_VCT_NAME_PATTERN.match(name))

    def get_events_by_region(
        self, region: str, force_refresh: bool = False
    ) -> list[DiscoveredEvent]:
        """Get events for a region name or alias."""
        target_region = canonical_region(region)
        if not target_region:
            logger.warning(f"Unknown region: {region}")
            return []

        events = self.discover_events(force_refresh=force_refresh)
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
