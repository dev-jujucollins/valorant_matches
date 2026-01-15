# Tests for the formatter module.
import pytest

from formatter import VALORANT_THEME, Formatter


@pytest.fixture
def formatter():
    """Create a Formatter instance for testing."""
    return Formatter()


class TestFormatter:
    def test_formatter_initialization(self, formatter):
        """Test that formatter initializes correctly."""
        assert formatter.console is not None

    def test_format_basic(self, formatter):
        """Test basic text formatting."""
        result = formatter.format("Hello", "bright_cyan")
        assert "Hello" in result
        # Should contain ANSI escape codes
        assert "\x1b[" in result

    def test_format_with_bold(self, formatter):
        """Test formatting with bold style."""
        result = formatter.format("Bold Text", "bright_cyan", bold=True)
        assert "Bold Text" in result

    def test_format_with_underline(self, formatter):
        """Test formatting with underline style."""
        result = formatter.format("Underlined", "bright_cyan", underline=True)
        assert "Underlined" in result

    def test_error_formatting(self, formatter):
        """Test error message formatting."""
        result = formatter.error("Error message")
        assert "Error message" in result

    def test_warning_formatting(self, formatter):
        """Test warning message formatting."""
        result = formatter.warning("Warning message")
        assert "Warning message" in result

    def test_success_formatting(self, formatter):
        """Test success message formatting."""
        result = formatter.success("Success message")
        assert "Success message" in result

    def test_info_formatting(self, formatter):
        """Test info message formatting."""
        result = formatter.info("Info message")
        assert "Info message" in result

    def test_team_name_formatting(self, formatter):
        """Test team name formatting."""
        result = formatter.team_name("Sentinels")
        assert "Sentinels" in result

    def test_score_formatting(self, formatter):
        """Test score formatting."""
        result = formatter.score("2 - 1")
        assert "2 - 1" in result

    def test_live_status_formatting(self, formatter):
        """Test live status formatting."""
        result = formatter.live_status("LIVE")
        assert "LIVE" in result

    def test_date_time_formatting(self, formatter):
        """Test date/time formatting."""
        result = formatter.date_time("Dec 23, 2025 3:00 PM")
        assert "Dec 23, 2025 3:00 PM" in result

    def test_stats_link_formatting(self, formatter):
        """Test stats link formatting."""
        result = formatter.stats_link("https://vlr.gg/match/12345")
        assert "https://vlr.gg/match/12345" in result

    def test_muted_formatting(self, formatter):
        """Test muted text formatting."""
        result = formatter.muted("Muted text")
        assert "Muted text" in result

    def test_highlight_formatting(self, formatter):
        """Test highlighted text formatting."""
        result = formatter.highlight("Highlighted")
        assert "Highlighted" in result

    def test_primary_formatting(self, formatter):
        """Test primary text formatting."""
        result = formatter.primary("Primary text")
        assert "Primary text" in result

    def test_secondary_formatting(self, formatter):
        """Test secondary text formatting."""
        result = formatter.secondary("Secondary text")
        assert "Secondary text" in result

    def test_accent_formatting(self, formatter):
        """Test accent text formatting."""
        result = formatter.accent("Accent text")
        assert "Accent text" in result

    def test_match_header_formatting(self, formatter):
        """Test match header formatting."""
        result = formatter.match_header("Match Header")
        assert "Match Header" in result


class TestValorantTheme:
    def test_theme_has_required_styles(self):
        """Test that theme includes all required style definitions."""
        required_styles = [
            "error",
            "warning",
            "success",
            "info",
            "primary",
            "secondary",
            "muted",
            "highlight",
            "accent",
            "team",
            "score",
            "live",
            "date_time",
            "link",
        ]

        for style in required_styles:
            assert style in VALORANT_THEME.styles
