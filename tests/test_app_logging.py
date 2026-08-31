from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))

import cineshelf


class ApplicationLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        logger = logging.getLogger(cineshelf.APP_ID)
        for handler in tuple(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        cineshelf._APP_LOGGER = None

    def test_log_is_private_and_readable_in_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {"XDG_STATE_HOME": temporary_directory},
                clear=False,
            ):
                cineshelf.application_logger().info("Simkl sync test entry")
                path = cineshelf.application_log_file()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn("Simkl sync test entry", cineshelf.read_application_log())


if __name__ == "__main__":
    unittest.main()
