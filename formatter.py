# Formatter class using Rich library for consistent terminal styling.
from rich.console import Console
from rich.text import Text
from rich.theme import Theme


# Custom theme for consistent styling across the application
VALORANT_THEME = Theme({
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
})


class Formatter:
    """Enhanced class for formatting text output using Rich library."""

    def __init__(self):
        self.console = Console(theme=VALORANT_THEME, force_terminal=True)

    def format(self, text: str, style: str, bold: bool = False, underline: bool = False) -> str:
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


# Global formatter instance for convenience
formatter = Formatter()
