# Typed run options: CLI flags merged with saved profile defaults.

import argparse
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Literal, TypeVar, get_args
from zoneinfo import ZoneInfo

from valorant_matches.profile import UserProfile

ViewMode = Literal["all", "upcoming", "results"]
SortKey = Literal["date", "team"]
GroupKey = Literal["date", "status"]
ExportFormat = Literal["json", "csv"]

VIEW_MODES: list[ViewMode] = list(get_args(ViewMode))
SORT_KEYS: list[SortKey] = list(get_args(SortKey))
GROUP_KEYS: list[GroupKey] = list(get_args(GroupKey))
EXPORT_FORMATS: list[ExportFormat] = list(get_args(ExportFormat))

# Value accepted by --sort, --group-by, and config to clear a saved choice
NONE_CHOICE = "none"

_Choice = TypeVar("_Choice", bound=str)


def pick(value: str | None, choices: list[_Choice]) -> _Choice | None:
    """Narrow a string to one of the allowed literal choices.

    Args:
        value: Untrusted value, e.g. from argparse or the profile file.
        choices: Allowed values. A list, not a tuple: Pyright keeps literal
            types when solving an invariant type variable.

    Returns:
        The matching choice, or None when value is not allowed.
    """
    return next((choice for choice in choices if choice == value), None)


@dataclass
class RunOptions:
    """Everything a match run needs, resolved once from flags and profile."""

    region: str | None = None
    event_id: str | None = None
    favorites_only: bool = False
    favorite_teams: list[str] = field(default_factory=list)
    view_mode: ViewMode = "all"
    cache_enabled: bool = True
    refresh: bool = False
    compact: bool = False
    sort_by: SortKey | None = None
    # Sort by date automatically when combining events, unless the user chose.
    auto_sort: bool = True
    group_by: GroupKey | None = None
    team: str | None = None
    export: ExportFormat | None = None
    output: str | None = None
    timezone: str | None = None
    today: bool = False
    watch: bool = False
    interval: int = 60
    interactive: bool = False

    @property
    def zone(self) -> tzinfo | None:
        """Display timezone; None means the system local timezone."""
        return ZoneInfo(self.timezone) if self.timezone else None

    @property
    def has_target(self) -> bool:
        """Whether a region, event, or favorite schedule was selected."""
        return bool(self.region or self.event_id or self.favorites_only)


def build_run_options(args: argparse.Namespace, profile: UserProfile) -> RunOptions:
    """Resolve parsed arguments against saved defaults.

    Explicit flags always win; "none" for sort or group clears a saved value.

    Args:
        args: Parsed arguments from cli.app.parse_args.
        profile: Saved user defaults.

    Returns:
        Fully resolved options.
    """
    region = args.region
    if region is None and not args.favorites and args.event is None:
        region = profile.default_region

    if args.upcoming:
        view_mode: ViewMode = "upcoming"
    elif args.results:
        view_mode = "results"
    elif args.all:
        view_mode = "all"
    else:
        view_mode = pick(profile.default_view_mode, VIEW_MODES) or "all"

    if args.sort is not None:
        sort_by = pick(args.sort, SORT_KEYS)
        auto_sort = False
    else:
        sort_by = pick(profile.default_sort, SORT_KEYS)
        auto_sort = sort_by is None

    group_value = profile.default_group_by if args.group_by is None else args.group_by

    return RunOptions(
        region=region,
        event_id=args.event,
        favorites_only=args.favorites,
        favorite_teams=list(profile.favorite_teams),
        view_mode=view_mode,
        cache_enabled=profile.cache_enabled if args.cache is None else args.cache,
        refresh=args.refresh,
        compact=profile.compact_mode if args.compact is None else args.compact,
        sort_by=sort_by,
        auto_sort=auto_sort,
        group_by=pick(group_value, GROUP_KEYS),
        team=args.team,
        export=pick(args.export, EXPORT_FORMATS),
        output=args.output,
        timezone=args.timezone,
        today=args.today,
        watch=args.watch,
        interval=args.interval,
        interactive=args.interactive,
    )
