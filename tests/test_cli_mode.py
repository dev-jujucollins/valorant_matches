# Tests for cli_mode.py

import argparse

from cli_mode import (
    DisplayOptions,
    MatchStats,
    filter_matches_by_team,
    get_display_options,
    get_match_status,
    get_view_mode,
    group_matches,
    sort_matches,
)
from match_extractor import Match


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

    def test_default_values(self):
        """Test default values are initialized to zero."""
        stats = MatchStats()
        assert stats.total == 0
        assert stats.displayed == 0
        assert stats.cache_hits == 0
        assert stats.failed == 0
        assert stats.tbd_count == 0
        assert stats.live_count == 0
        assert stats.upcoming_count == 0
        assert stats.completed_count == 0
        assert stats.fetch_time == 0.0

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


class TestDisplayOptions:
    """Tests for DisplayOptions dataclass."""

    def test_default_values(self):
        """Test default display options."""
        options = DisplayOptions()
        assert options.compact is False
        assert options.group_by is None
        assert options.sort_by is None

    def test_custom_values(self):
        """Test custom display options."""
        options = DisplayOptions(compact=True, group_by="status", sort_by="date")
        assert options.compact is True
        assert options.group_by == "status"
        assert options.sort_by == "date"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_match_status_live(self):
        """Test getting live match status."""
        match = make_match(is_live=True)
        assert get_match_status(match) == "live"

    def test_get_match_status_upcoming(self):
        """Test getting upcoming match status."""
        match = make_match(is_upcoming=True)
        assert get_match_status(match) == "upcoming"

    def test_get_match_status_completed(self):
        """Test getting completed match status."""
        match = make_match()
        assert get_match_status(match) == "completed"


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
