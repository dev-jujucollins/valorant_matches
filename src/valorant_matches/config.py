# Configuration settings for the Valorant Matches application.
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rich.console import Console

# Application home for config, cache, and logs (independent of CWD)
APP_DIR = Path(os.getenv("VALORANT_MATCHES_HOME", Path.home() / ".valorant-matches"))
LOG_FILE = APP_DIR / "valorant_matches.log"


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get a boolean value from an environment variable.

    Args:
        key: Environment variable name.
        default: Value used when the variable is unset.

    Returns:
        True for "true", "1", "yes", or "on" (case-insensitive).
    """
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int) -> int:
    """Get an integer from an environment variable, ignoring invalid values.

    Args:
        key: Environment variable name.
        default: Value used when the variable is unset or invalid.

    Returns:
        The parsed integer or the default.
    """
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float) -> float:
    """Get a float from an environment variable, ignoring invalid values.

    Args:
        key: Environment variable name.
        default: Value used when the variable is unset or invalid.

    Returns:
        The parsed float or the default.
    """
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def build_logging_config() -> dict[str, Any]:
    """Build the logging config: Rich on stderr plus a debug log file.

    Returns:
        A dictionary for logging.config.dictConfig.
    """
    return {
        "version": 1,
        "formatters": {
            "console": {"format": "%(message)s", "datefmt": "%I:%M:%S %p"},
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%I:%M:%S %p",
            },
        },
        "handlers": {
            "console": {
                "()": "rich.logging.RichHandler",
                "console": Console(stderr=True),
                "show_path": False,
                "formatter": "console",
                "level": os.getenv("LOG_LEVEL", "INFO"),
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": str(LOG_FILE),
                "formatter": "standard",
                "level": "DEBUG",
                # Open lazily so configuring logging never touches the filesystem
                "delay": True,
            },
        },
        "loggers": {
            "valorant_matches": {
                "handlers": ["console", "file"],
                "level": "DEBUG",
                "propagate": False,
            },
        },
    }


def _package_version() -> str:
    """Return the installed package version, or a placeholder from source."""
    try:
        return version("valorant-matches")
    except PackageNotFoundError:
        return "0+unknown"


# Application settings (configurable via environment variables)
BASE_URL = "https://vlr.gg"
REQUEST_TIMEOUT = get_env_int("REQUEST_TIMEOUT", 10)
MAX_RETRIES = get_env_int("MAX_RETRIES", 3)
RETRY_DELAY = get_env_int("RETRY_DELAY", 1)

# Cache settings. Only completed matches are cached and their results do not
# change, so entries can live for a week.
CACHE_ENABLED = get_env_bool("CACHE_ENABLED", True)
CACHE_TTL_SECONDS = get_env_int("CACHE_TTL_SECONDS", 7 * 24 * 60 * 60)
CACHE_DIR = Path(os.getenv("CACHE_DIR", APP_DIR / "cache"))

# Rate limiting settings
RATE_LIMIT_DELAY = get_env_float("RATE_LIMIT_DELAY", 0.5)

# Identify the tool honestly so vlr.gg can see who is scraping.
PROJECT_URL = "https://github.com/dev-jujucollins/valorant_matches"
HEADERS = {"User-Agent": f"valorant-matches/{_package_version()} (+{PROJECT_URL})"}
