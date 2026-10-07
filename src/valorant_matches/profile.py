# User configuration profile management.

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from valorant_matches.config import APP_DIR, CACHE_ENABLED

logger = logging.getLogger("valorant_matches")

CONFIG_FILE = APP_DIR / "config.json"


@dataclass
class UserProfile:
    """Saved CLI defaults."""

    default_region: str | None = None
    compact_mode: bool = False
    favorite_teams: list[str] = field(default_factory=list)
    default_view_mode: str = "all"  # "all", "upcoming", "results"
    default_sort: str | None = None  # "date", "team"
    default_group_by: str | None = None  # "date", "status"
    cache_enabled: bool = CACHE_ENABLED

    def add_favorite_team(self, team: str) -> None:
        """Add a team to favorites (case-preserved, deduped case-insensitively).

        Args:
            team: Team name as the user typed it.
        """
        if not any(
            existing.lower() == team.lower() for existing in self.favorite_teams
        ):
            self.favorite_teams.append(team)

    def remove_favorite_team(self, team: str) -> bool:
        """Remove a team from favorites, ignoring case.

        Args:
            team: Team name to remove.

        Returns:
            True when a team was removed.
        """
        team_lower = team.lower()
        for i, existing in enumerate(self.favorite_teams):
            if existing.lower() == team_lower:
                del self.favorite_teams[i]
                return True
        return False


class ConfigManager:
    """Load and save the user profile file."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or CONFIG_FILE
        self._profile: UserProfile | None = None

    def load(self) -> UserProfile:
        """Load the profile from disk once, falling back to defaults.

        Returns:
            The saved profile, or defaults when missing or invalid.
        """
        if self._profile is not None:
            return self._profile

        self._profile = UserProfile()
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._profile = UserProfile(**data)
                logger.debug(f"Loaded config from {self.config_path}")
            except (OSError, json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Invalid config file, using defaults: {e}")
        return self._profile

    def save(self, profile: UserProfile) -> None:
        """Save the profile to disk atomically.

        Args:
            profile: Profile to persist and keep as the loaded profile.
        """
        self._profile = profile
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        tmp_path.replace(self.config_path)
        logger.debug(f"Saved config to {self.config_path}")

    def reset(self) -> UserProfile:
        """Delete the saved profile and return defaults.

        Returns:
            A fresh default profile.
        """
        self._profile = UserProfile()
        self.config_path.unlink(missing_ok=True)
        return self._profile


# Global config manager instance
config_manager = ConfigManager()
