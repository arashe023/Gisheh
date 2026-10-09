from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gisheh import state_store as state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "profile/state.json"

    def test_missing_and_migration_preserve_unknown_data(self):
        self.assertEqual(state.inspect_state(self.path).status, "missing")
        self.path.parent.mkdir()
        self.path.write_text('{"custom": {"value": 2}, "bookmarks": ["one"]}')
        payload = state.read_state(self.path)
        self.assertEqual(payload["schema_version"], 1)
        state.write_state(payload, self.path)
        self.assertEqual(state.read_state(self.path)["custom"], {"value": 2})
        self.assertNotIn(
            "schema_version", json.loads(state.backup_file(self.path).read_text())
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(state.backup_file(self.path).stat().st_mode & 0o777, 0o600)

    def test_corrupt_and_future_are_never_overwritten(self):
        self.path.parent.mkdir()
        for contents, status in [
            ("bad", "corrupt"),
            ("[]", "corrupt"),
            ('{"schema_version": 999}', "future"),
            ('{"ratings": []}', "corrupt"),
        ]:
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                self.assertEqual(state.inspect_state(self.path).status, status)
                with self.assertRaises(state.StateError):
                    state.write_state({}, self.path)
                with self.assertRaises(state.StateError):
                    state.selected_library_mode(self.path)
                self.assertEqual(self.path.read_text(), contents)

    def test_unreadable_is_distinct(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(state.inspect_state(self.path).status, "unreadable")

    def test_failed_replace_keeps_previous_file_and_cleans_temporary(self):
        state.write_state({"bookmarks": ["old"]}, self.path)
        original = Path.replace

        def fail_target(source, target):
            if target == self.path:
                raise OSError("disk failure")
            return original(source, target)

        with patch.object(Path, "replace", fail_target), self.assertRaises(OSError):
            state.write_state({"bookmarks": ["new"]}, self.path)
        self.assertEqual(state.read_state(self.path)["bookmarks"], ["old"])
        self.assertFalse(list(self.path.parent.glob(".*.tmp-*")))

    def test_failed_temporary_creation_preserves_original(self):
        state.write_state({}, self.path)
        contents = self.path.read_bytes()
        with (
            patch.object(state.tempfile, "mkstemp", side_effect=OSError("full")),
            self.assertRaises(OSError),
        ):
            state.write_state({"bookmarks": ["new"]}, self.path)
        self.assertEqual(self.path.read_bytes(), contents)

    def test_recovery_preserves_corrupt_file_then_reset_removes_backups(self):
        state.write_state({"bookmarks": ["old"]}, self.path)
        state.write_state({"bookmarks": ["new"]}, self.path)
        self.path.write_text("broken")
        state.recover_state(self.path, use_backup=True)
        self.assertEqual(state.read_state(self.path)["bookmarks"], ["old"])
        copies = list(self.path.parent.glob("state.json.recovery-*"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_text(), "broken")
        export = self.path.parent / "user-export.json"
        export.write_text("{}")
        state.clear_state(self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(state.backup_file(self.path).exists())
        self.assertFalse(copies[0].exists())
        self.assertTrue(export.exists())

    def test_invalid_backup_does_not_change_original(self):
        state.write_state({}, self.path)
        state.backup_file(self.path).write_text("invalid")
        original = self.path.read_bytes()
        with self.assertRaises(state.StateError):
            state.recover_state(self.path, use_backup=True)
        self.assertEqual(self.path.read_bytes(), original)
