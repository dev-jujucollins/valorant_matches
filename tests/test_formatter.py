# Tests for the formatter module.
import pytest

from formatter import STATUS_ICONS, VALORANT_THEME, Formatter


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


class TestStatusIcons:
    """Tests for STATUS_ICONS constants."""

    def test_status_icons_defined(self):
        """Test that all status icons are defined."""
        assert "live" in STATUS_ICONS
        assert "upcoming" in STATUS_ICONS
        assert "completed" in STATUS_ICONS

    def test_status_icons_are_strings(self):
        """Test that all status icons are non-empty strings."""
        for icon in STATUS_ICONS.values():
            assert isinstance(icon, str)
            assert len(icon) > 0


class TestFormatMatchCompact:
    """Tests for format_match_compact method."""

    def test_format_match_compact_completed(self, formatter):
        """Test compact format for completed match."""
        result = formatter.format_match_compact(
            date="Dec 23 2025",
            team1="Sentinels",
            team2="Cloud9",
            score="2-1",
            is_live=False,
            is_upcoming=False,
        )
        assert "Dec 23" in result
        assert "Sentinels" in result
        assert "Cloud9" in result
        assert "2-1" in result
        assert STATUS_ICONS["completed"] in result

    def test_format_match_compact_live(self, formatter):
        """Test compact format for live match."""
        result = formatter.format_match_compact(
            date="Dec 23 2025",
            team1="Sentinels",
            team2="Cloud9",
            score="1-1",
            is_live=True,
            is_upcoming=False,
        )
        assert "LIVE" in result
        assert STATUS_ICONS["live"] in result

    def test_format_match_compact_upcoming(self, formatter):
        """Test compact format for upcoming match."""
        result = formatter.format_match_compact(
            date="Dec 23 2025",
            team1="Sentinels",
            team2="Cloud9",
            score="in 2h",
            is_live=False,
            is_upcoming=True,
        )
        assert "vs" in result
        assert STATUS_ICONS["upcoming"] in result

    def test_format_match_compact_preserves_full_date(self, formatter):
        """Test that compact format preserves full date."""
        result = formatter.format_match_compact(
            date="Thursday",
            team1="A",
            team2="B",
            score="2-1",
        )
        # Full date should be preserved
        assert "Thursday" in result


class TestPrintStatsFooter:
    """Tests for print_stats_footer method."""

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from text for easier testing."""
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def test_print_stats_footer_basic(self, formatter, capsys):
        """Test basic stats footer output."""
        formatter.print_stats_footer(
            displayed=10,
            cache_hits=5,
            failed=2,
            fetch_time=3.5,
            live_count=1,
        )
        captured = capsys.readouterr()
        # Check for key parts (allowing ANSI codes in between)
        assert "Displayed" in captured.out
        assert "10" in captured.out
        assert "Cache hits" in captured.out
        assert "Failed" in captured.out
        assert "Live" in captured.out
        assert "Time" in captured.out

    def test_print_stats_footer_singular_match(self, formatter, capsys):
        """Test stats footer with single match."""
        formatter.print_stats_footer(
            displayed=1,
            cache_hits=0,
            failed=0,
            fetch_time=1.0,
        )
        captured = capsys.readouterr()
        clean_out = self._strip_ansi(captured.out)
        assert "Displayed: 1 match" in clean_out
        # Should not show "matches" for singular
        assert "matches" not in clean_out

    def test_print_stats_footer_no_cache_hits(self, formatter, capsys):
        """Test stats footer without cache hits."""
        formatter.print_stats_footer(
            displayed=5,
            cache_hits=0,
            failed=0,
            fetch_time=2.0,
        )
        captured = capsys.readouterr()
        assert "Cache hits" not in captured.out

    def test_print_stats_footer_no_failures(self, formatter, capsys):
        """Test stats footer without failures."""
        formatter.print_stats_footer(
            displayed=5,
            cache_hits=3,
            failed=0,
            fetch_time=2.0,
        )
        captured = capsys.readouterr()
        assert "Failed" not in captured.out
