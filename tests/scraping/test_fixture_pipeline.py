"""Regression tests spanning HTTP responses, saved markup, and CLI output."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from bs4 import BeautifulSoup

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.display import run_cli_mode
from valorant_matches.output.formatter import Formatter
from valorant_matches.scraping.matches import extract_start_time
from valorant_matches.scraping.runner import _fetch_event_data

FIXTURES = Path(__file__).parents[1] / "fixtures" / "vlr"


def response_for(name: str, status: int = 200) -> Mock:
    """Wrap a fixture as an aiohttp response context manager."""
    response = Mock(status=status, headers={})
    response.text = AsyncMock(return_value=(FIXTURES / f"{name}.html").read_text())
    return Mock(__aenter__=AsyncMock(return_value=response), __aexit__=AsyncMock())


def fixture_get(url: str) -> Mock:
    """Resolve synthetic URLs into saved fixtures."""
    name = url.rsplit("-", 1)[-1] if "/event/" not in url else "event"
    return response_for(name)


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
    with (
        patch("aiohttp.ClientSession.get", side_effect=fixture_get),
        patch(
            "valorant_matches.scraping.client.AsyncRateLimiter.acquire",
            new_callable=AsyncMock,
        ),
    ):
        result = await _fetch_event_data(
            "https://vlr.gg/event/matches/1/fixture-event/",
            "fixture-event",
            mode,
            False,
            False,
        )
    assert result.error is None
    assert result.total_links == 5
    assert [match.status for _, match in result.processed.results] == statuses
    assert result.processed.skipped_count == skipped
    assert result.processed.tbd_count == 1
    assert result.processed.failed_count == 1
    assert result.processed.errors[0].error_type == "parse"


@pytest.mark.parametrize("export", [False, True])
def test_fixture_cli_partial_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], export: bool
) -> None:
    """Run the synchronous CLI through mocked HTTP and real parsing/export."""
    output = tmp_path / "matches.json"
    argv = ["valorant-matches", "-r", "americas", "--no-cache"]
    if export:
        argv += ["--export", "json", "--output", str(output)]
    with patch("sys.argv", argv):
        args = parse_args()
    event = Mock(
        url="https://vlr.gg/event/matches/1/fixture-event/",
        slug="fixture-event",
        status="ongoing",
    )
    with (
        patch("valorant_matches.cli.display.get_event_for_region", return_value=event),
        patch("aiohttp.ClientSession.get", side_effect=fixture_get),
        patch(
            "valorant_matches.scraping.client.AsyncRateLimiter.acquire",
            new_callable=AsyncMock,
        ),
    ):
        code = run_cli_mode(args, Formatter(), Mock(), Mock())
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
    response = response_for("malformed", status)
    with patch("aiohttp.ClientSession.get", return_value=response):
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
    assert extract_start_time(soup) == expected


def test_match_links_skip_non_string_href() -> None:
    """Unexpected href types are safely ignored."""
    from valorant_matches.scraping.matches import find_event_match_links

    soup = BeautifulSoup(
        '<a href="/1/match">Match</a>', "lxml", multi_valued_attributes={"a": ["href"]}
    )
    assert find_event_match_links(soup) == []
