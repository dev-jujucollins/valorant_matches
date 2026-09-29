# Interactive mode with menu-based navigation.

import json
import logging
from difflib import get_close_matches

from valorant_matches.cli.display import (
    DisplayOptions,
    MatchStats,
    display_results,
    prepare_matches,
    saved_discovery_notice,
)
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import UserProfile
from valorant_matches.scraping.discovery import EventDiscovery
from valorant_matches.scraping.matches import Match
from valorant_matches.scraping.runner import fetch_event_data

logger = logging.getLogger("valorant_matches")

# Keyboard shortcuts
SHORTCUTS = {
    "q": "Quit",
    "r": "Refresh events",
    "f": "Filter by team",
    "s": "Sort matches (date/team)",
    "g": "Group matches (date/status)",
    "v": "Toggle favorite-team filter",
    "h": "Show this help",
}

VIEW_MODE_OPTIONS = {"1": "all", "2": "results", "3": "upcoming"}


def print_shortcuts(formatter: Formatter) -> None:
    """Display keyboard shortcuts help."""
    print(f"\n{formatter.info('Keyboard Shortcuts:', bold=True)}")
    for key, description in SHORTCUTS.items():
        print(f"  {formatter.primary(key)} - {description}")
    print()


def select_view_mode(formatter: Formatter, default: str = "all") -> str | None:
    """Show the view mode menu. Returns a view mode, or None for 'back'."""
    print(f"\n{formatter.info(' View Mode:', bold=True)}")
    print(f"{formatter.primary('1.', bold=True)} {formatter.highlight('All Matches')}")
    print(
        f"{formatter.primary('2.', bold=True)} {formatter.highlight('Results Only')} {formatter.muted('(completed matches)')}"
    )
    print(
        f"{formatter.primary('3.', bold=True)} {formatter.highlight('Upcoming Only')} {formatter.muted('(scheduled matches)')}"
    )
    print(f"{formatter.primary('4.', bold=True)} {formatter.muted('Back to Events')}\n")
    choice = input(
        f"{formatter.info(f'Select view mode (Enter for {default}):', bold=True)} "
    ).strip()
    if choice == "4":
        return None
    return VIEW_MODE_OPTIONS.get(choice, default)


def _print_next_step_hint(formatter: Formatter, hint: str) -> None:
    """Print a lightweight next-step hint in interactive mode."""
    print(f"{formatter.muted(f'Next: {hint}')}\n")


def _suggest_team_names(
    results: list[tuple[dict, Match]], team_filter: str, limit: int = 3
) -> list[str]:
    """Return close team-name matches from loaded match results."""
    team_names = {match.team1 for _, match in results} | {
        match.team2 for _, match in results
    }
    if not team_names:
        return []
    return get_close_matches(team_filter, sorted(team_names), n=limit, cutoff=0.5)


def run_interactive_mode(
    formatter: Formatter,
    discovery: EventDiscovery,
    profile: UserProfile | None = None,
    cache_enabled: bool | None = None,
    timezone: str | None = None,
) -> int:
    """Run in interactive mode with menus.

    Args:
        formatter: Formatter instance for output styling
        discovery: EventDiscovery instance
    """
    force_refresh = False
    profile = profile or UserProfile()
    cache_enabled = profile.cache_enabled if cache_enabled is None else cache_enabled
    formatter.set_favorite_teams(profile.favorite_teams)

    # Current filter/sort/group state
    current_team_filter: str | None = None
    current_sort: str | None = profile.default_sort
    current_group: str | None = profile.default_group_by
    current_favorites_only = False
    last_loaded_results: list[tuple[dict, Match]] = []

    while True:
        try:
            # Discover events and build menu
            events = discovery.discover_events(force_refresh=force_refresh)
            force_refresh = False  # Reset after use

            if not events:
                print(formatter.error("No events found for selected season."))
                return 1
            notice = saved_discovery_notice(discovery)
            if notice:
                print(formatter.warning(notice))

            # Display event menu
            print(f"\n{formatter.info(' Available Events:', bold=True)}")
            print(
                f"{formatter.muted('  Enter an event number to open it | q: quit | r: refresh | h: all shortcuts')}"
            )
            for i, event in enumerate(events, 1):
                status = f" [{event.status}]" if event.status != "unknown" else ""
                print(
                    f"{formatter.primary(f'{i}.', bold=True)} "
                    f"{formatter.highlight(event.name)}"
                    f"{formatter.muted(status)}"
                )
            print()

            # Show active filters
            if (
                current_team_filter
                or current_sort
                or current_group
                or current_favorites_only
            ):
                active = []
                if current_team_filter:
                    active.append(f"team={current_team_filter}")
                if current_sort:
                    active.append(f"sort={current_sort}")
                if current_group:
                    active.append(f"group={current_group}")
                if current_favorites_only:
                    active.append("favorites")
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
                _print_next_step_hint(formatter, "choose an event number after refresh")
                continue

            if selected == "h":
                print_shortcuts(formatter)
                continue

            if selected == "v":
                if not profile.favorite_teams:
                    print(formatter.warning("No favorite teams saved."))
                else:
                    current_favorites_only = not current_favorites_only
                    print(
                        formatter.info(
                            "Favorite filter on"
                            if current_favorites_only
                            else "Favorite filter off"
                        )
                    )
                continue

            if selected == "f":
                team = input(
                    f"{formatter.info('Enter team name to filter (supports partial/fuzzy, empty to clear):')} "
                ).strip()
                current_team_filter = team if team else None
                if current_team_filter:
                    print(f"{formatter.success(f'Filter set: {current_team_filter}')}")
                    if last_loaded_results:
                        suggestions = _suggest_team_names(
                            last_loaded_results, current_team_filter
                        )
                        if suggestions:
                            print(
                                f"{formatter.muted('Did you mean: ' + ', '.join(suggestions))}"
                            )
                else:
                    print(f"{formatter.muted('Filter cleared')}")
                _print_next_step_hint(
                    formatter, "pick an event number to apply the filter"
                )
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
                _print_next_step_hint(
                    formatter, "pick an event number to apply sorting"
                )
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
                _print_next_step_hint(
                    formatter, "pick an event number to apply grouping"
                )
                continue

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

            # Show view mode menu before any network work
            view_mode = select_view_mode(formatter, profile.default_view_mode)
            if view_mode is None:
                continue  # Back to events

            fetch_result = fetch_event_data(
                event.url, event.slug, view_mode, cache_enabled=cache_enabled
            )
            if fetch_result.error:
                print(formatter.error(f"Fetch failed: {fetch_result.error.message}"))
                continue
            if fetch_result.processed.failed_count:
                print(
                    formatter.warning(
                        f"Incomplete results: {fetch_result.processed.failed_count} matches failed."
                    )
                )
                for error in fetch_result.processed.errors[:5]:
                    print(formatter.error(f"{error.message} ({error.url})"))
                if not fetch_result.processed.results:
                    continue
            if not fetch_result.total_links:
                logger.warning("No matches found for selected event")
                print(
                    f"\n{formatter.warning('No matches were found for this event page yet.')}"
                )
                print(
                    f"{formatter.muted('Try another event, press r to refresh, or run later when matches are posted.')}\n"
                )
                continue

            last_loaded_results = fetch_result.processed.results[:]
            results = prepare_matches(
                last_loaded_results,
                timezone=timezone,
                team=current_team_filter,
                favorite_teams=profile.favorite_teams,
                favorites_only=current_favorites_only,
                sort_by=current_sort,
            )

            # Log the actual number of matches being displayed
            match_type = {"upcoming": "upcoming", "results": "completed", "all": ""}
            type_str = f" {match_type[view_mode]}" if match_type[view_mode] else ""
            logger.info(f"Displaying {len(results)}{type_str} matches")
            print()

            if not results:
                if current_team_filter:
                    print(
                        f"\n{formatter.warning(f'No matches found for team filter: {current_team_filter}')}"
                    )
                    suggestions = _suggest_team_names(
                        last_loaded_results, current_team_filter
                    )
                    if suggestions:
                        print(
                            f"{formatter.muted('Try one of: ' + ', '.join(suggestions))}"
                        )
                    print(
                        f"{formatter.muted('You can press f to change/clear the team filter.')}\n"
                    )
                elif view_mode == "upcoming":
                    print(
                        f"\n{formatter.warning('No upcoming matches are scheduled right now for this event.')}"
                    )
                    print(
                        f"{formatter.muted('Try all matches mode or refresh events with r.')}\n"
                    )
                elif view_mode == "results":
                    print(
                        f"\n{formatter.warning('No completed matches are available for this event yet.')}"
                    )
                    print(
                        f"{formatter.muted('Try upcoming mode to see scheduled matches.')}\n"
                    )
                else:
                    print(
                        f"\n{formatter.warning('No matches available to display right now.')}"
                    )
                    print(
                        f"{formatter.muted('Press r to refresh events or pick another event.')}\n"
                    )
            else:
                display_results(
                    results,
                    formatter,
                    DisplayOptions(
                        compact=profile.compact_mode,
                        group_by=current_group,
                        sort_by=current_sort,
                    ),
                    MatchStats(),
                )

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            print(
                f"\n{formatter.warning('Application interrupted by user. Exiting...')}"
            )
            break
        except EOFError:
            logger.info("Input closed; exiting interactive mode")
            print(formatter.muted("Input closed. Exiting."))
            break
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
