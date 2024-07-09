#!/usr/bin/python3
"""Description: This script scrapes the VLR.gg website for the most recent matches in Champions Tour Americas and
outputs the team names, scores, match date, and link to the match stats."""

import re
import requests
from bs4 import BeautifulSoup

# URL
url = "https://www.vlr.gg/event/matches/2095/champions-tour-2024-americas-stage-2/?series_id=4031&group=completed"


def main():

    # Sending GET request to the page
    response = requests.get(url)

    # Checking if the request was successful
    if response.status_code == 200:
        # Parse the page content
        soup = BeautifulSoup(response.content, "html.parser")
        # Assuming the response is successful and soup has been created

        # Finding all <a> link elements
        all_links = soup.find_all("a")

        # Filtering through <a> elements by a specific pattern on their 'href' attribute
        matches = [link for link in all_links if "35" in link.get("href", "")]
        for match in matches:
            matches = "https://vlr.gg" + match["href"]

        # Extracting the match URLs
            response = requests.get(matches)
            soup = BeautifulSoup(response.content, "html.parser")
            teams = soup.find_all("div", class_="wf-title-med")
            team1 = teams[0].text.strip()
            team2 = teams[1].text.strip()

        # Extracting the match scores
            scores = soup.find_all("div", class_="js-spoiler")
            score = scores[0].text.strip()
            formatted_score = re.sub(r"\s*:\s*", ":", score)

        # Extracting the match date
            match_date = soup.find("div", class_="moment-tz-convert").text.strip()

            print(f"{team1} vs {team2}")
            print(f"Score | {formatted_score}")
            print(f"Match Date: {match_date}")
            print(f"Link to stats: {matches}")
            print("\n")
    else:
        print(f"Failed to retrieve the page. Status code: {response.status_code}")

if __name__ == "__main__":
    main()
