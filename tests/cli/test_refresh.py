"""Tests for freshness reporting, timezone display, and CLI failures."""

from argparse import Namespace
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import localize_matches, run_cli_mode, sort_matches
from valorant_matches.output.formatter import Formatter
from valorant_matches.scraping.matches import FetchError, Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult


def match_at(instant: str | None = "2026-01-02T01:00:00+00:00") -> Match:
    """Make a match whose date crosses midnight in US timezones."""
    return Match(
        "January 2, 2026",
        "1:00 AM",
        "Alpha",
        "Beta",
        "1-0",
        True,
        "https://vlr.gg/1",
        start_time=instant,
    )


def args_for(*flags: str) -> Namespace:
    """Use real argument parsing for workflow tests."""
    with patch("sys.argv", ["valorant-matches", "-r", "americas", *flags]):
        return parse_args()


def test_timezone_conversion_does_not_mutate_source() -> None:
    source = match_at()
    converted = localize_matches([({}, source)], "America/Los_Angeles", False)[0][1]
    assert converted.date == "January 01, 2026"
    assert converted.time == "05:00 PM PST"
    assert source.date == "January 2, 2026"
    assert converted.start_time == source.start_time


def test_today_uses_selected_timezone() -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 2, tzinfo=UTC)

    source = [
        ({}, match_at()),
        ({}, match_at(None)),
        ({}, match_at("2026-01-02T09:00:00+00:00")),
    ]
    with patch("valorant_matches.cli.display.datetime", FixedDateTime):
        result = localize_matches(source, "America/Los_Angeles", True)
    assert len(result) == 1
    assert result[0][1].date == "January 01, 2026"


def test_sort_uses_instants_and_legacy_time() -> None:
    early = match_at("2026-01-02T01:00:00+00:00")
    late = match_at("2026-01-01T23:00:00-05:00")
    assert [m for _, m in sort_matches([({}, late), ({}, early)], "date")] == [
        early,
        late,
    ]
    early = replace(early, start_time=None, time="2:00 AM")
    late = replace(early, time="11:00 AM")
    assert sort_matches([({}, late), ({}, early)], "date")[0][1] == early


@pytest.mark.parametrize(
    "flags",
    [
        ("--interval", "0"),
        ("--timezone", "Unknown/Zone"),
        ("--watch", "--export", "json"),
        ("--watch", "--interactive"),
        ("--results", "--upcoming"),
    ],
)
def test_invalid_options(flags: tuple[str, ...]) -> None:
    with pytest.raises(SystemExit) as error:
        args_for(*flags)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "result, expected",
    [
        (EventFetchResult(), 0),
        (
            EventFetchResult(
                error=FetchError("https://vlr.gg/event", "http", "HTTP 503")
            ),
            1,
        ),
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
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch("valorant_matches.cli.display.fetch_event_data", return_value=result),
    ):
        assert run_cli_mode(args_for(), Formatter(), Mock(), Mock()) == expected
    text = capsys.readouterr().out
    if expected:
        assert "No matches found" not in text


def test_watch_changes_and_recovers(capsys: pytest.CaptureFixture[str]) -> None:
    initial = match_at()
    final = replace(initial, score="2-0", is_live=False)
    results = [
        EventFetchResult(total_links=1, processed=ProcessedMatches([({}, initial)])),
        EventFetchResult(error=FetchError("https://vlr.gg/event", "http", "HTTP 503")),
        EventFetchResult(total_links=1, processed=ProcessedMatches([({}, final)])),
    ]
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data", side_effect=results
        ) as fetch,
        patch(
            "valorant_matches.cli.display.time.sleep",
            side_effect=[None, None, KeyboardInterrupt],
        ) as sleep,
    ):
        assert (
            run_cli_mode(
                args_for("--watch", "--interval", "15"), Formatter(), Mock(), Mock()
            )
            == 130
        )
    text = capsys.readouterr().out
    assert "1-0 (live) → 2-0 (completed)" in text
    assert "Refresh incomplete" in text
    updates = [
        line for line in text.splitlines() if line.startswith("Last successful update:")
    ]
    assert len(updates) == 3
    assert updates[0] == updates[1]
    assert "none yet" not in updates[0]
    assert fetch.call_count == 3
    assert all(call.args == (15,) for call in sleep.call_args_list)


def test_export_failure_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = EventFetchResult(
        total_links=1, processed=ProcessedMatches([({}, match_at())])
    )
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch("valorant_matches.cli.display.fetch_event_data", return_value=result),
        patch(
            "valorant_matches.cli.display.export_matches",
            side_effect=OSError("disk full"),
        ),
    ):
        assert (
            run_cli_mode(
                args_for("--export", "json", "-o", str(tmp_path / "matches.json")),
                Formatter(),
                Mock(),
                Mock(),
            )
            == 1
        )
    assert "Export failed: disk full" in capsys.readouterr().out


def test_empty_schedule_export(tmp_path: Path) -> None:
    """An empty successful schedule still produces a valid export."""
    import json

    output = tmp_path / "empty.json"
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            return_value=EventFetchResult(),
        ),
    ):
        assert (
            run_cli_mode(
                args_for("--export", "json", "-o", str(output)),
                Formatter(),
                Mock(),
                Mock(),
            )
            == 0
        )
    assert json.loads(output.read_text()) == {"matches": [], "count": 0}


def test_watch_first_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Never claim freshness before a successful fetch."""
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            return_value=EventFetchResult(error=FetchError("url", "http", "HTTP 503")),
        ),
        patch("valorant_matches.cli.display.time.sleep", side_effect=KeyboardInterrupt),
    ):
        assert run_cli_mode(args_for("--watch"), Formatter(), Mock(), Mock()) == 130
    assert "Last successful update: none yet" in capsys.readouterr().out


def test_watch_respects_team_filter(capsys: pytest.CaptureFixture[str]) -> None:
    """Watch changes only include the selected team."""
    initial = match_at()
    final = replace(initial, score="2-0")
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=Mock(status="ongoing"),
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            side_effect=[
                EventFetchResult(total_links=1, processed=ProcessedMatches([({}, m)]))
                for m in [initial, final]
            ],
        ),
        patch(
            "valorant_matches.cli.display.time.sleep",
            side_effect=[None, KeyboardInterrupt],
        ),
    ):
        run_cli_mode(
            args_for("--watch", "--team", "Other"), Formatter(), Mock(), Mock()
        )
    assert "Changed:" not in capsys.readouterr().out


def test_yearless_leap_day_sorts_without_error() -> None:
    """Legacy February 29 dates resolve to a real leap year."""
    from valorant_matches.cli.display import _parse_date

    parsed = _parse_date("Feb 29")
    assert parsed.month == 2
    assert parsed.day == 29
    assert parsed.year % 4 == 0
