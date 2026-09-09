# Valorant Matches

A Python application that fetches and displays match results from the Valorant Champions Tour (VCT) events.

## Features

- Real-time match results from VCT events
- Support for multiple regions (Americas, EMEA, APAC, China)
- **View modes**: All matches, Results only, or Upcoming only
- **Display options**: Compact mode, sorting (date/team), grouping (date/status)
- **Export**: Save matches to JSON or CSV format
- **Team filtering**: Filter matches by team name, with fuzzy suggestions in interactive mode
- **Interactive mode**: Keyboard shortcuts for quick navigation
- **Caching**: Match data cached locally with configurable TTL
- **Auto-discovery**: Automatically discovers current VCT events from vlr.gg
- **Diagnostics**: Built-in doctor mode for connectivity, cache, and discovery checks
- **Saved defaults**: Configure default region, view, sorting, grouping, compact mode, cache, and favorite teams
- **Shell completion**: Print or install completion scripts for bash, zsh, and fish
- Async/concurrent match processing for faster results
- Beautiful terminal output with Rich formatting
- **Resilient web scraping** with fallback CSS selectors
- **Configurable** via environment variables
- Comprehensive error handling and logging
- Rate limiting to respect the website's resources

## Installation

### Using UV

1. Install UV if you haven't already:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. Clone the repository:

```bash
git clone https://github.com/dev-jujucollins/valorant_matches.git
cd valorant_matches
```

3. Install dependencies and create a virtual environment:

```bash
uv sync
```

No manual activation is required. Run commands through uv. The installed CLI
entry point is `valorant_matches.cli.app:main`; direct module execution is also
available:

```bash
uv run python -m valorant_matches.cli.app
```

## Usage

### Interactive Mode

Run without arguments to enter interactive mode:

```bash
uv run valorant-matches
```

The application will display a menu of available VCT events. Use keyboard shortcuts for quick navigation:

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh events |
| `f` | Filter by team |
| `s` | Sort matches |
| `g` | Group matches |
| `h` | Show help |

Interactive team filter supports partial names and fuzzy suggestions from loaded matches.

### CLI Mode

Fetch matches directly with command-line arguments:

```bash
# Basic usage - fetch matches for a region
uv run valorant-matches --region americas
uv run valorant-matches -r emea

# Filter by match status
uv run valorant-matches -r americas --upcoming    # Only upcoming matches
uv run valorant-matches -r americas --results     # Only completed matches

# Display options
uv run valorant-matches -r americas --compact              # Single-line format
uv run valorant-matches -r americas --sort date            # Sort by date
uv run valorant-matches -r americas --sort team            # Sort by team name
uv run valorant-matches -r americas --group-by status      # Group by live/upcoming/completed
uv run valorant-matches -r americas --group-by date        # Group by date

# Filter by team
uv run valorant-matches -r americas --team sentinels

# Export matches
uv run valorant-matches -r americas --export json                    # Export to matches.json
uv run valorant-matches -r americas --export csv --output results.csv  # Custom filename

# Other options
uv run valorant-matches --clear-cache           # Clear cached data
uv run valorant-matches --no-cache              # Disable caching for this run
uv run valorant-matches --list-regions          # Show discovered regions/events
uv run valorant-matches --refresh               # Force refresh event discovery
uv run valorant-matches --doctor                # Run diagnostics
uv run valorant-matches --quickstart            # Show quickstart
uv run valorant-matches --print-completion zsh  # Print shell completion
uv run valorant-matches --interactive -r emea   # Show CLI results, then enter interactive mode
```

CLI mode exits after printing or exporting results. Use `--interactive` when you want to continue browsing after a direct region query.

### Saved Defaults

Save common options so short commands do the right thing:

```bash
uv run valorant-matches config set default-region americas
uv run valorant-matches config set default-view results
uv run valorant-matches config set compact true
uv run valorant-matches config set sort date
uv run valorant-matches config set group-by status
uv run valorant-matches config favorite add Sentinels
uv run valorant-matches config get
```

After setting `default-region`, running `uv run valorant-matches` uses that region instead of opening interactive mode. Explicit CLI flags always override saved defaults.

### Shell Completion

```bash
uv run valorant-matches completion print zsh
uv run valorant-matches completion install zsh
```

### Region Aliases

| Alias | Region |
|-------|--------|
| `americas`, `am` | Americas |
| `emea`, `eu` | EMEA |
| `apac`, `pacific` | Pacific |
| `china`, `cn` | China |
| `champions` | Valorant Champions |
| `masters` | Valorant Masters |

## Configuration

Copy `.env.example` to `.env` to customize settings:

```bash
cp .env.example .env
```

Available options:

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUEST_TIMEOUT` | 10 | HTTP request timeout in seconds |
| `MAX_RETRIES` | 3 | Number of retry attempts for failed requests |
| `RETRY_DELAY` | 1 | Delay between retries in seconds |
| `CACHE_ENABLED` | true | Enable/disable match data caching |
| `CACHE_TTL_SECONDS` | 3600 | Completed-match cache TTL in seconds |
| `RATE_LIMIT_DELAY` | 0.5 | Minimum delay between match requests |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `VALORANT_MATCHES_HOME` | `~/.valorant-matches` | Runtime data directory |
| `CACHE_DIR` | `<app home>/cache` | Optional cache-only override |

## Project Structure

```
valorant_matches/
├── src/valorant_matches/
│   ├── cli/
│   │   ├── app.py            # Entry point and argument parsing
│   │   ├── display.py        # Non-interactive CLI workflows
│   │   └── interactive.py    # Interactive menu workflows
│   ├── output/
│   │   ├── exporters.py      # JSON/CSV export
│   │   └── formatter.py      # Rich terminal formatting
│   ├── scraping/
│   │   ├── client.py         # Async match fetching
│   │   ├── discovery.py      # VCT event discovery
│   │   ├── event_selection.py
│   │   ├── matches.py        # Match parsing and models
│   │   └── runner.py         # Sync wrapper for async fetching
│   ├── cache.py               # File cache
│   ├── config.py              # Environment and constants
│   └── profile.py             # Saved user defaults
├── tests/                      # Mirrors package areas above
│   ├── cli/
│   ├── output/
│   ├── scraping/
│   ├── test_cache.py
│   ├── test_config.py
│   ├── test_profile.py
│   └── test_project_config.py
├── pyproject.toml              # Project metadata and dependencies
├── requirements.txt            # Runtime dependency mirror
└── .env.example                # Configuration template
```

The repeated name is intentional: outer `valorant_matches/` is the repository,
while `src/valorant_matches/` is the importable Python package. The `src/`
boundary prevents accidental imports from the repository root. Inside the
package, modules are grouped by responsibility:

- `cli/`: command parsing and user workflows
- `scraping/`: event discovery, selection, requests, and HTML parsing
- `output/`: Rich terminal formatting and JSON/CSV export
- root modules: shared cache, configuration, and saved profile state

Logs and the match cache live in `~/.valorant-matches/` (override with
`VALORANT_MATCHES_HOME` or `CACHE_DIR`), so running the CLI never litters
the current directory.

## Testing

Run the test suite:

```bash
# Using UV
uv run pytest

# With coverage
uv run pytest --cov

# Focused areas
uv run pytest tests/cli/test_app.py
uv run pytest tests/scraping/test_matches.py -k "extract_teams"
```

GitHub Actions runs locked dependency sync, Ruff formatting and lint checks,
Pyright, and the full pytest suite for every push and pull request. See
`.github/workflows/ci.yml`.

## Logging

The application logs to the console and
`~/.valorant-matches/valorant_matches.log` by default. Log levels:

- DEBUG: Detailed information for debugging
- INFO: General operational information
- WARNING: Warning messages for potential issues
- ERROR: Error messages for failed operations

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Acknowledgments

- Data sourced from [vlr.gg](https://vlr.gg)
- Built with [Rich](https://github.com/Textualize/rich) for beautiful terminal output

Preview:

<img width="929" height="625" alt="Screenshot 2025-11-09 at 10 20 51 AM" src="https://github.com/user-attachments/assets/cb21b275-c0de-4117-8591-e3298d4a91cd" />
<img width="929" height="625" alt="Screenshot 2025-11-09 at 10 21 02 AM" src="https://github.com/user-attachments/assets/ddbf326b-9348-48dd-a856-619cf2787a78" />
<img width="929" height="625" alt="Screenshot 2025-11-09 at 10 21 43 AM" src="https://github.com/user-attachments/assets/9dd2385c-9ab8-43b4-ad53-a23fc038b239" />
<img width="929" height="693" alt="Screenshot 2025-11-09 at 10 24 50 AM" src="https://github.com/user-attachments/assets/951e69dd-f5c7-4345-be0b-adb92b180b42" />

## Freshness, timestamps, and watch mode

```bash
uv run valorant-matches -r americas --watch --interval 60
uv run valorant-matches -r emea --today --timezone America/Los_Angeles
uv run valorant-matches -r champions --sort date --timezone UTC
```

`--watch` refreshes until Ctrl+C (exit 130), shows score/status changes and the
last fully successful update, and retries after incomplete refreshes. The interval
is a delay **after** each fetch finishes (default 60 seconds, minimum 10).
Existing request rate limiting and completed-match caching still apply; use
`--no-cache` for fresh completed scores too. Watch requires a region or saved
default-region and cannot combine with export or interactive mode.

`--results` includes completed matches only; `--upcoming` includes scheduled
matches only. Use the default all view to include live matches. Filtered matches
are counted separately from failures.

Match start times use the source UTC timestamp. Display defaults to the local
timezone; `--timezone` accepts an IANA name. `--today` uses that timezone's date
and excludes matches without a known timestamp. Older markup without timestamps
keeps its original display text; sorting falls back to its date/time text.
JSON and CSV exports include `start_time` (ISO 8601 UTC, null/empty if unknown).
The cache schema has changed; older cached entries are refetched automatically.

Exit 0 means a successful query, including a genuinely empty schedule or filter.
Exit 1 means discovery selection, fetching, parsing, or export failed. Partial
results remain visible/exportable but return 1; errors include the affected URL.
Invalid CLI arguments return 2. HTTP retries honor `Retry-After` when provided.

CI tests Python 3.11–3.14 on Linux, plus a Windows smoke/test job. Each job builds
and installs the wheel into a clean environment and checks the installed CLI from
outside the checkout. Parser fixtures live in `tests/fixtures/vlr/`.
