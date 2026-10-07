# Tests for CLI argument parsing, subcommands, and dispatch.

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from valorant_matches.cli.app import (
    CLI_COMMAND,
    _completion_words,
    build_parser,
    get_completion_script,
    list_regions,
    main,
    parse_args,
    run,
    run_config_command,
    run_doctor,
)
from valorant_matches.output.formatter import Formatter
from valorant_matches.profile import ConfigManager, UserProfile


@pytest.fixture
def manager(tmp_path: Path):
    """Point config commands at a temporary profile file."""
    manager = ConfigManager(tmp_path / "config.json")
    with patch("valorant_matches.cli.app.config_manager", manager):
        yield manager


def config(*argv: str) -> int:
    """Run a config subcommand."""
    return run_config_command(parse_args(["config", *argv]), Formatter())


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_flags(self) -> None:
        """Simple flags parse."""
        args = parse_args(["--doctor", "--quickstart"])
        assert args.doctor and args.quickstart

    def test_cache_and_compact_are_tristate(self) -> None:
        """Unset, on, and off are distinguishable."""
        assert parse_args([]).cache is None
        assert parse_args(["--cache"]).cache is True
        assert parse_args(["--no-cache"]).cache is False
        assert parse_args(["--no-compact"]).compact is False

    def test_config_set(self) -> None:
        """Config subcommand parses key and value."""
        args = parse_args(["config", "set", "default-region", "americas"])
        assert (args.command, args.config_command) == ("config", "set")
        assert (args.key, args.value) == ("default-region", "americas")

    def test_unknown_config_get_key_rejected(self) -> None:
        """config get only accepts known keys."""
        with pytest.raises(SystemExit):
            parse_args(["config", "get", "add_favorite_team"])

    def test_completion_install(self) -> None:
        """Completion install parses the shell."""
        args = parse_args(["completion", "install", "zsh"])
        assert (args.command, args.completion_command, args.shell) == (
            "completion",
            "install",
            "zsh",
        )

    def test_help_lists_regions_from_aliases(self, capsys) -> None:
        """The epilog is generated from the region table."""
        with pytest.raises(SystemExit):
            parse_args(["--help"])
        assert "americas (am)" in capsys.readouterr().out


class TestShellCompletion:
    """Tests for shell completion script generation."""

    def test_words_come_from_parser(self) -> None:
        """Every option and subcommand is completed, with no extras."""
        words = _completion_words(build_parser())
        for expected in ("config", "completion", "--doctor", "--watch", "-r", "--help"):
            assert expected in words
        assert "--print-completion" not in words

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_scripts_target_cli_command(self, shell: str) -> None:
        """Completion binds to the installed CLI, not every python command."""
        script = get_completion_script(shell)
        assert CLI_COMMAND in script
        assert "--timezone" in script and "americas" in script
        assert "python" not in script

    def test_print_and_install(self, tmp_path: Path, capsys) -> None:
        """print writes the script; install writes it under the home dir."""
        assert run(parse_args(["completion", "print", "bash"]), Formatter()) == 0
        assert "complete -F" in capsys.readouterr().out
        with (
            patch("valorant_matches.cli.app.Path.home", return_value=tmp_path),
            patch("valorant_matches.cli.app.shutil.which", return_value=None),
        ):
            assert run(parse_args(["completion", "install", "zsh"]), Formatter()) == 0
        assert (tmp_path / ".zfunc" / f"_{CLI_COMMAND}").exists()
        output = capsys.readouterr().out
        assert "not found on PATH" in output and "fpath" in output


class TestConfigCommand:
    """Tests for config subcommands."""

    def test_set_and_get_each_key(self, manager: ConfigManager, capsys) -> None:
        """Every key can be set and read back."""
        for key, value in [
            ("default-region", "emea"),
            ("default-view", "results"),
            ("compact", "yes"),
            ("sort", "date"),
            ("group-by", "status"),
            ("cache", "off"),
        ]:
            assert config("set", key, value) == 0
        profile = ConfigManager(manager.config_path).load()
        assert profile == UserProfile(
            default_region="emea",
            default_view_mode="results",
            compact_mode=True,
            default_sort="date",
            default_group_by="status",
            cache_enabled=False,
        )
        capsys.readouterr()
        assert config("get", "sort") == 0
        assert capsys.readouterr().out == "date\n"

    def test_none_clears_values(self, manager: ConfigManager) -> None:
        """ "none" clears sort, grouping, and region."""
        config("set", "sort", "team")
        config("set", "default-region", "am")
        assert config("set", "sort", "none") == 0
        assert config("set", "default-region", "none") == 0
        assert manager.load().default_sort is None
        assert manager.load().default_region is None

    @pytest.mark.parametrize(
        ("key", "value", "message"),
        [
            ("default-region", "mars", "default-region must be one of"),
            ("default-view", "some", "default-view must be one of"),
            ("compact", "maybe", "expected one of"),
            ("sort", "score", "sort must be one of"),
        ],
    )
    def test_invalid_values(
        self, manager: ConfigManager, capsys, key: str, value: str, message: str
    ) -> None:
        """Invalid values are rejected without saving."""
        assert config("set", key, value) == 1
        assert message in capsys.readouterr().out
        assert not manager.config_path.exists()

    def test_get_all(self, manager: ConfigManager, capsys) -> None:
        """config get prints every key."""
        assert config("get") == 0
        output = capsys.readouterr().out
        assert "default-region: (none)" in output
        assert "favorite-teams: (none)" in output

    def test_favorites(self, manager: ConfigManager, capsys) -> None:
        """Favorites can be added, listed, and removed."""
        assert config("favorite", "add") == 1
        assert config("favorite", "add", "Sentinels") == 0
        assert config("favorite", "list") == 0
        assert config("get", "favorite-teams") == 0
        assert config("favorite", "remove", "sentinels") == 0
        assert config("favorite", "remove", "Cloud9") == 0
        output = capsys.readouterr().out
        assert "Team name required." in output
        assert output.splitlines().count("Sentinels") == 2
        assert "Removed favorite team: sentinels" in output
        assert "Favorite team not found: Cloud9" in output

    def test_reset(self, manager: ConfigManager) -> None:
        """reset deletes the saved profile."""
        config("set", "compact", "true")
        assert config("reset") == 0
        assert not manager.config_path.exists()


class TestDoctor:
    """Tests for diagnostic mode."""

    def test_all_checks_pass(self, capsys) -> None:
        """Doctor reuses discovery for connectivity and reports success."""
        discovery = Mock()
        discovery.can_reach_vlr.return_value = True
        discovery.discover_events.return_value = [Mock()]
        assert run_doctor(Formatter(), discovery) == 0
        discovery.can_reach_vlr.assert_called_once_with()
        assert "Diagnostics passed" in capsys.readouterr().out

    def test_failures_are_counted(self, tmp_path: Path, capsys) -> None:
        """Each failed check is reported with guidance."""
        blocker = tmp_path / "file"
        blocker.write_text("")
        discovery = Mock()
        discovery.can_reach_vlr.return_value = False
        discovery.discover_events.return_value = []
        with patch("valorant_matches.cli.app.CACHE_DIR", blocker / "cache"):
            assert run_doctor(Formatter(), discovery) == 1
        output = capsys.readouterr().out
        assert "3 issue(s)" in output
        assert str(blocker / "cache") in output


class TestListRegions:
    """Tests for --list-regions output."""

    def test_groups_events_by_region(self, capsys) -> None:
        """Events print under their region aliases."""
        discovery = Mock(is_stale=False)
        discovery.discover_events.return_value = [
            SimpleNamespace(
                event_id="2", name="VCT 2026: EMEA", status="ongoing", region="emea"
            )
        ]
        assert list_regions(Formatter(), discovery, force_refresh=True) == 0
        discovery.discover_events.assert_called_once_with(force_refresh=True)
        output = capsys.readouterr().out
        assert "emea, eu:" in output
        assert "- 2: VCT 2026: EMEA [ongoing]" in output


class TestRun:
    """Tests for top-level dispatch."""

    def _run(self, *argv: str, profile: UserProfile | None = None) -> tuple[int, dict]:
        """Run dispatch with collaborators mocked out."""
        mocks: dict = {}
        with (
            patch(
                "valorant_matches.cli.app.config_manager.load",
                return_value=profile or UserProfile(),
            ),
            patch("valorant_matches.cli.app.EventDiscovery") as mocks["discovery"],
            patch("valorant_matches.cli.app.run_cli_mode", return_value=0) as mocks[
                "cli"
            ],
            patch(
                "valorant_matches.cli.app.run_interactive_mode", return_value=0
            ) as mocks["interactive"],
            patch("valorant_matches.cli.app.MatchCache") as mocks["cache"],
        ):
            code = run(parse_args(list(argv)), Formatter())
        return code, mocks

    def test_quickstart(self, capsys) -> None:
        """Quickstart prints installed-command examples."""
        assert self._run("--quickstart")[0] == 0
        output = capsys.readouterr().out
        assert f"{CLI_COMMAND} --doctor" in output
        assert "uv run" not in output

    def test_clear_cache(self, capsys) -> None:
        """--clear-cache clears even when caching is disabled."""
        code, mocks = self._run("--clear-cache")
        assert code == 0
        mocks["cache"].assert_called_once_with(enabled=True)

    def test_favorites_without_teams(self, capsys) -> None:
        """--favorites needs saved teams."""
        assert self._run("--favorites")[0] == 2
        assert "No favorite teams saved" in capsys.readouterr().out

    def test_watch_needs_target(self, capsys) -> None:
        """--watch, --today, and --timezone need a region or saved default."""
        assert self._run("--today")[0] == 2

    def test_no_target_opens_interactive(self) -> None:
        """Without a target the menu opens with resolved options."""
        _, mocks = self._run("--sort", "team")
        mocks["cli"].assert_not_called()
        assert mocks["interactive"].call_args.args[2].sort_by == "team"

    def test_saved_region_runs_cli(self) -> None:
        """A saved default region runs CLI mode."""
        _, mocks = self._run(profile=UserProfile(default_region="emea"))
        assert mocks["cli"].call_args.args[0].region == "emea"
        mocks["interactive"].assert_not_called()

    def test_interactive_after_cli(self) -> None:
        """--interactive continues into the menu after results."""
        _, mocks = self._run("-r", "am", "--interactive")
        mocks["cli"].assert_called_once()
        mocks["interactive"].assert_called_once()

    def test_season_reaches_discovery(self) -> None:
        """--season selects the discovery year."""
        _, mocks = self._run("--season", "2025", "-r", "am")
        mocks["discovery"].assert_called_once_with(season=2025)


def test_main_exits_with_run_code(tmp_path: Path) -> None:
    """main configures logging and exits with run's status."""
    with (
        patch.object(sys, "argv", ["valorant-matches", "--list-regions"]),
        patch("valorant_matches.cli.app.APP_DIR", tmp_path),
        patch("valorant_matches.cli.app.logging.config.dictConfig") as dict_config,
        patch("valorant_matches.cli.app.run", return_value=1),
        pytest.raises(SystemExit) as exit_result,
    ):
        main()
    assert exit_result.value.code == 1
    dict_config.assert_called_once()
