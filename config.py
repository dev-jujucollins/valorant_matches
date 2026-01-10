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
        name="VCT 25: Americas Kickoff",
        url=f"{BASE_URL}/event/matches/2274/champions-tour-2025-americas-kickoff/",
        series_id="4405",
    ),
    "2": Event(
        name="VCT 25: EMEA Kickoff",
        url=f"{BASE_URL}/event/matches/2276/champions-tour-2025-emea-kickoff/",
        series_id="4407",
    ),
    "3": Event(
        name="VCT 25: APAC Kickoff",
        url=f"{BASE_URL}/event/matches/2277/champions-tour-2025-pacific-kickoff/",
        series_id="4408",
    ),
    "4": Event(
        name="VCT 25: China Kickoff",
        url=f"{BASE_URL}/event/matches/2275/champions-tour-2025-china-kickoff/",
        series_id="4406",
    ),
    "5": Event(
        name="VCT 25: Champions - Playoffs",
        url=f"{BASE_URL}/event/matches/2283/valorant-champions-2025/?series_id=5080/",
        series_id="4416",
    ),
}

# Match status codes to filter
MATCH_CODES = ("427", "428", "429", "430", "431", "498", "499", "542")

# HTTP headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
