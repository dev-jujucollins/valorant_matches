# Tests for match-list helpers and the CLI workflow.

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import (
    MatchStats,
    filter_matches_by_favorites,
    filter_matches_by_team,
    group_matches,
    print_empty_results,
    print_error_summary,
    run_cli_mode,
    sort_matches,
)
from valorant_matches.cli.options import RunOptions, build_run_options
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.matches import FetchError, Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult

BASE_MATCH = Match(
    url="https://vlr.gg/123",
    team1="Team A",
    team2="Team B",
    status="completed",
    score="2-1",
    date_label="Jan 15",
    time_label="12:00",
)


def make_match(**overrides: Any) -> Match:
    """Build a match for display tests."""
    return replace(BASE_MATCH, **overrides)


def opts_for(*flags: str) -> RunOptions:
    """Resolve CLI flags without saved state."""
    return build_run_options(parse_args(list(flags)), UserProfile())


EVENT = SimpleNamespace(
    event_id="1",
    name="VCT Americas",
    status="ongoing",
    url="https://vlr.gg/event/matches/1/vct-americas/",
    slug="vct-americas",
)


def fetch_result(*matches: Match, **counts) -> EventFetchResult:
    """Wrap matches in a successful fetch result."""
    return EventFetchResult(
        total_links=counts.pop("total_links", len(matches)),
        processed=ProcessedMatches(list(matches), **counts),
    )


class TestMatchStats:
    """Tests for MatchStats.add_fetch."""

    def test_event_error_counts_as_failure(self) -> None:
        """An event-level error is one failure with its error kept."""
        stats = MatchStats()
        error = FetchError("https://vlr.gg/e", "http", "HTTP 503")
        stats.add_fetch(EventFetchResult(error=error))
        assert stats.failed == 1 and stats.errors == [error]

    def test_processed_counts_accumulate(self) -> None:
        """Counts add up across events."""
        stats = MatchStats()
        for _ in range(2):
            stats.add_fetch(
                fetch_result(
                    make_match(),
                    total_links=3,
                    cache_hits=1,
                    tbd_count=1,
                    skipped_count=1,
                    failed_count=1,
                )
            )
        assert (stats.total, stats.cache_hits, stats.tbd_count) == (6, 2, 2)
        assert (stats.skipped_count, stats.failed) == (2, 2)


class TestSortAndGroup:
    """Tests for sort_matches and group_matches."""

    def test_no_sort_keeps_order(self) -> None:
        """No sort returns the input order."""
        matches = [make_match(team1="Z"), make_match(team1="A")]
        assert sort_matches(matches, None) == matches

    def test_sort_by_date(self) -> None:
        """Label-only dates still sort chronologically."""
        later, earlier = (
            make_match(date_label="Jan 15"),
            make_match(date_label="Jan 10"),
        )
        assert sort_matches([later, earlier], "date") == [earlier, later]

    def test_sort_by_team(self) -> None:
        """Team sort ignores case."""
        zeta, alpha = make_match(team1="Zeta"), make_match(team1="alpha")
        assert sort_matches([zeta, alpha], "team") == [alpha, zeta]

    def test_sort_prefers_timestamps(self) -> None:
        """Known instants sort across offsets; label times break ties."""
        early = make_match(starts_at=datetime(2026, 1, 2, 1, tzinfo=UTC))
        late = make_match(starts_at=datetime(2026, 1, 2, 4, tzinfo=UTC))
        assert sort_matches([late, early], "date") == [early, late]
        morning = make_match(time_label="2:00 AM")
        noon = make_match(time_label="11:00 AM")
        assert sort_matches([noon, morning], "date") == [morning, noon]

    def test_group_none(self) -> None:
        """No grouping puts everything under "all"."""
        matches = [make_match(), make_match()]
        assert group_matches(matches, None) == {"all": matches}

    def test_group_by_status(self) -> None:
        """Status groups follow first appearance."""
        live = make_match(status="live")
        upcoming = make_match(status="upcoming", score=None)
        done = make_match()
        grouped = group_matches([live, upcoming, done], "status")
        assert list(grouped) == ["live", "upcoming", "completed"]

    def test_group_by_local_date(self) -> None:
        """Date groups use the display timezone."""
        match = make_match(starts_at=datetime(2026, 1, 2, 1, tzinfo=UTC))
        grouped = group_matches([match], "date", ZoneInfo("America/Los_Angeles"))
        assert list(grouped) == ["January 01, 2026"]


class TestFilters:
    """Tests for team and favorite filters."""

    MATCHES = [
        make_match(team1="Sentinels", team2="Cloud9"),
        make_match(team1="LOUD", team2="NRG"),
    ]

    @pytest.mark.parametrize(
        ("team", "expected"),
        [(None, 2), ("sentinels", 1), ("Cloud", 1), ("NRG", 1), ("Fnatic", 0)],
    )
    def test_team_filter(self, team: str | None, expected: int) -> None:
        """Partial, case-insensitive names match either side."""
        assert len(filter_matches_by_team(self.MATCHES, team)) == expected

    def test_favorites_need_exact_names(self) -> None:
        """Favorites compare whole names, ignoring case."""
        assert filter_matches_by_favorites(self.MATCHES, ["loud"]) == [self.MATCHES[1]]
        assert filter_matches_by_favorites(self.MATCHES, ["LOU"]) == []


class TestMessages:
    """Tests for shared empty-result and error messages."""

    @pytest.mark.parametrize(
        ("kwargs", "cli_text", "interactive_text"),
        [
            ({"view_mode": "all", "team": "X"}, "--team", "Press f"),
            ({"view_mode": "upcoming"}, "removing --upcoming", "all matches mode"),
            ({"view_mode": "results"}, "Try --upcoming", "upcoming mode"),
            ({"view_mode": "all"}, "--list-regions", "Press r"),
        ],
    )
    def test_hints_match_mode(
        self, capsys, kwargs: dict, cli_text: str, interactive_text: str
    ) -> None:
        """Hints mention flags in CLI mode and keys in interactive mode."""
        print_empty_results(Formatter(), **kwargs)
        assert cli_text in capsys.readouterr().out
        print_empty_results(Formatter(), interactive=True, **kwargs)
        assert interactive_text in capsys.readouterr().out

    def test_today_and_favorites_messages(self, capsys) -> None:
        """Special filters explain themselves."""
        print_empty_results(Formatter(), view_mode="all", today_only=True)
        print_empty_results(Formatter(), view_mode="all", favorites_only=True)
        output = capsys.readouterr().out
        assert "known start times today" in output
        assert "saved favorite teams" in output

    def test_error_summary_truncates(self, capsys) -> None:
        """Only the first five errors are listed."""
        errors = [
            FetchError(f"https://vlr.gg/{i}", "http", "HTTP 500") for i in range(7)
        ]
        print_error_summary(Formatter(), errors)
        output = capsys.readouterr().out
        assert "Errors encountered (7)" in output
        assert "https://vlr.gg/4" in output and "https://vlr.gg/5" not in output
        assert "... and 2 more errors" in output


class TestRunCliMode:
    """Tests for the CLI flow."""

    def _run(self, opts: RunOptions, *results: EventFetchResult) -> int:
        with (
            patch("valorant_matches.cli.display.select_events", return_value=[EVENT]),
            patch("valorant_matches.cli.display.fetch_event_data", side_effect=results),
        ):
            return run_cli_mode(opts, Formatter(), Mock(is_stale=False))

    def test_success_prints_matches_and_footer(self, capsys) -> None:
        """A successful run lists matches and a footer, exit 0."""
        match = make_match(team1="Sentinels", team2="Cloud9")
        assert self._run(opts_for("-r", "am"), fetch_result(match, cache_hits=1)) == 0
        output = capsys.readouterr().out
        assert "Sentinels vs Cloud9" in output
        assert "Displayed: 1 match | Cache hits: 1" in output

    def test_failed_count_from_processing(self, capsys) -> None:
        """Failures are reported from processing even if filters hide matches."""
        result = fetch_result(make_match(), total_links=3, failed_count=2)
        assert self._run(opts_for("-r", "am", "--team", "Fnatic"), result) == 1
        output = capsys.readouterr().out
        assert "No matches found for team filter: Fnatic" in output
        assert "Failed: 2" in output

    def test_compact_grouped_output(self, capsys) -> None:
        """Compact and grouping options reach the formatter."""
        result = fetch_result(make_match(status="live"))
        assert (
            self._run(opts_for("-r", "am", "--compact", "--group-by", "status"), result)
            == 0
        )
        output = capsys.readouterr().out
        assert "LIVE MATCHES" in output
        assert "Team A 2-1 Team B | ● LIVE" in output
        assert "Live: 1" in output

    def test_no_events_is_error(self, capsys) -> None:
        """An unknown target exits 1 with guidance."""
        with patch("valorant_matches.cli.display.select_events", return_value=[]):
            code = run_cli_mode(opts_for("-r", "am"), Formatter(), Mock(is_stale=False))
        assert code == 1
        assert "No events found for: am" in capsys.readouterr().out

    def test_matches_deduplicated_across_events(self, capsys) -> None:
        """The same match from two events is shown once."""
        match = make_match()
        with (
            patch(
                "valorant_matches.cli.display.select_events",
                return_value=[
                    EVENT,
                    SimpleNamespace(**{**vars(EVENT), "event_id": "2"}),
                ],
            ),
            patch(
                "valorant_matches.cli.display.fetch_event_data",
                side_effect=[fetch_result(match), fetch_result(match)],
            ),
        ):
            run_cli_mode(opts_for("-r", "am"), Formatter(), Mock(is_stale=False))
        assert "Displayed: 1 match" in capsys.readouterr().out


class TestParseDateYearInference:
    """Tests for year inference on yearless dates."""

    def _patched_parse(self, date_str: str, fake_today: datetime) -> datetime:
        from valorant_matches.cli.display import _parse_date

        class FakeDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_today

        with patch("valorant_matches.cli.display.datetime", FakeDateTime):
            return _parse_date(date_str)

    def test_january_date_in_december_resolves_to_next_year(self) -> None:
        assert self._patched_parse("Jan 10", datetime(2025, 12, 30)).year == 2026

    def test_december_date_in_january_resolves_to_previous_year(self) -> None:
        assert self._patched_parse("Dec 28", datetime(2026, 1, 5)).year == 2025

    def test_same_season_date_keeps_current_year(self) -> None:
        assert self._patched_parse("Jun 15", datetime(2026, 6, 10)).year == 2026

    def test_unparseable_sorts_last(self) -> None:
        from valorant_matches.cli.display import _parse_date

        assert _parse_date("Unknown date") == datetime.max
