# Tests for non-interactive CLI display workflows.

import argparse
from unittest.mock import Mock, patch

from valorant_matches.cli.display import (
    MatchStats,
    filter_matches_by_team,
    get_display_options,
    get_view_mode,
    group_matches,
    run_cli_mode,
    sort_matches,
)
from valorant_matches.scraping.matches import Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult


def make_match(
    date: str = "Jan 15",
    time: str = "12:00",
    team1: str = "Team A",
    team2: str = "Team B",
    score: str = "2-1",
    is_live: bool = False,
    is_upcoming: bool = False,
    url: str = "https://vlr.gg/123",
) -> Match:
    """Helper to create Match objects for testing."""
    return Match(
        date=date,
        time=time,
        team1=team1,
        team2=team2,
        score=score,
        is_live=is_live,
        is_upcoming=is_upcoming,
        url=url,
    )


class TestMatchStats:
    """Tests for MatchStats dataclass."""

    def test_increment_cache_hit(self):
        """Test incrementing cache hit counter."""
        stats = MatchStats()
        stats.increment_cache_hit()
        assert stats.cache_hits == 1
        stats.increment_cache_hit()
        assert stats.cache_hits == 2

    def test_increment_failed(self):
        """Test incrementing failed counter."""
        stats = MatchStats()
        stats.increment_failed()
        assert stats.failed == 1

    def test_count_match_live(self):
        """Test counting live match."""
        stats = MatchStats()
        match = make_match(is_live=True)
        stats.count_match(match)
        assert stats.live_count == 1
        assert stats.upcoming_count == 0
        assert stats.completed_count == 0

    def test_count_match_upcoming(self):
        """Test counting upcoming match."""
        stats = MatchStats()
        match = make_match(is_upcoming=True)
        stats.count_match(match)
        assert stats.live_count == 0
        assert stats.upcoming_count == 1
        assert stats.completed_count == 0

    def test_count_match_completed(self):
        """Test counting completed match."""
        stats = MatchStats()
        match = make_match()
        stats.count_match(match)
        assert stats.live_count == 0
        assert stats.upcoming_count == 0
        assert stats.completed_count == 1


class TestGetViewMode:
    """Tests for get_view_mode function."""

    def test_view_mode_upcoming(self):
        """Test view mode is upcoming when flag is set."""
        args = argparse.Namespace(upcoming=True, results=False)
        assert get_view_mode(args) == "upcoming"

    def test_view_mode_results(self):
        """Test view mode is results when flag is set."""
        args = argparse.Namespace(upcoming=False, results=True)
        assert get_view_mode(args) == "results"

    def test_view_mode_all(self):
        """Test view mode is all when no flags are set."""
        args = argparse.Namespace(upcoming=False, results=False)
        assert get_view_mode(args) == "all"


class TestGetDisplayOptions:
    """Tests for get_display_options function."""

    def test_display_options_default(self):
        """Test display options with no flags set."""
        args = argparse.Namespace()
        options = get_display_options(args)
        assert options.compact is False
        assert options.group_by is None
        assert options.sort_by is None

    def test_display_options_compact(self):
        """Test display options with compact flag."""
        args = argparse.Namespace(compact=True, group_by=None, sort=None)
        options = get_display_options(args)
        assert options.compact is True

    def test_display_options_group_by(self):
        """Test display options with group_by flag."""
        args = argparse.Namespace(compact=False, group_by="status", sort=None)
        options = get_display_options(args)
        assert options.group_by == "status"

    def test_display_options_sort(self):
        """Test display options with sort flag."""
        args = argparse.Namespace(compact=False, group_by=None, sort="date")
        options = get_display_options(args)
        assert options.sort_by == "date"


class TestSortMatches:
    """Tests for sort_matches function."""

    def test_sort_matches_no_sort(self):
        """Test that no sorting returns original order."""
        results = [
            ({"href": "/1"}, make_match(date="Jan 15", team1="Team Z")),
            ({"href": "/2"}, make_match(date="Jan 10", team1="Team A")),
        ]
        sorted_results = sort_matches(results, None)
        assert sorted_results == results

    def test_sort_matches_by_date(self):
        """Test sorting by date."""
        results = [
            ({"href": "/1"}, make_match(date="Jan 15", team1="Team A")),
            ({"href": "/2"}, make_match(date="Jan 10", team1="Team C")),
        ]
        sorted_results = sort_matches(results, "date")
        assert sorted_results[0][1].date == "Jan 10"
        assert sorted_results[1][1].date == "Jan 15"

    def test_sort_matches_by_team(self):
        """Test sorting by team name."""
        results = [
            ({"href": "/1"}, make_match(team1="Zeta", team2="Alpha")),
            ({"href": "/2"}, make_match(team1="Alpha", team2="Beta")),
        ]
        sorted_results = sort_matches(results, "team")
        # Alpha comes before Zeta
        assert sorted_results[0][1].team1 == "Alpha"


class TestGroupMatches:
    """Tests for group_matches function."""

    def test_group_matches_no_group(self):
        """Test that no grouping returns all matches under 'all'."""
        results = [
            ({"href": "/1"}, make_match()),
            ({"href": "/2"}, make_match()),
        ]
        grouped = group_matches(results, None)
        assert "all" in grouped
        assert len(grouped["all"]) == 2

    def test_group_matches_by_status(self):
        """Test grouping by match status."""
        results = [
            ({"href": "/1"}, make_match(is_live=True)),
            ({"href": "/2"}, make_match(is_upcoming=True)),
            ({"href": "/3"}, make_match()),
        ]
        grouped = group_matches(results, "status")
        assert "live" in grouped
        assert "upcoming" in grouped
        assert "completed" in grouped
        assert len(grouped["live"]) == 1
        assert len(grouped["upcoming"]) == 1
        assert len(grouped["completed"]) == 1

    def test_group_matches_by_date(self):
        """Test grouping by date."""
        results = [
            ({"href": "/1"}, make_match(date="Jan 15")),
            ({"href": "/2"}, make_match(date="Jan 15")),
            ({"href": "/3"}, make_match(date="Jan 16")),
        ]
        grouped = group_matches(results, "date")
        assert "Jan 15" in grouped
        assert "Jan 16" in grouped
        assert len(grouped["Jan 15"]) == 2
        assert len(grouped["Jan 16"]) == 1


class TestFilterMatchesByTeam:
    """Tests for filter_matches_by_team function."""

    def test_filter_no_team(self):
        """Test that no filter returns all matches."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
        ]
        filtered = filter_matches_by_team(results, None)
        assert len(filtered) == 2

    def test_filter_by_team_name(self):
        """Test filtering by exact team name."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
            ({"href": "/3"}, make_match(team1="Sentinels", team2="LOUD")),
        ]
        filtered = filter_matches_by_team(results, "Sentinels")
        assert len(filtered) == 2

    def test_filter_case_insensitive(self):
        """Test that filter is case insensitive."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
        ]
        filtered = filter_matches_by_team(results, "sentinels")
        assert len(filtered) == 1
        assert filtered[0][1].team1 == "Sentinels"

    def test_filter_partial_match(self):
        """Test filtering with partial team name."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
        ]
        filtered = filter_matches_by_team(results, "Cloud")
        assert len(filtered) == 1
        assert filtered[0][1].team2 == "Cloud9"

    def test_filter_matches_opponent(self):
        """Test that filter also matches opponent team."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
        ]
        filtered = filter_matches_by_team(results, "Cloud9")
        assert len(filtered) == 1

    def test_filter_no_matches(self):
        """Test filter with no matching team."""
        results = [
            ({"href": "/1"}, make_match(team1="Sentinels", team2="Cloud9")),
            ({"href": "/2"}, make_match(team1="LOUD", team2="NRG")),
        ]
        filtered = filter_matches_by_team(results, "Fnatic")
        assert len(filtered) == 0


def _make_cli_args(**overrides) -> argparse.Namespace:
    """Build a CLI args namespace with sensible defaults."""
    values = {
        "region": "americas",
        "no_cache": False,
        "upcoming": False,
        "results": False,
        "refresh": False,
        "team": None,
        "export": None,
        "compact": False,
        "group_by": None,
        "sort": None,
        "interactive": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _make_cli_formatter() -> Mock:
    formatter = Mock()
    formatter.info.side_effect = lambda text, bold=False: text
    formatter.warning.side_effect = lambda text, bold=False: text
    formatter.error.side_effect = lambda text, bold=False: text
    formatter.muted.side_effect = lambda text, bold=False: text
    formatter.print_stats_footer = Mock()
    return formatter


def _make_fetch_result(**overrides) -> EventFetchResult:
    processed = ProcessedMatches(
        results=[
            (
                {"href": "/1/match"},
                make_match(team1="Sentinels", team2="Cloud9"),
            )
        ],
        tbd_count=0,
        cache_hits=1,
    )
    defaults = {"total_links": 1, "processed": processed}
    defaults.update(overrides)
    return EventFetchResult(**defaults)


class TestRunCliMode:
    """Tests for CLI mode flow."""

    def test_cli_mode_exits_after_results_by_default(self):
        """CLI mode should not enter interactive mode unless requested."""
        formatter = _make_cli_formatter()
        event = Mock(name="VCT Americas", status="ongoing", url="https://vlr.gg/e")
        event.slug = "vct-americas"
        args = _make_cli_args()
        run_interactive = Mock(return_value=0)

        with (
            patch(
                "valorant_matches.cli.display.fetch_event_data",
                return_value=_make_fetch_result(),
            ),
            patch(
                "valorant_matches.cli.display.get_event_for_region", return_value=event
            ),
        ):
            exit_code = run_cli_mode(args, formatter, Mock(), run_interactive)

        assert exit_code == 0
        run_interactive.assert_not_called()
        formatter.print_stats_footer.assert_called_once()

    def test_cli_mode_enters_interactive_when_requested(self):
        """--interactive should opt into post-results interactive mode."""
        formatter = _make_cli_formatter()
        event = Mock(name="VCT Americas", status="ongoing", url="https://vlr.gg/e")
        event.slug = "vct-americas"
        args = _make_cli_args(interactive=True)
        run_interactive = Mock(return_value=7)

        with (
            patch(
                "valorant_matches.cli.display.fetch_event_data",
                return_value=_make_fetch_result(),
            ),
            patch(
                "valorant_matches.cli.display.get_event_for_region", return_value=event
            ),
        ):
            exit_code = run_cli_mode(args, formatter, Mock(), run_interactive)

        assert exit_code == 7
        run_interactive.assert_called_once()

    def test_cli_mode_reports_failed_count_from_processing(self):
        """Failed stat should come from processing, not be inferred from filters."""
        formatter = _make_cli_formatter()
        event = Mock(name="VCT Americas", status="ongoing", url="https://vlr.gg/e")
        event.slug = "vct-americas"
        # Team filter removes the only result; failed must stay at the real value.
        args = _make_cli_args(team="Fnatic")

        fetch_result = _make_fetch_result(total_links=3)
        fetch_result.processed.failed_count = 2

        with (
            patch(
                "valorant_matches.cli.display.fetch_event_data",
                return_value=fetch_result,
            ),
            patch(
                "valorant_matches.cli.display.get_event_for_region", return_value=event
            ),
        ):
            exit_code = run_cli_mode(args, formatter, Mock(), Mock())

        assert exit_code == 1
        footer_kwargs = formatter.print_stats_footer.call_args.kwargs
        assert footer_kwargs["failed"] == 2


class TestParseDateYearInference:
    """Tests for year inference on yearless dates."""

    def _patched_parse(self, date_str: str, fake_today):
        from datetime import datetime as real_datetime

        from valorant_matches.cli.display import _parse_date

        class FakeDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_today

        with patch("valorant_matches.cli.display.datetime", FakeDateTime):
            return _parse_date(date_str)

    def test_january_date_in_december_resolves_to_next_year(self):
        from datetime import datetime

        parsed = self._patched_parse("Jan 10", datetime(2025, 12, 30))
        assert parsed.year == 2026

    def test_december_date_in_january_resolves_to_previous_year(self):
        from datetime import datetime

        parsed = self._patched_parse("Dec 28", datetime(2026, 1, 5))
        assert parsed.year == 2025

    def test_same_season_date_keeps_current_year(self):
        from datetime import datetime

        parsed = self._patched_parse("Jun 15", datetime(2026, 6, 10))
        assert parsed.year == 2026
