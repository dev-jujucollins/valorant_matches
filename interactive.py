# Interactive mode with menu-based navigation.

import json
import logging

from requests.exceptions import RequestException

from cli_mode import (
    filter_matches_by_team,
    format_match_full,
    group_matches,
    sort_matches,
)
from config import EVENTS
from event_discovery import DiscoveredEvent, EventDiscovery
from formatter import Formatter
from valorant_client import ValorantClient

logger = logging.getLogger("valorant_matches")

# Keyboard shortcuts
SHORTCUTS = {
    "q": "quit",
    "r": "refresh",
    "f": "filter",
    "s": "sort",
    "g": "group",
    "h": "help",
}


def print_shortcuts(formatter: Formatter) -> None:
    """Display keyboard shortcuts help."""
    print(f"\n{formatter.info('Keyboard Shortcuts:', bold=True)}")
    print(f"  {formatter.primary('q')} - Quit")
    print(f"  {formatter.primary('r')} - Refresh events")
    print(f"  {formatter.primary('f')} - Filter by team")
    print(f"  {formatter.primary('s')} - Sort matches (date/team)")
    print(f"  {formatter.primary('g')} - Group matches (date/status)")
    print(f"  {formatter.primary('h')} - Show this help")
    print()


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

    # Current filter/sort/group state
    current_team_filter: str | None = None
    current_sort: str | None = None
    current_group: str | None = None

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
            print(f"{formatter.muted('  (Press h for keyboard shortcuts)')}")
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

            # Show active filters
            if current_team_filter or current_sort or current_group:
                active = []
                if current_team_filter:
                    active.append(f"team={current_team_filter}")
                if current_sort:
                    active.append(f"sort={current_sort}")
                if current_group:
                    active.append(f"group={current_group}")
                print(f"{formatter.muted('Active: ' + ', '.join(active))}\n")

            selected = (
                input(f"{formatter.info('Select an event (or shortcut):', bold=True)} ")
                .strip()
                .lower()
            )

            # Handle keyboard shortcuts
            if selected == "q":
                logger.info("User chose to quit via shortcut")
                print(
                    f"\n{formatter.success('Thank you for using the Valorant Match Tracker!')}"
                )
                break

            if selected == "r":
                logger.info("User requested event refresh via shortcut")
                print(f"\n{formatter.info('Refreshing events...')}")
                force_refresh = True
                continue

            if selected == "h":
                print_shortcuts(formatter)
                continue

            if selected == "f":
                team = input(
                    f"{formatter.info('Enter team name to filter (empty to clear):')} "
                ).strip()
                current_team_filter = team if team else None
                if current_team_filter:
                    print(f"{formatter.success(f'Filter set: {current_team_filter}')}")
                else:
                    print(f"{formatter.muted('Filter cleared')}")
                continue

            if selected == "s":
                print(f"{formatter.info('Sort by:')}")
                print(f"  {formatter.primary('1.')} Date")
                print(f"  {formatter.primary('2.')} Team")
                print(f"  {formatter.primary('3.')} Clear sort")
                sort_choice = input(f"{formatter.info('Choice:')} ").strip()
                if sort_choice == "1":
                    current_sort = "date"
                elif sort_choice == "2":
                    current_sort = "team"
                else:
                    current_sort = None
                continue

            if selected == "g":
                print(f"{formatter.info('Group by:')}")
                print(f"  {formatter.primary('1.')} Date")
                print(f"  {formatter.primary('2.')} Status")
                print(f"  {formatter.primary('3.')} Clear grouping")
                group_choice = input(f"{formatter.info('Choice:')} ").strip()
                if group_choice == "1":
                    current_group = "date"
                elif group_choice == "2":
                    current_group = "status"
                else:
                    current_group = None
                continue

            # Handle refresh (numeric)
            if selected == str(len(events) + 1):
                logger.info("User requested event refresh")
                print(f"\n{formatter.info('Refreshing events...')}")
                force_refresh = True
                continue

            # Handle exit (numeric)
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
                    f"\n{formatter.error('Invalid choice. Please enter a number or shortcut.')}\n"
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

            results, _tbd_count = process_matches_func(client, match_links, view_mode)

            # Apply team filter if set
            if current_team_filter:
                results = filter_matches_by_team(results, current_team_filter)

            # Apply sorting if set
            if current_sort:
                results = sort_matches(results, current_sort)

            # Log the actual number of matches being displayed
            match_type = {"upcoming": "upcoming", "results": "completed", "all": ""}
            type_str = f" {match_type[view_mode]}" if match_type[view_mode] else ""
            logger.info(f"Displaying {len(results)}{type_str} matches")
            print()

            if not results:
                if current_team_filter:
                    print(
                        f"\n{formatter.warning(f'No matches found for team: {current_team_filter}')}\n"
                    )
                elif view_mode == "upcoming":
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
                # Apply grouping if set
                if current_group:
                    grouped = group_matches(results, current_group)
                    for group_key, group_results in grouped.items():
                        if group_key != "all":
                            print(f"\n{formatter.info(group_key.upper(), bold=True)}")
                            print(formatter.muted("─" * 30))
                        for _, match in group_results:
                            print(format_match_full(formatter, match))
                else:
                    for _, match in results:
                        print(format_match_full(formatter, match))

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
