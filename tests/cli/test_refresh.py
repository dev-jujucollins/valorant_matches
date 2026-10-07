"""Tests for freshness reporting, timezone display, and CLI failures."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import filter_today, run_cli_mode
from valorant_matches.cli.options import RunOptions, build_run_options
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.matches import FetchError, Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult

EVENT = SimpleNamespace(
    event_id="1", name="Event", status="ongoing", url="https://vlr.gg/e", slug="e"
)


def match_at(instant: datetime | None = datetime(2026, 1, 2, 1, tzinfo=UTC)) -> Match:
    """Make a live match whose date crosses midnight in US timezones."""
    return Match(
        url="https://vlr.gg/1",
        team1="Alpha",
        team2="Beta",
        status="live",
        score="1-0",
        starts_at=instant,
        date_label="January 2, 2026",
        time_label="1:00 AM",
    )


def opts_for(*flags: str) -> RunOptions:
    """Use real argument parsing for workflow tests."""
    return build_run_options(parse_args(["-r", "americas", *flags]), UserProfile())


def ok(*matches: Match) -> EventFetchResult:
    """A successful fetch of the given matches."""
    return EventFetchResult(
        total_links=len(matches), processed=ProcessedMatches(list(matches))
    )


def run(opts: RunOptions, results: list[EventFetchResult], sleeps=None) -> int:
    """Run the CLI against canned fetch results."""
    with (
        patch("valorant_matches.cli.display.select_events", return_value=[EVENT]),
        patch("valorant_matches.cli.display.fetch_event_data", side_effect=results),
        patch("valorant_matches.cli.display.time.sleep", side_effect=sleeps),
    ):
        return run_cli_mode(opts, Formatter(), Mock(is_stale=False))


def test_timezone_conversion_does_not_mutate_source() -> None:
    """Display conversion leaves the source match unchanged."""
    source = match_at()
    zone = ZoneInfo("America/Los_Angeles")
    assert source.local_date_time(zone) == ("January 01, 2026", "05:00 PM PST")
    assert source.date_label == "January 2, 2026"


def test_today_uses_selected_timezone() -> None:
    """--today compares dates in the chosen zone and drops unknown starts."""

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 2, tzinfo=UTC)

    source = [
        match_at(),
        match_at(None),
        match_at(datetime(2026, 1, 2, 9, tzinfo=UTC)),
    ]
    with patch("valorant_matches.cli.display.datetime", FixedDateTime):
        result = filter_today(source, ZoneInfo("America/Los_Angeles"))
    assert result == [source[0]]


@pytest.mark.parametrize(
    "flags",
    [
        ("--interval", "0"),
        ("--timezone", "Unknown/Zone"),
        ("--watch", "--export", "json"),
        ("--watch", "--interactive"),
        ("--results", "--upcoming"),
        ("--event", "abc"),
        ("--season", "1999"),
        ("--event", "1"),
    ],
)
def test_invalid_options(flags: tuple[str, ...]) -> None:
    """Invalid combinations exit with status 2."""
    with pytest.raises(SystemExit) as error:
        parse_args(["-r", "americas", *flags])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "result, expected",
    [
        (EventFetchResult(), 0),
        (EventFetchResult(error=FetchError("https://vlr.gg/e", "http", "HTTP 503")), 1),
        (
            EventFetchResult(
                total_links=1,
                processed=ProcessedMatches(
                    [],
                    failed_count=1,
                    errors=[FetchError("https://vlr.gg/1", "parse", "missing teams")],
                ),
            ),
            1,
        ),
    ],
)
def test_empty_and_failed_fetch_exit_codes(
    result: EventFetchResult, expected: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty schedules succeed; failures never look like empty schedules."""
    assert run(opts_for(), [result]) == expected
    text = capsys.readouterr().out
    if expected:
        assert "No matches found" not in text


def test_watch_changes_and_recovers(capsys: pytest.CaptureFixture[str]) -> None:
    """Watch reports changes, survives a failed refresh, and keeps freshness."""
    initial = match_at()
    final = replace(initial, score="2-0", status="completed")
    results = [
        ok(initial),
        EventFetchResult(error=FetchError("https://vlr.gg/e", "http", "HTTP 503")),
        ok(final),
    ]
    with (
        patch("valorant_matches.cli.display.select_events", return_value=[EVENT]),
        patch(
            "valorant_matches.cli.display.fetch_event_data", side_effect=results
        ) as fetch,
        patch(
            "valorant_matches.cli.display.time.sleep",
            side_effect=[None, None, KeyboardInterrupt],
        ) as sleep,
    ):
        code = run_cli_mode(
            opts_for("--watch", "--interval", "15"), Formatter(), Mock(is_stale=False)
        )
    assert code == 130
    text = capsys.readouterr().out
    assert "1-0 (live) → 2-0 (completed)" in text
    assert "Refresh incomplete" in text
    updates = [line for line in text.splitlines() if line.startswith("Last successful")]
    assert len(updates) == 3
    assert updates[0] == updates[1]
    assert "none yet" not in updates[0]
    assert fetch.call_count == 3
    assert all(call.args == (15,) for call in sleep.call_args_list)


def test_watch_ignores_countdown_ticks(capsys: pytest.CaptureFixture[str]) -> None:
    """A countdown changing between refreshes is not reported as a change."""
    first = replace(match_at(), status="upcoming", score=None, countdown="1h 5m")
    second = replace(first, countdown="1h 4m")
    run(opts_for("--watch"), [ok(first), ok(second)], [None, KeyboardInterrupt])
    assert "Changed:" not in capsys.readouterr().out


def test_watch_first_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Never claim freshness before a successful fetch."""
    failure = EventFetchResult(error=FetchError("url", "http", "HTTP 503"))
    assert run(opts_for("--watch"), [failure], KeyboardInterrupt) == 130
    assert "Last successful update: none yet" in capsys.readouterr().out


def test_watch_respects_team_filter(capsys: pytest.CaptureFixture[str]) -> None:
    """Watch changes only include the selected team."""
    initial = match_at()
    final = replace(initial, score="2-0")
    run(
        opts_for("--watch", "--team", "Other"),
        [ok(initial), ok(final)],
        [None, KeyboardInterrupt],
    )
    assert "Changed:" not in capsys.readouterr().out


def test_export_failure_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed export write exits 1."""
    with patch(
        "valorant_matches.cli.display.export_matches", side_effect=OSError("disk full")
    ):
        code = run(
            opts_for("--export", "json", "-o", str(tmp_path / "m.json")),
            [ok(match_at())],
        )
    assert code == 1
    assert "Export failed: disk full" in capsys.readouterr().out


def test_export_uses_display_timezone(tmp_path: Path) -> None:
    """Exported date_time follows --timezone."""
    output = tmp_path / "m.json"
    flags = ("--export", "json", "-o", str(output), "--timezone", "America/Los_Angeles")
    assert run(opts_for(*flags), [ok(match_at())]) == 0
    row = json.loads(output.read_text())["matches"][0]
    assert row["date_time"] == "January 01, 2026 05:00 PM PST"


def test_empty_schedule_export(tmp_path: Path) -> None:
    """An empty successful schedule still produces a valid export."""
    output = tmp_path / "empty.json"
    assert (
        run(opts_for("--export", "json", "-o", str(output)), [EventFetchResult()]) == 0
    )
    assert json.loads(output.read_text()) == {"matches": [], "count": 0}


def test_yearless_leap_day_sorts_without_error() -> None:
    """Label-only February 29 dates resolve to a real leap year."""
    from valorant_matches.cli.display import _parse_date

    parsed = _parse_date("Feb 29")
    assert (parsed.month, parsed.day) == (2, 29)
    assert parsed.year % 4 == 0
