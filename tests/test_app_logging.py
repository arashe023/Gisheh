from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh import app_logging as gisheh


class ApplicationLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        logger = logging.getLogger(gisheh.APP_ID)
        for handler in tuple(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        gisheh._APP_LOGGER = None

    def test_log_is_private_and_readable_in_application(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_STATE_HOME": temporary_directory},
                clear=False,
            ),
        ):
            gisheh.application_logger().info("Simkl sync test entry")
            path = gisheh.application_log_file()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("Simkl sync test entry", gisheh.read_application_log())


if __name__ == "__main__":
    unittest.main()
