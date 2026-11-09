# Match models and HTML extraction for vlr.gg match pages.

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any, Literal, get_args
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from valorant_matches.config import BASE_URL

logger = logging.getLogger("valorant_matches")

# Pre-compiled regex patterns for performance
MATCH_URL_PATTERN = re.compile(r"^/\d+/")
EVENT_SLUG_PATTERN = re.compile(r"/event/matches/\d+/([^/]+)")
COUNTDOWN_PATTERN = re.compile(r"^\d+[dhm]\s")
# Notes VLR appends inside the score element on completed matches, e.g.
# "final", "vs."/"vs", and the best-of designation "Bo3"/"Bo5".
SCORE_NOTE_PATTERN = re.compile(r"\b(?:Bo\d+|final|vs)\b\.?", re.IGNORECASE)
# Score-element text VLR shows before a match has a real score.
PLACEHOLDER_SCORES = {"tbd", "tbd –", "tbd —", "tbd -", "–", "—", "-"}

UNKNOWN_TEAMS = ["Unknown Team 1", "Unknown Team 2"]
UNKNOWN_DATE = "Unknown date"
UNKNOWN_TIME = "Unknown time"

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

MatchStatus = Literal["live", "upcoming", "completed"]
MATCH_STATUSES: tuple[MatchStatus, ...] = get_args(MatchStatus)

# VLR's "data-utc-ts" attribute holds US Eastern wall time, not UTC: a match
# the site renders as "2:00 AM PDT" carries "05:00:00" there.
SOURCE_TIMEZONE = ZoneInfo("America/New_York")

# Status badge classes on an event listing row.
LISTING_STATUS_CLASSES: dict[str, MatchStatus] = {
    "mod-live": "live",
    "mod-upcoming": "upcoming",
    "mod-completed": "completed",
}


def _parse_aware_datetime(raw: str) -> datetime:
    """Parse an ISO timestamp that must carry a timezone.

    Raises:
        ValueError: When the value is not ISO 8601 or has no timezone.
    """
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {raw}")
    return value


@dataclass(frozen=True)
class Match:
    """A Valorant match as shown on its vlr.gg page.

    Attributes:
        url: Absolute match page URL; identifies the match.
        team1: First team name.
        team2: Second team name.
        status: Whether the match is live, upcoming, or completed.
        score: Map score such as "2 : 1", or None before the match has one.
        countdown: Time until start such as "1d 5h", when VLR shows one.
        starts_at: Scheduled start as an aware datetime, when known.
        date_label: Source date text, shown when starts_at is unknown.
        time_label: Source time text, shown when starts_at is unknown.
    """

    url: str
    team1: str
    team2: str
    status: MatchStatus
    score: str | None = None
    countdown: str | None = None
    starts_at: datetime | None = None
    date_label: str = UNKNOWN_DATE
    time_label: str = UNKNOWN_TIME

    def local_date_time(self, zone: tzinfo | None = None) -> tuple[str, str]:
        """Return display date and time for a timezone.

        Args:
            zone: Target timezone; None means the system local timezone.

        Returns:
            Converted date and time when the start is known, else source labels.
        """
        if self.starts_at is None:
            return self.date_label, self.time_label
        local = self.starts_at.astimezone(zone)
        return local.strftime("%B %d, %Y"), local.strftime("%I:%M %p %Z")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible values.

        Returns:
            A dictionary accepted by from_dict.
        """
        data = asdict(self)
        data["starts_at"] = self.starts_at.isoformat() if self.starts_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Match":
        """Rebuild a match from to_dict output.

        Args:
            data: Serialized match values.

        Returns:
            The validated match.

        Raises:
            TypeError: When fields are missing, unknown, or the wrong type.
            ValueError: When the status or timestamp is invalid.
        """
        values = dict(data)
        raw_start = values.get("starts_at")
        if raw_start is not None and not isinstance(raw_start, str):
            raise TypeError("starts_at must be a string or null")
        values["starts_at"] = _parse_aware_datetime(raw_start) if raw_start else None
        match = cls(**values)
        if match.status not in MATCH_STATUSES:
            raise ValueError(f"unknown match status: {match.status!r}")
        text_fields = (match.url, match.team1, match.team2)
        labels = (match.date_label, match.time_label)
        if not all(isinstance(value, str) for value in (*text_fields, *labels)):
            raise TypeError("match text fields must be strings")
        return match


@dataclass(frozen=True)
class ListingRow:
    """One match as listed on an event's matches page.

    The listing shows teams, score, and status for every match, so most runs
    never need the match page. It has no real timestamp (its clock text is
    rendered in the viewer's timezone), so start times still come from match
    pages; ``schedule`` only detects when a match has been rescheduled.

    Attributes:
        url: Absolute match page URL.
        team1: First team name, when the row could be read.
        team2: Second team name, when the row could be read.
        status: Listed status, when the row could be read.
        score: Map score such as "2 : 1", or None when none is listed.
        countdown: Time until start such as "1d 5h", for upcoming matches.
        schedule: Listed date and clock text, compared between runs.
    """

    url: str
    team1: str | None = None
    team2: str | None = None
    status: MatchStatus | None = None
    score: str | None = None
    countdown: str | None = None
    schedule: str = ""

    @property
    def has_details(self) -> bool:
        """Whether teams and status were read; otherwise only the URL is known."""
        return bool(self.team1 and self.team2 and self.status)

    @property
    def is_tbd(self) -> bool:
        """Whether a team is still undecided."""
        return "TBD" in (self.team1, self.team2)


@dataclass
class FetchError:
    """A fetch or parsing failure with source context."""

    url: str
    error_type: str
    message: str


@dataclass
class ProcessMatchResult:
    """Result metadata for one processed match."""

    match: Match | None = None
    is_tbd: bool = False
    cache_hit: bool = False
    skipped: bool = False
    error: FetchError | None = None


@dataclass
class ProcessedMatches:
    """Batch result metadata for processed matches."""

    results: list[Match]
    tbd_count: int = 0
    cache_hits: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    errors: list[FetchError] = field(default_factory=list)


def extract_teams(soup: BeautifulSoup) -> list[str]:
    """Extract team names with fallback selectors.

    Args:
        soup: Parsed match page.

    Returns:
        Two team names, or UNKNOWN_TEAMS when no selector matches.
    """
    for tag, class_name in TEAM_SELECTORS:
        elements = soup.find_all(tag, class_=class_name)
        if len(elements) >= 2:
            teams = [el.text.strip().split("(")[0].strip() for el in elements[:2]]
            if all(teams):
                return teams

    logger.warning("Could not extract team names with any selector")
    return list(UNKNOWN_TEAMS)


def extract_countdown(soup: BeautifulSoup) -> str | None:
    """Extract the time-until-start note, such as "1d 5h".

    Args:
        soup: Parsed match page.

    Returns:
        The normalized countdown text, or None when absent.
    """
    element = soup.find("span", class_="match-header-vs-note mod-upcoming")
    text = " ".join(element.get_text().split()) if element else ""
    return text or None


def is_placeholder_score(text: str) -> bool:
    """Return True when score text is a pre-match placeholder, not a score.

    Args:
        text: Raw or normalized score-element text.
    """
    normalized = " ".join(text.lower().split())
    return (
        not normalized
        or normalized in PLACEHOLDER_SCORES
        or bool(COUNTDOWN_PATTERN.match(normalized))
    )


def extract_score(soup: BeautifulSoup) -> str | None:
    """Extract the map score with fallback selectors.

    Args:
        soup: Parsed match page.

    Returns:
        The score such as "2 : 1", or None when the match has no score yet.
    """
    # Unscheduled Champions matches have a dash placeholder, not a score.
    if soup.select_one(".match-header-vs-placeholder") and not extract_live_status(
        soup
    ):
        return None

    for tag, class_name in SCORE_SELECTORS:
        score_elem = soup.find(tag, class_=class_name)
        if not score_elem:
            continue
        # Strip the notes (e.g. "final", "vs.", "Bo3") VLR appends inside the
        # score element, so they don't render between the score and team2.
        score = " ".join(SCORE_NOTE_PATTERN.sub("", score_elem.text).split())
        if score and not is_placeholder_score(score):
            return score
    return None


def extract_live_status(soup: BeautifulSoup) -> bool:
    """Extract live status with fallback selectors.

    Args:
        soup: Parsed match page.
    """
    for tag, class_name in LIVE_SELECTORS:
        if soup.find(tag, class_=class_name):
            return True

    header = soup.find("div", class_="match-header-vs")
    return bool(header and "live" in header.text.lower())


def extract_date_time(soup: BeautifulSoup) -> tuple[str, str]:
    """Extract source date and time labels with fallback selectors.

    Args:
        soup: Parsed match page.

    Returns:
        Date and time text, or UNKNOWN_DATE and UNKNOWN_TIME.
    """
    header = soup.select_one(".match-header-date")
    if header and "time tbd" in header.get_text(" ", strip=True).lower():
        date_elem = header.select_one(".moment-tz-convert")
        date = date_elem.get_text(" ", strip=True) if date_elem else UNKNOWN_DATE
        tentative = "tentative" in header.get_text(" ", strip=True).lower()
        return date, "Time TBD (date tentative)" if tentative else "Time TBD"
    for tag, class_name in DATE_SELECTORS:
        date_elem = soup.find(tag, class_=class_name)
        if date_elem:
            match_date = date_elem.text.strip()
            time_elem = date_elem.find_next("div", class_="moment-tz-convert")
            if not time_elem:
                time_elem = date_elem.find_next("div")
            match_time = time_elem.text.strip() if time_elem else UNKNOWN_TIME
            if match_date and match_date != UNKNOWN_DATE:
                return match_date, match_time

    logger.debug("Could not extract date/time with any selector")
    return UNKNOWN_DATE, UNKNOWN_TIME


def extract_start_time(soup: BeautifulSoup) -> datetime | None:
    """Read VLR date strings or Unix timestamps as aware UTC datetimes.

    Date strings without an offset are US Eastern wall time (see
    SOURCE_TIMEZONE); Unix timestamps are UTC by definition.

    Args:
        soup: Parsed match page.

    Returns:
        The scheduled start in UTC, or None when unknown or only tentative.
    """
    header = soup.select_one(".match-header-date")
    if header and "time tbd" in header.get_text(" ", strip=True).lower():
        return None  # The source attribute is a placeholder, not a scheduled instant.
    for element in soup.select(".moment-tz-convert[data-utc-ts]"):
        raw = str(element.get("data-utc-ts"))
        try:
            try:
                value = datetime.fromisoformat(raw)
            except ValueError:
                return datetime.fromtimestamp(float(raw), UTC)
            if value.tzinfo is None:
                value = value.replace(tzinfo=SOURCE_TIMEZONE)
            return value.astimezone(UTC)
        except (ValueError, OverflowError, OSError):
            continue
    return None


def build_match_from_soup(soup: BeautifulSoup, match_url: str) -> ProcessMatchResult:
    """Build a Match from a parsed match page.

    Args:
        soup: Parsed match page.
        match_url: Absolute URL of the page.

    Returns:
        The match, a TBD marker when teams are undecided, or a parse error.
    """
    teams = extract_teams(soup)
    if "TBD" in teams:
        return ProcessMatchResult(is_tbd=True)
    if teams == UNKNOWN_TEAMS:
        return ProcessMatchResult(
            error=FetchError(match_url, "parse", "Match page is missing team names")
        )

    is_live = extract_live_status(soup)
    score = extract_score(soup)
    countdown = None if is_live else extract_countdown(soup)
    status: MatchStatus
    if is_live:
        status = "live"
    elif score is None or countdown:
        status = "upcoming"
    else:
        status = "completed"

    date_label, time_label = extract_date_time(soup)
    return ProcessMatchResult(
        match=Match(
            url=match_url,
            team1=teams[0],
            team2=teams[1],
            status=status,
            score=score,
            countdown=countdown,
            starts_at=extract_start_time(soup),
            date_label=date_label,
            time_label=time_label,
        )
    )


def should_use_cached_match(match: Match) -> bool:
    """Return True when cached match data is safe to display.

    Used when the event listing gave no details to refresh the cached copy
    with: only a finished match with a real score can be trusted as is.

    Args:
        match: A match rebuilt from the cache.
    """
    return (
        match.status == "completed"
        and match.score is not None
        and not is_placeholder_score(match.score)
    )


def extract_event_slug(event_url: str) -> str | None:
    """Extract the event slug from a VLR event matches URL.

    Args:
        event_url: URL such as https://vlr.gg/event/matches/1/vct-2026-kickoff/.
    """
    slug_match = EVENT_SLUG_PATTERN.search(event_url)
    if slug_match:
        return slug_match.group(1)
    return None


def _clean(text: str) -> str:
    """Collapse runs of whitespace."""
    return " ".join(text.split())


def _listing_status(link: Tag) -> MatchStatus | None:
    """Read a listing row's status from its badge class, then its label."""
    badge = link.select_one(".ml")
    if badge is None:
        return None
    classes = badge.get("class") or []
    for class_name, status in LISTING_STATUS_CLASSES.items():
        if class_name in classes:
            return status
    label = badge.select_one(".ml-status")
    text = _clean(label.get_text()).lower() if label else ""
    return next((status for status in MATCH_STATUSES if status == text), None)


def _listing_schedule(link: Tag) -> str:
    """Join a row's date heading and clock text, e.g. "Thu, May 1 | 2:00 PM"."""
    heading = link.find_previous("div", class_="wf-label")
    # Direct text only: VLR nests a "Today" tag in the heading, which would
    # otherwise make the value change from one day to the next.
    date = (
        _clean(
            "".join(
                str(text) for text in heading.find_all(string=True, recursive=False)
            )
        )
        if isinstance(heading, Tag)
        else ""
    )
    clock = link.select_one(".match-item-time")
    return f"{date} | {_clean(clock.get_text()) if clock else ''}"


def _listing_row(link: Tag, url: str) -> ListingRow:
    """Read one listing link; a row that cannot be read keeps only its URL."""
    names = [
        _clean(element.get_text(" "))
        for element in link.select(".match-item-vs-team-name")
    ]
    status = _listing_status(link)
    if len(names) != 2 or not all(names) or status is None:
        return ListingRow(url=url)

    scores = [
        _clean(element.get_text())
        for element in link.select(".match-item-vs-team-score")
    ]
    has_score = (
        status != "upcoming"
        and len(scores) == 2
        and all(score.isdigit() for score in scores)
    )
    eta = link.select_one(".ml-eta")
    countdown = _clean(eta.get_text()) if eta and status == "upcoming" else ""
    return ListingRow(
        url=url,
        team1=names[0],
        team2=names[1],
        status=status,
        score=f"{scores[0]} : {scores[1]}" if has_score else None,
        countdown=countdown or None,
        schedule=_listing_schedule(link),
    )


def parse_event_listing(
    soup: BeautifulSoup,
    slug_pattern: re.Pattern[str] | None = None,
) -> list[ListingRow]:
    """Read the match rows on an event's matches page, in page order.

    Args:
        soup: Parsed event matches page.
        slug_pattern: Optional pattern a link must contain to belong to the event.

    Returns:
        One row per unique match link. Links whose markup is not a readable
        match row are kept with only their URL, so callers can still fetch them.
    """
    rows: dict[str, ListingRow] = {}
    for link in soup.select("a[href]"):
        href = link.get("href")
        if not isinstance(href, str) or not MATCH_URL_PATTERN.match(href):
            continue
        if slug_pattern and not slug_pattern.search(href.lower()):
            continue
        url = urljoin(BASE_URL, href)
        if url not in rows:
            rows[url] = _listing_row(link, url)
    return list(rows.values())


def find_event_match_urls(
    soup: BeautifulSoup,
    slug_pattern: re.Pattern[str] | None = None,
) -> list[str]:
    """Find absolute match URLs on an event page, in page order.

    Args:
        soup: Parsed event matches page.
        slug_pattern: Optional pattern a link must contain to belong to the event.

    Returns:
        Unique absolute match URLs.
    """
    return [row.url for row in parse_event_listing(soup, slug_pattern)]
