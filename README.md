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
- `requirements.txt` - Project dependencies

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

<img width="962" alt="Screenshot 2024-08-16 at 2 46 41 AM" src="https://github.com/user-attachments/assets/3d86a8bb-697a-4e76-b227-17cd166a96ca">
<img width="962" alt="Screenshot 2024-08-16 at 2 48 12 AM" src="https://github.com/user-attachments/assets/c651087a-0dcb-46ab-a050-db20d40eb836">
<img width="962" alt="Screenshot 2024-08-16 at 2 54 25 AM" src="https://github.com/user-attachments/assets/54855d0c-6bca-4f1e-b6b4-668c4b232fd6">
