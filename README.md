# Valorant Matches

A Python application that fetches and displays match results from the Valorant Champions Tour (VCT) events.

## Features

- Real-time match results from VCT events
- Support for multiple regions (Americas, EMEA, APAC, China)
- **View modes**: All matches, Results only, or Upcoming only
- **Display options**: Compact mode, sorting (date/team), grouping (date/status)
- **Export**: Save matches to JSON or CSV format
- **Team filtering**: Filter matches by team name
- **Interactive mode**: Keyboard shortcuts for quick navigation
- **User profiles**: Persistent configuration for preferences
- **Caching**: Match data cached locally with configurable TTL
- **Auto-discovery**: Automatically discovers current VCT events from vlr.gg
- Async/concurrent match processing for faster results
- Beautiful terminal output with Rich formatting
- **Resilient web scraping** with fallback CSS selectors
- **Configurable** via environment variables
- Comprehensive error handling and logging
- Rate limiting to respect the website's resources

## Installation

### Using UV (Recommended)

1. Install UV if you haven't already:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. Clone the repository:

```bash
git clone https://github.com/yourusername/valorant_matches.git
cd valorant_matches
```

3. Install dependencies and create a virtual environment:

```bash
uv sync
```

4. Activate the virtual environment:

```bash
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Using pip (Alternative)

1. Clone the repository:

```bash
git clone https://github.com/yourusername/valorant_matches.git
cd valorant_matches
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Interactive Mode

Run without arguments to enter interactive mode:

```bash
python main.py
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

### CLI Mode

Fetch matches directly with command-line arguments:

```bash
# Basic usage - fetch matches for a region
python main.py --region americas
python main.py -r emea

# Filter by match status
python main.py -r americas --upcoming    # Only upcoming matches
python main.py -r americas --results     # Only completed matches

# Display options
python main.py -r americas --compact              # Single-line format
python main.py -r americas --sort date            # Sort by date
python main.py -r americas --sort team            # Sort by team name
python main.py -r americas --group-by status      # Group by live/upcoming/completed
python main.py -r americas --group-by date        # Group by date

# Filter by team
python main.py -r americas --team sentinels

# Export matches
python main.py -r americas --export json                    # Export to matches.json
python main.py -r americas --export csv --output results.csv  # Custom filename

# Other options
python main.py --clear-cache      # Clear cached data
python main.py --no-cache         # Disable caching for this run
python main.py --refresh-events   # Force refresh event discovery
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
| `MAX_WORKERS` | 10 | Number of concurrent workers |
| `CACHE_ENABLED` | true | Enable/disable match data caching |
| `CACHE_TTL_SECONDS` | 300 | Cache time-to-live (5 minutes) |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Project Structure

```
valorant_matches/
├── main.py              # Application entry point and CLI argument parsing
├── valorant_client.py   # Synchronous match fetching and processing
├── async_client.py      # Async match fetching with rate limiting
├── event_discovery.py   # Auto-discovers VCT events from vlr.gg
├── event_manager.py     # Event selection and region mapping
├── cli_mode.py          # CLI mode logic and display options
├── interactive.py       # Interactive mode with keyboard shortcuts
├── match_extractor.py   # HTML parsing and data extraction
├── exporters.py         # JSON/CSV export functionality
├── config_profile.py    # User configuration profile management
├── config.py            # Configuration and constants
├── formatter.py         # Rich-based terminal formatting
├── cache.py             # Match data caching with TTL
├── tests/               # Test suite
│   ├── test_async_client.py
│   ├── test_cache.py
│   ├── test_cli_mode.py
│   ├── test_config.py
│   ├── test_config_profile.py
│   ├── test_exporters.py
│   ├── test_formatter.py
│   └── test_valorant_client.py
├── pyproject.toml       # Project metadata and dependencies
├── requirements.txt     # Legacy pip dependencies
└── .env.example         # Configuration template
```

## Testing

Run the test suite:

```bash
# Using UV
uv run pytest

# With coverage
uv run pytest --cov

# Using pip
pytest
```

## Logging

The application logs information to both the console and a file (`valorant_matches.log`). Log levels:

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

