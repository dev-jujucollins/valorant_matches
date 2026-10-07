# Interactive mode with menu-based navigation.

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from difflib import get_close_matches

from rich.text import Text

from valorant_matches.cli.display import (
    MatchStats,
    display_results,
    fetch_matches,
    prepare_matches,
    print_empty_results,
    print_error_summary,
    saved_discovery_notice,
)
from valorant_matches.cli.options import (
    GROUP_KEYS,
    SORT_KEYS,
    GroupKey,
    RunOptions,
    SortKey,
    ViewMode,
    pick,
)
from valorant_matches.output.formatter import Formatter
from valorant_matches.scraping.discovery import DiscoveredEvent, EventDiscovery
from valorant_matches.scraping.matches import Match

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

VIEW_MODE_OPTIONS: dict[str, ViewMode] = {"1": "all", "2": "results", "3": "upcoming"}


@dataclass
class InteractiveState:
    """Filters and display choices that persist between event selections."""

    team: str | None = None
    sort_by: SortKey | None = None
    group_by: GroupKey | None = None
    favorites_only: bool = False
    force_refresh: bool = False
    last_loaded: list[Match] = field(default_factory=list)

    def active_filters(self) -> list[str]:
        """Describe the active filters, e.g. ["team=fnatic", "favorites"]."""
        active = []
        if self.team:
            active.append(f"team={self.team}")
        if self.sort_by:
            active.append(f"sort={self.sort_by}")
        if self.group_by:
            active.append(f"group={self.group_by}")
        if self.favorites_only:
            active.append("favorites")
        return active


def _menu_item(key: str, label: str, note: str = "") -> Text:
    """Build a numbered menu line."""
    return Text.assemble(
        (f"{key}.", "bold primary"), " ", (label, "highlight"), (note, "muted")
    )


def print_shortcuts(formatter: Formatter) -> None:
    """Display keyboard shortcuts help.

    Args:
        formatter: Output formatter.
    """
    formatter.blank()
    formatter.info("Keyboard Shortcuts:", bold=True)
    for key, description in SHORTCUTS.items():
        formatter.print(Text.assemble("  ", (key, "primary"), f" - {description}"))
    formatter.blank()


def select_view_mode(
    formatter: Formatter, default: ViewMode = "all"
) -> ViewMode | None:
    """Show the view mode menu.

    Args:
        formatter: Output formatter.
        default: Mode used when the user presses Enter.

    Returns:
        The chosen view mode, or None to go back to events.
    """
    formatter.blank()
    formatter.info(" View Mode:", bold=True)
    formatter.print(_menu_item("1", "All Matches"))
    formatter.print(_menu_item("2", "Results Only", " (completed matches)"))
    formatter.print(_menu_item("3", "Upcoming Only", " (scheduled matches)"))
    formatter.print(
        Text.assemble(("4.", "bold primary"), " ", ("Back to Events", "muted"))
    )
    formatter.blank()
    choice = formatter.ask(f"Select view mode (Enter for {default}):").strip()
    if choice == "4":
        return None
    return VIEW_MODE_OPTIONS.get(choice, default)


def _print_next_step_hint(formatter: Formatter, hint: str) -> None:
    """Print a lightweight next-step hint."""
    formatter.muted(f"Next: {hint}")
    formatter.blank()


def _suggest_team_names(
    matches: list[Match], team_filter: str, limit: int = 3
) -> list[str]:
    """Return close team-name matches from loaded matches.

    Args:
        matches: Recently loaded matches.
        team_filter: Name the user typed.
        limit: Maximum number of suggestions.
    """
    team_names = {match.team1 for match in matches} | {match.team2 for match in matches}
    return get_close_matches(team_filter, sorted(team_names), n=limit, cutoff=0.5)


def _prompt_choice(
    formatter: Formatter, title: str, choices: Sequence[str], clear_label: str
) -> str | None:
    """Ask for one of several choices by number; anything else clears.

    Args:
        formatter: Output formatter.
        title: Menu heading such as "Sort by:".
        choices: Values offered as options 1..n.
        clear_label: Label for the final "clear" option.

    Returns:
        The chosen value, or None to clear.
    """
    formatter.info(title)
    for index, choice in enumerate(choices, 1):
        formatter.print(
            Text.assemble("  ", (f"{index}.", "primary"), f" {choice.title()}")
        )
    formatter.print(
        Text.assemble("  ", (f"{len(choices) + 1}.", "primary"), f" {clear_label}")
    )
    selected = formatter.ask("Choice:").strip()
    if selected.isdigit() and 1 <= int(selected) <= len(choices):
        return choices[int(selected) - 1]
    return None


def _set_team_filter(formatter: Formatter, state: InteractiveState) -> None:
    """Prompt for a team filter and suggest close names."""
    team = formatter.ask(
        "Enter team name to filter (supports partial/fuzzy, empty to clear):"
    ).strip()
    state.team = team or None
    if not state.team:
        formatter.muted("Filter cleared")
    else:
        formatter.success(f"Filter set: {state.team}")
        suggestions = _suggest_team_names(state.last_loaded, state.team)
        if suggestions:
            formatter.muted("Did you mean: " + ", ".join(suggestions))
    _print_next_step_hint(formatter, "pick an event number to apply the filter")


def _set_sort(formatter: Formatter, state: InteractiveState) -> None:
    """Prompt for a sort order."""
    choice = _prompt_choice(formatter, "Sort by:", SORT_KEYS, "Clear sort")
    state.sort_by = pick(choice, SORT_KEYS)
    _print_next_step_hint(formatter, "pick an event number to apply sorting")


def _set_group(formatter: Formatter, state: InteractiveState) -> None:
    """Prompt for a grouping."""
    choice = _prompt_choice(formatter, "Group by:", GROUP_KEYS, "Clear grouping")
    state.group_by = pick(choice, GROUP_KEYS)
    _print_next_step_hint(formatter, "pick an event number to apply grouping")


def _toggle_favorites(
    formatter: Formatter, state: InteractiveState, opts: RunOptions
) -> None:
    """Toggle the favorite-team filter when favorites are saved."""
    if not opts.favorite_teams:
        formatter.warning("No favorite teams saved.")
        return
    state.favorites_only = not state.favorites_only
    formatter.info(f"Favorite filter {'on' if state.favorites_only else 'off'}")


def _request_refresh(formatter: Formatter, state: InteractiveState) -> None:
    """Rediscover events before the next menu."""
    logger.info("User requested event refresh via shortcut")
    formatter.blank()
    formatter.info("Refreshing events...")
    state.force_refresh = True
    _print_next_step_hint(formatter, "choose an event number after refresh")


def _print_event_menu(
    formatter: Formatter, events: list[DiscoveredEvent], state: InteractiveState
) -> None:
    """Print the numbered event list and the active filters."""
    formatter.blank()
    formatter.info(" Available Events:", bold=True)
    formatter.muted(
        "  Enter an event number to open it | q: quit | r: refresh | h: all shortcuts"
    )
    for index, event in enumerate(events, 1):
        status = f" [{event.status}]" if event.status != "unknown" else ""
        formatter.print(_menu_item(str(index), event.name, status))
    formatter.blank()

    active = state.active_filters()
    if active:
        formatter.muted("Active: " + ", ".join(active))
        formatter.blank()


def _parse_event_choice(
    choice: str, events: list[DiscoveredEvent]
) -> DiscoveredEvent | None:
    """Return the event for a 1-based menu number, or None if invalid."""
    if choice.isdigit() and 1 <= int(choice) <= len(events):
        return events[int(choice) - 1]
    return None


def _show_event(
    formatter: Formatter,
    event: DiscoveredEvent,
    view_mode: ViewMode,
    state: InteractiveState,
    opts: RunOptions,
) -> None:
    """Fetch and display one event with the current filters."""
    stats = MatchStats()
    fetched = fetch_matches(
        [event],
        formatter,
        view_mode=view_mode,
        cache_enabled=opts.cache_enabled,
        stats=stats,
    )
    if stats.failed:
        if fetched:
            formatter.warning(f"Incomplete results: {stats.failed} matches failed.")
        print_error_summary(formatter, stats.errors)
        if not fetched:
            return
    if not stats.total:
        logger.warning("No matches found for selected event")
        formatter.warning("No matches were found for this event page yet.")
        formatter.muted(
            "Try another event, press r to refresh, "
            "or run later when matches are posted."
        )
        formatter.blank()
        return

    state.last_loaded = fetched
    matches = prepare_matches(
        fetched,
        zone=opts.zone,
        team=state.team,
        favorite_teams=opts.favorite_teams,
        favorites_only=state.favorites_only,
        sort_by=state.sort_by,
    )
    logger.info(f"Displaying {len(matches)} matches")
    formatter.blank()

    if matches:
        display_results(
            matches,
            formatter,
            compact=opts.compact,
            group_by=state.group_by,
            zone=opts.zone,
        )
        return

    print_empty_results(
        formatter,
        view_mode=view_mode,
        team=state.team,
        favorites_only=state.favorites_only,
        interactive=True,
    )
    if state.team:
        suggestions = _suggest_team_names(fetched, state.team)
        if suggestions:
            formatter.muted("Try one of: " + ", ".join(suggestions))
    formatter.blank()


def run_interactive_mode(
    formatter: Formatter,
    discovery: EventDiscovery,
    opts: RunOptions | None = None,
) -> int:
    """Run the menu loop until the user quits.

    Args:
        formatter: Output formatter.
        discovery: Event discovery service.
        opts: Resolved options; their filters and display choices seed the menu.

    Returns:
        0 after a normal exit, 1 when no events can be discovered.
    """
    opts = opts or RunOptions()
    formatter.set_favorite_teams(opts.favorite_teams)
    state = InteractiveState(
        team=opts.team,
        sort_by=opts.sort_by,
        group_by=opts.group_by,
        favorites_only=opts.favorites_only,
    )
    shortcuts: dict[str, Callable[[], None]] = {
        "r": lambda: _request_refresh(formatter, state),
        "h": lambda: print_shortcuts(formatter),
        "v": lambda: _toggle_favorites(formatter, state, opts),
        "f": lambda: _set_team_filter(formatter, state),
        "s": lambda: _set_sort(formatter, state),
        "g": lambda: _set_group(formatter, state),
    }

    while True:
        try:
            events = discovery.discover_events(force_refresh=state.force_refresh)
            state.force_refresh = False
            if not events:
                formatter.error("No events found for selected season.")
                return 1
            notice = saved_discovery_notice(discovery)
            if notice:
                formatter.warning(notice)

            _print_event_menu(formatter, events, state)
            selected = formatter.ask("Select an event (or shortcut):").strip().lower()

            if selected == "q":
                logger.info("User chose to quit via shortcut")
                formatter.blank()
                formatter.success("Thank you for using the Valorant Match Tracker!")
                break
            handler = shortcuts.get(selected)
            if handler:
                handler()
                continue

            event = _parse_event_choice(selected, events)
            if event is None:
                logger.warning(f"Invalid event selection: {selected}")
                formatter.blank()
                formatter.error("Invalid choice. Please enter a number or shortcut.")
                formatter.blank()
                continue

            # Show view mode menu before any network work
            view_mode = select_view_mode(formatter, opts.view_mode)
            if view_mode is not None:
                _show_event(formatter, event, view_mode, state, opts)

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            formatter.blank()
            formatter.warning("Application interrupted by user. Exiting...")
            break
        except EOFError:
            logger.info("Input closed; exiting interactive mode")
            formatter.muted("Input closed. Exiting.")
            break
        except Exception as e:
            # Keep the menu alive after unexpected failures; details go to the log.
            logger.error(f"Unexpected error: {e}", exc_info=True)
            formatter.blank()
            formatter.error("An unexpected error occurred. Please try again.")
            formatter.blank()

    return 0
