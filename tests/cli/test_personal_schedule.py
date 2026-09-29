"""End-to-end CLI behavior for event choice and personal schedules."""

import argparse
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from valorant_matches.cli.app import apply_profile_defaults, parse_args
from valorant_matches.cli.display import run_cli_mode
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.matches import Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult


def _args(*flags: str) -> argparse.Namespace:
    """Parse production arguments without using saved user state."""
    with patch("sys.argv", ["valorant-matches", *flags]):
        args = parse_args()
    args.favorite_teams = ["Sentinels"]
    return args


def _event(event_id: str, status: str = "ongoing") -> SimpleNamespace:
    """Build a discovered event for mocked event selection."""
    return SimpleNamespace(
        event_id=event_id,
        name=f"Event {event_id}",
        status=status,
        slug=f"event-{event_id}",
        url=f"https://vlr.gg/event/matches/{event_id}/event-{event_id}/",
    )


def _result(
    team: str, url: str, start: str, upcoming: bool = False
) -> EventFetchResult:
    """Build one fetched match with a source timestamp."""
    match = Match(
        date="Jan 1",
        time="12:00",
        team1=team,
        team2="Opponent",
        score="Match has not started yet." if upcoming else "2-1",
        is_live=False,
        is_upcoming=upcoming,
        url=url,
        start_time=start,
    )
    return EventFetchResult(total_links=1, processed=ProcessedMatches([({}, match)]))


def test_favorites_aggregate_regions(capsys: pytest.CaptureFixture[str]) -> None:
    """Personal schedule uses favorite matches from more than one region."""
    args = _args("--favorites")
    discovery = Mock(is_stale=False)
    discovery.list_regions.return_value = ["americas", "emea"]
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            side_effect=[_event("1"), _event("2")],
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            side_effect=[
                _result("Other", "https://vlr.gg/1", "2026-01-01T00:00:00+00:00"),
                _result("Sentinels", "https://vlr.gg/2", "2026-01-02T00:00:00+00:00"),
            ],
        ) as fetch,
    ):
        assert run_cli_mode(args, Formatter(color=False), discovery, Mock()) == 0
    output = capsys.readouterr().out
    assert "★ Sentinels" in output
    assert "Other vs" not in output
    assert "Displayed: 1 match" in output
    assert fetch.call_count == 2


@pytest.mark.parametrize("sort_none", [False, True])
def test_upcoming_combines_events_in_match_time_order(
    capsys: pytest.CaptureFixture[str], sort_none: bool
) -> None:
    """Ongoing tournament fixtures can precede a future tournament."""
    flags = ("--sort", "none") if sort_none else ()
    args = _args("-r", "americas", "--upcoming", *flags)
    if sort_none:
        apply_profile_defaults(args, UserProfile(default_sort="team"))
    discovery = Mock(is_stale=False)
    with (
        patch(
            "valorant_matches.cli.display.get_events_for_region",
            return_value=[_event("2", "upcoming"), _event("1", "ongoing")],
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            side_effect=[
                _result(
                    "Future", "https://vlr.gg/2", "2026-01-05T00:00:00+00:00", True
                ),
                _result("Soon", "https://vlr.gg/1", "2026-01-02T00:00:00+00:00", True),
            ],
        ),
    ):
        assert run_cli_mode(args, Formatter(color=False), discovery, Mock()) == 0
    output = capsys.readouterr().out
    if sort_none:
        assert output.index("Future vs") < output.index("Soon vs")
    else:
        assert output.index("Soon vs") < output.index("Future vs")


def test_event_id_override(capsys: pytest.CaptureFixture[str]) -> None:
    """An explicit discovered event ID bypasses regional ranking."""
    args = _args("--event", "42")
    discovery = Mock(is_stale=False)
    discovery.get_event_by_id.return_value = _event("42")
    with patch(
        "valorant_matches.cli.display.fetch_event_data",
        return_value=_result(
            "Sentinels", "https://vlr.gg/42", "2026-01-02T00:00:00+00:00"
        ),
    ):
        assert run_cli_mode(args, Formatter(color=False), discovery, Mock()) == 0
    discovery.get_event_by_id.assert_called_once_with("42", force_refresh=False)
    assert "Sentinels" in capsys.readouterr().out


def test_completed_only_region_has_empty_upcoming_schedule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A valid season with no future events is an empty result, not an error."""
    args = _args("-r", "americas", "--upcoming")
    discovery = Mock(is_stale=False)
    discovery.discover_events.return_value = [_event("1", "completed")]
    with patch("valorant_matches.cli.display.get_events_for_region", return_value=[]):
        assert run_cli_mode(args, Formatter(color=False), discovery, Mock()) == 0
    assert "No upcoming VCT events" in capsys.readouterr().out


def test_saved_discovery_reports_its_age(capsys: pytest.CaptureFixture[str]) -> None:
    """Offline results identify when event discovery last succeeded."""
    args = _args("-r", "americas")
    discovery = Mock(is_stale=True, last_updated=1_700_000_000.0)
    with (
        patch(
            "valorant_matches.cli.display.get_event_for_region",
            return_value=_event("1"),
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            return_value=_result(
                "Sentinels", "https://vlr.gg/1", "2026-01-02T00:00:00+00:00"
            ),
        ),
    ):
        assert run_cli_mode(args, Formatter(color=False), discovery, Mock()) == 0
    assert "Using saved event list from" in capsys.readouterr().out
