# Tests for exporters.py

import csv
import json
import tempfile
from pathlib import Path

from exporters import (
    export_csv,
    export_json,
    export_matches,
    match_to_dict,
)
from match_extractor import Match


def make_match(
    date: str = "Dec 23",
    time: str = "3:00 PM",
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


class TestMatchToDict:
    """Tests for match_to_dict function."""

    def test_completed_match(self):
        """Test converting completed match to dict."""
        match = make_match(
            team1="Sentinels",
            team2="Cloud9",
            score="2-1",
        )
        data = match_to_dict(match)

        assert data["team1"] == "Sentinels"
        assert data["team2"] == "Cloud9"
        assert data["score"] == "2-1"
        assert data["status"] == "completed"
        assert data["url"] == "https://vlr.gg/123"

    def test_live_match(self):
        """Test converting live match to dict."""
        match = make_match(is_live=True, score="1-1")
        data = match_to_dict(match)

        assert data["status"] == "live"
        assert data["score"] == "1-1"

    def test_upcoming_match(self):
        """Test converting upcoming match to dict."""
        match = make_match(is_upcoming=True, score="in 2h 30m")
        data = match_to_dict(match)

        assert data["status"] == "upcoming"
        assert data["score"] == "in 2h 30m"


class TestExportJson:
    """Tests for export_json function."""

    def test_export_json_creates_file(self):
        """Test that export_json creates a JSON file."""
        results = [
            ({"href": "/1"}, make_match(team1="Team A", team2="Team B")),
            ({"href": "/2"}, make_match(team1="Team C", team2="Team D", score="0-2")),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_matches.json"
            count = export_json(results, output_path)

            assert count == 2
            assert output_path.exists()

            with open(output_path) as f:
                data = json.load(f)

            assert data["count"] == 2
            assert len(data["matches"]) == 2

    def test_export_json_content(self):
        """Test that exported JSON contains correct data."""
        results = [
            (
                {"href": "/1"},
                make_match(team1="Sentinels", team2="Cloud9", score="2-1"),
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.json"
            export_json(results, output_path)

            with open(output_path) as f:
                data = json.load(f)

            match = data["matches"][0]
            assert match["team1"] == "Sentinels"
            assert match["team2"] == "Cloud9"
            assert match["score"] == "2-1"

    def test_export_json_creates_parent_dirs(self):
        """Test that export_json creates parent directories if needed."""
        results = [({"href": "/1"}, make_match())]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "dir" / "matches.json"
            export_json(results, output_path)

            assert output_path.exists()


class TestExportCsv:
    """Tests for export_csv function."""

    def test_export_csv_creates_file(self):
        """Test that export_csv creates a CSV file."""
        results = [
            ({"href": "/1"}, make_match(team1="Team A", team2="Team B")),
            ({"href": "/2"}, make_match(team1="Team C", team2="Team D", score="0-2")),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_matches.csv"
            count = export_csv(results, output_path)

            assert count == 2
            assert output_path.exists()

    def test_export_csv_content(self):
        """Test that exported CSV contains correct headers and data."""
        results = [
            (
                {"href": "/1"},
                make_match(team1="Sentinels", team2="Cloud9", score="2-1"),
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.csv"
            export_csv(results, output_path)

            with open(output_path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row["team1"] == "Sentinels"
            assert row["team2"] == "Cloud9"
            assert row["score"] == "2-1"

    def test_export_csv_has_headers(self):
        """Test that CSV has expected headers."""
        results = [({"href": "/1"}, make_match())]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.csv"
            export_csv(results, output_path)

            with open(output_path) as f:
                reader = csv.reader(f)
                headers = next(reader)

            expected = ["date_time", "team1", "team2", "score", "status", "url"]
            assert headers == expected


class TestExportMatches:
    """Tests for export_matches function."""

    def test_export_matches_json(self):
        """Test export_matches with JSON format."""
        results = [({"href": "/1"}, make_match())]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            count = export_matches(results, "json", output_path)

            assert count == 1
            assert output_path.exists()

    def test_export_matches_csv(self):
        """Test export_matches with CSV format."""
        results = [({"href": "/1"}, make_match())]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            count = export_matches(results, "csv", output_path)

            assert count == 1
            assert output_path.exists()

    def test_export_matches_invalid_format(self):
        """Test export_matches with invalid format raises error."""
        import pytest

        results = [({"href": "/1"}, make_match())]

        with pytest.raises(ValueError, match="Unsupported export format"):
            export_matches(results, "invalid", "output.txt")

    def test_export_matches_default_path(self):
        """Test export_matches with default output path."""
        import os

        results = [({"href": "/1"}, make_match())]

        # Use current directory for default path test
        try:
            export_matches(results, "json", None)
            assert Path("matches.json").exists()
        finally:
            # Cleanup
            if Path("matches.json").exists():
                os.remove("matches.json")
