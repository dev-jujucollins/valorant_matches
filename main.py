#!/usr/bin/python3
import time
from rich.progress import Progress
from formatter import Formatter
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import menu, get_event_url, fetch_and_parse, extract_match_links, process_match

print("\nValorant Champions Tour 25\n")

def main():
    while True:
        selected_option = menu()
        if selected_option == 6:
            break

        event_url = get_event_url(selected_option)
        if not event_url:
            print(Formatter().format("\nInvalid choice. Try again.\n", "red"))
            continue

        event_soup = fetch_and_parse(event_url)
        if event_soup is None:
            print(Formatter().format("\Error fetching event data. Try again later.\n", "red"))
            continue

        match_links = extract_match_links(event_soup)
        if not match_links:
            print(Formatter().format("\nNo matches found for the selected event\n", "red"))
            continue

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures_to_link = {
                executor.submit(process_match, link): link for link in match_links
            }
            results = []

            with Progress() as progress:
                task = progress.add_task("[magenta]Getting match results", total=len(futures_to_link))

                for future in as_completed(futures_to_link):
                    result = future.result()
                    if result is not None:
                        results.append((futures_to_link[future], result))
                    progress.update(task, advance=1)
                    time.sleep(0.5)

            sorted_results = sorted(results, key=lambda x: match_links.index(x[0]))

            for _, result in sorted_results:
                print(result)

if __name__ == "__main__":
    main()