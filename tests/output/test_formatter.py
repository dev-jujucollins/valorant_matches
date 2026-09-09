# Tests for the formatter module.
import pytest

from valorant_matches.output.formatter import STATUS_ICONS, Formatter


@pytest.fixture
def formatter():
    """Create a Formatter instance for testing."""
    return Formatter()


class TestFormatter:
    def test_format_basic(self, formatter):
        """Test basic text formatting."""
        result = formatter.format("Hello", "bright_cyan")
        assert "Hello" in result
        # Should contain ANSI escape codes
        assert "\x1b[" in result

    def test_format_does_not_print_directly(self, formatter, capsys):
        """Formatting should return styled text without writing to stdout."""
        formatter.format("Hello", "bright_cyan")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_format_with_bold(self, formatter):
        """Test formatting with bold style."""
        result = formatter.format("Bold Text", "bright_cyan", bold=True)
        assert "Bold Text" in result

    def test_format_with_underline(self, formatter):
        """Test formatting with underline style."""
        result = formatter.format("Underlined", "bright_cyan", underline=True)
        assert "Underlined" in result


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


class TestFormatMatchFull:
    """Tests for full match formatting (ported from the removed sync client)."""

    def _make_match(self, **overrides):
        from valorant_matches.scraping.matches import Match

        values = {
            "date": "Dec 23, 2025",
            "time": "3:00 PM",
            "team1": "Sentinels",
            "team2": "Cloud9",
            "score": "2 : 1",
            "is_live": False,
            "url": "https://vlr.gg/match/12345",
            "is_upcoming": False,
        }
        values.update(overrides)
        return Match(**values)

    def test_completed_match(self, formatter):
        output = formatter.format_match_full(self._make_match())
        assert "Sentinels" in output
        assert "Cloud9" in output
        assert "2 : 1" in output
        assert "LIVE" not in output
        assert "UPCOMING" not in output

    def test_live_match(self, formatter):
        output = formatter.format_match_full(
            self._make_match(team1="LOUD", team2="NRG", score="1 : 1", is_live=True)
        )
        assert "LOUD" in output
        assert "NRG" in output
        assert "LIVE" in output

    def test_upcoming_match_without_countdown(self, formatter):
        output = formatter.format_match_full(
            self._make_match(score="Match has not started yet.", is_upcoming=True)
        )
        assert "UPCOMING" in output

    def test_upcoming_match_with_eta(self, formatter):
        output = formatter.format_match_full(
            self._make_match(score="1h 30m", is_upcoming=True)
        )
        assert "in 1h 30m" in output
        assert "UPCOMING" not in output


def test_footer_separates_skipped_from_failed(capsys) -> None:
    """Intentional filtering is visible without implying a failure."""
    formatter = Formatter()
    formatter.print_stats_footer(
        displayed=1, cache_hits=0, failed=0, fetch_time=0, skipped_count=3
    )
    output = capsys.readouterr().out
    assert "Skipped: 3" in output
    assert "Failed:" not in output


@pytest.mark.parametrize("width, legacy_windows", [(60, False), (80, True)])
def test_full_match_keeps_links_intact_and_rule_within_terminal(
    width: int, legacy_windows: bool
) -> None:
    """Styling must not insert newlines into URLs or double-wrap separators."""
    from rich.text import Text

    from valorant_matches.scraping.matches import Match

    formatter = Formatter()
    formatter.console.width = width
    formatter.console.height = 25
    formatter.console.legacy_windows = legacy_windows
    match = Match(
        "Saturday, September 26",
        "Time TBD (date tentative)",
        "Karmine Corp",
        "Xi Lai Gaming",
        "Match has not started yet.",
        False,
        "https://vlr.gg/753459/karmine-corp-vs-xi-lai-gaming-valorant-champions-2026-opening-d",
        is_upcoming=True,
    )
    output = Text.from_ansi(formatter.format_match_full(match)).plain
    assert f"Stats: {match.url}" in output.splitlines()
    rules = [line for line in output.splitlines() if line and set(line) == {"─"}]
    assert rules == ["─" * formatter.console.width]
    assert "Time TBD (date tentative)" in output
