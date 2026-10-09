import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gi.repository import Gio
from gisheh.application import GishehApplication


class StartupRecoveryTests(unittest.TestCase):
    def test_invalid_state_shows_recovery_without_starting_onboarding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("broken")
            with patch.dict(os.environ, {"GISHEH_STATE_FILE": str(path)}):
                app = GishehApplication()
                app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
                app.register(None)
                app.activate()
                try:
                    self.assertIsNone(app.welcome_window)
                    self.assertIsNone(app.controller)
                    self.assertEqual(len(app.get_windows()), 1)
                    self.assertEqual(path.read_text(), "broken")
                finally:
                    for window in app.get_windows():
                        window.destroy()
