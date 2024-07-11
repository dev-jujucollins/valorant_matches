#!/usr/bin/python3
import re
import requests
from bs4 import BeautifulSoup

"""Description: This script scrapes the VLR.gg website for the most recent matches in Champions Tour Americas and
outputs the team names, scores, match date, and link to the match stats."""

# Constants
BASE_URL = "https://vlr.gg"
EVENT_URL = f"{BASE_URL}/event/matches/2095/champions-tour-2024-americas-stage-2/?series_id=4031&group=completed"

# Functions
def fetch_and_parse(url): # Fetches the page content and parses it
    response = requests.get(url)
    if response.status_code == 200:
        return BeautifulSoup(response.content, "html.parser")
    else:
        response.raise_for_status()

def extract_match_links(soup): # Extracts the match links from the page
    return [link for link in soup.find_all("a", href=True) if "35" in link["href"]]

def extract_team_names_and_scores(match_url): # Extracts the team names and scores from the match pages
    soup = fetch_and_parse(match_url)
    teams = [team.text.strip() for team in soup.find_all("div", class_="wf-title-med")][:2]
    score = soup.find("div", class_="js-spoiler").text.strip()
    formatted_score = re.sub(r"\s*:\s*", ":", score)
    return teams, formatted_score

def main():
    soup = fetch_and_parse(EVENT_URL)
    match_links = extract_match_links(soup)
    print("\n")
    print("Champions Tour Americas 2024 - Recent Matches:\n")

    for link in match_links:
        match_url = BASE_URL + link["href"]
        teams, formatted_score = extract_team_names_and_scores(match_url)
        print(f"{teams[0]} vs {teams[1]} | Score: {formatted_score}")

if __name__ == "__main__":
    main()
