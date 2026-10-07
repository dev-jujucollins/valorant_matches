# Tests for exporters.py

import csv
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from valorant_matches.output.exporters import (
    EXPORT_FIELDS,
    export_matches,
    match_to_dict,
)
from valorant_matches.scraping.matches import Match

BASE_MATCH = Match(
    url="https://vlr.gg/123",
    team1="Sentinels",
    team2="Cloud9",
    status="completed",
    score="2-1",
    date_label="Dec 23",
    time_label="3:00 PM",
)


def make_match(**overrides: Any) -> Match:
    """Build a match for export tests."""
    return replace(BASE_MATCH, **overrides)


class TestMatchToDict:
    """Tests for match_to_dict."""

    def test_completed_match(self) -> None:
        """Completed matches export their score and status."""
        data = match_to_dict(make_match())
        assert data == {
            "date_time": "Dec 23 3:00 PM",
            "start_time": None,
            "team1": "Sentinels",
            "team2": "Cloud9",
            "score": "2-1",
            "countdown": None,
            "status": "completed",
            "url": "https://vlr.gg/123",
        }

    def test_upcoming_match(self) -> None:
        """Upcoming matches export the countdown separately from the score."""
        data = match_to_dict(make_match(status="upcoming", score=None, countdown="2h"))
        assert data["status"] == "upcoming"
        assert data["score"] is None
        assert data["countdown"] == "2h"

    def test_start_time_is_utc_and_date_time_is_local(self) -> None:
        """start_time stays UTC; date_time follows the display timezone."""
        match = make_match(starts_at=datetime(2026, 1, 2, 1, tzinfo=UTC))
        data = match_to_dict(match, ZoneInfo("America/Los_Angeles"))
        assert data["start_time"] == "2026-01-02T01:00:00+00:00"
        assert data["date_time"] == "January 01, 2026 05:00 PM PST"


class TestExport:
    """Tests for file export."""

    def test_export_json_content(self, tmp_path: Path) -> None:
        """Exported JSON holds the rows and a count."""
        path = tmp_path / "nested" / "test.json"
        assert export_matches([make_match()], "json", path) == 1
        data = json.loads(path.read_text())
        assert data["count"] == 1
        assert data["matches"][0]["team1"] == "Sentinels"

    def test_export_csv_content(self, tmp_path: Path) -> None:
        """Exported CSV has the expected header and an empty cell for None."""
        path = tmp_path / "test.csv"
        export_matches([make_match()], "csv", path)
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert reader.fieldnames == EXPORT_FIELDS
        assert rows[0]["score"] == "2-1"
        assert rows[0]["start_time"] == ""

    def test_invalid_format(self) -> None:
        """Unknown formats raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_matches([make_match()], "invalid", "output.txt")

    def test_default_path(self, tmp_path: Path, monkeypatch) -> None:
        """Without a path the file is matches.<format> in the working directory."""
        monkeypatch.chdir(tmp_path)
        export_matches([make_match()], "json")
        assert (tmp_path / "matches.json").exists()
