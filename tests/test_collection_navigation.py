from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures/library.json"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import window as gisheh
from gisheh.services import simkl_client

UI_FILE = SOURCE_DIR / "gisheh" / "ui" / "window.ui"
WINDOW_FILE = SOURCE_DIR / "gisheh" / "window.py"


class _Adjustment:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def get_value(self) -> float:
        return self.value

    def set_value(self, value: float) -> None:
        self.value = value


class _Entry:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def get_text(self) -> str:
        return self.text

    def set_text(self, text: str) -> None:
        self.text = text


class _Dropdown:
    def __init__(self) -> None:
        self.selected = 0

    def set_selected(self, selected: int) -> None:
        self.selected = selected

    def get_selected(self) -> int:
        return self.selected


class _Selection:
    def __init__(self) -> None:
        self.selected = None
        self.unselect_count = 0

    def select_row(self, row) -> None:
        self.selected = row

    def unselect_all(self) -> None:
        self.selected = None
        self.unselect_count += 1


def _navigation_controller(origin: str) -> tuple[gisheh.GishehWindow, list[str]]:
    controller = object.__new__(gisheh.GishehWindow)
    controller.active_destination = origin
    controller.active_collection = "Watched"
    controller.selected_id = "origin-title"
    controller.explore_selected_id = None
    controller.details_open = False
    controller._updating = False
    controller.destination_list = _Selection()
    controller.collection_list = _Selection()
    controller.collection_rows = {
        name: SimpleNamespace(key=name) for name in gisheh.COLLECTION_NAMES
    }
    calls: list[str] = []
    controller.media_switcher = SimpleNamespace(
        set_visible=lambda visible: calls.append(f"media:{visible}")
    )
    controller.browser_stack = SimpleNamespace(
        set_visible_child_name=lambda name: calls.append(f"stack:{name}")
    )
    controller._remember_active_collection_state = lambda: calls.append("remember")
    controller._restore_active_collection_state = lambda: 37.0
    controller._refresh_results = lambda: calls.append("refresh")
    controller.results_scroller = object()
    controller._scroll_to_value = lambda _scroller, value: calls.append(
        f"scroll:{value}"
    )
    controller._save_user_state = lambda **_kwargs: calls.append("save")
    controller._close_sidebar_overlay = lambda: calls.append("close-sidebar")
    controller._queue_responsive_layout = lambda: calls.append("responsive")
    controller._set_details_open = lambda opened: calls.append(f"details:{opened}")
    return controller, calls


class CollectionStructureTests(unittest.TestCase):
    def test_library_row_is_not_created(self) -> None:
        source = WINDOW_FILE.read_text(encoding="utf-8")
        self.assertNotIn("self." + "library_row", source)
        self.assertNotIn("SidebarRow(\n            " + '"library"', source)

    def test_all_five_collections_have_one_source_of_truth(self) -> None:
        self.assertEqual(
            gisheh.COLLECTIONS,
            (
                ("Watching", "media-playback-start-symbolic"),
                ("Watched", "object-select-symbolic"),
                ("On Hold", "media-playback-pause-symbolic"),
                ("Dropped", "user-trash-symbolic"),
                ("Watchlist", "bookmark-new-symbolic"),
            ),
        )

    def test_selector_is_single_selection_and_not_split(self) -> None:
        root = ET.parse(UI_FILE).getroot()
        selector = root.find(".//object[@id='collection_list']")
        self.assertIsNotNone(selector)
        assert selector is not None
        mode = selector.find("./property[@name='selection-mode']")
        self.assertIsNotNone(mode)
        self.assertEqual(mode.text, "single")
        self.assertIsNone(root.find(".//object[@id='status_list']"))
        self.assertIsNone(root.find(".//object[@id='collections_list']"))

    def test_collection_stack_and_pane_are_singular(self) -> None:
        root = ET.parse(UI_FILE).getroot()
        self.assertIsNotNone(root.find(".//object[@id='collection_pane']"))
        source = WINDOW_FILE.read_text(encoding="utf-8")
        self.assertEqual(
            source.count('add_named(self.collection_pane, "collection")'), 1
        )
        legacy_stack_target = "set_visible_child_name(" + '"library")'
        self.assertNotIn(legacy_stack_target, source)

    def test_sync_selects_only_the_active_collection(self) -> None:
        controller, _calls = _navigation_controller("collection")
        controller.active_collection = "On Hold"
        controller.destination_list.selected = object()
        controller._sync_collection_selection()
        self.assertIsNone(controller.destination_list.selected)
        self.assertIs(
            controller.collection_list.selected,
            controller.collection_rows["On Hold"],
        )


class DirectCollectionNavigationTests(unittest.TestCase):
    def _assert_direct_open(self, origin: str) -> None:
        controller, calls = _navigation_controller(origin)
        controller._activate_collection("Watchlist")
        self.assertEqual(controller.active_destination, "collection")
        self.assertEqual(controller.active_collection, "Watchlist")
        self.assertIn("stack:collection", calls)
        self.assertIn("refresh", calls)
        self.assertIn("scroll:37.0", calls)
        self.assertIn("close-sidebar", calls)
        self.assertIsNone(controller.destination_list.selected)
        self.assertIs(
            controller.collection_list.selected,
            controller.collection_rows["Watchlist"],
        )

    def test_selecting_collection_from_explore_opens_collection_view(self) -> None:
        self._assert_direct_open("explore")

    def test_selecting_collection_from_calendar_opens_collection_view(self) -> None:
        self._assert_direct_open("calendar")

    def test_selecting_collection_from_profile_opens_collection_view(self) -> None:
        self._assert_direct_open("profile")

    def test_selection_scroll_and_filters_are_independent(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.active_collection = "Watched"
        controller.selected_id = "watched-title"
        controller.results_scroller = SimpleNamespace(
            get_vadjustment=lambda: _Adjustment(82.5)
        )
        controller.search_entry = _Entry("crime")
        controller.genre = "Drama"
        controller.sort_key = "rating"
        controller.sort_reversed = True
        controller.sort_dropdown = _Dropdown()
        controller._updating = False
        controller.collection_selected_ids = {
            name: None for name in gisheh.COLLECTION_NAMES
        }
        controller.collection_scroll_positions = {
            name: 0.0 for name in gisheh.COLLECTION_NAMES
        }
        controller.collection_view_states = {
            name: {
                "query": "",
                "genre": "All genres",
                "sortKey": "recent",
                "sortReversed": False,
            }
            for name in gisheh.COLLECTION_NAMES
        }
        controller._remember_active_collection_state()

        controller.active_collection = "Watching"
        controller.collection_selected_ids["Watching"] = "watching-title"
        controller.collection_scroll_positions["Watching"] = 14.0
        controller.collection_view_states["Watching"] = {
            "query": "space",
            "genre": "Science Fiction",
            "sortKey": "title",
            "sortReversed": False,
        }
        controller._update_genre_model = lambda **_kwargs: None
        scroll = controller._restore_active_collection_state()

        self.assertEqual(controller.collection_selected_ids["Watched"], "watched-title")
        self.assertEqual(controller.collection_scroll_positions["Watched"], 82.5)
        self.assertEqual(controller.selected_id, "watching-title")
        self.assertEqual(scroll, 14.0)
        self.assertEqual(controller.search_entry.get_text(), "space")
        self.assertEqual(controller.genre, "Science Fiction")
        self.assertEqual(controller.sort_key, "title")

    def test_last_active_collection_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_file = Path(temporary) / "state.json"
            controller = object.__new__(gisheh.GishehWindow)
            controller.state_file = state_file
            controller.bookmarks = set()
            controller.favorites = set()
            controller.completed = set()
            controller.ratings = {}
            controller.status_overrides = {}
            controller.episode_status_overrides = {}
            controller.episode_watched_at = {}
            controller.title_watched_at = {}
            controller.color_scheme = "system"
            controller.auto_sync = True
            controller.default_media = "Movies"
            controller.preferred_view_mode = "list"
            controller.active_collection = "Dropped"
            controller.collection_selected_ids = {
                name: None for name in gisheh.COLLECTION_NAMES
            }
            controller.collection_scroll_positions = {
                name: 0.0 for name in gisheh.COLLECTION_NAMES
            }
            controller.collection_view_states = {
                name: {
                    "query": "",
                    "genre": "All genres",
                    "sortKey": "recent",
                    "sortReversed": False,
                }
                for name in gisheh.COLLECTION_NAMES
            }
            controller._save_user_state()
            payload = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["collectionState"]["active"], "Dropped")


class CollectionBehaviorTests(unittest.TestCase):
    def _record(self):
        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        return next(record for record in records if record.media_type == "Movies")

    def test_status_change_moves_title_between_collections(self) -> None:
        record = self._record()
        controller = object.__new__(gisheh.GishehWindow)
        controller.records = (record,)
        controller.explore_records = ()
        controller.active_media = "Movies"
        controller.genre = "All genres"
        controller.sort_key = "recent"
        controller.sort_reversed = False
        controller.search_entry = _Entry()
        status = {"value": "Watched"}
        controller._effective_status = lambda _record: status["value"]

        controller.active_collection = "Watched"
        self.assertEqual(controller._filtered_collection_records(), (record,))
        status["value"] = "Watching"
        self.assertEqual(controller._filtered_collection_records(), ())
        controller.active_collection = "Watching"
        self.assertEqual(controller._filtered_collection_records(), (record,))

    def test_removing_bookmark_removes_title_from_watchlist(self) -> None:
        record = self._record()
        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.active_destination = "collection"
        controller.active_collection = "Watchlist"
        controller.selected_id = None
        controller.details_open = False
        controller.bookmarks = {controller._canonical_record_id(record)}
        controller.completed = set()
        controller.status_overrides = {}
        controller.records = (record,)
        controller.explore_records = ()
        controller.explore_ids = set()
        controller.library_ids = {record.id}
        controller.records_by_id = {record.id: record}
        controller.local_library_records = {}
        controller._tmdb_record_aliases = {}
        controller._library_records_by_canonical = {record.id: record}
        controller._invalidate_simkl_snapshot_after_mutation = lambda: None
        controller._save_user_state = lambda **_kwargs: None
        controller._remove_unused_local_library_record = lambda _canonical: None
        refreshes: list[str] = []
        controller._defer_collection_refresh_for_detail_mutation = lambda: (
            refreshes.append("collection")
        )
        controller._write_simkl_list_change = lambda _record, *, adding, on_success: (
            on_success()
        )
        controller._set_record_bookmarked(record, False)
        self.assertNotIn(controller._canonical_record_id(record), controller.bookmarks)
        self.assertEqual(refreshes, ["collection"])

    def test_tmdb_refresh_updates_active_collection_and_preserves_scroll(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller._tmdb_library_refresh_source_id = 9
        controller.active_destination = "collection"
        controller.results_scroller = SimpleNamespace(
            get_vadjustment=lambda: _Adjustment(48.0)
        )
        calls: list[object] = []
        controller._refresh_results = lambda: calls.append("refresh")
        controller._scroll_to_value = lambda _scroller, value: calls.append(value)
        result = controller._refresh_tmdb_library_ui()
        self.assertEqual(result, gisheh.GLib.SOURCE_REMOVE)
        self.assertEqual(calls, ["refresh", 48.0])

    def test_local_watchlist_mutation_never_calls_simkl(self) -> None:
        record = self._record()
        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller._ensure_local_library_record = lambda item: item.id
        controller._toast = lambda _message: None
        applied: list[str] = []
        with (
            patch.object(simkl_client, "set_list_status") as add,
            patch.object(simkl_client, "remove_from_library") as remove,
        ):
            controller._write_simkl_list_change(
                record,
                adding=True,
                on_success=lambda: applied.append("done"),
            )
        add.assert_not_called()
        remove.assert_not_called()
        self.assertEqual(applied, ["done"])

    def test_simkl_watchlist_mutation_keeps_existing_endpoint_contract(self) -> None:
        record = replace(self._record(), tmdb_id=77, tmdb_media_type="movie")
        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_SIMKL
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller._tmdb_record_aliases = {}
        controller._library_records_by_canonical = {}
        controller._run_simkl_mutation = lambda _key, operation, on_success, _message: (
            operation(),
            on_success(),
        )
        with patch.object(simkl_client, "set_list_status", return_value={}) as add:
            controller._write_simkl_list_change(
                record,
                adding=True,
                on_success=lambda: None,
            )
        add.assert_called_once()
        self.assertEqual(add.call_args.args[0:2], ("client", "token"))
        self.assertEqual(add.call_args.args[-1], "plantowatch")

    def test_every_collection_uses_the_same_empty_state(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.empty_page = object()
        controller.list_box = object()
        controller.grid_box = object()
        controller.view_mode = "list"
        scroller = SimpleNamespace(child=None)
        scroller.get_child = lambda: scroller.child
        scroller.set_child = lambda child: setattr(scroller, "child", child)
        controller.results_scroller = scroller
        for collection in gisheh.COLLECTION_NAMES:
            controller.active_collection = collection
            controller.visible_records = ()
            controller._sync_results_child()
            self.assertIs(scroller.child, controller.empty_page)

    def test_grid_and_list_still_share_collection_results(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller._updating = False
        controller.view_mode = "list"
        controller.visible_records = (
            SimpleNamespace(id="one"),
            SimpleNamespace(id="two"),
        )
        controller.selected_id = "two"
        controller.results_scroller = SimpleNamespace(get_width=lambda: 620)
        calls: list[object] = []
        controller._refresh_results = lambda: calls.append("refresh")
        controller._scroll_to_value = lambda _scroller, value: calls.append(value)
        group = SimpleNamespace(get_active_name=lambda: "grid")
        controller._on_view_changed(group, None)
        self.assertEqual(controller.view_mode, "grid")
        self.assertEqual(controller.preferred_view_mode, "grid")
        self.assertEqual(calls[0], "refresh")
        self.assertIsInstance(calls[1], int)


if __name__ == "__main__":
    unittest.main()
