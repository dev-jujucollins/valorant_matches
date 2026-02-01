# Tests for the match_extractor module.
import time

import pytest
from bs4 import BeautifulSoup

from match_extractor import (
    CIRCUIT_BREAKER_RESET_TIME,
    CIRCUIT_BREAKER_THRESHOLD,
    COUNTDOWN_PATTERN,
    DATE_SELECTORS,
    EVENT_SLUG_PATTERN,
    LIVE_SELECTORS,
    MATCH_URL_PATTERN,
    MAX_BACKOFF_DELAY,
    SCORE_SELECTORS,
    TEAM_SELECTORS,
    CircuitBreakerMixin,
    CircuitBreakerOpen,
    Match,
    extract_date_time,
    extract_live_status,
    extract_match_data,
    extract_score,
    extract_teams,
    format_eta,
    is_upcoming_match,
)


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

        match = EVENT_SLUG_PATTERN.search("/event/matches/1234/test-event/")
        assert match
        assert match.group(1) == "test-event"

        assert not EVENT_SLUG_PATTERN.search("/other/path/")

    def test_countdown_pattern(self):
        """Test COUNTDOWN_PATTERN matches countdown strings."""
        assert COUNTDOWN_PATTERN.match("1h 30m")
        assert COUNTDOWN_PATTERN.match("2d 5h")
        assert COUNTDOWN_PATTERN.match("0h 42m")
        assert COUNTDOWN_PATTERN.match("5m remaining")
        assert not COUNTDOWN_PATTERN.match("Match has not started")
        assert not COUNTDOWN_PATTERN.match("2 : 1")

    def test_max_backoff_delay(self):
        """Test MAX_BACKOFF_DELAY is a reasonable value."""
        assert MAX_BACKOFF_DELAY == 30
        assert isinstance(MAX_BACKOFF_DELAY, int)

    def test_circuit_breaker_threshold(self):
        """Test CIRCUIT_BREAKER_THRESHOLD is a reasonable value."""
        assert CIRCUIT_BREAKER_THRESHOLD == 5
        assert isinstance(CIRCUIT_BREAKER_THRESHOLD, int)

    def test_circuit_breaker_reset_time(self):
        """Test CIRCUIT_BREAKER_RESET_TIME is a reasonable value."""
        assert CIRCUIT_BREAKER_RESET_TIME == 60
        assert isinstance(CIRCUIT_BREAKER_RESET_TIME, int)


class TestCSSSelectors:
    """Tests for CSS selector constants."""

    def test_team_selectors_defined(self):
        """Test TEAM_SELECTORS is properly defined."""
        assert len(TEAM_SELECTORS) >= 2
        for selector in TEAM_SELECTORS:
            assert len(selector) == 2  # (tag, class)
            assert isinstance(selector[0], str)
            assert isinstance(selector[1], str)

    def test_score_selectors_defined(self):
        """Test SCORE_SELECTORS is properly defined."""
        assert len(SCORE_SELECTORS) >= 2
        for selector in SCORE_SELECTORS:
            assert len(selector) == 2

    def test_live_selectors_defined(self):
        """Test LIVE_SELECTORS is properly defined."""
        assert len(LIVE_SELECTORS) >= 2
        for selector in LIVE_SELECTORS:
            assert len(selector) == 2

    def test_date_selectors_defined(self):
        """Test DATE_SELECTORS is properly defined."""
        assert len(DATE_SELECTORS) >= 1
        for selector in DATE_SELECTORS:
            assert len(selector) == 2


class TestMatchDataclass:
    """Tests for Match dataclass."""

    def test_match_creation(self):
        """Test Match dataclass can be created."""
        match = Match(
            date="Dec 23, 2025",
            time="3:00 PM",
            team1="Sentinels",
            team2="Cloud9",
            score="2 : 1",
            is_live=False,
            url="https://vlr.gg/match/12345",
        )
        assert match.date == "Dec 23, 2025"
        assert match.time == "3:00 PM"
        assert match.team1 == "Sentinels"
        assert match.team2 == "Cloud9"
        assert match.score == "2 : 1"
        assert match.is_live is False
        assert match.url == "https://vlr.gg/match/12345"
        assert match.is_upcoming is False  # default

    def test_match_with_upcoming(self):
        """Test Match with is_upcoming flag."""
        match = Match(
            date="Dec 25, 2025",
            time="2:00 PM",
            team1="Team A",
            team2="Team B",
            score="1h 30m",
            is_live=False,
            url="https://vlr.gg/match/12346",
            is_upcoming=True,
        )
        assert match.is_upcoming is True

    def test_match_with_live(self):
        """Test Match with live status."""
        match = Match(
            date="Dec 23, 2025",
            time="5:00 PM",
            team1="LOUD",
            team2="NRG",
            score="1 : 1",
            is_live=True,
            url="https://vlr.gg/match/12347",
        )
        assert match.is_live is True


class TestCircuitBreakerMixin:
    """Tests for CircuitBreakerMixin."""

    def _create_mixin_instance(self):
        """Create a test class that uses CircuitBreakerMixin."""

        class TestClient(CircuitBreakerMixin):
            def __init__(self):
                self._init_circuit_breaker()

        return TestClient()

    def test_init_circuit_breaker(self):
        """Test _init_circuit_breaker initializes state."""
        client = self._create_mixin_instance()
        assert client._failure_count == 0
        assert client._circuit_open_time is None

    def test_calculate_backoff(self):
        """Test _calculate_backoff returns exponential delays."""
        client = self._create_mixin_instance()

        delay0 = client._calculate_backoff(0)
        delay1 = client._calculate_backoff(1)
        delay2 = client._calculate_backoff(2)

        # Delays should increase
        assert delay1 > delay0
        assert delay2 > delay1

    def test_calculate_backoff_max_limit(self):
        """Test _calculate_backoff is capped at MAX_BACKOFF_DELAY."""
        client = self._create_mixin_instance()
        delay = client._calculate_backoff(100)
        assert delay <= MAX_BACKOFF_DELAY

    def test_check_circuit_breaker_when_closed(self):
        """Test _check_circuit_breaker passes when circuit is closed."""
        client = self._create_mixin_instance()
        # Should not raise
        client._check_circuit_breaker()

    def test_check_circuit_breaker_when_open(self):
        """Test _check_circuit_breaker raises when circuit is open."""
        client = self._create_mixin_instance()
        client._circuit_open_time = time.time()
        client._failure_count = CIRCUIT_BREAKER_THRESHOLD

        with pytest.raises(CircuitBreakerOpen):
            client._check_circuit_breaker()

    def test_check_circuit_breaker_resets_after_timeout(self):
        """Test _check_circuit_breaker resets after timeout."""
        client = self._create_mixin_instance()
        client._circuit_open_time = time.time() - CIRCUIT_BREAKER_RESET_TIME - 1
        client._failure_count = CIRCUIT_BREAKER_THRESHOLD

        # Should not raise - circuit should reset
        client._check_circuit_breaker()

        assert client._circuit_open_time is None
        assert client._failure_count == 0

    def test_record_success(self):
        """Test _record_success resets failure count."""
        client = self._create_mixin_instance()
        client._failure_count = 3

        client._record_success()

        assert client._failure_count == 0
        assert client._circuit_open_time is None

    def test_record_failure_increments_count(self):
        """Test _record_failure increments failure count."""
        client = self._create_mixin_instance()

        client._record_failure()
        assert client._failure_count == 1

        client._record_failure()
        assert client._failure_count == 2

    def test_record_failure_trips_breaker(self):
        """Test _record_failure trips circuit after threshold."""
        client = self._create_mixin_instance()

        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            client._record_failure()

        assert client._circuit_open_time is not None
        assert client._failure_count == CIRCUIT_BREAKER_THRESHOLD


class TestExtractionFunctions:
    """Tests for extraction functions."""

    @pytest.fixture
    def completed_match_html(self):
        """Sample HTML for a completed match."""
        return """
        <html>
        <body>
            <div class="wf-title-med">Sentinels</div>
            <div class="wf-title-med">Cloud9</div>
            <div class="js-spoiler">2 : 1</div>
            <div class="moment-tz-convert">December 23, 2025</div>
            <div>3:00 PM EST</div>
        </body>
        </html>
        """

    @pytest.fixture
    def live_match_html(self):
        """Sample HTML for a live match."""
        return """
        <html>
        <body>
            <div class="wf-title-med">LOUD</div>
            <div class="wf-title-med">NRG</div>
            <div class="js-spoiler">1 : 1</div>
            <span class="match-header-vs-note mod-live">LIVE</span>
            <div class="moment-tz-convert">December 23, 2025</div>
            <div>5:00 PM EST</div>
        </body>
        </html>
        """

    @pytest.fixture
    def upcoming_match_html(self):
        """Sample HTML for an upcoming match with countdown."""
        return """
        <html>
        <body>
            <div class="wf-title-med">100 Thieves</div>
            <div class="wf-title-med">Evil Geniuses</div>
            <span class="match-header-vs-note mod-upcoming">1h 30m</span>
            <div class="moment-tz-convert">December 25, 2025</div>
            <div>2:00 PM EST</div>
        </body>
        </html>
        """

    def test_extract_teams(self, completed_match_html):
        """Test extract_teams extracts team names."""
        soup = BeautifulSoup(completed_match_html, "html.parser")
        teams = extract_teams(soup)

        assert len(teams) == 2
        assert teams[0] == "Sentinels"
        assert teams[1] == "Cloud9"

    def test_extract_teams_with_fallback_selector(self):
        """Test extract_teams uses fallback selectors."""
        html = """
        <html>
        <body>
            <div class="match-header-link-name">Team Alpha</div>
            <div class="match-header-link-name">Team Beta</div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        teams = extract_teams(soup)

        assert teams[0] == "Team Alpha"
        assert teams[1] == "Team Beta"

    def test_extract_teams_returns_unknown_when_not_found(self):
        """Test extract_teams returns unknown teams when not found."""
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        teams = extract_teams(soup)

        assert teams == ["Unknown Team 1", "Unknown Team 2"]

    def test_extract_teams_strips_seed_info(self):
        """Test extract_teams strips seed info in parentheses."""
        html = """
        <html>
        <body>
            <div class="wf-title-med">Sentinels (1)</div>
            <div class="wf-title-med">Cloud9 (2)</div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        teams = extract_teams(soup)

        assert teams[0] == "Sentinels"
        assert teams[1] == "Cloud9"

    def test_extract_score(self, completed_match_html):
        """Test extract_score extracts match score."""
        soup = BeautifulSoup(completed_match_html, "html.parser")
        score = extract_score(soup)

        assert score == "2 : 1"

    def test_extract_score_with_countdown(self, upcoming_match_html):
        """Test extract_score extracts countdown for upcoming matches."""
        soup = BeautifulSoup(upcoming_match_html, "html.parser")
        score = extract_score(soup)

        assert score == "1h 30m"

    def test_extract_score_returns_default(self):
        """Test extract_score returns default when not found."""
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        score = extract_score(soup)

        assert score == "Match has not started yet."

    def test_extract_live_status_live(self, live_match_html):
        """Test extract_live_status detects live match."""
        soup = BeautifulSoup(live_match_html, "html.parser")
        is_live = extract_live_status(soup)

        assert is_live is True

    def test_extract_live_status_not_live(self, completed_match_html):
        """Test extract_live_status returns False for non-live match."""
        soup = BeautifulSoup(completed_match_html, "html.parser")
        is_live = extract_live_status(soup)

        assert is_live is False

    def test_extract_live_status_header_fallback(self):
        """Test extract_live_status uses header text fallback."""
        html = """
        <html>
        <body>
            <div class="match-header-vs">This match is LIVE now</div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        is_live = extract_live_status(soup)

        assert is_live is True

    def test_extract_date_time(self, completed_match_html):
        """Test extract_date_time extracts date and time."""
        soup = BeautifulSoup(completed_match_html, "html.parser")
        date, time_str = extract_date_time(soup)

        assert date == "December 23, 2025"
        assert time_str == "3:00 PM EST"

    def test_extract_date_time_returns_unknown(self):
        """Test extract_date_time returns unknown when not found."""
        soup = BeautifulSoup("<html><body></body></html>", "html.parser")
        date, time_str = extract_date_time(soup)

        assert date == "Unknown date"
        assert time_str == "Unknown time"

    def test_extract_match_data(self, completed_match_html):
        """Test extract_match_data extracts all data."""
        soup = BeautifulSoup(completed_match_html, "html.parser")
        teams, score, is_live = extract_match_data(soup)

        assert teams == ["Sentinels", "Cloud9"]
        assert score == "2 : 1"
        assert is_live is False


class TestFormatEta:
    """Tests for format_eta function."""

    def test_format_eta_with_countdown(self):
        """Test format_eta with countdown patterns."""
        assert format_eta("1h 30m") == "in 1h 30m"
        assert format_eta("2d 5h") == "in 2d 5h"
        assert format_eta("0h 42m") == "in 0h 42m"

    def test_format_eta_fallback(self):
        """Test format_eta returns UPCOMING for non-countdown."""
        assert format_eta("Match has not started yet.") == "UPCOMING"
        assert format_eta("") == "UPCOMING"
        assert format_eta("vs") == "UPCOMING"
        assert format_eta("2 : 1") == "UPCOMING"


class TestIsUpcomingMatch:
    """Tests for is_upcoming_match function."""

    def test_is_upcoming_with_countdown(self):
        """Test is_upcoming_match with countdown patterns."""
        assert is_upcoming_match("1h 30m") is True
        assert is_upcoming_match("2d 5h") is True
        assert is_upcoming_match("0h 42m") is True

    def test_is_upcoming_with_not_started_text(self):
        """Test is_upcoming_match with 'match has not started' text."""
        assert is_upcoming_match("Match has not started yet.") is True
        assert is_upcoming_match("match has not started") is True

    def test_is_upcoming_completed_match(self):
        """Test is_upcoming_match returns False for completed matches."""
        assert is_upcoming_match("2 : 1") is False
        assert is_upcoming_match("0 : 2") is False

    def test_is_upcoming_empty_string(self):
        """Test is_upcoming_match with empty string."""
        assert is_upcoming_match("") is False


class TestCircuitBreakerOpenException:
    """Tests for CircuitBreakerOpen exception."""

    def test_exception_message(self):
        """Test CircuitBreakerOpen exception has message."""
        exc = CircuitBreakerOpen("Test message")
        assert str(exc) == "Test message"

    def test_exception_can_be_raised(self):
        """Test CircuitBreakerOpen can be raised and caught."""
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            raise CircuitBreakerOpen("Circuit is open")
        assert "Circuit is open" in str(exc_info.value)
