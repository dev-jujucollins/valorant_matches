import re
import requests
import textwrap
import time
from rich.progress import Progress
from formatter import Formatter
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://vlr.gg"

def menu():
    options = [
        "VCT 25: Americas Kickoff",
        "VCT 25: EMEA Kickoff",
        "VCT 25: APAC Kickoff",
        "VCT 25: China Kickoff",
        "Exit",
    ]
    print("Regions:")
    for i, option in enumerate(options, start=1):
        print(f"{i}. {option}")
    print("\n")
    choice = input("\nWhich matches would you like to see results for: ")
    return choice.strip()

def get_event_url(choice):
    event_urls = {
        "1": f"{BASE_URL}//event/matches/2274/champions-tour-2025-americas-kickoff/?series_id=4405",
        "2": f"{BASE_URL}/event/matches/2276/champions-tour-2025-emea-kickoff/?series_id=4407",
        "3": f"{BASE_URL}/event/matches/2277/champions-tour-2025-pacific-kickoff/?series_id=4408",
        "4": f"{BASE_URL}/event/matches/2275/champions-tour-2025-china-kickoff/?series_id=4406",
    }
    if choice in event_urls:
        return event_urls[choice]
    elif choice == "5":
        print(Formatter().format("\nExiting...\n", "red"))
        exit()
    else:
        return None

def fetch_and_parse(url):
    response = requests.get(url)
    if response.status_code == 200:
        return BeautifulSoup(response.content, "html.parser")
    else:
        response.raise_for_status()

def extract_match_links(soup):
    return [
        link
        for link in soup.find_all("a", href=True)
        if any(code in link["href"] for code in ("427", "428", "429", "430", "431"))
    ]

def extract_teams_and_scores(match_url):
    soup = fetch_and_parse(match_url)
    teams = [team.text.strip() for team in soup.find_all("div", class_="wf-title-med")][:2]
    try:
        score = soup.find("div", class_="js-spoiler").text.strip()
    except AttributeError:
        score = "Match has not started yet."

    is_live = soup.find("span", class_="match-header-vs-note mod-live")
    formatted_score = re.sub(r"\s*:\s*", ":", score)
    teams = [re.sub(r'\s*\(.*?\)\s*', '', team) for team in teams]
    return teams, formatted_score, is_live

def extract_date(soup):
    match_date = soup.find("div", class_="moment-tz-convert").text.strip()
    match_time = soup.find("div", class_="moment-tz-convert").find_next("div").text.strip()
    return match_date, match_time

def process_match(link):
    match_url = BASE_URL + link["href"]
    match_soup = fetch_and_parse(match_url)
    if match_soup is None:
        return Formatter().format("Failed to fetch match data", "red")

    teams, formatted_score, is_live = extract_teams_and_scores(match_url)
    if "TBD" in teams:
        return None

    match_date, match_time = extract_date(match_soup)
    match_link = BASE_URL + link["href"]
    output = format_output(match_date, match_time, teams, formatted_score, match_link, is_live)
    
    return output

def format_output(match_date, match_time, teams, formatted_score, match_link, is_live):
    status = "In Progress" if is_live else ""
    output = textwrap.dedent(
        f"""
        {Formatter().format(f"{match_date}  {match_time}", "white")} | {Formatter().format(f"{teams[0]} vs {teams[1]}", "white")} | Score: {Formatter().format(f"{formatted_score}", "green")} {Formatter().format(status, "red")}
        {Formatter().format(f"Stats: {match_link}", "cyan")}
        {'-' * 100}
        """
    )
    return output