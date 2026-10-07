# Tests for match models and extraction.
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from valorant_matches.scraping.matches import (
    COUNTDOWN_PATTERN,
    EVENT_SLUG_PATTERN,
    MATCH_URL_PATTERN,
    UNKNOWN_TEAMS,
    Match,
    build_match_from_soup,
    extract_countdown,
    extract_date_time,
    extract_live_status,
    extract_score,
    extract_teams,
    find_event_match_urls,
    is_placeholder_score,
    should_use_cached_match,
)


def soup_of(html: str) -> BeautifulSoup:
    """Parse an HTML snippet."""
    return BeautifulSoup(html, "html.parser")


class TestConstants:
    """Tests for regex patterns and constants."""

    def test_match_url_pattern(self):
        """Test MATCH_URL_PATTERN matches correct URLs."""
        assert MATCH_URL_PATTERN.match("/12345/")
        assert MATCH_URL_PATTERN.match("/1/")
        assert MATCH_URL_PATTERN.match("/594001/team-a-vs-team-b")
        assert not MATCH_URL_PATTERN.match("/event/123")
        assert not MATCH_URL_PATTERN.match("12345/")
        assert not MATCH_URL_PATTERN.match("/abc/")

    def test_event_slug_pattern(self):
        """Test EVENT_SLUG_PATTERN extracts slugs correctly."""
        match = EVENT_SLUG_PATTERN.search(
            "/event/matches/2682/vct-2026-americas-kickoff/"
        )
        assert match
        assert match.group(1) == "vct-2026-americas-kickoff"
        assert not EVENT_SLUG_PATTERN.search("/other/path/")

    def test_countdown_pattern(self):
        """Test COUNTDOWN_PATTERN matches countdown strings."""
        assert COUNTDOWN_PATTERN.match("1h 30m")
        assert COUNTDOWN_PATTERN.match("2d 5h")
        assert COUNTDOWN_PATTERN.match("5m remaining")
        assert not COUNTDOWN_PATTERN.match("Match has not started")
        assert not COUNTDOWN_PATTERN.match("2 : 1")


class TestMatchModel:
    """Tests for Match serialization and display helpers."""

    def _match(self, **overrides) -> Match:
        values = {
            "url": "https://vlr.gg/1",
            "team1": "Sentinels",
            "team2": "Cloud9",
            "status": "completed",
            "score": "2 : 1",
            "starts_at": datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
            "date_label": "January 2, 2026",
            "time_label": "1:00 AM",
        }
        values.update(overrides)
        return Match(**values)

    def test_round_trip(self) -> None:
        """to_dict output rebuilds an equal match."""
        match = self._match(countdown=None)
        assert Match.from_dict(match.to_dict()) == match

    def test_round_trip_without_start(self) -> None:
        """Matches without a known start survive serialization."""
        match = self._match(starts_at=None)
        assert Match.from_dict(match.to_dict()) == match

    @pytest.mark.parametrize(
        "change",
        [
            {"status": "finished"},
            {"starts_at": "2026-01-02T01:00:00"},
            {"starts_at": "not a date"},
            {"starts_at": 123},
            {"team1": None},
            {"unexpected": True},
        ],
    )
    def test_from_dict_rejects_invalid_data(self, change: dict) -> None:
        """Damaged records raise instead of producing a bad match."""
        data = self._match().to_dict() | change
        with pytest.raises((TypeError, ValueError)):
            Match.from_dict(data)

    def test_from_dict_rejects_missing_fields(self) -> None:
        """Records from the old schema are rejected."""
        with pytest.raises(TypeError):
            Match.from_dict({"team1": "A"})

    def test_local_date_time_converts_known_start(self) -> None:
        """A known start renders in the requested timezone."""
        date, time = self._match().local_date_time(ZoneInfo("America/Los_Angeles"))
        assert date == "January 01, 2026"
        assert time == "05:00 PM PST"

    def test_local_date_time_falls_back_to_labels(self) -> None:
        """Without a start, the source labels are shown unchanged."""
        match = self._match(starts_at=None)
        assert match.local_date_time(ZoneInfo("UTC")) == ("January 2, 2026", "1:00 AM")

    def test_should_use_cached_match(self) -> None:
        """Only completed matches with real scores are served from cache."""
        assert should_use_cached_match(self._match())
        assert not should_use_cached_match(self._match(status="live"))
        assert not should_use_cached_match(self._match(score=None))
        assert not should_use_cached_match(self._match(score="TBD –"))


class TestExtractionFunctions:
    """Tests for extraction functions."""

    @pytest.fixture
    def completed_soup(self) -> BeautifulSoup:
        """Sample HTML for a completed match."""
        return soup_of(
            """
            <div class="wf-title-med">Sentinels</div>
            <div class="wf-title-med">Cloud9</div>
            <div class="js-spoiler">2 : 1</div>
            <div class="moment-tz-convert">December 23, 2025</div>
            <div>3:00 PM EST</div>
            """
        )

    @pytest.fixture
    def live_soup(self) -> BeautifulSoup:
        """Sample HTML for a live match."""
        return soup_of(
            """
            <div class="wf-title-med">LOUD</div>
            <div class="wf-title-med">NRG</div>
            <div class="js-spoiler">1 : 1</div>
            <span class="match-header-vs-note mod-live">LIVE</span>
            """
        )

    @pytest.fixture
    def upcoming_soup(self) -> BeautifulSoup:
        """Sample HTML for an upcoming match with a countdown."""
        return soup_of(
            """
            <div class="wf-title-med">100 Thieves</div>
            <div class="wf-title-med">Evil Geniuses</div>
            <div class="match-header-vs-score">
              <span class="match-header-vs-note mod-upcoming">1h  30m</span>
            </div>
            """
        )

    def test_extract_teams(self, completed_soup):
        """Test extract_teams extracts team names."""
        assert extract_teams(completed_soup) == ["Sentinels", "Cloud9"]

    def test_extract_teams_with_fallback_selector(self):
        """Test extract_teams uses fallback selectors."""
        soup = soup_of(
            '<div class="match-header-link-name">Team Alpha</div>'
            '<div class="match-header-link-name">Team Beta</div>'
        )
        assert extract_teams(soup) == ["Team Alpha", "Team Beta"]

    def test_extract_teams_returns_unknown_when_not_found(self):
        """Test extract_teams returns unknown teams when not found."""
        assert extract_teams(soup_of("<html></html>")) == UNKNOWN_TEAMS

    def test_extract_teams_strips_seed_info(self):
        """Test extract_teams strips seed info in parentheses."""
        soup = soup_of(
            '<div class="wf-title-med">Sentinels (1)</div>'
            '<div class="wf-title-med">Cloud9 (2)</div>'
        )
        assert extract_teams(soup) == ["Sentinels", "Cloud9"]

    def test_extract_score(self, completed_soup):
        """Test extract_score extracts match score."""
        assert extract_score(completed_soup) == "2 : 1"

    def test_extract_score_strips_notes(self):
        """Test extract_score removes the final/vs./Bo3 notes VLR appends."""
        soup = soup_of('<div class="js-spoiler">final 2 : 1 vs. Bo3</div>')
        assert extract_score(soup) == "2 : 1"

    def test_extract_score_ignores_countdown(self, upcoming_soup):
        """A countdown inside the score element is not a score."""
        assert extract_score(upcoming_soup) is None

    @pytest.mark.parametrize("text", ["TBD –", "–", "-", ""])
    def test_extract_score_ignores_placeholders(self, text: str):
        """Placeholder text before a match starts yields no score."""
        soup = soup_of(f'<div class="match-header-vs-score">{text}</div>')
        assert extract_score(soup) is None

    def test_extract_score_returns_none_when_missing(self):
        """Test extract_score returns None when no element matches."""
        assert extract_score(soup_of("<html></html>")) is None

    def test_extract_countdown(self, upcoming_soup, completed_soup):
        """Countdown text is normalized; absent countdowns are None."""
        assert extract_countdown(upcoming_soup) == "1h 30m"
        assert extract_countdown(completed_soup) is None

    def test_extract_live_status_live(self, live_soup):
        """Test extract_live_status detects live match."""
        assert extract_live_status(live_soup) is True

    def test_extract_live_status_not_live(self, completed_soup):
        """Test extract_live_status returns False for non-live match."""
        assert extract_live_status(completed_soup) is False

    def test_extract_live_status_header_fallback(self):
        """Test extract_live_status uses header text fallback."""
        soup = soup_of('<div class="match-header-vs">This match is LIVE now</div>')
        assert extract_live_status(soup) is True

    def test_extract_date_time(self, completed_soup):
        """Test extract_date_time extracts date and time."""
        assert extract_date_time(completed_soup) == ("December 23, 2025", "3:00 PM EST")

    def test_extract_date_time_returns_unknown(self):
        """Test extract_date_time returns unknown when not found."""
        assert extract_date_time(soup_of("<html></html>")) == (
            "Unknown date",
            "Unknown time",
        )


class TestBuildMatch:
    """Tests for turning a page into a Match with a status."""

    @pytest.mark.parametrize(
        ("html", "status", "score", "countdown"),
        [
            (
                '<div class="js-spoiler">2 : 1</div>',
                "completed",
                "2 : 1",
                None,
            ),
            (
                '<div class="js-spoiler">1 : 1</div>'
                '<span class="match-header-vs-note mod-live">LIVE</span>',
                "live",
                "1 : 1",
                None,
            ),
            (
                '<span class="match-header-vs-note mod-upcoming">1d 5h</span>',
                "upcoming",
                None,
                "1d 5h",
            ),
            ("", "upcoming", None, None),
        ],
    )
    def test_status_from_page(
        self, html: str, status: str, score: str | None, countdown: str | None
    ) -> None:
        """Live wins, a missing score or a countdown means upcoming."""
        teams = '<div class="wf-title-med">A</div><div class="wf-title-med">B</div>'
        result = build_match_from_soup(soup_of(teams + html), "https://vlr.gg/1")
        assert result.match is not None
        assert result.match.status == status
        assert result.match.score == score
        assert result.match.countdown == countdown

    def test_tbd_teams(self) -> None:
        """Undecided teams are reported as TBD, not as a match."""
        soup = soup_of(
            '<div class="wf-title-med">TBD</div><div class="wf-title-med">B</div>'
        )
        result = build_match_from_soup(soup, "https://vlr.gg/1")
        assert result.is_tbd and result.match is None

    def test_missing_teams_is_parse_error(self) -> None:
        """Pages without team names produce a parse error."""
        result = build_match_from_soup(soup_of("<html></html>"), "https://vlr.gg/1")
        assert result.error is not None
        assert result.error.error_type == "parse"


class TestIsPlaceholderScore:
    """Tests for is_placeholder_score."""

    @pytest.mark.parametrize("text", ["", "TBD", "tbd –", "—", "1h 30m", "2d 5h"])
    def test_placeholders(self, text: str) -> None:
        """Dashes, TBD, and countdowns are not scores."""
        assert is_placeholder_score(text) is True

    @pytest.mark.parametrize("text", ["2 : 1", "0 : 2", "13-11"])
    def test_scores(self, text: str) -> None:
        """Real scores are not placeholders."""
        assert is_placeholder_score(text) is False


class TestFindEventMatchUrls:
    """Tests for find_event_match_urls."""

    def test_returns_unique_absolute_urls_in_order(self) -> None:
        """Duplicate links collapse and relative links become absolute."""
        soup = soup_of(
            '<a href="/2/b">b</a><a href="/1/a">a</a><a href="/2/b">again</a>'
            '<a href="/event/9">event</a>'
        )
        assert find_event_match_urls(soup) == [
            "https://vlr.gg/2/b",
            "https://vlr.gg/1/a",
        ]
