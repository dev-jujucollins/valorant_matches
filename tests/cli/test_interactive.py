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


def test_interactive_eof_exits_without_retrying(capsys) -> None:
    """Closed stdin should exit once rather than loop over rediscovery."""
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from valorant_matches.cli.interactive import run_interactive_mode
    from valorant_matches.output.formatter import Formatter

    discovery = Mock()
    discovery.discover_events.return_value = [
        SimpleNamespace(name="Test", status="ongoing")
    ]
    with patch("builtins.input", side_effect=EOFError):
        assert run_interactive_mode(Formatter(color=False), discovery) == 0
    discovery.discover_events.assert_called_once()
    assert "Input closed. Exiting." in capsys.readouterr().out


def test_interactive_uses_saved_display_and_cache_settings(capsys) -> None:
    """Menu fetch and rendering use same preparation as CLI mode."""
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from valorant_matches.cli.interactive import run_interactive_mode
    from valorant_matches.output.formatter import Formatter
    from valorant_matches.profile import UserProfile
    from valorant_matches.scraping.matches import ProcessedMatches
    from valorant_matches.scraping.runner import EventFetchResult

    event = SimpleNamespace(
        name="Test", status="ongoing", url="https://vlr.gg/event", slug="test"
    )
    discovery = Mock()
    discovery.discover_events.return_value = [event]
    match = make_match("Sentinels", "Cloud9")
    match.start_time = "2026-01-02T01:00:00+00:00"
    fetched = EventFetchResult(total_links=1, processed=ProcessedMatches([({}, match)]))
    profile = UserProfile(
        default_view_mode="upcoming",
        compact_mode=True,
        favorite_teams=["Sentinels"],
        cache_enabled=False,
    )
    with (
        patch("builtins.input", side_effect=["1", "", "q"]),
        patch(
            "valorant_matches.cli.interactive.fetch_event_data", return_value=fetched
        ) as fetch,
    ):
        assert (
            run_interactive_mode(
                Formatter(color=False),
                discovery,
                profile=profile,
                cache_enabled=False,
                timezone="America/Los_Angeles",
            )
            == 0
        )
    fetch.assert_called_once_with(
        event.url, event.slug, "upcoming", cache_enabled=False
    )
    output = capsys.readouterr().out
    assert "January 01, 2026" in output
    assert "★ Sentinels" in output
