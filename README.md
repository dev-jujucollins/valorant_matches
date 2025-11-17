# Valorant Matches

A Python application that fetches and displays match results from the Valorant Champions Tour (VCT) events.

(**Currently not updated with newer events**)

## Features

- Real-time match results from VCT events
- Support for multiple regions (Americas, EMEA, APAC, China)
- Concurrent match processing for faster results
- Beautiful terminal output with rich formatting
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

Run the application:

```bash
python main.py
```

The application will display a menu of available VCT events. Select a number to view match results for that event.

## Project Structure

- `main.py` - Application entry point
- `valorant_client.py` - Core functionality for fetching and processing match data
- `config.py` - Configuration settings and constants
- `formatter.py` - Terminal output formatting utilities
- `pyproject.toml` - Project metadata and dependencies (UV/pip compatible)
- `requirements.txt` - Project dependencies (legacy support)

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

