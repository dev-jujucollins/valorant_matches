"""End-to-end CLI behavior for event choice and personal schedules."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import run_cli_mode
from valorant_matches.cli.options import RunOptions, build_run_options
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.matches import Match, ProcessedMatches
from valorant_matches.scraping.runner import EventFetchResult

SELECTION = "valorant_matches.scraping.event_selection"


def _opts(*flags: str, profile: UserProfile | None = None) -> RunOptions:
    """Parse production arguments with Sentinels as a saved favorite."""
    profile = profile or UserProfile(favorite_teams=["Sentinels"])
    return build_run_options(parse_args(list(flags)), profile)


def _event(event_id: str, status: str = "ongoing") -> SimpleNamespace:
    """Build a discovered event for mocked event selection."""
    return SimpleNamespace(
        event_id=event_id,
        name=f"Event {event_id}",
        status=status,
        slug=f"event-{event_id}",
        url=f"https://vlr.gg/event/matches/{event_id}/event-{event_id}/",
    )


def _result(team: str, url: str, day: int, upcoming: bool = False) -> EventFetchResult:
    """Build one fetched match with a source timestamp."""
    match = Match(
        url=url,
        team1=team,
        team2="Opponent",
        status="upcoming" if upcoming else "completed",
        score=None if upcoming else "2-1",
        starts_at=datetime(2026, 1, day, tzinfo=UTC),
    )
    return EventFetchResult(total_links=1, processed=ProcessedMatches([match]))


def test_favorites_aggregate_regions(capsys: pytest.CaptureFixture[str]) -> None:
    """Personal schedule uses favorite matches from more than one region."""
    discovery = Mock(is_stale=False)
    discovery.list_regions.return_value = ["americas", "emea"]
    with (
        patch(
            f"{SELECTION}.get_event_for_region", side_effect=[_event("1"), _event("2")]
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            side_effect=[
                _result("Other", "https://vlr.gg/1", 1),
                _result("Sentinels", "https://vlr.gg/2", 2),
            ],
        ) as fetch,
    ):
        assert run_cli_mode(_opts("--favorites"), Formatter(), discovery) == 0
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
    profile = UserProfile(default_sort="team") if sort_none else None
    opts = _opts("-r", "americas", "--upcoming", *flags, profile=profile)
    with (
        patch(
            f"{SELECTION}.get_events_for_region",
            return_value=[_event("2", "upcoming"), _event("1", "ongoing")],
        ),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            side_effect=[
                _result("Future", "https://vlr.gg/2", 5, True),
                _result("Soon", "https://vlr.gg/1", 2, True),
            ],
        ),
    ):
        assert run_cli_mode(opts, Formatter(), Mock(is_stale=False)) == 0
    output = capsys.readouterr().out
    if sort_none:
        assert output.index("Future vs") < output.index("Soon vs")
    else:
        assert output.index("Soon vs") < output.index("Future vs")


def test_event_id_override(capsys: pytest.CaptureFixture[str]) -> None:
    """An explicit discovered event ID bypasses regional ranking."""
    discovery = Mock(is_stale=False)
    discovery.get_event_by_id.return_value = _event("42")
    with patch(
        "valorant_matches.cli.display.fetch_event_data",
        return_value=_result("Sentinels", "https://vlr.gg/42", 2),
    ):
        assert run_cli_mode(_opts("--event", "42"), Formatter(), discovery) == 0
    discovery.get_event_by_id.assert_called_once_with("42", force_refresh=False)
    assert "Sentinels" in capsys.readouterr().out


def test_completed_only_region_has_empty_upcoming_schedule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A valid season with no future events is an empty result, not an error."""
    discovery = Mock(is_stale=False)
    discovery.discover_events.return_value = [_event("1", "completed")]
    with patch(f"{SELECTION}.get_events_for_region", return_value=[]):
        opts = _opts("-r", "americas", "--upcoming")
        assert run_cli_mode(opts, Formatter(), discovery) == 0
    assert "No upcoming VCT events" in capsys.readouterr().out


def test_saved_discovery_reports_its_age(capsys: pytest.CaptureFixture[str]) -> None:
    """Offline results identify when event discovery last succeeded."""
    discovery = Mock(is_stale=True, last_updated=1_700_000_000.0)
    with (
        patch(f"{SELECTION}.get_event_for_region", return_value=_event("1")),
        patch(
            "valorant_matches.cli.display.fetch_event_data",
            return_value=_result("Sentinels", "https://vlr.gg/1", 2),
        ),
    ):
        assert run_cli_mode(_opts("-r", "americas"), Formatter(), discovery) == 0
    assert "Using saved event list from" in capsys.readouterr().out
