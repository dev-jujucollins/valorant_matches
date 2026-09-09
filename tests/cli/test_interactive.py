"""Tests for interactive CLI workflows."""

from valorant_matches.cli.interactive import _suggest_team_names
from valorant_matches.scraping.matches import Match


def make_match(team1: str, team2: str) -> Match:
    """Create a minimal Match object for testing."""
    return Match(
        date="Jan 1",
        time="12:00",
        team1=team1,
        team2=team2,
        score="0-0",
        is_live=False,
        url="https://vlr.gg/1",
        is_upcoming=True,
    )


class TestInteractiveSuggestions:
    """Tests for fuzzy team suggestions in interactive mode."""

    def test_suggest_team_names_returns_close_match(self):
        """Fuzzy search should suggest close team names."""
        results = [
            ({"href": "/1"}, make_match("Sentinels", "Cloud9")),
            ({"href": "/2"}, make_match("Fnatic", "Team Heretics")),
        ]

        suggestions = _suggest_team_names(results, "Sentinal")

        assert "Sentinels" in suggestions


def test_interactive_fetch_error_is_not_empty_schedule(capsys) -> None:
    """Failed requests should give a retryable error, not an empty schedule."""
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from valorant_matches.cli.interactive import run_interactive_mode
    from valorant_matches.output.formatter import Formatter
    from valorant_matches.scraping.matches import FetchError
    from valorant_matches.scraping.runner import EventFetchResult

    discovery = Mock()
    discovery.discover_events.return_value = [
        SimpleNamespace(
            name="Test event", status="ongoing", url="https://vlr.gg/event", slug="test"
        )
    ]
    with (
        patch("builtins.input", side_effect=["1", "1", "q"]),
        patch(
            "valorant_matches.cli.interactive.fetch_event_data",
            return_value=EventFetchResult(error=FetchError("url", "http", "HTTP 503")),
        ),
    ):
        assert run_interactive_mode(Formatter(), discovery) == 0
    output = capsys.readouterr().out
    assert "Fetch failed: HTTP 503" in output
    assert "No matches found" not in output
