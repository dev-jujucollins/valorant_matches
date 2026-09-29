# Configuration settings for the Valorant Matches application.
import os
from pathlib import Path

import colorlog
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Application home for config, cache, and logs (independent of CWD)
APP_DIR = Path(os.getenv("VALORANT_MATCHES_HOME", Path.home() / ".valorant-matches"))
LOG_FILE = APP_DIR / "valorant_matches.log"


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
            "filename": str(LOG_FILE),
            "formatter": "standard",
            "level": "DEBUG",
            # Open lazily so importing this module never touches the filesystem
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

# Application settings (configurable via environment variables)
BASE_URL = "https://vlr.gg"
REQUEST_TIMEOUT = get_env_int("REQUEST_TIMEOUT", 10)
MAX_RETRIES = get_env_int("MAX_RETRIES", 3)
RETRY_DELAY = get_env_int("RETRY_DELAY", 1)
MAX_WORKERS = get_env_int("MAX_WORKERS", 10)

# Cache settings
CACHE_ENABLED = get_env_bool("CACHE_ENABLED", True)
# 1 hour TTL for completed matches (they don't change)
CACHE_TTL_SECONDS = get_env_int("CACHE_TTL_SECONDS", 3600)
CACHE_DIR = Path(os.getenv("CACHE_DIR", APP_DIR / "cache"))

# Rate limiting settings
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.5"))


# HTTP headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
