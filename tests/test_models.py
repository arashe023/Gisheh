import subprocess
import sys
import unittest


class ModelIsolationTests(unittest.TestCase):
    def test_models_and_storage_do_not_import_gtk(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from gisheh import models, state_store, library_backup, controllers; "
                'assert "gi.repository.Gtk" not in sys.modules; '
                'assert models.runtime_minutes("2h 30m") == 150',
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
