# Rich terminal output for messages and match listings.

from collections.abc import Iterable
from datetime import tzinfo

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

from valorant_matches.scraping.matches import Match

# Custom theme for consistent styling across the application
VALORANT_THEME = Theme(
    {
        "error": "bold bright_red",
        "warning": "bright_yellow",
        "success": "bright_green",
        "info": "bright_blue",
        "primary": "bright_cyan",
        "muted": "bright_black",
        "highlight": "bold bright_white",
        "team": "bold bright_cyan",
        "score": "bold bright_green",
        "live": "bold bright_red",
        "date_time": "bright_blue",
        "link": "underline bright_magenta",
    }
)

# Status icons for match states
STATUS_ICONS = {
    "live": "●",  # Bullet (red circle in most terminals)
    "upcoming": "⏱",  # Stopwatch
    "completed": "✓",  # Checkmark
}

# Widest separator drawn under a full match entry
MAX_RULE_WIDTH = 100


def eta_label(match: Match) -> str:
    """Describe when an upcoming match starts.

    Args:
        match: An upcoming match.

    Returns:
        "in <countdown>" when VLR shows a countdown, else "UPCOMING".
    """
    return f"in {match.countdown}" if match.countdown else "UPCOMING"


class Formatter:
    """Print styled messages and matches through one Rich console.

    Dynamic text is never parsed as Rich markup, so team names containing
    brackets print literally.
    """

    def __init__(
        self,
        color: bool | None = None,
        favorite_teams: Iterable[str] = (),
        console: Console | None = None,
    ) -> None:
        """Create a formatter.

        Args:
            color: Force color on or off; None detects the terminal.
            favorite_teams: Team names to mark with a star.
            console: Console to print to; built from the theme when omitted.
        """
        self.console = console or Console(
            theme=VALORANT_THEME,
            highlight=False,
            force_terminal=color,
            no_color=color is False,
        )
        self.set_favorite_teams(favorite_teams)

    def set_favorite_teams(self, teams: Iterable[str]) -> None:
        """Mark saved teams in all match views.

        Args:
            teams: Team names to mark, compared case-insensitively.
        """
        self.favorite_teams = {team.casefold() for team in teams}

    def _team_label(self, team: str) -> str:
        """Add a visible favorite marker to a saved team."""
        return f"★ {team}" if team.casefold() in self.favorite_teams else team

    def print(self, text: str | Text = "", style: str = "", bold: bool = False) -> None:
        """Print one line without markup parsing or wrapping.

        Args:
            text: Plain text or prebuilt Rich text.
            style: Theme style name for plain text.
            bold: Add bold to the style.
        """
        if isinstance(text, str):
            text = Text(text, style=f"bold {style}" if bold else style)
        self.console.print(text, soft_wrap=True)

    def blank(self) -> None:
        """Print an empty line."""
        self.console.print()

    def error(self, message: str) -> None:
        """Print an error message."""
        self.print(message, "error")

    def warning(self, message: str) -> None:
        """Print a warning message."""
        self.print(message, "warning")

    def success(self, message: str) -> None:
        """Print a success message."""
        self.print(message, "success")

    def info(self, message: str, bold: bool = False) -> None:
        """Print an informational message."""
        self.print(message, "info", bold=bold)

    def muted(self, message: str) -> None:
        """Print de-emphasized text such as hints."""
        self.print(message, "muted")

    def rule(self, width: int = 40, style: str = "muted") -> None:
        """Print a horizontal separator.

        Args:
            width: Number of characters.
            style: Theme style name.
        """
        self.print("─" * width, style)

    def ask(self, prompt: str) -> str:
        """Prompt for one line of input.

        Args:
            prompt: Question shown before the cursor.

        Returns:
            The raw line the user typed.

        Raises:
            EOFError: When input is closed.
        """
        return self.console.input(Text(f"{prompt} ", style="bold info"))

    def format_match_compact(self, match: Match, zone: tzinfo | None = None) -> Text:
        """Format a match on one line, e.g. "Jan 1 | A 2 : 1 B | ✓".

        Args:
            match: Match to format.
            zone: Display timezone; None means local time.

        Returns:
            Styled single-line text.
        """
        date, _ = match.local_date_time(zone)
        team1, team2 = self._team_label(match.team1), self._team_label(match.team2)
        score = match.score or "–"
        if match.status == "live":
            teams = f"{team1} {score} {team2}"
            status = Text(f"{STATUS_ICONS['live']} LIVE", style="live")
        elif match.status == "upcoming":
            teams = f"{team1} vs {team2}"
            status = Text(f"{STATUS_ICONS['upcoming']} {eta_label(match)}", "warning")
        else:
            teams = f"{team1} {score} {team2}"
            status = Text(STATUS_ICONS["completed"], style="success")
        return Text.assemble((date, "muted"), " | ", (teams, "team"), " | ", status)

    def format_match_full(self, match: Match, zone: tzinfo | None = None) -> Text:
        """Format a match as a header line, a stats link, and a separator.

        Args:
            match: Match to format.
            zone: Display timezone; None means local time.

        Returns:
            Styled multi-line text ending with a blank line.
        """
        date, time = match.local_date_time(zone)
        teams = f"{self._team_label(match.team1)} vs {self._team_label(match.team2)}"
        line = Text.assemble(
            (f"{date}  {time}", "date_time"), " | ", (teams, "team"), " | "
        )
        if match.status == "upcoming":
            line.append(eta_label(match), style="warning")
        else:
            line.append("Score: ")
            line.append(match.score or "–", style="score")
            if match.status == "live":
                line.append(" ")
                line.append("LIVE", style="live")

        separator = "─" * min(MAX_RULE_WIDTH, self.console.width)
        return Text("\n").join(
            [
                line,
                Text(f"Stats: {match.url}", style="link"),
                Text(separator, style="muted"),
                Text(""),
            ]
        )

    def print_match(
        self, match: Match, zone: tzinfo | None = None, compact: bool = False
    ) -> None:
        """Print a match in compact or full form.

        Args:
            match: Match to print.
            zone: Display timezone; None means local time.
            compact: Use the single-line form.
        """
        if compact:
            self.print(self.format_match_compact(match, zone))
        else:
            self.print(self.format_match_full(match, zone))

    def print_stats_footer(
        self,
        displayed: int,
        cache_hits: int,
        failed: int,
        fetch_time: float,
        live_count: int = 0,
        tbd_count: int = 0,
        skipped_count: int = 0,
    ) -> None:
        """Print a one-line summary after a match listing.

        Example: Displayed: 15 matches | TBD: 5 | Cache hits: 8 | Time: 2.3s

        Args:
            displayed: Matches shown.
            cache_hits: Matches served from cache.
            failed: Matches or events that could not be loaded.
            fetch_time: Seconds the run took.
            live_count: Live matches shown.
            tbd_count: Matches skipped because teams are undecided.
            skipped_count: Matches filtered out by the view mode.
        """
        plural = "es" if displayed != 1 else ""
        parts: list[tuple[str, str | None]] = [
            (f"Displayed: {displayed} match{plural}", None)
        ]
        if skipped_count > 0:
            parts.append((f"Skipped: {skipped_count}", None))
        if tbd_count > 0:
            parts.append((f"TBD: {tbd_count}", None))
        if cache_hits > 0:
            parts.append((f"Cache hits: {cache_hits}", None))
        if failed > 0:
            parts.append((f"Failed: {failed}", "warning"))
        if live_count > 0:
            parts.append((f"Live: {live_count}", "live"))
        parts.append((f"Time: {fetch_time:.1f}s", None))

        footer = Text(style="muted")
        for index, (label, style) in enumerate(parts):
            if index:
                footer.append(" | ")
            footer.append(label, style=style)
        self.print(footer)
