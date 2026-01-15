# Tests for the config module.
import os
from unittest.mock import patch


class TestEnvHelpers:
    def test_get_env_bool_true_values(self):
        """Test get_env_bool with various true values."""
        from config import get_env_bool

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
        from config import get_env_bool

        with patch.dict(os.environ, {"TEST_VAR": "false"}):
            assert get_env_bool("TEST_VAR") is False

        with patch.dict(os.environ, {"TEST_VAR": "0"}):
            assert get_env_bool("TEST_VAR") is False

        with patch.dict(os.environ, {"TEST_VAR": "no"}):
            assert get_env_bool("TEST_VAR") is False

    def test_get_env_bool_default(self):
        """Test get_env_bool returns default when env var not set."""
        from config import get_env_bool

        with patch.dict(os.environ, {}, clear=True):
            assert get_env_bool("NONEXISTENT_VAR", default=True) is True
            assert get_env_bool("NONEXISTENT_VAR", default=False) is False

    def test_get_env_int_valid(self):
        """Test get_env_int with valid integer values."""
        from config import get_env_int

        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert get_env_int("TEST_INT", default=0) == 42

        with patch.dict(os.environ, {"TEST_INT": "0"}):
            assert get_env_int("TEST_INT", default=10) == 0

    def test_get_env_int_invalid(self):
        """Test get_env_int returns default for invalid values."""
        from config import get_env_int

        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            assert get_env_int("TEST_INT", default=10) == 10

    def test_get_env_int_default(self):
        """Test get_env_int returns default when env var not set."""
        from config import get_env_int

        with patch.dict(os.environ, {}, clear=True):
            assert get_env_int("NONEXISTENT_VAR", default=25) == 25


class TestConfigValues:
    def test_base_url(self):
        """Test BASE_URL is set correctly."""
        from config import BASE_URL
        assert BASE_URL == "https://vlr.gg"

    def test_events_defined(self):
        """Test EVENTS dictionary is populated."""
        from config import EVENTS
        assert len(EVENTS) > 0
        assert "1" in EVENTS

    def test_event_structure(self):
        """Test Event dataclass structure."""
        from config import EVENTS
        event = EVENTS["1"]

        assert hasattr(event, "name")
        assert hasattr(event, "url")
        assert hasattr(event, "series_id")
        assert event.name is not None
        assert event.url is not None

    def test_headers_defined(self):
        """Test HEADERS is defined with User-Agent."""
        from config import HEADERS
        assert "User-Agent" in HEADERS

    def test_logging_config_structure(self):
        """Test LOGGING_CONFIG has required structure."""
        from config import LOGGING_CONFIG

        assert "version" in LOGGING_CONFIG
        assert "formatters" in LOGGING_CONFIG
        assert "handlers" in LOGGING_CONFIG
        assert "loggers" in LOGGING_CONFIG
