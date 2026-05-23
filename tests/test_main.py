# Tests for main.py CLI helpers.

import sys
from unittest.mock import Mock, patch

from config_profile import ConfigManager, UserProfile
from interactive import _suggest_team_names
from main import (
    CLI_COMMAND,
    apply_profile_defaults,
    get_completion_script,
    parse_args,
    run_config_command,
    run_doctor,
)
from match_extractor import Match


def make_match(team1: str, team2: str) -> Match:
    """Create a minimal Match object for testing."""
    return Match(
        date="Jan 1",
        time="12:00",
        team1=team1,
        team2=team2,
        score="0-0",
        is_live=False,
        url="https://vlr.gg/1",
        is_upcoming=True,
    )


class TestMainArgs:
    """Tests for CLI argument parsing."""

    def test_parse_args_doctor(self):
        """--doctor flag should parse correctly."""
        with patch.object(sys, "argv", ["main.py", "--doctor"]):
            args = parse_args()
        assert args.doctor is True

    def test_parse_args_quickstart(self):
        """--quickstart flag should parse correctly."""
        with patch.object(sys, "argv", ["main.py", "--quickstart"]):
            args = parse_args()
        assert args.quickstart is True

    def test_parse_args_print_completion(self):
        """--print-completion should parse shell choice."""
        with patch.object(sys, "argv", ["main.py", "--print-completion", "bash"]):
            args = parse_args()
        assert args.print_completion == "bash"

    def test_parse_args_config_set(self):
        """Config subcommand should parse key and value."""
        with patch.object(
            sys, "argv", ["main.py", "config", "set", "default-region", "americas"]
        ):
            args = parse_args()
        assert args.command == "config"
        assert args.config_command == "set"
        assert args.key == "default-region"
        assert args.value == "americas"

    def test_parse_args_completion_install(self):
        """Completion install subcommand should parse shell."""
        with patch.object(sys, "argv", ["main.py", "completion", "install", "zsh"]):
            args = parse_args()
        assert args.command == "completion"
        assert args.completion_command == "install"
        assert args.shell == "zsh"


class TestShellCompletion:
    """Tests for shell completion script generation."""

    def test_completion_scripts_include_doctor_flag(self):
        """All shell scripts should include key UX flags."""
        for shell in ("bash", "zsh", "fish"):
            script = get_completion_script(shell)
            assert "--doctor" in script
            assert "--quickstart" in script
            assert "--print-completion" in script
            assert "config" in script
            assert "completion" in script

    def test_completion_scripts_target_cli_command_only(self):
        """Completion output should bind to installed CLI, not every python command."""
        bash_script = get_completion_script("bash")
        zsh_script = get_completion_script("zsh")
        fish_script = get_completion_script("fish")

        assert CLI_COMMAND in bash_script
        assert CLI_COMMAND in zsh_script
        assert CLI_COMMAND in fish_script
        assert "complete -F _valorant_matches_completions python" not in bash_script
        assert "#compdef python" not in zsh_script
        assert "complete -c python" not in fish_script


class TestDoctor:
    """Tests for diagnostic mode."""

    def test_run_doctor_uses_discovery_probe(self):
        """Doctor should reuse discovery HTTP settings for connectivity."""
        formatter = Mock()
        formatter.info.side_effect = lambda text, bold=False: text
        formatter.success.side_effect = lambda text, bold=False: text
        formatter.error.side_effect = lambda text, bold=False: text
        formatter.warning.side_effect = lambda text, bold=False: text
        formatter.muted.side_effect = lambda text, bold=False: text

        discovery = Mock()
        discovery.can_reach_vlr.return_value = True
        discovery.discover_events.return_value = [Mock()]

        exit_code = run_doctor(formatter, discovery)

        assert exit_code == 0
        discovery.can_reach_vlr.assert_called_once_with()


class TestProfileDefaults:
    """Tests for saved profile defaults."""

    def test_apply_profile_defaults_sets_missing_cli_values(self):
        """Saved profile should fill absent CLI values."""
        args = Mock()
        args.region = None
        args.upcoming = False
        args.results = False
        args.compact = False
        args.sort = None
        args.group_by = None
        args.no_cache = False

        profile = UserProfile(
            default_region="americas",
            compact_mode=True,
            default_view_mode="results",
            default_sort="date",
            default_group_by="status",
            cache_enabled=False,
        )

        apply_profile_defaults(args, profile)

        assert args.region == "americas"
        assert args.results is True
        assert args.compact is True
        assert args.sort == "date"
        assert args.group_by == "status"
        assert args.no_cache is True

    def test_apply_profile_defaults_preserves_explicit_cli_values(self):
        """Explicit CLI values should win over saved profile."""
        args = Mock()
        args.region = "emea"
        args.upcoming = True
        args.results = False
        args.compact = True
        args.sort = "team"
        args.group_by = "date"
        args.no_cache = True

        profile = UserProfile(
            default_region="americas",
            compact_mode=False,
            default_view_mode="results",
            default_sort="date",
            default_group_by="status",
            cache_enabled=True,
        )

        apply_profile_defaults(args, profile)

        assert args.region == "emea"
        assert args.upcoming is True
        assert args.results is False
        assert args.compact is True
        assert args.sort == "team"
        assert args.group_by == "date"
        assert args.no_cache is True


class TestConfigCommand:
    """Tests for config command behavior."""

    def test_config_set_default_region_saves_profile(self, tmp_path):
        """Config set should persist default region."""
        formatter = Mock()
        formatter.success.side_effect = lambda text, bold=False: text
        formatter.error.side_effect = lambda text, bold=False: text
        formatter.muted.side_effect = lambda text, bold=False: text

        manager = ConfigManager(tmp_path / "config.json")
        args = Mock(config_command="set", key="default-region", value="americas")

        with patch("main.config_manager", manager):
            exit_code = run_config_command(args, formatter)

        assert exit_code == 0
        assert manager.load().default_region == "americas"


class TestInteractiveSuggestions:
    """Tests for fuzzy team suggestions in interactive mode."""

    def test_suggest_team_names_returns_close_match(self):
        """Fuzzy search should suggest close team names."""
        results = [
            ({"href": "/1"}, make_match("Sentinels", "Cloud9")),
            ({"href": "/2"}, make_match("Fnatic", "Team Heretics")),
        ]
        suggestions = _suggest_team_names(results, "Sentinal")
        assert "Sentinels" in suggestions
