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

<img width="1216" alt="Screenshot 2025-06-05 at 2 35 05 PM" src="https://github.com/user-attachments/assets/3884547a-d2c8-4fea-90d0-b9eac90cc691" />
<img width="1216" alt="Screenshot 2025-06-05 at 2 35 14 PM" src="https://github.com/user-attachments/assets/e4e38dd8-7c75-43c6-89be-b6354c210842" />
<img width="1216" alt="Screenshot 2025-06-05 at 2 35 25 PM" src="https://github.com/user-attachments/assets/22a84d1b-efeb-45dc-9cdf-9d52744995e0" />
<img width="1216" alt="Screenshot 2025-06-05 at 2 35 40 PM" src="https://github.com/user-attachments/assets/08a9d2f1-cf93-4d89-a4da-a0a2b2e539df" />


