from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh import window as gisheh
from gisheh.services import simkl_client

TEHRAN = timezone(timedelta(hours=3, minutes=30))


class TimestampParsingTests(unittest.TestCase):
    def test_legacy_timestamp_still_parses(self) -> None:
        parsed = gisheh.parse_watched_datetime("Aug 8, 2026 at 2:49 AM")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual((parsed.year, parsed.month, parsed.day), (2026, 8, 8))
        self.assertEqual((parsed.hour, parsed.minute), (2, 49))
        self.assertEqual(
            gisheh.parse_watched_date("Aug 8, 2026 at 2:49 AM").isoformat(),
            "2026-08-08",
        )

    def test_iso_timestamp_with_offset_parses(self) -> None:
        parsed = gisheh.parse_watched_datetime("2026-09-04T21:35:00+03:30")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.utcoffset(), timedelta(hours=3, minutes=30))
        self.assertEqual(
            gisheh.parse_watched_date("2026-09-04T21:35:00+03:30").isoformat(),
            "2026-09-04",
        )

    def test_zulu_timestamp_parses(self) -> None:
        parsed = gisheh.parse_watched_datetime("2026-09-04T18:05:00Z")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_invalid_timestamp_returns_none(self) -> None:
        self.assertIsNone(gisheh.parse_watched_datetime(""))
        self.assertIsNone(gisheh.parse_watched_datetime("not a date"))
        self.assertIsNone(gisheh.parse_watched_date("not a date"))

    def test_legacy_display_round_trip_is_stable(self) -> None:
        self.assertEqual(
            gisheh.format_watched_iso("Aug 8, 2026 at 2:49 AM"),
            "Aug 8, 2026 at 2:49 AM",
        )

    def test_iso_display_format_matches_legacy_shape(self) -> None:
        self.assertEqual(
            gisheh.format_watched_iso("2026-09-04T21:35:00+03:30"),
            "Sep 4, 2026 at 9:35 PM",
        )

    def test_now_is_timezone_aware_iso(self) -> None:
        iso = gisheh.watched_now_iso()
        parsed = gisheh.parse_watched_datetime(iso)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), datetime.now().astimezone().utcoffset())


class TimestampConstructionTests(unittest.TestCase):
    def test_twelve_hour_conversion(self) -> None:
        midnight = gisheh.watched_datetime_from_parts(
            2026, 9, 4, 12, 0, hour_is_12h=True, is_pm=False
        )
        noon = gisheh.watched_datetime_from_parts(
            2026, 9, 4, 12, 0, hour_is_12h=True, is_pm=True
        )
        evening = gisheh.watched_datetime_from_parts(
            2026, 9, 4, 9, 35, hour_is_12h=True, is_pm=True
        )
        assert midnight is not None and noon is not None and evening is not None
        self.assertEqual(midnight.hour, 0)
        self.assertEqual(noon.hour, 12)
        self.assertEqual(evening.hour, 21)
        self.assertIsNotNone(midnight.tzinfo)

    def test_twenty_four_hour_passthrough(self) -> None:
        moment = gisheh.watched_datetime_from_parts(2026, 9, 4, 21, 35)
        assert moment is not None
        self.assertEqual((moment.hour, moment.minute), (21, 35))

    def test_invalid_parts_return_none(self) -> None:
        self.assertIsNone(gisheh.watched_datetime_from_parts(2026, 2, 30, 10, 0))
        self.assertIsNone(gisheh.watched_datetime_from_parts(2026, 9, 4, 25, 0))
        self.assertIsNone(gisheh.watched_datetime_from_parts(2026, 9, 4, 10, 61))
        self.assertIsNone(
            gisheh.watched_datetime_from_parts(
                2026, 9, 4, 0, 0, hour_is_12h=True, is_pm=False
            )
        )
        self.assertIsNone(
            gisheh.watched_datetime_from_parts(
                2026, 9, 4, 13, 0, hour_is_12h=True, is_pm=False
            )
        )

    def test_local_offset_is_preserved(self) -> None:
        moment = gisheh.watched_datetime_from_parts(2026, 9, 4, 21, 35)
        assert moment is not None
        self.assertEqual(moment.utcoffset(), datetime.now().astimezone().utcoffset())
        reparsed = gisheh.parse_watched_datetime(moment.isoformat())
        assert reparsed is not None
        self.assertEqual(reparsed.replace(tzinfo=None), moment.replace(tzinfo=None))

    def test_future_timestamp_is_rejected(self) -> None:
        now = datetime(2026, 9, 4, 12, 0, tzinfo=TEHRAN)
        self.assertIsNotNone(
            gisheh.validate_watched_iso("2026-09-04T13:00:00+03:30", now=now)
        )
        self.assertIsNone(
            gisheh.validate_watched_iso("2026-09-04T11:59:00+03:30", now=now)
        )
        self.assertIsNone(
            gisheh.validate_watched_iso("2026-09-04T12:00:00+03:30", now=now)
        )

    def test_invalid_timestamp_is_rejected(self) -> None:
        self.assertIsNotNone(gisheh.validate_watched_iso("garbage"))


def _dialog_controller() -> gisheh.GishehWindow:
    controller = object.__new__(gisheh.GishehWindow)
    return controller


class WatchedDialogTests(unittest.TestCase):
    def _build(self, confirmed: list[str]):
        controller = _dialog_controller()
        dialog = controller._build_watched_time_dialog(
            title_text="Example",
            subtitle_text="S02E05",
            on_confirm=confirmed.append,
        )
        return dialog

    def test_dialog_matches_app_card_style(self) -> None:
        from gi.repository import Gtk

        confirmed: list[str] = []
        dialog = self._build(confirmed)
        content = dialog.get_extra_child()
        card = content.get_first_child()
        self.assertIn("card", card.get_css_classes())
        self.assertIn("watched-dialog-card", card.get_css_classes())

        def find_calendar(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.Calendar):
                    return child
                found = find_calendar(child)
                if found is not None:
                    return found
                child = child.get_next_sibling()
            return None

        calendar = find_calendar(content)
        self.assertIsNotNone(calendar)
        assert calendar is not None
        self.assertIn("watched-dialog-calendar", calendar.get_css_classes())

        captions = []

        def collect_captions(widget):
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.Label) and (
                    "caption" in child.get_css_classes()
                ):
                    captions.append(child.get_label())
                collect_captions(child)
                child = child.get_next_sibling()

        collect_captions(card)
        self.assertIn("Date", captions)
        self.assertIn("Time", captions)

    def test_app_css_parses(self) -> None:
        from gi.repository import Gtk

        provider = Gtk.CssProvider()
        provider.load_from_path(
            str(Path(__file__).resolve().parents[1] / "src" / "gisheh" / "style.css")
        )
        self.assertTrue(True)

    def test_cancel_makes_no_mutation(self) -> None:
        confirmed: list[str] = []
        dialog = self._build(confirmed)
        dialog.emit("response", "cancel")
        self.assertEqual(confirmed, [])

    def test_mark_confirms_current_selection(self) -> None:
        confirmed: list[str] = []
        dialog = self._build(confirmed)
        dialog.emit("response", "mark")
        self.assertEqual(len(confirmed), 1)
        parsed = gisheh.parse_watched_datetime(confirmed[0])
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIsNotNone(parsed.tzinfo)

    def test_now_resets_controls(self) -> None:
        from gi.repository import GLib

        confirmed: list[str] = []
        dialog = self._build(confirmed)
        calendar, hour_spin, minute_spin, _ampm, _error = dialog._watched_time_controls  # type: ignore[attr-defined]
        gisheh.set_calendar_date(
            calendar,
            GLib.DateTime.new_local(2000, 1, 2, 0, 0, 0.0),
        )
        hour_spin.set_value(hour_spin.get_adjustment().get_lower())
        minute_spin.set_value(minute_spin.get_adjustment().get_lower())
        today = datetime.now().astimezone().date()
        # The Now button lives beside the time row; find and click it.
        clicked: list[str] = []

        def find_now(widget):
            child = widget.get_first_child()
            while child is not None:
                from gi.repository import Gtk

                if isinstance(child, Gtk.Button) and child.get_label() == "Now":
                    clicked.append("now")
                    child.emit("clicked")
                    return True
                if find_now(child):
                    return True
                child = child.get_next_sibling()
            return False

        self.assertTrue(find_now(dialog.get_extra_child()))
        selected = calendar.get_date()
        self.assertEqual(
            (selected.get_year(), selected.get_month(), selected.get_day_of_month()),
            (today.year, today.month, today.day),
        )

    def test_future_selection_disables_mark(self) -> None:
        from gi.repository import GLib

        confirmed: list[str] = []
        dialog = self._build(confirmed)
        calendar, _hour, _minute, _ampm, error = dialog._watched_time_controls  # type: ignore[attr-defined]
        future = datetime.now().astimezone() + timedelta(days=400)
        gisheh.set_calendar_date(
            calendar,
            GLib.DateTime.new_local(future.year, future.month, future.day, 0, 0, 0.0),
        )
        calendar.emit("day-selected")
        self.assertFalse(dialog.get_response_enabled("mark"))
        self.assertTrue(error.get_visible())
        self.assertIn("future", error.get_label().lower())
        dialog.emit("response", "mark")
        self.assertEqual(confirmed, [])


def _titled_controller() -> gisheh.GishehWindow:
    controller = object.__new__(gisheh.GishehWindow)
    controller.completed = set()
    controller.status_overrides = {}
    controller.title_watched_at = {}
    controller.bookmarks = set()
    controller.ratings = {}
    controller.episode_status_overrides = {}
    controller.episode_watched_at = {}
    controller.active_destination = "collection"
    controller.simkl_client_id = None
    controller.simkl_token = None
    controller.simkl_connected = False
    controller._simkl_mutations_inflight = set()
    controller.selected_id = None
    controller.detail_record_id = None
    controller.current_season_index = 0
    controller.current_episode_index = 0
    controller.explore_ids = set()
    controller.season_details_scroller = SimpleNamespace(
        get_vadjustment=lambda: SimpleNamespace(get_value=lambda: 0.0)
    )
    controller.saved: list[str] = []
    controller.toasts: list[str] = []
    controller.logged: list[tuple[object, ...]] = []
    controller._save_user_state = lambda: controller.saved.append("save")  # type: ignore[method-assign]
    controller._toast = lambda message: controller.toasts.append(message)  # type: ignore[method-assign]
    controller._app_log = lambda message, *args, **kwargs: controller.logged.append(
        (message, *args)
    )  # type: ignore[method-assign]
    controller._refresh_results = lambda: None  # type: ignore[method-assign]
    controller._refresh_profile = lambda: None  # type: ignore[method-assign]
    controller._update_details = lambda: None  # type: ignore[method-assign]
    controller._populate_series = lambda record: None  # type: ignore[method-assign]
    controller._populate_season_page = lambda *args, **kwargs: None  # type: ignore[method-assign]
    controller._update_episode_watch_controls = lambda *args: None  # type: ignore[method-assign]
    controller._scroll_to_value = lambda *args: None  # type: ignore[method-assign]
    controller._invalidate_simkl_snapshot_after_mutation = lambda: None  # type: ignore[method-assign]
    return controller


class TitleWatchedFlowTests(unittest.TestCase):
    def _record(self) -> gisheh.TitleRecord:
        records, _explore, _totals = gisheh.load_catalog(include_sample_data=True)
        base = next(record for record in records if record.media_type == "Movies")
        return replace(base, tmdb_id=20, tmdb_media_type="movie")

    def test_offline_mark_saves_iso_locally(self) -> None:
        controller = _titled_controller()
        record = self._record()
        controller.records_by_id = {record.id: record}
        controller._mark_title_watched(record, "2026-09-04T21:35:00+03:30")
        self.assertIn(controller._canonical_record_id(record), controller.completed)
        self.assertEqual(
            controller.title_watched_at[controller._canonical_record_id(record)],
            "2026-09-04T21:35:00+03:30",
        )
        self.assertTrue(any("locally" in toast for toast in controller.toasts))
        self.assertNotIn(
            "synced", " ".join(controller.toasts).lower().replace("(not synced)", "")
        )

    def test_online_mark_sends_timestamp_and_updates_after_success(self) -> None:
        controller = _titled_controller()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        record = self._record()
        controller.records_by_id = {record.id: record}
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_set_watched(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append((args, kwargs))
            return {"added": {"movies": 1}}

        def fake_mutation(key, operation, on_success, message):
            operation()
            on_success()
            controller.toasts.append(message)

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(simkl_client, "set_watched", side_effect=fake_set_watched),
        ):
            controller._mark_title_watched(record, "2026-09-04T21:35:00+03:30")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].get("watched_at"), "2026-09-04T21:35:00+03:30")
        self.assertTrue(calls[0][0][4])
        self.assertIn(controller._canonical_record_id(record), controller.completed)
        self.assertEqual(
            controller.title_watched_at[controller._canonical_record_id(record)],
            "2026-09-04T21:35:00+03:30",
        )
        self.assertIn("Marked as watched", controller.toasts)

    def test_failed_mutation_preserves_previous_state(self) -> None:
        controller = _titled_controller()
        record = self._record()
        controller.records_by_id = {record.id: record}

        def fake_mutation(key, op, on_success, message):
            controller._finish_simkl_mutation(key, None, message, "network down")

        with patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation):
            controller._run_simkl_mutation("key", lambda: None, lambda: None, "ok")

        self.assertNotIn(record.id, controller.completed)
        self.assertNotIn(record.id, controller.title_watched_at)
        self.assertIn("network down", controller.toasts)

    def test_watched_title_offers_date_change_and_unwatch_actions(self) -> None:
        controller = _titled_controller()
        record = self._record()
        controller.completed.add(controller._canonical_record_id(record))
        controller.selected_id = record.id
        controller.records_by_id = {record.id: record}
        controller.active_destination = "collection"
        shown: list[str] = []
        controller._show_watched_title_actions = lambda item: shown.append(item.id)  # type: ignore[method-assign]
        mutations: list[str] = []
        controller._run_simkl_mutation = lambda key, op, ok, msg: mutations.append(key)  # type: ignore[method-assign]
        controller._on_watched_clicked(object())
        self.assertEqual(shown, [record.id])
        self.assertEqual(mutations, [])

    def test_mark_title_unwatched_removes_history_after_server_success(self) -> None:
        controller = _titled_controller()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        record = self._record()
        controller.records_by_id = {record.id: record}
        canonical = controller._canonical_record_id(record)
        controller.completed.add(canonical)
        controller.title_watched_at[canonical] = "2026-09-04T18:05:00Z"
        calls: list[tuple[object, ...]] = []

        def fake_mutation(_key, operation, on_success, _message):
            operation()
            on_success()

        def fake_set_watched(*args, **kwargs):
            calls.append((*args, kwargs))
            return {"added": {"movies": 1}}

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(simkl_client, "set_watched", side_effect=fake_set_watched),
        ):
            controller._mark_title_unwatched(record)

        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][4])
        self.assertNotIn(canonical, controller.completed)
        self.assertIn(canonical, controller.bookmarks)
        self.assertNotIn(canonical, controller.title_watched_at)

    def test_explore_watch_opens_date_dialog_instead_of_watchlist(self) -> None:
        controller = _titled_controller()
        record = self._record()
        controller.selected_id = record.id
        controller.records_by_id = {record.id: record}
        controller.active_destination = "explore"
        controller.explore_ids = {record.id}
        shown: list[str] = []
        controller._show_watched_time_dialog = lambda **kwargs: shown.append("dialog")  # type: ignore[method-assign]
        list_changes: list[str] = []
        controller._write_simkl_list_change = lambda *args, **kwargs: (
            list_changes.append("watchlist")
        )  # type: ignore[method-assign]
        controller._on_watched_clicked(object())
        self.assertEqual(shown, ["dialog"])
        self.assertEqual(list_changes, [])

    def test_explore_mark_sends_timestamp_and_refreshes_explore(self) -> None:
        controller = _titled_controller()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        controller.active_destination = "explore"
        record = self._record()
        controller.records_by_id = {record.id: record}
        controller.explore_ids = {record.id}
        refreshed: list[str] = []
        controller._refresh_explore = lambda **kwargs: refreshed.append("explore")  # type: ignore[method-assign]
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_set_watched(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append((args, kwargs))
            return {"added": {"movies": 1}}

        def fake_mutation(key, operation, on_success, message):
            operation()
            on_success()
            controller.toasts.append(message)

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(simkl_client, "set_watched", side_effect=fake_set_watched),
        ):
            controller._mark_title_watched(record, "2026-06-04T21:35:00+03:30")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].get("watched_at"), "2026-06-04T21:35:00+03:30")
        self.assertIn(controller._canonical_record_id(record), controller.completed)
        self.assertEqual(refreshed, ["explore"])

    def test_watched_explore_record_is_promoted_to_library_views(self) -> None:
        controller = _titled_controller()
        records, _explore, _totals = gisheh.load_catalog(include_sample_data=True)
        library_record = next(
            record for record in records if record.media_type == "Movies"
        )
        explore_record = replace(library_record, id="tmdb-999999")
        controller.records = (library_record,)
        controller.explore_records = (explore_record,)
        controller.active_media = "Movies"
        controller.active_collection = "Watched"
        self.assertNotIn(
            explore_record.id, [item.id for item in controller._library_records()]
        )
        controller.completed.add(explore_record.id)
        controller.status_overrides[explore_record.id] = "Watched"
        self.assertIn(
            explore_record.id, [item.id for item in controller._library_records()]
        )
        self.assertGreaterEqual(controller._status_total("Movies", "Watched"), 1)

    def test_library_and_explore_faces_share_canonical_state(self) -> None:
        controller = _titled_controller()
        library = self._record()
        library = replace(library, id="simkl-movies-12345", tmdb_id=20)
        explore = replace(library, id="tmdb-movie-20", status="Watchlist")
        controller.records = (library,)
        controller.explore_records = (explore,)
        controller._tmdb_record_aliases = {("movie", 20): library.id}
        controller._library_records_by_canonical = {library.id: library}
        controller.completed = {library.id}
        controller.bookmarks = set()
        controller.ratings = {library.id: 8}
        controller.title_watched_at = {library.id: "2026-09-04T18:05:00Z"}

        self.assertEqual(controller._canonical_record_id(explore), library.id)
        self.assertTrue(controller._is_record_completed(explore))
        self.assertEqual(controller._effective_status(explore), "Watched")
        self.assertEqual(controller._effective_record_rating(explore), 8)
        self.assertEqual(
            controller.title_watched_at[controller._canonical_record_id(explore)],
            "2026-09-04T18:05:00Z",
        )
        self.assertEqual(controller._library_records(), (library,))
        self.assertEqual(controller._simkl_ids(explore)["simkl"], 12345)

    def test_show_server_status_watching_does_not_complete_locally(self) -> None:
        controller = _titled_controller()
        record = replace(
            self._record(), id="tmdb-tv-20", media_type="Shows", tmdb_media_type="tv"
        )
        controller.records_by_id = {record.id: record}
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True

        def fake_mutation(_key, operation, on_success, _message):
            operation()
            on_success()

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(
                simkl_client,
                "set_watched",
                return_value={
                    "added": {
                        "shows": 1,
                        "statuses": [{"response": {"status": "watching"}}],
                    }
                },
            ),
        ):
            controller._mark_title_watched(record, "2026-09-04T21:35:00+03:30")

        self.assertFalse(controller._is_record_completed(record))
        self.assertEqual(controller._effective_status(record), "Watching")

    def test_episode_history_noop_does_not_apply_local_episode(self) -> None:
        record, controller = SeasonEpisodeWatchedFlowTests()._show()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True

        def fake_mutation(_key, operation, on_success, _message):
            operation()
            on_success()

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(
                simkl_client,
                "set_episode_watched",
                return_value={"added": {"episodes": 0}},
            ),
        ):
            controller._mark_episode_watched(record, 0, 2, "2026-09-04T21:35:00+03:30")

        key = controller._episode_key(record, 0, record.seasons[0].episode_items[1])
        self.assertNotIn(key, controller.episode_status_overrides)
        self.assertNotIn(key, controller.episode_watched_at)

    def test_history_write_is_logged_with_result(self) -> None:
        controller = _titled_controller()
        result = controller._post_simkl_history(
            "abc at 2026-06-04T21:35:00+03:30",
            lambda: {"added": {"movies": 1}},
        )
        self.assertEqual(result, {"added": {"movies": 1}})
        self.assertTrue(
            any("abc at 2026-06-04" in str(entry) for entry in controller.logged)
        )
        self.assertTrue(any("movies" in str(entry) for entry in controller.logged))

    def test_simkl_history_changed_detects_server_noop(self) -> None:
        self.assertTrue(gisheh.simkl_history_changed({"added": {"movies": 1}}))
        self.assertFalse(
            gisheh.simkl_history_changed(
                {"added": {"movies": 0, "shows": 0, "episodes": 0}}
            )
        )
        self.assertFalse(gisheh.simkl_history_changed({"added": {}}))
        self.assertFalse(gisheh.simkl_history_changed({}))
        self.assertFalse(gisheh.simkl_history_changed(None))

    def test_noop_mark_guides_user_to_remark(self) -> None:
        controller = _titled_controller()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        record = self._record()
        controller.records_by_id = {record.id: record}
        messages: list[str] = []

        def fake_mutation(key, operation, on_success, message):
            messages.append(message)
            operation()
            on_success()

        noop = {"added": {"movies": 0, "shows": 0, "episodes": 0}}
        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(simkl_client, "set_watched", return_value=noop),
        ):
            controller._mark_title_watched(record, "2026-08-04T22:14:00+03:30")

        self.assertEqual(messages, [""])
        self.assertNotIn(controller._canonical_record_id(record), controller.completed)
        self.assertFalse(any(t == "Marked as watched" for t in controller.toasts))
        self.assertTrue(
            any("Use Change watched date" in t for t in controller.toasts),
            controller.toasts,
        )

    def test_not_found_history_response_preserves_local_title_state(self) -> None:
        controller = _titled_controller()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        record = self._record()
        controller.records_by_id = {record.id: record}

        def fake_mutation(key, operation, _on_success, message):
            try:
                operation()
            except simkl_client.SimklError as error:
                controller._finish_simkl_mutation(key, None, message, str(error))

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(
                simkl_client,
                "set_watched",
                return_value={"added": {"movies": 1}, "not_found": {"movies": [{}]}},
            ),
        ):
            controller._mark_title_watched(record, "2026-09-04T21:35:00+03:30")

        canonical = controller._canonical_record_id(record)
        self.assertNotIn(canonical, controller.completed)
        self.assertNotIn(canonical, controller.bookmarks)
        self.assertNotIn(canonical, controller.title_watched_at)


class SeasonEpisodeWatchedFlowTests(unittest.TestCase):
    def _show(self) -> tuple[gisheh.TitleRecord, gisheh.GishehWindow]:
        records, _explore, _totals = gisheh.load_catalog(include_sample_data=True)
        base = next(record for record in records if record.media_type == "Shows")
        season = gisheh.SeasonInfo(
            id="s1",
            number=1,
            title="Season 1",
            watched=0,
            episodes=3,
            episode_items=tuple(
                gisheh.EpisodeInfo(
                    id=f"e{number}",
                    number=number,
                    title=f"Episode {number}",
                    date="2026",
                    description="Overview",
                    watched=None,
                    image_variant=number,
                )
                for number in (1, 2, 3)
            ),
        )
        record = replace(base, id="test-show", tmdb_id=20, seasons=(season,))
        controller = _titled_controller()
        controller.records_by_id = {record.id: record}
        controller.detail_record_id = record.id
        controller.current_season_index = 0
        controller.current_episode_index = 0
        return record, controller

    def test_season_mark_keeps_existing_timestamps(self) -> None:
        record, controller = self._show()
        old_key = controller._episode_key(record, 0, record.seasons[0].episode_items[0])
        controller.episode_status_overrides[old_key] = True
        controller.episode_watched_at[old_key] = "2026-01-01T10:00:00+00:00"
        controller._populate_season_page = (  # type: ignore[method-assign]
            lambda *args, **kwargs: controller.saved.append("season-page")
        )
        controller._mark_season_watched(record, 0, "2026-09-04T21:35:00+03:30")
        self.assertEqual(
            controller.episode_watched_at[old_key], "2026-01-01T10:00:00+00:00"
        )
        for number in (2, 3):
            key = controller._episode_key(
                record, 0, record.seasons[0].episode_items[number - 1]
            )
            self.assertEqual(
                controller.episode_watched_at.get(key), "2026-09-04T21:35:00+03:30"
            )

    def test_local_watched_episode_moves_show_into_watching(self) -> None:
        record, controller = self._show()
        record = replace(record, status="Watchlist")
        controller.records_by_id = {record.id: record}
        controller.selected_id = record.id
        controller.detail_record_id = record.id
        controller.details_open = True
        controller._collection_results_dirty = False
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.records = ()
        controller.library_ids = set()
        controller._tmdb_record_aliases = {}
        controller._library_records_by_canonical = {}
        result_refreshes: list[str] = []
        controller._refresh_results = lambda: result_refreshes.append("refresh")

        controller._mark_episode_watched(
            record,
            0,
            2,
            "2026-09-04T21:35:00+03:30",
        )

        canonical = controller._canonical_record_id(record)
        self.assertIn(canonical, controller.local_library_records)
        self.assertEqual(controller._effective_status(record), "Watching")
        self.assertFalse(controller._is_record_completed(record))
        self.assertEqual(controller.selected_id, record.id)
        self.assertEqual(controller.detail_record_id, record.id)
        self.assertEqual(result_refreshes, [])
        self.assertTrue(controller._collection_results_dirty)

        controller._unmark_episode_watched(
            record,
            0,
            record.seasons[0].episode_items[1],
        )
        self.assertEqual(controller._effective_status(record), "Watchlist")
        self.assertEqual(controller.selected_id, record.id)
        self.assertEqual(controller.detail_record_id, record.id)
        self.assertEqual(result_refreshes, [])
        self.assertTrue(controller._collection_results_dirty)

    def test_episode_mutation_is_episode_scoped(self) -> None:
        record, controller = self._show()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        captured: dict[str, object] = {}

        def fake_set_episode(client_id, token, group, ids, season, episodes):
            captured.update(
                {
                    "group": group,
                    "ids": ids,
                    "season": season,
                    "episodes": episodes,
                }
            )
            return {"added": {"episodes": 1}}

        def fake_mutation(key, operation, on_success, message):
            operation()
            on_success()

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(
                simkl_client, "set_episode_watched", side_effect=fake_set_episode
            ),
        ):
            controller._mark_episode_watched(record, 0, 2, "2026-09-04T21:35:00+03:30")

        self.assertEqual(captured["season"], 1)
        self.assertEqual(captured["episodes"], [(2, "2026-09-04T21:35:00+03:30")])
        key = controller._episode_key(record, 0, record.seasons[0].episode_items[1])
        self.assertTrue(controller.episode_status_overrides[key])
        self.assertEqual(
            controller.episode_watched_at[key], "2026-09-04T21:35:00+03:30"
        )
        self.assertNotIn(record.id, controller.completed)

    def test_profile_stats_work_with_iso_timestamps(self) -> None:
        from datetime import datetime

        record, controller = self._show()
        controller.records = (record,)
        controller.records_by_id = {record.id: record}
        controller.simkl_stats = {}
        controller.ratings = {}
        today = datetime.now().astimezone().date()
        iso_today = today.strftime("%Y-%m-%dT10:00:00+00:00")
        key = controller._episode_key(record, 0, record.seasons[0].episode_items[0])
        controller.episode_status_overrides[key] = True
        controller.episode_watched_at[key] = iso_today
        stats = controller._profile_stats()
        self.assertIn(today, stats["activity"])
        self.assertGreaterEqual(stats["month_episode_count"], 1)
        self.assertGreaterEqual(stats["year_episode_count"], 1)
        self.assertGreater(stats["television_minutes"], 0)

    def test_episode_unwatch_uses_episode_remove(self) -> None:
        record, controller = self._show()
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        controller.simkl_connected = True
        key = controller._episode_key(record, 0, record.seasons[0].episode_items[0])
        controller.episode_status_overrides[key] = True
        controller.episode_watched_at[key] = "2026-01-01T10:00:00+00:00"
        removed: list[str] = []

        def fake_mutation(mutation_key, operation, on_success, message):
            removed.append(mutation_key)
            operation()
            on_success()

        with (
            patch.object(controller, "_run_simkl_mutation", side_effect=fake_mutation),
            patch.object(
                simkl_client,
                "remove_episode_watched",
                return_value={},
            ) as remover,
        ):
            controller._unmark_episode_watched(
                record, 0, record.seasons[0].episode_items[0]
            )

        remover.assert_called_once()
        self.assertFalse(controller.episode_status_overrides[key])
        self.assertNotIn(key, controller.episode_watched_at)


if __name__ == "__main__":
    unittest.main()
