from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from gisheh.controllers import CalendarController, SyncController


class ControllerTests(unittest.TestCase):
    def test_calendar_partial_success_keeps_warning(self):
        class Failure(Exception):
            pass

        client = SimpleNamespace(
            SimklError=Failure,
            fetch_calendar=Mock(
                side_effect=[{"movies": []}, Failure("offline"), {"anime": []}]
            ),
            merge_calendar_snapshots=Mock(return_value="merged"),
        )
        self.assertEqual(
            CalendarController(client).fetch_month("id", 2026, 10, None),
            ("merged", "offline"),
        )
        self.assertEqual(client.fetch_calendar.call_count, 3)

    def test_unchanged_sync_uses_cache_without_network(self):
        client = Mock()
        result = SyncController(client).library(
            "id",
            "token",
            cached_library={"movies": []},
            cached_activities={},
            activities={"all": "same"},
            last_sync="same",
            incremental=True,
        )
        self.assertEqual(result, {"movies": []})
        client.fetch_library.assert_not_called()
        client.fetch_library_delta.assert_not_called()

    def test_removed_ids_are_reconciled(self):
        client = Mock()
        SyncController(client).library(
            "id",
            "token",
            cached_library={"movies": []},
            cached_activities={},
            activities={"all": "new"},
            last_sync="old",
            incremental=True,
        )
        client.library_ids.assert_called_once_with(
            client.fetch_library_ids.return_value
        )
        client.merge_library.assert_called_once_with(
            {"movies": []},
            client.fetch_library_delta.return_value,
            client.library_ids.return_value,
        )
