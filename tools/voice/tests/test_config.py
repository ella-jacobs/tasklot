"""Tests for Settings.from_env: defaults, overrides, and malformed values."""
import os
import unittest
from pathlib import Path

from tasklot.config import (
    DEFAULT_PORT, LLM_TIMEOUT_S, RESET_DELAY_S, VOICE_DIR, ConfigError, Settings,
)


class SettingsTest(unittest.TestCase):
    """Environment variables map onto Settings fields."""

    def test_defaults_hold_no_personal_paths(self):
        s = Settings.from_env({})
        self.assertEqual(s.port, DEFAULT_PORT)
        self.assertEqual(s.reset_delay, RESET_DELAY_S)
        self.assertTrue(s.llm_enabled)
        self.assertEqual(s.llm_timeout, LLM_TIMEOUT_S)
        self.assertEqual(s.whisper_model, os.path.expanduser("~/.whisper-models/ggml-base.en.bin"))
        self.assertEqual(s.cmd_file, Path("/tmp/tasklot_cmd.txt"))
        self.assertEqual(s.tasks_file, VOICE_DIR / "tasks.json")

    def test_overrides(self):
        s = Settings.from_env({"TASKLOT_PORT": "/dev/ttyACM0", "TASKLOT_LLM": "0",
                               "TASKLOT_LLM_TIMEOUT": "5", "TASKLOT_RESET_DELAY": "0.5",
                               "TASKLOT_CMD_FILE": "/var/tmp/cmd.txt",
                               "TASKLOT_FAKE_TRANSCRIPT": "call mom"})
        self.assertEqual((s.port, s.llm_enabled, s.llm_timeout, s.reset_delay),
                         ("/dev/ttyACM0", False, 5.0, 0.5))
        self.assertEqual(s.cmd_file, Path("/var/tmp/cmd.txt"))
        self.assertEqual(s.fake_transcript, "call mom")

    def test_malformed_number_names_the_variable(self):
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({"TASKLOT_LLM_TIMEOUT": "soon"})
        self.assertIn("TASKLOT_LLM_TIMEOUT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
