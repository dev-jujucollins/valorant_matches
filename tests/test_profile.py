# Tests for saved configuration profiles.

import tempfile
from pathlib import Path

from valorant_matches.profile import ConfigManager, UserProfile


class TestUserProfile:
    """Tests for UserProfile dataclass."""

    def test_default_values(self):
        """Test default profile values."""
        profile = UserProfile()
        assert profile.default_region is None
        assert profile.compact_mode is False
        assert profile.favorite_teams == []
        assert profile.default_view_mode == "all"
        assert profile.default_sort is None
        assert profile.default_group_by is None
        assert profile.cache_enabled is True

    def test_add_favorite_team(self):
        """Test adding a team to favorites."""
        profile = UserProfile()
        profile.add_favorite_team("Sentinels")
        assert "Sentinels" in profile.favorite_teams

    def test_add_favorite_team_deduped(self):
        """Test that duplicate teams are not added."""
        profile = UserProfile()
        profile.add_favorite_team("Sentinels")
        profile.add_favorite_team("sentinels")  # Same team, different case
        profile.add_favorite_team("SENTINELS")
        assert len(profile.favorite_teams) == 1

    def test_remove_favorite_team(self):
        """Test removing a team from favorites."""
        profile = UserProfile()
        profile.add_favorite_team("Sentinels")
        profile.add_favorite_team("Cloud9")

        removed = profile.remove_favorite_team("Sentinels")
        assert removed is True
        assert "Sentinels" not in profile.favorite_teams
        assert "Cloud9" in profile.favorite_teams

    def test_remove_favorite_team_case_insensitive(self):
        """Test that team removal is case insensitive."""
        profile = UserProfile()
        profile.add_favorite_team("Sentinels")

        removed = profile.remove_favorite_team("sentinels")
        assert removed is True
        assert len(profile.favorite_teams) == 0

    def test_remove_favorite_team_not_found(self):
        """Test removing a team that doesn't exist."""
        profile = UserProfile()
        profile.add_favorite_team("Sentinels")

        removed = profile.remove_favorite_team("Cloud9")
        assert removed is False
        assert len(profile.favorite_teams) == 1


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_load_creates_default_profile(self):
        """Test that loading from non-existent file creates default profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            manager = ConfigManager(config_path)

            profile = manager.load()
            assert profile.default_region is None
            assert profile.compact_mode is False

    def test_save_and_load(self):
        """Test saving and loading a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            manager = ConfigManager(config_path)

            profile = UserProfile(
                default_region="americas",
                compact_mode=True,
                favorite_teams=["Sentinels", "Cloud9"],
            )
            manager.save(profile)

            # Create new manager to force reload
            manager2 = ConfigManager(config_path)
            loaded = manager2.load()

            assert loaded.default_region == "americas"
            assert loaded.compact_mode is True
            assert loaded.favorite_teams == ["Sentinels", "Cloud9"]

    def test_save_creates_directory(self):
        """Test that save creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "dir" / "config.json"
            manager = ConfigManager(config_path)

            manager.save(UserProfile())
            assert config_path.exists()

    def test_reset(self):
        """Test resetting profile to defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            manager = ConfigManager(config_path)

            # Save a modified profile
            profile = UserProfile(default_region="americas")
            manager.save(profile)
            assert config_path.exists()

            # Reset
            reset_profile = manager.reset()
            assert reset_profile.default_region is None
            assert not config_path.exists()

    def test_load_invalid_json(self):
        """Test loading from invalid JSON file uses defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # Write invalid JSON
            with open(config_path, "w") as f:
                f.write("not valid json {{{")

            manager = ConfigManager(config_path)
            profile = manager.load()

            # Should return default profile
            assert profile.default_region is None

    def test_load_wrong_fields_uses_defaults(self, tmp_path):
        """A config with unknown keys falls back to defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"unknown": 1}')
        assert ConfigManager(config_path).load() == UserProfile()

    def test_save_leaves_no_temp_file(self, tmp_path):
        """Saving replaces the file atomically."""
        config_path = tmp_path / "config.json"
        ConfigManager(config_path).save(UserProfile(default_region="emea"))
        assert [p.name for p in tmp_path.iterdir()] == ["config.json"]

    def test_reset_without_file(self, tmp_path):
        """Resetting when nothing is saved is not an error."""
        assert ConfigManager(tmp_path / "config.json").reset() == UserProfile()
