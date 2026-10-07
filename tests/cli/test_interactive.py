"""Tests for interactive CLI workflows."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from valorant_matches.cli.interactive import (
    InteractiveState,
    _suggest_team_names,
    run_interactive_mode,
)
from valorant_matches.cli.options import RunOptions
from valorant_matches.output.formatter import Formatter
from valorant_matches.scraping.matches import FetchError, Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult

FETCH = "valorant_matches.cli.display.fetch_event_data"
EVENT = SimpleNamespace(
    event_id="1", name="Test event", status="ongoing", url="https://vlr.gg/e", slug="t"
)


def make_match(team1: str, team2: str, url: str = "https://vlr.gg/1") -> Match:
    """Create a minimal upcoming match."""
    return Match(
        url=url,
        team1=team1,
        team2=team2,
        status="upcoming",
        starts_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
    )


def fetched(*matches: Match) -> EventFetchResult:
    """A successful fetch of the given matches."""
    return EventFetchResult(
        total_links=len(matches), processed=ProcessedMatches(list(matches))
    )


def discovery_with(*events: SimpleNamespace) -> Mock:
    """A discovery stub that always returns the given events."""
    discovery = Mock(is_stale=False)
    discovery.discover_events.return_value = list(events or [EVENT])
    return discovery


def run_with_inputs(
    inputs: list[str],
    result: EventFetchResult | None = None,
    opts: RunOptions | None = None,
    discovery: Mock | None = None,
) -> tuple[int, Mock]:
    """Drive the menu with scripted input and a canned fetch result."""
    discovery = discovery or discovery_with()
    with (
        patch("builtins.input", side_effect=inputs),
        patch(FETCH, return_value=result or fetched()) as fetch,
    ):
        code = run_interactive_mode(Formatter(), discovery, opts)
    return code, fetch


def test_suggest_team_names_returns_close_match() -> None:
    """Fuzzy search should suggest close team names."""
    matches = [make_match("Sentinels", "Cloud9"), make_match("Fnatic", "Heretics")]
    assert "Sentinels" in _suggest_team_names(matches, "Sentinal")


def test_active_filters() -> None:
    """Active filters are summarized for the menu."""
    state = InteractiveState(team="x", sort_by="date", group_by="status")
    state.favorites_only = True
    assert state.active_filters() == [
        "team=x",
        "sort=date",
        "group=status",
        "favorites",
    ]


def test_fetch_error_is_not_empty_schedule(capsys) -> None:
    """Failed requests give a retryable error, not an empty schedule."""
    error = EventFetchResult(error=FetchError("https://vlr.gg/e", "http", "HTTP 503"))
    code, _ = run_with_inputs(["1", "1", "q"], error)
    assert code == 0
    output = capsys.readouterr().out
    assert "Fetch failed: HTTP 503" in output
    assert "No matches found" not in output


def test_eof_exits_without_retrying(capsys) -> None:
    """Closed stdin exits once rather than looping over rediscovery."""
    discovery = discovery_with()
    with patch("builtins.input", side_effect=EOFError):
        assert run_interactive_mode(Formatter(), discovery) == 0
    discovery.discover_events.assert_called_once()
    assert "Input closed. Exiting." in capsys.readouterr().out


def test_keyboard_interrupt_exits(capsys) -> None:
    """Ctrl+C leaves the menu cleanly."""
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        assert run_interactive_mode(Formatter(), discovery_with()) == 0
    assert "interrupted" in capsys.readouterr().out


def test_no_events_returns_one(capsys) -> None:
    """Without events there is nothing to browse."""
    discovery = Mock(is_stale=False)
    discovery.discover_events.return_value = []
    assert run_interactive_mode(Formatter(), discovery) == 1


def test_uses_options_for_display_and_cache(capsys) -> None:
    """Menu fetch and rendering use the resolved run options."""
    opts = RunOptions(
        view_mode="upcoming",
        compact=True,
        favorite_teams=["Sentinels"],
        cache_enabled=False,
        timezone="America/Los_Angeles",
    )
    code, fetch = run_with_inputs(
        ["1", "", "q"], fetched(make_match("Sentinels", "Cloud9")), opts
    )
    assert code == 0
    fetch.assert_called_once_with(
        EVENT.url, EVENT.slug, view_mode="upcoming", cache_enabled=False
    )
    output = capsys.readouterr().out
    assert "January 01, 2026 | ★ Sentinels vs Cloud9" in output


def test_team_filter_with_suggestions(capsys) -> None:
    """The f shortcut filters and suggests names from loaded matches."""
    result = fetched(make_match("Sentinels", "Cloud9"))
    run_with_inputs(["1", "1", "f", "Sentinal", "1", "1", "q"], result)
    output = capsys.readouterr().out
    assert "Filter set: Sentinal" in output
    assert "Did you mean: Sentinels" in output
    assert "No matches found for team filter: Sentinal" in output
    assert "Try one of: Sentinels" in output
    assert "Active: team=Sentinal" in output


def test_clear_team_filter(capsys) -> None:
    """An empty team name clears the filter."""
    run_with_inputs(["f", "", "q"])
    assert "Filter cleared" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("key", "choice", "active"),
    [("s", "2", "sort=team"), ("g", "2", "group=status"), ("s", "9", None)],
)
def test_sort_and_group_menus(
    capsys, key: str, choice: str, active: str | None
) -> None:
    """Sort and group menus set state; unknown choices clear it."""
    run_with_inputs([key, choice, "q"])
    output = capsys.readouterr().out
    if active:
        assert f"Active: {active}" in output
    else:
        assert "Active:" not in output


def test_group_by_status_renders_headers(capsys) -> None:
    """Grouping chosen in the menu applies to the next listing."""
    run_with_inputs(["g", "2", "1", "1", "q"], fetched(make_match("A", "B")))
    assert "UPCOMING MATCHES" in capsys.readouterr().out


def test_favorite_toggle(capsys) -> None:
    """v needs saved favorites and then toggles the filter."""
    run_with_inputs(["v", "q"])
    assert "No favorite teams saved." in capsys.readouterr().out

    opts = RunOptions(favorite_teams=["Sentinels"])
    run_with_inputs(["v", "v", "q"], opts=opts)
    output = capsys.readouterr().out
    assert "Favorite filter on" in output and "Favorite filter off" in output


def test_help_refresh_and_invalid_choice(capsys) -> None:
    """h shows help, r forces rediscovery, junk input is rejected."""
    discovery = discovery_with()
    run_with_inputs(["h", "r", "99", "x", "q"], discovery=discovery)
    output = capsys.readouterr().out
    assert "Keyboard Shortcuts:" in output
    assert "Refreshing events..." in output
    assert output.count("Invalid choice") == 2
    refreshes = [
        call.kwargs["force_refresh"]
        for call in discovery.discover_events.call_args_list
    ]
    assert refreshes == [False, False, True, False, False]


def test_back_from_view_menu_skips_fetch() -> None:
    """Choosing Back returns to events without network work."""
    _, fetch = run_with_inputs(["1", "4", "q"])
    fetch.assert_not_called()


def test_partial_failure_still_shows_matches(capsys) -> None:
    """Some failed matches warn but still show the rest."""
    result = fetched(make_match("A", "B"))
    result.processed.failed_count = 1
    result.processed.errors.append(FetchError("https://vlr.gg/2", "parse", "bad"))
    run_with_inputs(["1", "1", "q"], result)
    output = capsys.readouterr().out
    assert "Incomplete results: 1 matches failed." in output
    assert "A vs B" in output


def test_empty_event_page(capsys) -> None:
    """An event without posted matches says so."""
    run_with_inputs(["1", "1", "q"], EventFetchResult())
    assert "No matches were found for this event page yet." in capsys.readouterr().out


def test_unexpected_error_keeps_menu_alive(capsys) -> None:
    """An unexpected failure is reported and the loop continues."""
    discovery = discovery_with()
    discovery.discover_events.side_effect = [RuntimeError("boom"), [EVENT]]
    with patch("builtins.input", side_effect=["q"]):
        assert run_interactive_mode(Formatter(), discovery) == 0
    output = capsys.readouterr().out
    assert "An unexpected error occurred" in output
    assert "Thank you for using" in output
