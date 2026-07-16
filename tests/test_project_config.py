import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _package_name(requirement: str) -> str:
    """Extract a normalized package name from a requirement string."""
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        requirement = requirement.split(separator, maxsplit=1)[0]
    return requirement.strip()


class TestRequirementsFile:
    """Tests for dependency metadata."""

    def test_requirements_include_runtime_dependencies(self):
        """requirements.txt should stay aligned with runtime dependencies."""
        pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())
        runtime_dependencies = {
            _package_name(requirement)
            for requirement in pyproject["project"]["dependencies"]
        }
        requirements = {
            _package_name(line)
            for line in (ROOT_DIR / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }

        assert runtime_dependencies <= requirements


class TestProjectLayout:
    """Tests for package organization and entry-point wiring."""

    def test_cli_entry_point_uses_cli_package(self):
        """Installed command should target the grouped CLI application."""
        pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text())

        assert (
            pyproject["project"]["scripts"]["valorant-matches"]
            == "valorant_matches.cli.app:main"
        )

    def test_source_modules_are_grouped_by_responsibility(self):
        """CLI, output, and scraping code should live in focused packages."""
        package_dir = ROOT_DIR / "src" / "valorant_matches"
        expected_modules = {
            "cli/app.py",
            "cli/display.py",
            "cli/interactive.py",
            "output/exporters.py",
            "output/formatter.py",
            "scraping/client.py",
            "scraping/discovery.py",
            "scraping/event_selection.py",
            "scraping/matches.py",
            "scraping/runner.py",
        }

        assert all((package_dir / module).is_file() for module in expected_modules)


class TestGitHubActionsConfig:
    """Tests for GitHub Actions CI wiring."""

    def test_ci_runs_checks_in_uv_environment(self):
        """CI should install and run checks from the project uv environment."""
        config_text = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text()

        assert "actions/checkout@v6" in config_text
        assert "astral-sh/setup-uv@" in config_text
        assert 'python-version: "3.11"' in config_text
        assert "enable-cache: true" in config_text
        assert "run: uv sync --locked" in config_text
        assert "run: uv run ruff format --check ." in config_text
        assert "run: uv run ruff check ." in config_text
        assert "run: uv run pyright" in config_text
        assert "run: uv run pytest --junitxml=test-results/junit.xml" in config_text
        assert "actions/upload-artifact@v4" in config_text

    def test_ci_locked_sync_requires_committed_lockfile(self):
        """Locked CI sync should have a checked-in uv.lock file."""
        config_text = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text()

        assert "run: uv sync --locked" in config_text
        assert (ROOT_DIR / "uv.lock").exists()

    def test_legacy_automation_is_removed(self):
        """CircleCI and OpenCode comment automation should stay removed."""
        assert not (ROOT_DIR / ".circleci").exists()
        assert not (ROOT_DIR / ".github" / "workflows" / "opencode.yml").exists()
