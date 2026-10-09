"""Isolated test entrypoint; GTK tests require a usable display, never skip it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PURE_MODULES = {
    "test_image_http",
    "test_simkl_client",
    "test_tmdb_client",
    "test_tmdb_content_language",
    "test_transactions",
    "test_controllers",
    "test_app_logging",
    "test_state_store",
    "test_library_backup",
    "test_models",
    "test_jobs",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=("unit", "gtk"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gisheh-tests-") as temporary:
        for key, directory in (
            ("XDG_STATE_HOME", "state"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
        ):
            os.environ[key] = str(Path(temporary) / directory)
        os.environ["GISHEH_STATE_FILE"] = str(Path(temporary) / "state.json")
        os.environ["GSETTINGS_BACKEND"] = "memory"
        os.environ["GIO_USE_VFS"] = "local"
        os.environ["GTK_A11Y"] = "test"
        os.environ["SIMKL_ACCESS_TOKEN"] = ""
        os.environ["TMDB_READ_TOKEN"] = ""
        os.environ["PYTHONPATH"] = str(ROOT / "src")
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        if args.suite == "gtk":
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gtk

            if not Gtk.init_check():
                parser.error(
                    "GTK tests require a display; use xvfb-run and dbus-run-session"
                )
            Adw.init()
        suite = unittest.TestSuite()
        for source in sorted((ROOT / "tests").glob("test_*.py")):
            if (source.stem in PURE_MODULES) == (args.suite == "unit"):
                suite.addTests(
                    unittest.defaultTestLoader.loadTestsFromName(source.stem)
                )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
