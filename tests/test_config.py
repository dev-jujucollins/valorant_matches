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
