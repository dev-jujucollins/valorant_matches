"""Regression tests spanning HTTP responses, saved markup, and CLI output."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import filter_today, run_cli_mode
from valorant_matches.cli.options import build_run_options
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.client import AsyncValorantClient, process_matches_async
from valorant_matches.scraping.matches import (
    Match,
    extract_start_time,
    find_event_match_urls,
)
from valorant_matches.scraping.runner import _fetch_event_data

FIXTURES = Path(__file__).parents[1] / "fixtures" / "vlr"
CHAMPIONS_URL = "https://vlr.gg/753444/champions"


def response_for(name: str, status: int = 200) -> Mock:
    """Wrap a fixture as an aiohttp response context manager."""
    response = Mock(status=status, headers={})
    response.text = AsyncMock(return_value=(FIXTURES / f"{name}.html").read_text())
    return Mock(__aenter__=AsyncMock(return_value=response), __aexit__=AsyncMock())


def fixture_get(url: str) -> Mock:
    """Resolve synthetic URLs into saved fixtures."""
    name = url.rsplit("-", 1)[-1] if "/event/" not in url else "event"
    return response_for(name)


def no_rate_limit():
    """Skip request spacing in fixture runs."""
    return patch(
        "valorant_matches.scraping.http.AsyncRateLimiter.acquire",
        new_callable=AsyncMock,
    )


@pytest.mark.parametrize(
    ("mode", "statuses", "skipped"),
    [
        ("all", ["completed", "live", "upcoming"], 0),
        ("results", ["completed"], 2),
        ("upcoming", ["upcoming"], 2),
    ],
)
async def test_fixture_pipeline(mode: str, statuses: list[str], skipped: int) -> None:
    """Real parsing keeps errors, TBD, and intentional filters distinct."""
    with patch("aiohttp.ClientSession.get", side_effect=fixture_get), no_rate_limit():
        result = await _fetch_event_data(
            "https://vlr.gg/event/matches/1/fixture-event/",
            "fixture-event",
            mode,
            False,
            False,
        )
    assert result.error is None
    assert result.total_links == 5
    assert [match.status for match in result.processed.results] == statuses
    assert result.processed.skipped_count == skipped
    assert result.processed.tbd_count == 1
    assert result.processed.failed_count == 1
    assert result.processed.errors[0].error_type == "parse"


async def test_fixture_fields() -> None:
    """Saved markup yields separate score, countdown, and start values."""
    with patch("aiohttp.ClientSession.get", side_effect=fixture_get), no_rate_limit():
        result = await _fetch_event_data(
            "https://vlr.gg/event/matches/1/fixture-event/",
            "fixture-event",
            "all",
            False,
            False,
        )
    completed, live, upcoming = result.processed.results
    assert completed.score and not completed.countdown
    assert live.score == "1 : 1"
    assert upcoming.score is None and upcoming.countdown == "1d 5h"
    assert upcoming.starts_at is not None
    assert upcoming.starts_at.isoformat() == "2025-12-09T04:00:00+00:00"


@pytest.mark.parametrize("export", [False, True])
def test_fixture_cli_partial_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], export: bool
) -> None:
    """Run the synchronous CLI through mocked HTTP and real parsing/export."""
    output = tmp_path / "matches.json"
    argv = ["-r", "americas", "--no-cache"]
    if export:
        argv += ["--export", "json", "--output", str(output)]
    opts = build_run_options(parse_args(argv), UserProfile())
    event = SimpleNamespace(
        event_id="1",
        name="Fixture event",
        url="https://vlr.gg/event/matches/1/fixture-event/",
        slug="fixture-event",
        status="ongoing",
    )
    with (
        patch("valorant_matches.cli.display.select_events", return_value=[event]),
        patch("aiohttp.ClientSession.get", side_effect=fixture_get),
        no_rate_limit(),
    ):
        code = run_cli_mode(opts, Formatter(), Mock(is_stale=False))
    assert code == 1
    text = capsys.readouterr().out
    assert "missing team names" in text
    if export:
        payload = json.loads(output.read_text())
        assert payload["count"] == 3
        assert payload["matches"][0]["start_time"] == "2025-12-09T04:00:00+00:00"
    else:
        assert "Kookje University" in text


@pytest.mark.parametrize("status", [200, 404])
async def test_empty_page_vs_http_failure(status: int) -> None:
    """An empty successful response differs from an HTTP failure."""
    with patch(
        "aiohttp.ClientSession.get", return_value=response_for("malformed", status)
    ):
        result = await _fetch_event_data(
            "https://vlr.gg/event/test", None, "all", False, False
        )
    if status == 404:
        assert result.error is not None
        assert result.error.message == "HTTP 404"
    else:
        assert result.error is None
    assert result.total_links == 0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2025-12-09 04:00:00", "2025-12-09T04:00:00+00:00"),
        ("0", "1970-01-01T00:00:00+00:00"),
        ("2025-12-09T05:00:00+01:00", "2025-12-09T04:00:00+00:00"),
        ("invalid", None),
        ("1e999", None),
    ],
)
def test_source_timestamps(raw: str, expected: str | None) -> None:
    """Support observed UTC attributes and tolerate malformed values."""
    soup = BeautifulSoup(
        f'<div class="moment-tz-convert" data-utc-ts="{raw}"></div>', "lxml"
    )
    start = extract_start_time(soup)
    assert (start.isoformat() if start else None) == expected


def test_match_links_skip_non_string_href() -> None:
    """Unexpected href types are safely ignored."""
    soup = BeautifulSoup(
        '<a href="/1/match">Match</a>', "lxml", multi_valued_attributes={"a": ["href"]}
    )
    assert find_event_match_urls(soup) == []


@pytest.mark.parametrize("mode, count", [("all", 1), ("upcoming", 1), ("results", 0)])
async def test_champions_tentative_schedule(mode: str, count: int) -> None:
    """Tentative Champions fixtures stay upcoming without invented start times."""
    async with AsyncValorantClient(cache_enabled=False) as client:
        with patch(
            "aiohttp.ClientSession.get",
            return_value=response_for("champions-tentative"),
        ):
            processed = await process_matches_async(client, [CHAMPIONS_URL], mode)
    assert len(processed.results) == count
    assert processed.failed_count == 0
    if count:
        match = processed.results[0]
        assert match.status == "upcoming"
        assert match.starts_at is None
        assert match.local_date_time(ZoneInfo("America/Los_Angeles")) == (
            "Saturday, September 26",
            "Time TBD (date tentative)",
        )
        output = Formatter().format_match_full(match).plain
        assert "UPCOMING" in output
        assert "Score:" not in output
        assert "Time TBD" in output
        assert not filter_today(processed.results, ZoneInfo("UTC"))


async def test_champions_rejects_previously_miscached_score() -> None:
    """Refetch cache records that mislabeled TBD matches as completed."""
    stale = Match(
        url=CHAMPIONS_URL,
        team1="100 Thieves",
        team2="T1",
        status="completed",
        score="TBD –",
    )
    with patch("valorant_matches.scraping.client.MatchCache") as cache:
        cache.return_value.get.return_value = stale.to_dict()
        async with AsyncValorantClient() as client:
            with patch(
                "aiohttp.ClientSession.get",
                return_value=response_for("champions-tentative"),
            ) as get:
                result = await client.process_match(CHAMPIONS_URL)
        get.assert_called_once()
        cache.return_value.invalidate.assert_called_once_with(CHAMPIONS_URL)
        cache.return_value.set.assert_not_called()
    assert result.match is not None
    assert result.match.status == "upcoming"
    assert result.match.starts_at is None
    assert not result.cache_hit
