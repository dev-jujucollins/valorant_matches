class Formatter:  # Enhanced class for formatting text output with colors and styles
    def __init__(self):
        # Enhanced color palette with better contrast and readability
        self.colors = {
            # Basic colors
            "black": "\033[30m",
            "red": "\033[31m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "cyan": "\033[36m",
            "white": "\033[37m",
            # Bright colors for better readability
            "bright_black": "\033[90m",
            "bright_red": "\033[91m",
            "bright_green": "\033[92m",
            "bright_yellow": "\033[93m",
            "bright_blue": "\033[94m",
            "bright_magenta": "\033[95m",
            "bright_cyan": "\033[96m",
            "bright_white": "\033[97m",
            # Background colors
            "bg_black": "\033[40m",
            "bg_red": "\033[41m",
            "bg_green": "\033[42m",
            "bg_yellow": "\033[43m",
            "bg_blue": "\033[44m",
            "bg_magenta": "\033[45m",
            "bg_cyan": "\033[46m",
            "bg_white": "\033[47m",
            # Text styles
            "bold": "\033[1m",
            "dim": "\033[2m",
            "italic": "\033[3m",
            "underline": "\033[4m",
            "blink": "\033[5m",
            "reverse": "\033[7m",
            "strikethrough": "\033[9m",
            # Reset
            "reset": "\033[0m",
        }

        # Semantic color mappings for consistent theming
        self.semantic_colors = {
            "error": "bright_red",
            "warning": "bright_yellow",
            "success": "bright_green",
            "info": "bright_blue",
            "primary": "bright_cyan",
            "secondary": "bright_magenta",
            "muted": "bright_black",
            "highlight": "bright_white",
            "accent": "bright_yellow",
        }

    def format(self, text, color_or_style, bold=False, underline=False):
        """Format text with color and optional styles"""
        if color_or_style in self.semantic_colors:
            color = self.semantic_colors[color_or_style]
        else:
            color = color_or_style

        style_codes = []
        if color in self.colors:
            style_codes.append(self.colors[color])
        if bold:
            style_codes.append(self.colors["bold"])
        if underline:
            style_codes.append(self.colors["underline"])

        return f"{''.join(style_codes)}{text}{self.colors['reset']}"

    # Semantic formatting methods for common use cases
    def error(self, text, bold=True):
        """Format error messages"""
        return self.format(text, "error", bold=bold)

    def warning(self, text, bold=False):
        """Format warning messages"""
        return self.format(text, "warning", bold=bold)

    def success(self, text, bold=False):
        """Format success messages"""
        return self.format(text, "success", bold=bold)

    def info(self, text, bold=False):
        """Format info messages"""
        return self.format(text, "info", bold=bold)

    def primary(self, text, bold=False):
        """Format primary content"""
        return self.format(text, "primary", bold=bold)

    def secondary(self, text, bold=False):
        """Format secondary content"""
        return self.format(text, "secondary", bold=bold)

    def muted(self, text, bold=False):
        """Format muted/secondary text"""
        return self.format(text, "muted", bold=bold)

    def highlight(self, text, bold=True):
        """Format highlighted text"""
        return self.format(text, "highlight", bold=bold)

    def accent(self, text, bold=False):
        """Format accent text"""
        return self.format(text, "accent", bold=bold)

    def match_header(self, text):
        """Format match headers with special styling"""
        return self.format(text, "bright_white", bold=True, underline=True)

    def team_name(self, text):
        """Format team names"""
        return self.format(text, "bright_cyan", bold=True)

    def score(self, text):
        """Format scores"""
        return self.format(text, "bright_green", bold=True)

    def live_status(self, text):
        """Format live match status"""
        return self.format(text, "bright_red", bold=True)

    def date_time(self, text):
        """Format date and time"""
        return self.format(text, "bright_blue", bold=False)

    def stats_link(self, text):
        """Format stats links"""
        return self.format(text, "bright_magenta", bold=False, underline=True)


formatter = Formatter()
