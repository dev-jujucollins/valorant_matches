#!/usr/bin/python3

import logging
import logging.config
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from rich.progress import Progress
from config import MAX_WORKERS, LOGGING_CONFIG
from valorant_client import ValorantClient

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("valorant_matches")


def process_matches(client: ValorantClient, match_links: List[dict]) -> List[tuple]:
    # Process matches concurrently and return results.
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures_to_link = {
            executor.submit(client.process_match, link): link for link in match_links
        }

        with Progress() as progress:
            task = progress.add_task(
                "[magenta]Getting match results", total=len(futures_to_link)
            )

            for future in as_completed(futures_to_link):
                result = future.result()
                if result is not None:
                    results.append((futures_to_link[future], result))
                progress.update(task, advance=1)
                time.sleep(0.5)  # Rate limiting

    return sorted(results, key=lambda x: match_links.index(x[0]))


def main() -> None:

    logger.info("Starting Valorant Matches application")
    print("\nValorant Champions Tour 25\n")

    client = ValorantClient()

    while True:
        try:
            selected_option = client.display_menu()
            if selected_option == "6":
                logger.info("User chose to exit")
                break

            event_url = client.get_event_url(selected_option)
            if not event_url:
                logger.warning("Invalid event selection")
                print(client.formatter.format("\nInvalid choice. Try again.\n", "red"))
                continue

            match_links = client.fetch_event_matches(event_url)
            if not match_links:
                logger.warning("No matches found for selected event")
                print(
                    client.formatter.format(
                        "\nNo matches found for the selected event\n", "red"
                    )
                )
                continue

            results = process_matches(client, match_links)
            for _, result in results:
                print(result)

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            print("\nExiting...")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            print(
                client.formatter.format(
                    "\nAn unexpected error occurred. Please try again.\n", "red"
                )
            )

    logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
