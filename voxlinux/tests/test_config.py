"""Unit tests for voxapp.config I/O with an isolated XDG_DATA_HOME."""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest

import voxapp.config as config


class ConfigIOTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_DATA_HOME"] = self._tmp.name
        importlib.reload(config)

    def tearDown(self) -> None:
        if self._old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg
        importlib.reload(config)
        self._tmp.cleanup()

    def test_load_config_missing_file_returns_empty(self) -> None:
        self.assertEqual(config.load_config(), {})

    def test_save_and_load_round_trip(self) -> None:
        config.save_config({"hotkey": "ctrl", "model": "gigaam-v3"})
        self.assertEqual(
            config.load_config(), {"hotkey": "ctrl", "model": "gigaam-v3"}
        )

    def test_update_config_merges(self) -> None:
        config.save_config({"hotkey": "ctrl"})
        updated = config.update_config(model="gigaam-v3")
        self.assertEqual(updated, {"hotkey": "ctrl", "model": "gigaam-v3"})
        self.assertEqual(config.load_config(), updated)

    def test_initial_hotkey_default_when_missing(self) -> None:
        self.assertEqual(config.initial_hotkey(), config.DEFAULT_HOTKEY)

    def test_initial_hotkey_valid_stored_value(self) -> None:
        config.save_config({"hotkey": "ctrl"})
        self.assertEqual(config.initial_hotkey(), "ctrl")

    def test_initial_hotkey_invalid_falls_back_to_default(self) -> None:
        config.save_config({"hotkey": "not-a-real-hotkey"})
        self.assertEqual(config.initial_hotkey(), config.DEFAULT_HOTKEY)


if __name__ == "__main__":
    unittest.main()
