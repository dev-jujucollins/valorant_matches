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


class TestCircleCIConfig:
    """Tests for CircleCI test job wiring."""

    def test_circleci_runs_tests_in_uv_environment(self):
        """CircleCI should install and run tests from the project uv environment."""
        config_text = (ROOT_DIR / ".circleci" / "config.yml").read_text()

        assert "python -m pip install uv" in config_text
        assert "command: uv sync" in config_text
        assert "command: uv run pytest --junitxml=junit.xml" in config_text
