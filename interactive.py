# Interactive mode with menu-based navigation.

import json
import logging

from requests.exceptions import RequestException

from config import EVENTS
from event_discovery import DiscoveredEvent, EventDiscovery
from formatter import Formatter
from valorant_client import ValorantClient

logger = logging.getLogger("valorant_matches")


def run_interactive_mode(
    formatter: Formatter,
    discovery: EventDiscovery,
    process_matches_func,
) -> int:
    """Run in interactive mode with menus.

    Args:
        formatter: Formatter instance for output styling
        discovery: EventDiscovery instance
        process_matches_func: Function to process matches (injected to avoid circular import)
    """
    client = ValorantClient()
    force_refresh = False

    while True:
        try:
            # Discover events and build menu
            events = discovery.discover_events(force_refresh=force_refresh)
            force_refresh = False  # Reset after use

            if not events:
                # Fallback to hardcoded events
                logger.warning("No events discovered, using fallback config")
                events = [
                    DiscoveredEvent(
                        name=e.name,
                        url=e.url,
                        event_id=e.series_id,
                        slug="",
                        status="unknown",
                        dates="",
                        region="",
                    )
                    for e in EVENTS.values()
                ]

            # Display event menu
            print(f"\n{formatter.info(' Available Events:', bold=True)}")
            for i, event in enumerate(events, 1):
                status = f" [{event.status}]" if event.status != "unknown" else ""
                print(
                    f"{formatter.primary(f'{i}.', bold=True)} "
                    f"{formatter.highlight(event.name)}"
                    f"{formatter.muted(status)}"
                )
            print(
                f"{formatter.primary(f'{len(events) + 1}.', bold=True)} "
                f"{formatter.muted('Refresh events')}"
            )
            print(
                f"{formatter.primary(f'{len(events) + 2}.', bold=True)} "
                f"{formatter.muted('Exit')}\n"
            )

            selected = input(
                f"{formatter.info('Select an event:', bold=True)} "
            ).strip()

            # Handle refresh
            if selected == str(len(events) + 1):
                logger.info("User requested event refresh")
                print(f"\n{formatter.info('Refreshing events...')}")
                force_refresh = True
                continue

            # Handle exit
            if selected == str(len(events) + 2):
                logger.info("User chose to exit")
                print(
                    f"\n{formatter.success('Thank you for using the Valorant Match Tracker!')}"
                )
                break

            # Validate selection
            try:
                idx = int(selected) - 1
                if idx < 0 or idx >= len(events):
                    raise ValueError("Index out of range")
                event = events[idx]
            except (ValueError, IndexError):
                logger.warning(f"Invalid event selection: {selected}")
                print(
                    f"\n{formatter.error('Invalid choice. Please enter a number from the menu.')}\n"
                )
                continue

            match_links = client.fetch_event_matches(event.url, event.slug)
            if not match_links:
                logger.warning("No matches found for selected event")
                print(
                    f"\n{formatter.warning('No matches found for the selected event')}\n"
                )
                continue

            # Show view mode menu
            view_mode_option = client.display_view_mode_menu()
            if view_mode_option == "4":
                continue  # Back to events

            view_mode_map = {"1": "all", "2": "results", "3": "upcoming"}
            view_mode = view_mode_map.get(view_mode_option, "all")

            results = process_matches_func(client, match_links, view_mode)

            # Log the actual number of matches being displayed
            match_type = {"upcoming": "upcoming", "results": "completed", "all": ""}
            type_str = f" {match_type[view_mode]}" if match_type[view_mode] else ""
            logger.info(f"Displaying {len(results)}{type_str} matches")
            print()

            if not results:
                if view_mode == "upcoming":
                    print(
                        f"\n{formatter.warning('No upcoming matches found for this event.')}\n"
                    )
                elif view_mode == "results":
                    print(
                        f"\n{formatter.warning('No completed matches found for this event.')}\n"
                    )
                else:
                    print(f"\n{formatter.warning('No matches found.')}\n")
            else:
                for _, result in results:
                    print(result)

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            print(
                f"\n{formatter.warning('Application interrupted by user. Exiting...')}"
            )
            break
        except RequestException as e:
            logger.error(f"Network error: {e}")
            print(
                f"\n{formatter.error('Network error. Please check your connection and try again.')}\n"
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Data parsing error: {e}", exc_info=True)
            print(
                f"\n{formatter.error('Failed to parse response data. Please try again.')}\n"
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            print(
                f"\n{formatter.error('An unexpected error occurred. Please try again.')}\n"
            )

    return 0
