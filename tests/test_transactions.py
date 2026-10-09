from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from gisheh.transactions import persisted_change


class TransactionTests(unittest.TestCase):
    def controller(self):
        return SimpleNamespace(bookmarks={"old"}, _toast=Mock(), _app_log=Mock())

    def test_failed_local_write_rolls_back_and_never_reports_success(self):
        controller = self.controller()

        @persisted_change
        def change(self):
            self.bookmarks.add("new")
            raise OSError("disk full")

        change(controller)
        self.assertEqual(controller.bookmarks, {"old"})
        controller._toast.assert_called_once()
        self.assertIn("previous local state", controller._toast.call_args.args[0])

    def test_remote_success_is_not_rolled_back_or_retried(self):
        controller = self.controller()

        @persisted_change
        def change(self):
            self._remote_commit = True
            self.bookmarks.add("remote")
            raise OSError("disk full")

        change(controller)
        self.assertEqual(controller.bookmarks, {"old", "remote"})
        self.assertIn("Simkl was updated", controller._toast.call_args.args[0])
        self.assertFalse(controller._remote_commit)
