from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures/library.json"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import window as gisheh
from gisheh.services import tmdb_client


def _base_record() -> gisheh.TitleRecord:
    records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
    base = next(record for record in records if record.media_type == "Shows")
    return base


def _episodes(*numbers: int) -> tuple[gisheh.EpisodeInfo, ...]:
    return tuple(
        gisheh.EpisodeInfo(
            id=f"e{number}",
            number=number,
            title=f"Placeholder {number}",
            date="2026",
            description="Placeholder overview",
            watched=None,
            image_variant=number,
        )
        for number in numbers
    )


def _controller_for(record: gisheh.TitleRecord, token: str | None = "token"):
    controller = object.__new__(gisheh.GishehWindow)
    controller.tmdb_token = token
    controller.completed = set()
    controller.episode_status_overrides = {}
    controller._tmdb_episode_details_loading = set()
    controller._tmdb_episode_details_loaded = set()
    controller._tmdb_season_details_loading = set()
    controller._tmdb_season_details_loaded = set()
    controller.records_by_id = {record.id: record}
    return controller


class SeasonMergeTests(unittest.TestCase):
    def test_episodes_matched_by_number_despite_order(self) -> None:
        episodes = _episodes(1, 2, 3)
        payload = [
            {
                "episode_number": 3,
                "name": "Third",
                "air_date": "2026-03-01",
                "overview": "Third overview",
                "runtime": 45,
                "guest_stars": [],
                "still_path": "",
            },
            {
                "episode_number": 1,
                "name": "First",
                "air_date": "2026-01-01",
                "overview": "First overview",
                "runtime": 50,
                "guest_stars": [],
                "still_path": "",
            },
            {
                "episode_number": 2,
                "name": "Second",
                "air_date": "2026-02-01",
                "overview": "Second overview",
                "runtime": 55,
                "guest_stars": [],
                "still_path": "",
            },
        ]
        merged = gisheh.merge_tmdb_season_episodes(episodes, payload)
        by_number = {episode.number: episode for episode in merged}
        self.assertEqual(by_number[1].title, "First")
        self.assertEqual(by_number[2].title, "Second")
        self.assertEqual(by_number[3].title, "Third")

    def test_empty_tmdb_values_preserve_existing(self) -> None:
        existing = gisheh.EpisodeInfo(
            id="e1",
            number=1,
            title="Kept title",
            date="2026-01-01",
            description="Kept overview",
            watched=True,
            image_variant=3,
            artwork_file="/cache/kept.jpg",
            runtime="45m",
            cast=(gisheh.CastMember("Actor", "Lead"),),
        )
        payload = [
            {
                "episode_number": 1,
                "name": "",
                "air_date": "",
                "overview": "",
                "runtime": 0,
                "guest_stars": [],
                "still_path": "",
            },
            {
                "episode_number": 1,
                "name": "Ignored duplicate",
                "air_date": "",
                "overview": "",
                "runtime": 0,
                "guest_stars": [],
                "still_path": "",
            },
            "malformed",
            {"no_number": True},
        ]
        with patch.object(tmdb_client, "cached_image", return_value=None):
            merged = gisheh.merge_tmdb_season_episodes((existing,), payload)
        self.assertEqual(merged[0].title, "Kept title")
        self.assertEqual(merged[0].date, "2026-01-01")
        self.assertEqual(merged[0].description, "Kept overview")
        self.assertEqual(merged[0].runtime, "45m")
        self.assertEqual(merged[0].cast, (gisheh.CastMember("Actor", "Lead"),))
        self.assertEqual(merged[0].artwork_file, "/cache/kept.jpg")

    def test_runtime_uses_format_watch_time(self) -> None:
        episodes = _episodes(4)
        payload = [
            {
                "episode_number": 4,
                "name": "Runtime",
                "air_date": "2026-04-01",
                "overview": "Overview",
                "runtime": 125,
                "guest_stars": [],
                "still_path": "",
            },
        ]
        merged = gisheh.merge_tmdb_season_episodes(episodes, payload)
        self.assertEqual(merged[0].runtime, gisheh.format_watch_time(125))

    def test_specials_season_zero_uses_real_number(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._tmdb_season_cache_key("rec", 0),
            "rec:s0",
        )
        self.assertNotEqual(
            gisheh.GishehWindow._tmdb_season_cache_key("rec", 0),
            gisheh.GishehWindow._tmdb_season_cache_key("rec", 1),
        )
        episodes = _episodes(1)
        payload = [
            {
                "episode_number": 1,
                "name": "Special One",
                "air_date": "2026-01-01",
                "overview": "Special overview",
                "runtime": 30,
                "guest_stars": [],
                "still_path": "",
            },
        ]
        merged = gisheh.merge_tmdb_season_episodes(episodes, payload)
        self.assertEqual(merged[0].title, "Special One")

    def test_watched_state_and_identity_preserved(self) -> None:
        existing = gisheh.EpisodeInfo(
            id="local-e7",
            number=7,
            title="Old",
            date="2026",
            description="Old",
            watched=True,
            image_variant=9,
            artwork_file="/cache/old.jpg",
        )
        payload = [
            {
                "episode_number": 7,
                "name": "New",
                "air_date": "2026-07-01",
                "overview": "New overview",
                "runtime": 42,
                "guest_stars": [
                    {"name": "Guest", "character": "Visitor", "profile_path": ""}
                ],
                "still_path": "",
            },
        ]
        with patch.object(tmdb_client, "cached_image", return_value=None):
            merged = gisheh.merge_tmdb_season_episodes((existing,), payload)
        self.assertEqual(merged[0].id, "local-e7")
        self.assertTrue(merged[0].watched)
        self.assertEqual(merged[0].image_variant, 9)
        self.assertEqual(merged[0].title, "New")
        self.assertEqual(len(merged[0].cast), 1)
        self.assertEqual(merged[0].cast[0].name, "Guest")


class SeasonRequestTests(unittest.TestCase):
    def _record(self, season_number: int = 1) -> gisheh.TitleRecord:
        base = _base_record()
        season = gisheh.SeasonInfo(
            id="specials" if season_number == 0 else f"s{season_number}",
            number=season_number,
            title="Specials" if season_number == 0 else f"Season {season_number}",
            watched=0,
            episodes=3,
            episode_items=_episodes(1, 2, 3),
        )
        other = gisheh.SeasonInfo(
            id="s2" if season_number != 2 else "s1",
            number=2 if season_number != 2 else 1,
            title="Season 2",
            watched=0,
            episodes=2,
        )
        return replace(base, id="test-title", tmdb_id=20, seasons=(season, other))

    def test_loading_request_is_deduplicated(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller._tmdb_season_details_loading.add("test-title:s1")
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            controller._load_tmdb_season_details_async(record, 0)
        thread.assert_not_called()

    def test_loaded_season_is_not_fetched_again(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller._tmdb_season_details_loaded.add("test-title:s1")
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            controller._load_tmdb_season_details_async(record, 0)
        thread.assert_not_called()

    def test_different_seasons_use_different_keys(self) -> None:
        record = self._record(season_number=1)
        controller = _controller_for(record)
        started: list[str] = []

        def fake_thread(*args, **kwargs):
            started.append(args[0])
            raise AssertionError("stop")

        with patch.object(gisheh.GishehWindow, "_start_worker", side_effect=fake_thread):
            with self.assertRaises(AssertionError):
                controller._load_tmdb_season_details_async(record, 0)
            key_one = next(iter(controller._tmdb_season_details_loading))
            controller._tmdb_season_details_loading.clear()
            controller._tmdb_season_details_loaded.add(key_one)
            with self.assertRaises(AssertionError):
                controller._load_tmdb_season_details_async(record, 1)
            key_two = next(key for key in controller._tmdb_season_details_loading)
        self.assertNotEqual(key_one, key_two)
        self.assertIn(":s1", key_one)
        self.assertIn(":s2", key_two)
        self.assertEqual(len(started), 2)

    def test_missing_token_or_tmdb_id_starts_no_request(self) -> None:
        record = self._record()
        no_token = _controller_for(record, token=None)
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            no_token._load_tmdb_season_details_async(record, 0)
        thread.assert_not_called()
        no_id_record = replace(record, tmdb_id=None)
        no_id = _controller_for(no_id_record, token="token")
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            no_id._load_tmdb_season_details_async(no_id_record, 0)
        thread.assert_not_called()

    def test_episode_opening_waits_for_the_complete_season_response(self) -> None:
        record = self._record()
        controller = _controller_for(record)

        self.assertFalse(controller._season_episode_details_ready(record, 0))
        controller._tmdb_season_details_loaded.add("test-title:s1")
        self.assertTrue(controller._season_episode_details_ready(record, 0))

        local_only = _controller_for(record, token=None)
        self.assertTrue(local_only._season_episode_details_ready(record, 0))

    def test_episode_loader_skipped_after_season_loaded_or_loading(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller._tmdb_season_details_loaded.add("test-title:s1")
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            controller._load_tmdb_episode_details_async(record, 0, 0)
        thread.assert_not_called()
        controller._tmdb_season_details_loaded.clear()
        controller._tmdb_season_details_loading.add("test-title:s1")
        with patch.object(gisheh.GishehWindow, "_start_worker") as thread:
            controller._load_tmdb_episode_details_async(record, 0, 0)
        thread.assert_not_called()

    def test_season_preload_starts_from_season_entry_point(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        season_activated = source.split("def _on_season_activated")[1].split(
            "def _on_episode_activated"
        )[0]
        self.assertIn("_load_tmdb_season_details_async", season_activated)
        self.assertNotIn("def _on_season_switch_changed", source)

        episode_activated = source.split("def _on_episode_activated")[1].split(
            "def _on_episode_row_watched_clicked"
        )[0]
        self.assertIn("_season_episode_details_ready", episode_activated)
        self.assertIn(
            "Wait for all episode details to finish loading",
            episode_activated,
        )

    def test_apply_marks_episode_keys_loaded(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller._store_tmdb_record = lambda updated, refresh_details=True: (
            controller.records_by_id.__setitem__(updated.id, updated)
        )
        controller._refresh_visible_season_page = lambda *args: None
        controller._refresh_visible_episode_for_season = lambda *args: None
        updates = (
            (1, "One", "2026-01-01", "Overview one", "45m", (), None),
            (2, "Two", "2026-01-02", "Overview two", "45m", (), None),
        )
        result = controller._apply_tmdb_season_details(
            record.id, 1, "test-title:s1", updates
        )
        self.assertFalse(result)
        self.assertIn("test-title:s1", controller._tmdb_season_details_loaded)
        self.assertIn("test-title:s1:e1", controller._tmdb_episode_details_loaded)
        self.assertIn("test-title:s1:e2", controller._tmdb_episode_details_loaded)
        stored = controller.records_by_id[record.id]
        titles = {
            episode.number: episode.title for episode in stored.seasons[0].episode_items
        }
        self.assertEqual(titles[1], "One")
        self.assertEqual(titles[2], "Two")

    def test_season_is_published_only_after_pending_stills_finish(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        scheduled: list[tuple[object, tuple[object, ...]]] = []
        payload = {
            "episodes": [
                {
                    "episode_number": 1,
                    "name": "One",
                    "air_date": "2026-01-01",
                    "overview": "Overview",
                    "runtime": 45,
                    "guest_stars": [],
                    "still_path": "/one.jpg",
                }
            ]
        }

        with (
            patch.object(
                gisheh.tmdb_client, "fetch_season_details", return_value=payload
            ),
            patch.object(gisheh.tmdb_client, "cached_image", return_value=None),
            patch.object(
                gisheh.tmdb_client, "cache_image", return_value="/cache/one.jpg"
            ),
            patch.object(
                gisheh.GLib,
                "idle_add",
                side_effect=lambda callback, *args: scheduled.append((callback, args)),
            ),
        ):
            controller._load_tmdb_season_details_worker(
                record.id,
                "token",
                record.tmdb_id or 0,
                1,
                "test-title:s1",
            )

        self.assertEqual(len(scheduled), 1)
        callback, arguments = scheduled[0]
        self.assertEqual(callback.__name__, "_apply_tmdb_season_details")
        updates = arguments[-1]
        self.assertEqual(updates[0][-1], "/cache/one.jpg")

    def test_background_update_cannot_switch_the_open_episode(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller.detail_record_id = record.id
        controller.current_season_index = 0
        controller.current_episode_index = 0
        controller.detail_navigation = type(
            "Navigation",
            (),
            {"get_visible_page_tag": lambda self: "episode"},
        )()

        with patch.object(controller, "_populate_episode_page") as populate:
            controller._refresh_visible_episode_page(record, 1, 2)
            populate.assert_not_called()
            controller._refresh_visible_episode_page(record, 1, 1)
            populate.assert_called_once_with(
                record,
                0,
                0,
                reset_scroll=False,
            )

    def test_background_title_refresh_does_not_close_open_episode(self) -> None:
        record = self._record()
        controller = _controller_for(record)
        controller.selected_id = record.id
        controller.detail_record_id = record.id
        controller.detail_box = MagicMock()
        controller.detail_poster_host = MagicMock()
        controller.detail_status_label = MagicMock()
        controller.detail_overline = MagicMock()
        controller.detail_title = MagicMock()
        controller.community_rating = MagicMock()
        controller.watched_button = MagicMock()
        controller.runtime_label = MagicMock()
        controller.genres_label = MagicMock()
        controller.overview_label = MagicMock()
        controller.creator_row = MagicMock()
        controller.release_row = MagicMock()
        controller.country_row = MagicMock()
        controller.activity_row = MagicMock()
        controller.bookmark_button = MagicMock()
        controller.rating_buttons = {}
        controller.rating_value = MagicMock()
        controller.rating_button = MagicMock()
        controller.details_scroller = MagicMock()
        controller.bookmarks = set()
        controller.ratings = {}

        with (
            patch.object(controller, "_reset_detail_navigation") as reset,
            patch.object(controller, "_build_detail_hero"),
            patch.object(controller, "_populate_detail_sections"),
            patch.object(controller, "_effective_status", return_value="Watching"),
            patch.object(controller, "_is_record_bookmarked", return_value=False),
            patch.object(controller, "_effective_record_rating", return_value=None),
        ):
            controller._update_details()

        reset.assert_not_called()


class EpisodePositionRemovalTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path(gisheh.__file__).read_text(encoding="utf-8")

    def test_position_widgets_and_update_logic_removed(self) -> None:
        source = self._source()
        self.assertNotIn("episode_position_label", source)
        self.assertNotIn("episode_position_dots", source)
        # Header must still carry the episode number (translatable form).
        self.assertIn(
            '_("Episode {number}").format(number=episode.number)',
            source,
        )

    def test_detail_layout_starts_with_hero_artwork(self) -> None:
        source = self._source()
        builder = source.split("def _build_episode_navigation_pages")[1].split(
            "def _detail_navigation_action"
        )[0]
        self.assertNotIn("episode_position", builder)
        self.assertNotIn(
            "CenterBox",
            builder.split("self.episode_hero_host")[1].split(
                "self.episode_detail_box = Gtk.Box"
            )[0]
            if "self.episode_detail_box = Gtk.Box" in builder
            else builder,
        )
        first_append = None
        for line in builder.splitlines():
            stripped = line.strip()
            if stripped.startswith("self.episode_detail_box.append("):
                first_append = stripped
                break
        self.assertEqual(
            first_append,
            "self.episode_detail_box.append(self.episode_hero_host)",
        )

    def test_episode_details_follow_the_title_details_visual_hierarchy(self) -> None:
        source = self._source()
        builder = source.split("def _build_episode_navigation_pages")[1].split(
            "def _detail_navigation_action"
        )[0]
        episode_layout = builder.split("self.episode_detail_box = Gtk.Box")[1]

        for component in (
            "self.episode_hero_host",
            "self.episode_status_label",
            "episode_identity",
            "episode_actions",
            "self.episode_watched_at_label",
            "episode_facts",
            "episode_overview",
            "self.episode_cast_section",
        ):
            self.assertIn(
                f"self.episode_detail_box.append({component})",
                episode_layout,
            )
        self.assertNotIn(
            "self.episode_detail_box.append(Gtk.Separator())", episode_layout
        )
        self.assertIn('add_css_class("detail-tint-content")', episode_layout)


if __name__ == "__main__":
    unittest.main()
