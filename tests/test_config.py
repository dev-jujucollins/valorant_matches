# Tests for the config module.
import os
from unittest.mock import patch


class TestEnvHelpers:
    def test_get_env_bool_true_values(self):
        """Test get_env_bool with various true values."""
        from valorant_matches.config import get_env_bool

        with patch.dict(os.environ, {"TEST_VAR": "true"}):
            assert get_env_bool("TEST_VAR") is True

        with patch.dict(os.environ, {"TEST_VAR": "1"}):
            assert get_env_bool("TEST_VAR") is True

        with patch.dict(os.environ, {"TEST_VAR": "yes"}):
            assert get_env_bool("TEST_VAR") is True

        with patch.dict(os.environ, {"TEST_VAR": "on"}):
            assert get_env_bool("TEST_VAR") is True

    def test_get_env_bool_false_values(self):
        """Test get_env_bool with various false values."""
        from valorant_matches.config import get_env_bool

        with patch.dict(os.environ, {"TEST_VAR": "false"}):
            assert get_env_bool("TEST_VAR") is False

        with patch.dict(os.environ, {"TEST_VAR": "0"}):
            assert get_env_bool("TEST_VAR") is False

        with patch.dict(os.environ, {"TEST_VAR": "no"}):
            assert get_env_bool("TEST_VAR") is False

    def test_get_env_bool_default(self):
        """Test get_env_bool returns default when env var not set."""
        from valorant_matches.config import get_env_bool

        with patch.dict(os.environ, {}, clear=True):
            assert get_env_bool("NONEXISTENT_VAR", default=True) is True
            assert get_env_bool("NONEXISTENT_VAR", default=False) is False

    def test_get_env_int_valid(self):
        """Test get_env_int with valid integer values."""
        from valorant_matches.config import get_env_int

        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert get_env_int("TEST_INT", default=0) == 42

        with patch.dict(os.environ, {"TEST_INT": "0"}):
            assert get_env_int("TEST_INT", default=10) == 0

    def test_get_env_int_invalid(self):
        """Test get_env_int returns default for invalid values."""
        from valorant_matches.config import get_env_int

        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            assert get_env_int("TEST_INT", default=10) == 10

    def test_get_env_int_default(self):
        """Test get_env_int returns default when env var not set."""
        from valorant_matches.config import get_env_int

        with patch.dict(os.environ, {}, clear=True):
            assert get_env_int("NONEXISTENT_VAR", default=25) == 25


class TestEnvFloat:
    def test_get_env_float(self):
        """Floats parse; invalid values fall back to the default."""
        from valorant_matches.config import get_env_float

        with patch.dict(os.environ, {"TEST_FLOAT": "0.25"}):
            assert get_env_float("TEST_FLOAT", 1.0) == 0.25
        with patch.dict(os.environ, {"TEST_FLOAT": "fast"}):
            assert get_env_float("TEST_FLOAT", 1.0) == 1.0


class TestLoggingConfig:
    def test_logging_config_is_valid(self, tmp_path):
        """The config applies cleanly and keeps the file handler lazy."""
        import logging
        import logging.config

        from rich.logging import RichHandler

        from valorant_matches.config import build_logging_config

        config = build_logging_config()
        config["handlers"]["file"]["filename"] = str(tmp_path / "app.log")
        config["disable_existing_loggers"] = False
        app_logger = logging.getLogger("valorant_matches")
        saved = (app_logger.handlers[:], app_logger.level, app_logger.propagate)
        try:
            logging.config.dictConfig(config)
            handlers = app_logger.handlers
            assert any(isinstance(handler, RichHandler) for handler in handlers)
            assert not (tmp_path / "app.log").exists()
        finally:
            for handler in app_logger.handlers:
                handler.close()
            app_logger.handlers, app_logger.level, app_logger.propagate = saved


def test_user_agent_identifies_project():
    """Requests name this tool rather than impersonating a browser."""
    from valorant_matches.config import HEADERS, PROJECT_URL

    assert HEADERS["User-Agent"].startswith("valorant-matches/")
    assert PROJECT_URL in HEADERS["User-Agent"]
