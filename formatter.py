class Formatter:  # Class for formatting text output with colors
    def __init__(self):
        self.colors = {
            "white": "\033[37m",
            "red": "\033[31m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "cyan": "\033[36m",
            "reset": "\033[0m"
        }

    def format(self, text, color):
        return f"{self.colors[color]}{text}{self.colors['reset']}"

formatter = Formatter()