# User configuration profile management.

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("valorant_matches")

# Default config directory
CONFIG_DIR = Path.home() / ".valorant-matches"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class UserProfile:
    """User configuration profile."""

    default_region: str | None = None
    compact_mode: bool = False
    favorite_teams: list[str] = field(default_factory=list)
    default_view_mode: str = "all"  # "all", "upcoming", "results"
    default_sort: str | None = None  # "date", "team"
    default_group_by: str | None = None  # "date", "status"
    cache_enabled: bool = True

    def add_favorite_team(self, team: str) -> None:
        """Add a team to favorites (case-preserved, deduped)."""
        # Check if team already exists (case-insensitive)
        for existing in self.favorite_teams:
            if existing.lower() == team.lower():
                return
        self.favorite_teams.append(team)

    def remove_favorite_team(self, team: str) -> bool:
        """Remove a team from favorites. Returns True if removed."""
        team_lower = team.lower()
        for i, existing in enumerate(self.favorite_teams):
            if existing.lower() == team_lower:
                del self.favorite_teams[i]
                return True
        return False

    def is_favorite_team(self, team: str) -> bool:
        """Check if a team is in favorites (case-insensitive)."""
        team_lower = team.lower()
        return any(t.lower() == team_lower for t in self.favorite_teams)


class ConfigManager:
    """Manages user configuration profiles."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or CONFIG_FILE
        self._profile: UserProfile | None = None

    def _ensure_config_dir(self) -> None:
        """Create config directory if it doesn't exist."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> UserProfile:
        """Load user profile from disk, or return defaults."""
        if self._profile is not None:
            return self._profile

        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._profile = UserProfile(**data)
                logger.debug(f"Loaded config from {self.config_path}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Invalid config file, using defaults: {e}")
                self._profile = UserProfile()
        else:
            self._profile = UserProfile()

        return self._profile

    def save(self, profile: UserProfile | None = None) -> None:
        """Save user profile to disk."""
        if profile is not None:
            self._profile = profile

        if self._profile is None:
            self._profile = UserProfile()

        self._ensure_config_dir()

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self._profile), f, indent=2)

        logger.debug(f"Saved config to {self.config_path}")

    def reset(self) -> UserProfile:
        """Reset to default profile."""
        self._profile = UserProfile()
        if self.config_path.exists():
            self.config_path.unlink()
        return self._profile

    @property
    def profile(self) -> UserProfile:
        """Get current profile (loads if not cached)."""
        return self.load()

    def update(self, **kwargs) -> UserProfile:
        """Update profile with provided values and save."""
        profile = self.load()

        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
            else:
                logger.warning(f"Unknown config key: {key}")

        self.save(profile)
        return profile


# Global config manager instance
config_manager = ConfigManager()


def get_profile() -> UserProfile:
    """Get the current user profile."""
    return config_manager.profile


def save_profile(profile: UserProfile) -> None:
    """Save the user profile."""
    config_manager.save(profile)
