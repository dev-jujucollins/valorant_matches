# Formatter class using Rich library for consistent terminal styling.
from rich.console import Console
from rich.text import Text
from rich.theme import Theme

# Custom theme for consistent styling across the application
VALORANT_THEME = Theme(
    {
        "error": "bold bright_red",
        "warning": "bright_yellow",
        "success": "bright_green",
        "info": "bright_blue",
        "primary": "bright_cyan",
        "secondary": "bright_magenta",
        "muted": "bright_black",
        "highlight": "bold bright_white",
        "accent": "bright_yellow",
        "team": "bold bright_cyan",
        "score": "bold bright_green",
        "live": "bold bright_red",
        "date_time": "bright_blue",
        "link": "underline bright_magenta",
    }
)


class Formatter:
    """Enhanced class for formatting text output using Rich library."""

    def __init__(self):
        self.console = Console(theme=VALORANT_THEME, force_terminal=True)

    def format(
        self, text: str, style: str, bold: bool = False, underline: bool = False
    ) -> str:
        """Format text with a style and optional modifiers."""
        style_parts = []
        if bold:
            style_parts.append("bold")
        if underline:
            style_parts.append("underline")
        style_parts.append(style)

        formatted = Text(text)
        formatted.stylize(" ".join(style_parts))

        # Return as string with ANSI codes for compatibility
        with self.console.capture() as capture:
            self.console.print(formatted, end="")
        return capture.get()

    def error(self, text: str, bold: bool = True) -> str:
        """Format error messages."""
        return self.format(text, "error", bold=bold)

    def warning(self, text: str, bold: bool = False) -> str:
        """Format warning messages."""
        return self.format(text, "warning", bold=bold)

    def success(self, text: str, bold: bool = False) -> str:
        """Format success messages."""
        return self.format(text, "success", bold=bold)

    def info(self, text: str, bold: bool = False) -> str:
        """Format info messages."""
        return self.format(text, "info", bold=bold)

    def primary(self, text: str, bold: bool = False) -> str:
        """Format primary content."""
        return self.format(text, "primary", bold=bold)

    def secondary(self, text: str, bold: bool = False) -> str:
        """Format secondary content."""
        return self.format(text, "secondary", bold=bold)

    def muted(self, text: str, bold: bool = False) -> str:
        """Format muted/secondary text."""
        return self.format(text, "muted", bold=bold)

    def highlight(self, text: str, bold: bool = True) -> str:
        """Format highlighted text."""
        return self.format(text, "highlight", bold=bold)

    def accent(self, text: str, bold: bool = False) -> str:
        """Format accent text."""
        return self.format(text, "accent", bold=bold)

    def match_header(self, text: str) -> str:
        """Format match headers with special styling."""
        return self.format(text, "bright_white", bold=True, underline=True)

    def team_name(self, text: str) -> str:
        """Format team names."""
        return self.format(text, "team")

    def score(self, text: str) -> str:
        """Format scores."""
        return self.format(text, "score")

    def live_status(self, text: str) -> str:
        """Format live match status."""
        return self.format(text, "live")

    def date_time(self, text: str) -> str:
        """Format date and time."""
        return self.format(text, "date_time")

    def stats_link(self, text: str) -> str:
        """Format stats links."""
        return self.format(text, "link")

    def format_match_compact(
        self,
        date: str,
        team1: str,
        team2: str,
        score: str,
        is_live: bool = False,
        is_upcoming: bool = False,
    ) -> str:
        """Format match in compact single-line format.

        Example: Thursday | Sentinels 2-1 Cloud9 | LIVE
        """
        # Build teams vs teams string with score
        if is_live:
            status_icon = STATUS_ICONS["live"]
            status = self.live_status(f"{status_icon} LIVE")
            match_str = f"{team1} {score} {team2}"
        elif is_upcoming:
            status_icon = STATUS_ICONS["upcoming"]
            status = self.warning(f"{status_icon} {score}")
            match_str = f"{team1} vs {team2}"
        else:
            status_icon = STATUS_ICONS["completed"]
            status = self.success(status_icon)
            match_str = f"{team1} {score} {team2}"

        return f"{self.muted(date)} | {self.team_name(match_str)} | {status}"

    def print_stats_footer(
        self,
        displayed: int,
        cache_hits: int,
        failed: int,
        fetch_time: float,
        live_count: int = 0,
        tbd_count: int = 0,
    ) -> None:
        """Print statistics footer after match display.

        Example: Displayed: 15 matches | TBD: 5 | Cache hits: 8 | Time: 2.3s
        """
        parts = [
            f"Displayed: {displayed} match{'es' if displayed != 1 else ''}",
        ]
        if tbd_count > 0:
            parts.append(self.muted(f"TBD: {tbd_count}"))
        if cache_hits > 0:
            parts.append(f"Cache hits: {cache_hits}")
        if failed > 0:
            parts.append(self.warning(f"Failed: {failed}"))
        if live_count > 0:
            parts.append(self.live_status(f"Live: {live_count}"))
        parts.append(f"Time: {fetch_time:.1f}s")

        # Use print() directly since parts may already contain ANSI codes
        print(self.muted(" | ".join(parts)))


# Status icons for match states
STATUS_ICONS = {
    "live": "\u25cf",  # Bullet (red circle in most terminals)
    "upcoming": "\u23f1",  # Stopwatch
    "completed": "\u2713",  # Checkmark
}

# Global formatter instance for convenience
formatter = Formatter()
