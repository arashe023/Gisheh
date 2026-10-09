from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gisheh import library_backup as backup, state_store
from gisheh.models import load_catalog, title_record_to_mapping


class LibraryBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        records, _, _ = load_catalog(
            sample_data_path=Path(__file__).parent / "fixtures/library.json"
        )
        self.record = title_record_to_mapping(records[0])
        self.profile = {key: kind() for key, kind in backup.PERSONAL_FIELDS.items()}
        self.profile["bookmarks"] = [self.record["id"]]
        self.profile["ratings"] = {self.record["id"]: 8}
        state_store.write_state(
            {
                "preferences": {"libraryMode": "local", "colorScheme": "dark"},
                "localLibrary": [self.record],
                "localProfile": self.profile,
                "simkl": {"keep": True},
            },
            self.path,
        )

    def test_round_trip_preserves_library_and_preferences_without_cloud_calls(self):
        exported = backup.parse_export(backup.export_library(self.path))
        with patch(
            "gisheh.services.simkl_client._request_json",
            side_effect=AssertionError("network"),
        ):
            self.assertEqual(backup.import_library(exported, self.path), 1)
        stored = state_store.read_state(self.path)
        self.assertEqual(stored["localProfile"], self.profile)
        self.assertEqual(stored["preferences"]["colorScheme"], "dark")
        self.assertEqual(stored["simkl"], {"keep": True})
        self.assertTrue(state_store.backup_file(self.path).exists())

    def test_export_excludes_credentials_and_cache_paths(self):
        payload = state_store.read_state(self.path)
        payload["access_token"] = "secret-value"
        payload["localLibrary"][0]["posterFile"] = "/private/cache.jpg"
        payload["localLibrary"][0]["unknown_secret"] = "secret-value"
        state_store.write_state(payload, self.path)
        data = backup.export_library(self.path).decode()
        self.assertNotIn("secret-value", data)
        self.assertNotIn("/private/cache.jpg", data)

    def test_invalid_import_is_atomic(self):
        good = backup.parse_export(backup.export_library(self.path))
        before = self.path.read_bytes()
        for field, value in [
            ("format_version", 99),
            ("format", "other"),
            ("localLibrary", [{}]),
        ]:
            payload = deepcopy(good)
            payload[field] = value
            with self.assertRaises(ValueError):
                backup.import_library(payload, self.path)
            self.assertEqual(self.path.read_bytes(), before)
        good["localProfile"]["ratings"] = {self.record["id"]: 100}
        with self.assertRaises(ValueError):
            backup.import_library(good, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_simkl_mode_cannot_import(self):
        payload = backup.parse_export(backup.export_library(self.path))
        state_store.save_library_mode("simkl", self.path)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            backup.import_library(payload, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_pre_import_recovery_copy_survives_later_saves(self):
        exported = backup.parse_export(backup.export_library(self.path))
        original = self.path.read_bytes()
        backup.import_library(exported, self.path)
        state_store.write_state(state_store.read_state(self.path), self.path)
        copies = list(self.path.parent.glob("state.json.recovery-*"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), original)
