# Tests for the valorant_client module.
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_client import Match, ValorantClient


@pytest.fixture
def client():
    """Create a ValorantClient instance for testing."""
    with patch("valorant_client.MatchCache"):
        return ValorantClient()


@pytest.fixture
def sample_match_html():
    """Sample HTML for a completed match page."""
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
def sample_live_match_html():
    """Sample HTML for a live match page."""
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
def sample_upcoming_match_html():
    """Sample HTML for an upcoming match page."""
    return """
    <html>
    <body>
        <div class="wf-title-med">100 Thieves</div>
        <div class="wf-title-med">Evil Geniuses</div>
        <div class="moment-tz-convert">December 25, 2025</div>
        <div>2:00 PM EST</div>
    </body>
    </html>
    """


@pytest.fixture
def sample_upcoming_match_with_countdown_html():
    """Sample HTML for an upcoming match page with countdown."""
    return """
    <html>
    <body>
        <div class="wf-title-med">100 Thieves</div>
        <div class="wf-title-med">Evil Geniuses</div>
        <div class="match-header-vs-score">
            <div class="match-header-vs-note">
                <span class="match-header-vs-note mod-upcoming">
                    1h 30m
                </span>
            </div>
        </div>
        <div class="moment-tz-convert">December 25, 2025</div>
        <div>2:00 PM EST</div>
    </body>
    </html>
    """


class TestMatch:
    def test_match_dataclass(self):
        """Test Match dataclass creation."""
        match = Match(
            date="December 23, 2025",
            time="3:00 PM EST",
            team1="Sentinels",
            team2="Cloud9",
            score="2 : 1",
            is_live=False,
            url="https://vlr.gg/match/12345",
        )

        assert match.team1 == "Sentinels"
        assert match.team2 == "Cloud9"
        assert match.score == "2 : 1"
        assert match.is_live is False
        assert match.is_upcoming is False

    def test_match_upcoming(self):
        """Test Match with is_upcoming flag."""
        match = Match(
            date="December 25, 2025",
            time="2:00 PM EST",
            team1="100 Thieves",
            team2="Evil Geniuses",
            score="Match has not started yet.",
            is_live=False,
            url="https://vlr.gg/match/12346",
            is_upcoming=True,
        )

        assert match.is_upcoming is True


class TestValorantClient:
    def test_client_initialization(self, client):
        """Test ValorantClient initializes correctly."""
        assert client.session is not None
        assert client.formatter is not None

    def test_extract_teams(self, client, sample_match_html):
        """Test team extraction from HTML."""
        soup = BeautifulSoup(sample_match_html, "html.parser")
        teams = client._extract_teams(soup)

        assert len(teams) == 2
        assert teams[0] == "Sentinels"
        assert teams[1] == "Cloud9"

    def test_extract_teams_fallback(self, client):
        """Test team extraction with fallback selector."""
        html = """
        <html>
        <body>
            <div class="match-header-link-name">Team Alpha</div>
            <div class="match-header-link-name">Team Beta</div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")
        teams = client._extract_teams(soup)

        assert len(teams) == 2
        assert teams[0] == "Team Alpha"
        assert teams[1] == "Team Beta"

    def test_extract_teams_unknown(self, client):
        """Test team extraction returns unknown when no teams found."""
        html = "<html><body></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        teams = client._extract_teams(soup)

        assert teams == ["Unknown Team 1", "Unknown Team 2"]

    def test_extract_score(self, client, sample_match_html):
        """Test score extraction from HTML."""
        soup = BeautifulSoup(sample_match_html, "html.parser")
        score = client._extract_score(soup)

        assert score == "2 : 1"

    def test_extract_score_not_started(self, client, sample_upcoming_match_html):
        """Test score extraction for upcoming match."""
        soup = BeautifulSoup(sample_upcoming_match_html, "html.parser")
        score = client._extract_score(soup)

        assert score == "Match has not started yet."

    def test_extract_score_countdown(
        self, client, sample_upcoming_match_with_countdown_html
    ):
        """Test score extraction for upcoming match with countdown."""
        soup = BeautifulSoup(sample_upcoming_match_with_countdown_html, "html.parser")
        score = client._extract_score(soup)

        assert score == "1h 30m"

    def test_extract_live_status_live(self, client, sample_live_match_html):
        """Test live status extraction for live match."""
        soup = BeautifulSoup(sample_live_match_html, "html.parser")
        is_live = client._extract_live_status(soup)

        assert is_live is True

    def test_extract_live_status_not_live(self, client, sample_match_html):
        """Test live status extraction for non-live match."""
        soup = BeautifulSoup(sample_match_html, "html.parser")
        is_live = client._extract_live_status(soup)

        assert is_live is False

    def test_extract_date_time(self, client, sample_match_html):
        """Test date/time extraction from HTML."""
        soup = BeautifulSoup(sample_match_html, "html.parser")
        date, time = client._extract_date_time(soup)

        assert date == "December 23, 2025"
        assert time == "3:00 PM EST"

    def test_extract_date_time_unknown(self, client):
        """Test date/time extraction when not found."""
        html = "<html><body></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        date, time = client._extract_date_time(soup)

        assert date == "Unknown date"
        assert time == "Unknown time"

    def test_format_match_output_completed(self, client):
        """Test formatting completed match output."""
        match = Match(
            date="Dec 23, 2025",
            time="3:00 PM",
            team1="Sentinels",
            team2="Cloud9",
            score="2 : 1",
            is_live=False,
            url="https://vlr.gg/match/12345",
        )

        output = client._format_match_output(match)

        assert "Sentinels" in output
        assert "Cloud9" in output
        assert "2 : 1" in output
        assert "LIVE" not in output
        assert "UPCOMING" not in output

    def test_format_match_output_live(self, client):
        """Test formatting live match output."""
        match = Match(
            date="Dec 23, 2025",
            time="5:00 PM",
            team1="LOUD",
            team2="NRG",
            score="1 : 1",
            is_live=True,
            url="https://vlr.gg/match/12346",
        )

        output = client._format_match_output(match)

        assert "LOUD" in output
        assert "NRG" in output
        assert "LIVE" in output

    def test_format_match_output_upcoming(self, client):
        """Test formatting upcoming match output."""
        match = Match(
            date="Dec 25, 2025",
            time="2:00 PM",
            team1="100 Thieves",
            team2="Evil Geniuses",
            score="Match has not started yet.",
            is_live=False,
            url="https://vlr.gg/match/12347",
            is_upcoming=True,
        )

        output = client._format_match_output(match)

        assert "100 Thieves" in output
        assert "Evil Geniuses" in output
        assert "UPCOMING" in output

    def test_format_match_output_upcoming_with_eta(self, client):
        """Test formatting upcoming match output with countdown ETA."""
        match = Match(
            date="Dec 25, 2025",
            time="2:00 PM",
            team1="100 Thieves",
            team2="Evil Geniuses",
            score="1h 30m",
            is_live=False,
            url="https://vlr.gg/match/12347",
            is_upcoming=True,
        )

        output = client._format_match_output(match)

        assert "100 Thieves" in output
        assert "Evil Geniuses" in output
        assert "in 1h 30m" in output
        assert "UPCOMING" not in output

    def test_format_eta_with_countdown(self, client):
        """Test _format_eta with countdown patterns."""
        assert client._format_eta("1h 30m") == "in 1h 30m"
        assert client._format_eta("2d 5h") == "in 2d 5h"
        assert client._format_eta("0h 42m") == "in 0h 42m"
        assert client._format_eta("5m 30s") == "in 5m 30s"

    def test_format_eta_fallback(self, client):
        """Test _format_eta fallback to UPCOMING."""
        assert client._format_eta("Match has not started yet.") == "UPCOMING"
        assert client._format_eta("") == "UPCOMING"
        assert client._format_eta("vs") == "UPCOMING"

    def test_get_event_url_valid(self, client):
        """Test getting event URL for valid choice."""
        url = client.get_event_url("1")
        assert url is not None
        assert "vlr.gg" in url

    def test_get_event_url_invalid(self, client):
        """Test getting event URL for invalid choice."""
        url = client.get_event_url("99")
        assert url is None

    def test_get_event_url_exit(self, client):
        """Test getting event URL for exit choice."""
        url = client.get_event_url("7")
        assert url is None

    @patch.object(ValorantClient, "_make_request")
    def test_fetch_event_matches(self, mock_request, client):
        """Test fetching event matches using slug-based matching."""
        mock_html = """
        <html>
        <body>
            <a href="/594001/team-a-vs-team-b-vct-2026-test-event-ur1">Match 1</a>
            <a href="/595002/team-c-vs-team-d-vct-2026-test-event-ur1">Match 2</a>
            <a href="/other/link">Other Link</a>
            <a href="/123456/some-other-event-match">Wrong event</a>
        </body>
        </html>
        """
        mock_request.return_value = BeautifulSoup(mock_html, "html.parser")

        # URL contains slug 'vct-2026-test-event' which matches the first two hrefs
        matches = client.fetch_event_matches(
            "https://vlr.gg/event/matches/2682/vct-2026-test-event/"
        )

        assert len(matches) == 2

    @patch.object(ValorantClient, "_make_request")
    def test_fetch_event_matches_empty(self, mock_request, client):
        """Test fetching event matches when none found."""
        mock_request.return_value = BeautifulSoup(
            "<html><body></body></html>", "html.parser"
        )

        matches = client.fetch_event_matches("https://vlr.gg/event/123")

        assert len(matches) == 0

    @patch.object(ValorantClient, "_make_request")
    def test_fetch_event_matches_request_fails(self, mock_request, client):
        """Test fetching event matches when request fails."""
        mock_request.return_value = None

        matches = client.fetch_event_matches("https://vlr.gg/event/123")

        assert len(matches) == 0


class TestMakeRequest:
    @patch("valorant_client.requests.Session.get")
    def test_make_request_success(self, mock_get):
        """Test successful HTTP request."""
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with patch("valorant_client.MatchCache"):
            client = ValorantClient()
            result = client._make_request("https://vlr.gg/test")

        assert result is not None
        assert isinstance(result, BeautifulSoup)

    @patch("valorant_client.requests.Session.get")
    def test_make_request_retry_on_failure(self, mock_get):
        """Test request retry on failure."""
        from requests.exceptions import ConnectionError as ReqConnectionError

        # Use ConnectionError which is a retryable error type
        mock_get.side_effect = ReqConnectionError("Connection failed")

        with (
            patch("valorant_client.MatchCache"),
            patch("valorant_client.time.sleep"),  # Skip sleep during test
        ):
            client = ValorantClient()
            result = client._make_request("https://vlr.gg/test", retries=2)

        assert result is None
        assert mock_get.call_count == 2


class TestClientCacheControl:
    def test_client_cache_enabled_by_default(self):
        """Test that cache is enabled by default."""
        with patch("valorant_client.MatchCache") as mock_cache:
            ValorantClient()
            mock_cache.assert_called_once_with(enabled=True)

    def test_client_cache_disabled(self):
        """Test that cache can be disabled via constructor."""
        with patch("valorant_client.MatchCache") as mock_cache:
            ValorantClient(cache_enabled=False)
            mock_cache.assert_called_once_with(enabled=False)


class TestExponentialBackoff:
    def test_calculate_backoff_increases(self):
        """Test that backoff delay increases with attempts."""
        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            delay0 = client._calculate_backoff(0)
            delay1 = client._calculate_backoff(1)
            delay2 = client._calculate_backoff(2)

            # Each delay should be roughly double the previous (with some jitter)
            assert delay1 > delay0
            assert delay2 > delay1

    def test_calculate_backoff_max_limit(self):
        """Test that backoff delay is capped at MAX_BACKOFF_DELAY."""
        from valorant_client import MAX_BACKOFF_DELAY

        with patch("valorant_client.MatchCache"):
            client = ValorantClient()

            # Very high attempt number should still be capped
            delay = client._calculate_backoff(100)

            assert delay <= MAX_BACKOFF_DELAY
