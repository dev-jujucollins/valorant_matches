"""Tests for resolving CLI flags against saved defaults."""

from zoneinfo import ZoneInfo

import pytest

from valorant_matches.cli.app import parse_args
from valorant_matches.cli.options import RunOptions, build_run_options, pick
from valorant_matches.profile import UserProfile

SAVED = UserProfile(
    default_region="americas",
    compact_mode=True,
    favorite_teams=["Sentinels"],
    default_view_mode="results",
    default_sort="team",
    default_group_by="status",
    cache_enabled=False,
)


def opts_for(*flags: str, profile: UserProfile | None = None) -> RunOptions:
    """Parse flags and resolve them against a profile."""
    return build_run_options(parse_args(list(flags)), profile or UserProfile())


class TestBuildRunOptions:
    """Tests for build_run_options."""

    def test_defaults_without_profile(self) -> None:
        """No flags and no saved state give neutral options."""
        opts = opts_for()
        assert opts == RunOptions(cache_enabled=UserProfile().cache_enabled)
        assert not opts.has_target

    def test_saved_profile_fills_missing_values(self) -> None:
        """Saved defaults apply when flags are absent."""
        opts = opts_for(profile=SAVED)
        assert opts.region == "americas"
        assert opts.view_mode == "results"
        assert opts.compact is True
        assert opts.sort_by == "team" and opts.auto_sort is False
        assert opts.group_by == "status"
        assert opts.cache_enabled is False
        assert opts.favorite_teams == ["Sentinels"]
        assert opts.has_target

    def test_explicit_flags_win(self) -> None:
        """Explicit flags override every saved choice."""
        opts = opts_for(
            "-r",
            "emea",
            "--upcoming",
            "--no-compact",
            "--sort",
            "date",
            "--group-by",
            "date",
            "--cache",
            profile=SAVED,
        )
        assert opts.region == "emea"
        assert opts.view_mode == "upcoming"
        assert opts.compact is False
        assert opts.sort_by == "date"
        assert opts.group_by == "date"
        assert opts.cache_enabled is True

    def test_none_clears_saved_choices(self) -> None:
        """--all, --sort none, and --group-by none restore unsaved behavior."""
        opts = opts_for("--all", "--sort", "none", "--group-by", "none", profile=SAVED)
        assert opts.view_mode == "all"
        assert opts.sort_by is None
        assert opts.auto_sort is False
        assert opts.group_by is None

    def test_auto_sort_only_without_any_choice(self) -> None:
        """Combining events sorts by date unless a sort was chosen anywhere."""
        assert opts_for().auto_sort is True
        assert opts_for(profile=UserProfile(default_sort="date")).auto_sort is False

    @pytest.mark.parametrize("flags", [("--favorites",), ("--event", "42")])
    def test_saved_region_not_applied_to_other_targets(
        self, flags: tuple[str, ...]
    ) -> None:
        """Favorites and event IDs do not inherit the saved region."""
        assert opts_for(*flags, profile=SAVED).region is None

    def test_invalid_saved_values_fall_back(self) -> None:
        """Hand-edited profile values outside the choices are ignored."""
        profile = UserProfile(
            default_view_mode="weird", default_sort="x", default_group_by="y"
        )
        opts = opts_for(profile=profile)
        assert opts.view_mode == "all"
        assert opts.sort_by is None and opts.group_by is None

    def test_zone(self) -> None:
        """The timezone name becomes a ZoneInfo; none means local time."""
        assert opts_for("-r", "am", "--timezone", "UTC").zone == ZoneInfo("UTC")
        assert opts_for().zone is None


def test_pick() -> None:
    """pick returns the matching choice or None."""
    assert pick("date", ["date", "team"]) == "date"
    assert pick("other", ["date", "team"]) is None
    assert pick(None, ["date"]) is None
