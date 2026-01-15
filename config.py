# Configuration settings for the Valorant Matches application.
import os
from dataclasses import dataclass
from pathlib import Path

import colorlog
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get a boolean value from environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_env_int(key: str, default: int) -> int:
    """Get an integer value from environment variable."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# Logging configuration
LOGGING_CONFIG = {
    "version": 1,
    "formatters": {
        "colored": {
            "()": colorlog.ColoredFormatter,
            "format": "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%I:%M:%S %p",
            "log_colors": {
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        },
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%I:%M:%S %p",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "colored",
            "level": os.getenv("LOG_LEVEL", "INFO"),
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "valorant_matches.log",
            "formatter": "standard",
            "level": "DEBUG",
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

# Application settings (configurable via environment variables)
BASE_URL = "https://vlr.gg"
REQUEST_TIMEOUT = get_env_int("REQUEST_TIMEOUT", 10)
MAX_RETRIES = get_env_int("MAX_RETRIES", 3)
RETRY_DELAY = get_env_int("RETRY_DELAY", 1)
MAX_WORKERS = get_env_int("MAX_WORKERS", 10)

# Cache settings
CACHE_ENABLED = get_env_bool("CACHE_ENABLED", True)
CACHE_TTL_SECONDS = get_env_int("CACHE_TTL_SECONDS", 300)
CACHE_DIR = Path(os.getenv("CACHE_DIR", ".cache"))


@dataclass
class Event:
    # Represents a VCT event

    name: str
    url: str
    series_id: str


# Event configurations
EVENTS: dict[str, Event] = {
    "1": Event(
        name="VCT 26: Americas Kickoff",
        url=f"{BASE_URL}/event/matches/2682/vct-2026-americas-kickoff/",
        series_id="2682",
    ),
    "2": Event(
        name="VCT 26: EMEA Kickoff",
        url=f"{BASE_URL}/event/matches/2684/vct-2026-emea-kickoff/",
        series_id="2684",
    ),
    "3": Event(
        name="VCT 26: Pacific Kickoff",
        url=f"{BASE_URL}/event/matches/2683/vct-2026-pacific-kickoff/",
        series_id="2683",
    ),
    "4": Event(
        name="VCT 26: China Kickoff",
        url=f"{BASE_URL}/event/matches/2685/vct-2026-china-kickoff/",
        series_id="2685",
    ),
    "5": Event(
        name="Valorant Champions 2026",
        url=f"{BASE_URL}/event/matches/2766/valorant-champions-2026/",
        series_id="2766",
    ),
}

# HTTP headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
