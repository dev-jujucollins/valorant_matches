# AGENTS.md

This file provides guidance for AI coding agents working on this codebase.

## Project Overview

A Python CLI application that fetches and displays Valorant Champions Tour (VCT) match results from vlr.gg. Uses Rich for terminal formatting, BeautifulSoup for HTML parsing, and includes a file-based caching system.

## Build/Lint/Test Commands

### Package Manager
- **Primary:** UV (recommended)
- **Alternative:** pip

### Install Dependencies
```bash
uv sync                           # Recommended
pip install -r requirements.txt   # Alternative
```

### Run Application
```bash
python main.py                          # Interactive mode
python main.py --region americas        # CLI mode - Americas matches
python main.py -r emea --upcoming       # CLI mode - upcoming EMEA matches
python main.py -r china --results       # CLI mode - completed China matches
python main.py --region champions --no-cache  # Force fresh data
python main.py --list-regions           # List available regions
python main.py --clear-cache            # Clear cached data
```

### Run Tests
```bash
# Run all tests
uv run pytest

# Run all tests (verbose, short traceback - default config)
uv run pytest -v --tb=short

# Run a single test file
uv run pytest tests/test_valorant_client.py

# Run a single test class
uv run pytest tests/test_valorant_client.py::TestValorantClient

# Run a single test method
uv run pytest tests/test_valorant_client.py::TestValorantClient::test_extract_teams

# Run tests with coverage
uv run pytest --cov

# Run tests matching a keyword
uv run pytest -k "test_extract"
```

### Type Checking
```bash
pyright                    # Type check entire project
pyright valorant_client.py # Type check single file
```

### Linting
```bash
uv run ruff check .        # Run linter
uv run ruff check --fix .  # Auto-fix linting issues
uv run ruff format .       # Format code
```

## Project Structure

```
valorant_matches/
├── main.py              # Application entry point
├── valorant_client.py   # Core match fetching and processing
├── config.py            # Configuration and constants
├── formatter.py         # Rich-based terminal formatting
├── cache.py             # Match data caching with TTL
├── tests/               # Test suite (pytest)
│   ├── test_cache.py
│   ├── test_config.py
│   ├── test_formatter.py
│   └── test_valorant_client.py
├── .cache/              # Runtime cache directory (JSON files)
└── pyproject.toml       # Project config, dependencies, pytest/pyright settings
```

## Code Style Guidelines

### Python Version
- **Required:** Python 3.11+

### Import Organization
Organize imports in this order, with blank lines between groups:
1. Standard library imports (alphabetically sorted)
2. Third-party imports
3. Local imports

```python
# Standard library
import logging
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict

# Third-party
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

# Local
from cache import MatchCache
from config import BASE_URL, EVENTS, HEADERS
from formatter import Formatter
```

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `ValorantClient`, `MatchCache` |
| Functions/Methods | snake_case | `fetch_event_matches`, `process_match` |
| Private methods | Leading underscore | `_extract_teams`, `_make_request` |
| Constants | UPPER_SNAKE_CASE | `BASE_URL`, `MAX_RETRIES` |
| Variables | snake_case | `match_links`, `is_live` |

### Type Hints
- **Required** on all function signatures (parameters and return types)
- Use modern Python 3.11+ syntax: `list`, `dict`, `tuple`, `X | None`
- Avoid deprecated `typing` module types (`List`, `Dict`, `Optional`)

```python
def _extract_teams(self, soup: BeautifulSoup) -> list[str]:
def get(self, url: str) -> Any | None:
def process_match(self, link: dict, upcoming_only: bool = False) -> str | None:
```

### Data Structures
- Use `@dataclass` for structured data containers

```python
@dataclass
class Match:
    date: str
    time: str
    team1: str
    team2: str
    score: str
    is_live: bool
    url: str
    is_upcoming: bool = False
```

### Error Handling
- Use specific exception types, never bare `except:`
- Log errors with context before handling
- Return `None` or sensible defaults on failure
- Use `try/except` blocks around external calls (HTTP, file I/O)

```python
try:
    response = self.session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")
except RequestException as e:
    logger.warning(f"Request failed: {str(e)}")
    return None
```

### Logging
- Use Python's `logging` module with logger named `"valorant_matches"`
- Log levels: DEBUG (details), INFO (operations), WARNING (issues), ERROR (failures)
- Include context in log messages

```python
logger = logging.getLogger("valorant_matches")
logger.info(f"Fetching matches for event: {event_url}")
logger.warning(f"Request failed (attempt {attempt + 1}/{retries}): {str(e)}")
logger.error(f"Error processing match {match_url}: {str(e)}")
```

### Comments and Docstrings
- Module-level: Single line comment at top of file
- Class-level: Comment below class definition (not docstring)
- Method-level: Triple-quote docstrings for complex methods

```python
# Core functionality for fetching and processing Valorant match data.

class ValorantClient:
    # Client for fetching and processing Valorant match data

    def _extract_teams(self, soup: BeautifulSoup) -> List[str]:
        """Extract team names with fallback selectors."""
```

## Testing Guidelines

### Framework
- pytest with fixtures and mocking

### Test Organization
- Test files: `tests/test_<module>.py`
- Test classes: Group related tests in classes (e.g., `TestValorantClient`)
- Test methods: `test_<what_is_being_tested>`

### Test Patterns
```python
@pytest.fixture
def client():
    """Create a ValorantClient instance for testing."""
    with patch("valorant_client.MatchCache"):
        return ValorantClient()

class TestValorantClient:
    def test_extract_teams(self, client, sample_match_html):
        """Test team extraction from HTML."""
        soup = BeautifulSoup(sample_match_html, "html.parser")
        teams = client._extract_teams(soup)

        assert len(teams) == 2
        assert teams[0] == "Sentinels"
```

### Mocking
- Use `unittest.mock`: `Mock`, `patch`, `MagicMock`
- Use `tmp_path` fixture for file system tests
- Mock external dependencies (HTTP requests, cache)

## Configuration

### Environment Variables
See `.env.example` for available options:
- `REQUEST_TIMEOUT`, `MAX_RETRIES`, `RETRY_DELAY`, `MAX_WORKERS`
- `CACHE_ENABLED`, `CACHE_TTL_SECONDS`
- `LOG_LEVEL`

### Type Checking
- Tool: Pyright
- Mode: basic
- Config: `pyproject.toml` [tool.pyright] section
