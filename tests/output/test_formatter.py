# Tests for the formatter module.
import io
from dataclasses import replace
from typing import Any

import pytest
from rich.console import Console

from valorant_matches.output.formatter import (
    STATUS_ICONS,
    VALORANT_THEME,
    Formatter,
    eta_label,
)
from valorant_matches.scraping.matches import Match

BASE_MATCH = Match(
    url="https://vlr.gg/match/12345",
    team1="Sentinels",
    team2="Cloud9",
    status="completed",
    score="2 : 1",
    date_label="Dec 23, 2025",
    time_label="3:00 PM",
)


def make_match(**overrides: Any) -> Match:
    """Build a match for formatting tests."""
    return replace(BASE_MATCH, **overrides)


def recording_formatter(width: int = 80, color: bool = False) -> Formatter:
    """Build a formatter whose output can be read back."""
    console = Console(
        file=io.StringIO(),
        theme=VALORANT_THEME,
        width=width,
        record=True,
        force_terminal=color,
        no_color=not color,
    )
    return Formatter(console=console)


class TestMessages:
    """Tests for message printing."""

    def test_plain_output_when_not_a_terminal(self, capsys) -> None:
        """Redirected output carries no escape codes."""
        Formatter().info("hello")
        assert capsys.readouterr().out == "hello\n"

    def test_color_output_when_forced(self) -> None:
        """Forced color emits ANSI styling."""
        formatter = recording_formatter(color=True)
        formatter.error("boom")
        assert "\x1b[" in formatter.console.export_text(styles=True)

    def test_markup_is_not_interpreted(self, capsys) -> None:
        """Brackets in dynamic text print literally."""
        Formatter().warning("Team [bold]X[/bold]")
        assert capsys.readouterr().out == "Team [bold]X[/bold]\n"

    def test_long_lines_are_not_wrapped(self) -> None:
        """Messages never gain inserted newlines."""
        formatter = recording_formatter(width=20)
        formatter.print("x" * 50)
        assert formatter.console.export_text() == "x" * 50 + "\n"

    def test_ask_reads_input(self, monkeypatch) -> None:
        """Prompts print the question and return the typed line."""
        monkeypatch.setattr("builtins.input", lambda *args: "3")
        formatter = recording_formatter()
        assert formatter.ask("Pick:") == "3"
        assert "Pick:" in formatter.console.export_text()


class TestFormatMatchCompact:
    """Tests for format_match_compact."""

    def test_completed(self) -> None:
        """Completed matches show the score and a check mark."""
        text = Formatter().format_match_compact(make_match()).plain
        assert (
            text
            == f"Dec 23, 2025 | Sentinels 2 : 1 Cloud9 | {STATUS_ICONS['completed']}"
        )

    def test_live(self) -> None:
        """Live matches are labelled LIVE."""
        text = Formatter().format_match_compact(make_match(status="live")).plain
        assert "LIVE" in text and STATUS_ICONS["live"] in text

    def test_upcoming(self) -> None:
        """Upcoming matches show vs and the countdown."""
        match = make_match(status="upcoming", score=None, countdown="2h 5m")
        text = Formatter().format_match_compact(match).plain
        assert "Sentinels vs Cloud9" in text
        assert f"{STATUS_ICONS['upcoming']} in 2h 5m" in text

    def test_favorite_marker(self) -> None:
        """Saved teams get a star."""
        formatter = Formatter(favorite_teams=["sentinels"])
        assert "★ Sentinels" in formatter.format_match_compact(make_match()).plain


class TestFormatMatchFull:
    """Tests for format_match_full."""

    def test_completed_match(self) -> None:
        """Completed matches show the score without status labels."""
        output = Formatter().format_match_full(make_match()).plain
        assert "Sentinels vs Cloud9" in output
        assert "Score: 2 : 1" in output
        assert "LIVE" not in output and "UPCOMING" not in output

    def test_live_match(self) -> None:
        """Live matches show the score and LIVE."""
        output = Formatter().format_match_full(make_match(status="live")).plain
        assert "Score: 2 : 1 LIVE" in output

    def test_upcoming_match_without_countdown(self) -> None:
        """Upcoming matches without a countdown say UPCOMING."""
        match = make_match(status="upcoming", score=None)
        output = Formatter().format_match_full(match).plain
        assert "UPCOMING" in output and "Score:" not in output

    def test_upcoming_match_with_eta(self) -> None:
        """Upcoming matches with a countdown show it."""
        match = make_match(status="upcoming", score=None, countdown="1h 30m")
        output = Formatter().format_match_full(match).plain
        assert "in 1h 30m" in output and "UPCOMING" not in output

    @pytest.mark.parametrize("width", [60, 80, 200])
    def test_links_intact_and_rule_within_terminal(self, width: int) -> None:
        """Styling never breaks URLs, and the rule fits the terminal."""
        formatter = recording_formatter(width=width)
        url = (
            "https://vlr.gg/753459/karmine-corp-vs-xi-lai-gaming-"
            "valorant-champions-2026-opening-d"
        )
        formatter.print_match(make_match(url=url))
        lines = formatter.console.export_text().splitlines()
        assert f"Stats: {url}" in lines
        rules = [line for line in lines if line and set(line) == {"─"}]
        assert rules == ["─" * min(width, 100)]


def test_eta_label() -> None:
    """Countdowns read as "in ..."; otherwise UPCOMING."""
    assert eta_label(make_match(countdown="1d 5h")) == "in 1d 5h"
    assert eta_label(make_match()) == "UPCOMING"


class TestPrintStatsFooter:
    """Tests for print_stats_footer."""

    def test_full_footer(self, capsys) -> None:
        """Every non-zero count is listed in order."""
        Formatter().print_stats_footer(
            displayed=10,
            cache_hits=5,
            failed=2,
            fetch_time=3.5,
            live_count=1,
            tbd_count=4,
            skipped_count=3,
        )
        assert capsys.readouterr().out == (
            "Displayed: 10 matches | Skipped: 3 | TBD: 4 | Cache hits: 5 | "
            "Failed: 2 | Live: 1 | Time: 3.5s\n"
        )

    def test_singular_and_zero_counts_hidden(self, capsys) -> None:
        """One match is singular and zero counts are omitted."""
        Formatter().print_stats_footer(
            displayed=1, cache_hits=0, failed=0, fetch_time=1.0
        )
        assert capsys.readouterr().out == "Displayed: 1 match | Time: 1.0s\n"
