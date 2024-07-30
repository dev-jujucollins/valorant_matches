#!/usr/bin/python3
import re
import requests
import textwrap
from bs4 import BeautifulSoup

"""Description: This script scrapes the VLR.gg website for the most recent matches in Champions Tour Americas and
outputs the team names, scores, match date, and link to the match stats."""

# Constants
BASE_URL = "https://vlr.gg"

print("\nVALORANT CHAMPIONS TOUR 2024\n")


# Functions
def menu():
    options = [
        "Champions Tour Americas",
        "Champions Tour EMEA",
        "Champions Tour APAC",
        "Champions Tour China",
        "VCT Champions 2024",
        "Exit"
    ]
    print("Regions:")
    for i, option in enumerate(options, start=1):
        print(f"{i}. {option}")
    print("\n")
    choice = input("Which matches would you like to see results for: ")
    return choice


def get_event_url(choice):  # Returns the URL for the user selected event
    event_urls = {
        "1": f"{BASE_URL}/event/matches/2095/champions-tour-2024-americas-stage-2/?series_id=4032",
        "2": f"{BASE_URL}/event/matches/2094/champions-tour-2024-emea-stage-2/?series_id=4030",
        "3": f"{BASE_URL}/event/matches/2005/champions-tour-2024-pacific-stage-2/?series_id=3839",
        "4": f"{BASE_URL}/event/matches/2096/champions-tour-2024-china-stage-2/?series_id=4034",
        "5": f"{BASE_URL}/event/matches/2097/valorant-champions-2024/?series_id=4035",
    }
    if choice in event_urls:  # Checking if the user input is valid
        return event_urls[choice]
    elif choice == "6":
        print("\033[31mExiting...\033[0m")
        exit()
    else:
        return None


def fetch_and_parse(url):  # Fetches the page content and parses it
    response = requests.get(url)
    if response.status_code == 200:
        return BeautifulSoup(response.content, "html.parser")
    else:
        response.raise_for_status()


def extract_match_links(soup):  # Extracts the match links from the page
    return [link for link in soup.find_all("a", href=True) if "37" in link["href"] or "36" in link["href"]]


def extract_teams_and_scores(match_url):  # Extracts the team names and scores from the match pages
    soup = fetch_and_parse(match_url)
    teams = [team.text.strip() for team in soup.find_all("div", class_="wf-title-med")][:2]
    try:
        score = soup.find("div", class_="js-spoiler").text.strip()
    except AttributeError:
        score = "Match has not started yet."
    formatted_score = re.sub(r"\s*:\s*", ":", score)  # Cleaning up the score format
    return teams, formatted_score


def extract_date(soup):  # Extracts the date of the matches from the match pages
    return soup.find("div", class_="moment-tz-convert").text.strip()


def main():
    while True:
        choice = menu()
        if choice == 6:
            break

        event_url = get_event_url(choice)
        if not event_url:
            print("\033[31mInvalid choice. Try again.\033[0m")
            print("\n")
            continue

        soup = fetch_and_parse(event_url)
        if soup is None:
            print("\033[31mError fetching event data. Try again later.\033[0m")
            continue

        match_links = extract_match_links(soup)
        if not match_links:
            print("\033[31mNo matches found for the selected event.\033[0m")
            continue

        print("\nMatch Results:\n" + "-" * 100)
        for link in match_links:
            match_url = BASE_URL + link["href"]
            match_soup = fetch_and_parse(match_url)
            if match_soup is None:
                print("\033[31mFailed to fetch match data.\033[0m")
                continue

            teams, formatted_score = extract_teams_and_scores(match_url)
            if "TBD" in teams:
                break
            date = extract_date(fetch_and_parse(match_url))
            match_link = BASE_URL + link["href"]
            output = textwrap.dedent(f"""
                \033[31m{date} | {teams[0]} vs {teams[1]} | Score: {formatted_score}\033[0m
                Stats: {match_link}
                {'-' * 100}
            """)
            print(output)


if __name__ == "__main__":
    main()
