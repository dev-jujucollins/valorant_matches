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
