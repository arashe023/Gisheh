from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures/library.json"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import window as gisheh


class ExploreLayoutTests(unittest.TestCase):
    def test_pagination_keeps_existing_order_and_appends_new_records(self) -> None:
        existing = tuple(
            type("Record", (), {"id": record_id})() for record_id in ("a", "b", "c")
        )
        filtered = tuple(
            type("Record", (), {"id": record_id})()
            for record_id in ("new-high", "b", "a", "c", "new-low")
        )
        merged = gisheh.preserve_explore_page_prefix(existing, filtered)
        self.assertEqual(
            tuple(record.id for record in merged),
            ("a", "b", "c", "new-high", "new-low"),
        )

    def test_library_grid_columns_follow_real_card_width(self) -> None:
        self.assertEqual(gisheh.grid_columns_for_width(120), 1)
        self.assertEqual(gisheh.grid_columns_for_width(320), 2)
        self.assertEqual(gisheh.grid_columns_for_width(620), 4)
        self.assertEqual(gisheh.grid_columns_for_width(820), 5)
        self.assertEqual(gisheh.grid_columns_for_width(990), 6)
        self.assertEqual(gisheh.grid_columns_for_width(2000), 6)

    def test_rows_fill_without_using_a_full_width_card(self) -> None:
        for columns in (2, 3, 4, 5):
            for count in range(1, 24):
                plan = gisheh.build_explore_layout_plan(count, columns, seed=91)
                self.assertEqual(sum(len(row) for row in plan), count)
                for row_index, row in enumerate(plan):
                    used_columns = sum(span for _kind, span in row)
                    self.assertLessEqual(used_columns, columns)
                    if row_index < len(plan) - 1:
                        self.assertEqual(used_columns, columns)
                    for _kind, span in row:
                        self.assertLess(span, columns)
                        self.assertLessEqual(span / columns, 3 / 5)

    def test_plan_is_varied_and_stable_for_a_seed(self) -> None:
        first = gisheh.build_explore_layout_plan(18, 4, seed=2026)
        second = gisheh.build_explore_layout_plan(18, 4, seed=2026)
        self.assertEqual(first, second)
        kinds = {kind for row in first for kind, _span in row}
        self.assertGreaterEqual(len(kinds), 2)

    def test_initial_explore_loading_uses_content_skeletons(self) -> None:
        from gi.repository import Gtk

        view = gisheh.GishehWindow._build_explore_loading_view()
        self.assertIn("explore-loading-view", view.get_css_classes())
        placeholders = view.get_last_child()
        self.assertIsInstance(placeholders, Gtk.FlowBox)
        assert isinstance(placeholders, Gtk.FlowBox)
        count = 0
        child = placeholders.get_first_child()
        while child is not None:
            count += 1
            child = child.get_next_sibling()
        self.assertEqual(count, 5)

    def test_detail_loading_uses_media_and_cast_skeleton_shapes(self) -> None:
        media = gisheh.GishehWindow._loading_media_placeholder(
            96, 144, "Loading poster"
        )
        self.assertIn("content-skeleton-surface", media.get_css_classes())
        self.assertEqual(media.get_tooltip_text(), "Loading poster")

        cast = gisheh.GishehWindow._loading_cast_placeholder()
        avatar = cast.get_first_child()
        self.assertIsNotNone(avatar)
        assert avatar is not None
        self.assertIn("content-skeleton-avatar", avatar.get_css_classes())

    def test_missing_artwork_uses_loading_surface_instead_of_generated_cover(
        self,
    ) -> None:
        from gi.repository import Gtk

        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        record = replace(
            records[0],
            artwork_file=None,
            poster_file=None,
            backdrop_file=None,
        )
        poster = gisheh.PosterWidget(record, 140, 210)
        media = poster.get_first_child()

        self.assertIsInstance(media, Gtk.Box)
        assert media is not None
        self.assertIn("content-skeleton-surface", media.get_css_classes())
        self.assertIn("Loading artwork", media.get_tooltip_text())

    def test_episode_artwork_keeps_its_16_by_9_size_and_has_no_number_overlay(
        self,
    ) -> None:
        from gi.repository import Gtk

        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        record = next(item for item in records if item.media_type == "Shows")
        episode = gisheh.EpisodeInfo(
            id="episode-1",
            number=1,
            title="Pilot",
            date="2026-01-01",
            description="Overview",
            watched=False,
            image_variant=0,
        )
        controller = object.__new__(gisheh.GishehWindow)
        artwork = controller._episode_artwork(record, episode, 112, 63)

        self.assertEqual(artwork.get_size_request(), (112, 63))
        self.assertEqual(artwork.get_valign(), Gtk.Align.CENTER)
        self.assertIn("episode-artwork", artwork.get_css_classes())
        self.assertIsNone(artwork.get_child().get_next_sibling())

    def test_episode_watch_controls_use_native_adwaita_button_styles(self) -> None:
        from gi.repository import Gtk

        row_button = gisheh.GishehWindow._episode_watch_button(False)
        self.assertIn("circular", row_button.get_css_classes())
        self.assertIn("flat", row_button.get_css_classes())
        self.assertIn("episode-watch-button", row_button.get_css_classes())
        self.assertIsInstance(row_button.get_child(), Gtk.Image)
        self.assertEqual(row_button.get_child().get_pixel_size(), 14)

        watched_button = gisheh.GishehWindow._episode_watch_button(True)
        watched_icon = watched_button.get_child()
        self.assertIsInstance(watched_icon, Gtk.Image)
        self.assertEqual(watched_icon.get_icon_name(), "object-select-symbolic")
        self.assertIn("success", watched_icon.get_css_classes())

        stylesheet = (
            Path(__file__).resolve().parents[1] / "src/gisheh/style.css"
        ).read_text(encoding="utf-8")
        compact_rule = stylesheet.split("button.episode-watch-button {")[1].split("}")[
            0
        ]
        self.assertIn("min-width: 28px", compact_rule)
        self.assertIn("min-height: 28px", compact_rule)
        self.assertIn("padding: 0", compact_rule)
        hover_rule = stylesheet.split("button.episode-watch-button:hover {")[1].split(
            "}"
        )[0]
        self.assertIn("background-color: transparent", hover_rule)
        self.assertIn("box-shadow: none", hover_rule)

        detail_button = gisheh.GishehWindow._detail_navigation_action(
            "object-select-symbolic", "Mark watched"
        )
        self.assertNotIn("pill", detail_button.get_css_classes())
        self.assertNotIn("flat", detail_button.get_css_classes())
        content = detail_button.get_child()
        self.assertIsInstance(content, Gtk.Box)
        self.assertEqual(content.get_orientation(), Gtk.Orientation.HORIZONTAL)

    def test_carousel_labels_are_bounded_and_truncate_after_two_lines(self) -> None:
        from gi.repository import Gtk, Pango

        label = Gtk.Label(label="A very long unbroken carousel title " * 4)
        gisheh.GishehWindow._configure_bounded_card_label(label, 13)

        self.assertTrue(label.get_wrap())
        self.assertEqual(label.get_wrap_mode(), Pango.WrapMode.WORD_CHAR)
        self.assertEqual(label.get_lines(), 2)
        self.assertEqual(label.get_ellipsize(), Pango.EllipsizeMode.END)
        self.assertEqual(label.get_width_chars(), 13)
        self.assertEqual(label.get_max_width_chars(), 13)
        self.assertFalse(label.get_hexpand())

        short_label = Gtk.Label(label="Short title")
        gisheh.GishehWindow._configure_bounded_card_label(short_label, 13)
        self.assertEqual(
            label.measure(Gtk.Orientation.HORIZONTAL, -1),
            short_label.measure(Gtk.Orientation.HORIZONTAL, -1),
        )

    def test_single_line_carousel_labels_do_not_wrap(self) -> None:
        from gi.repository import Gtk, Pango

        label = Gtk.Label(label="A very long role or video title")
        gisheh.GishehWindow._configure_bounded_card_label(
            label,
            11,
            lines=1,
        )

        self.assertFalse(label.get_wrap())
        self.assertEqual(label.get_lines(), 1)
        self.assertEqual(label.get_ellipsize(), Pango.EllipsizeMode.END)


class DetailActionLayoutTests(unittest.TestCase):
    def test_section_counts_and_redundant_add_button_are_not_in_the_ui(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        objects = {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

        self.assertNotIn("section_count", objects)
        self.assertNotIn("add_title_button", objects)
        self.assertNotIn("explore_count_label", objects)
        self.assertEqual(objects["activity_progress_card"], "AdwBin")

    def test_completion_progress_is_only_shown_for_episodic_media(self) -> None:
        self.assertFalse(gisheh.should_show_completion_progress("Movies"))
        self.assertTrue(gisheh.should_show_completion_progress("Shows"))
        self.assertTrue(gisheh.should_show_completion_progress("Anime"))

    def test_season_completion_requires_at_least_one_episode(self) -> None:
        self.assertFalse(gisheh.is_episode_group_complete(0, 0))
        self.assertFalse(gisheh.is_episode_group_complete(5, 6))
        self.assertTrue(gisheh.is_episode_group_complete(6, 6))

    def test_rating_popover_and_native_secondary_menu_have_no_custom_rows(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        objects = {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

        self.assertEqual(objects["rating_button"], "GtkMenuButton")
        self.assertEqual(objects["rating_popover"], "GtkPopover")
        self.assertNotIn("more_button", objects)
        self.assertNotIn("detail_more_popover", objects)
        self.assertNotIn("comments_button", objects)
        self.assertNotIn("check_in_button", objects)
        self.assertNotIn("note_button", objects)
        self.assertNotIn("quick_actions_host", objects)
        self.assertNotIn("favorite_button", objects)
        self.assertNotIn("add_sidebar_button", objects)
        self.assertNotIn("storage_button", objects)
        self.assertNotIn("storage_progress", objects)

    def test_removed_actions_have_no_code_or_labels(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        for token in (
            "season_comments_button",
            "episode_comments_button",
            "episode_check_in_button",
            "_on_secondary_detail_action",
            "detail-comments",
            "detail-check-in",
            "detail-add-note",
            "Season comments opened",
            "Episode comments opened",
            "Episode check-in recorded",
            "Add dialog opened",
            "Library storage: 68% used",
            "12.4 / 18 GB",
        ):
            self.assertNotIn(token, source)
        ui_text = Path(gisheh.UI_FILE).read_text(encoding="utf-8")
        for token in (
            "add_sidebar_button",
            "storage_button",
            "storage_progress",
            "more_button",
            "Add to library",
            "Local library",
            "12.4 / 18 GB",
            "Comments",
            "Check in",
            "Add note",
        ):
            self.assertNotIn(token, ui_text)

    def test_season_and_episode_actions_keep_only_watched(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        season_block = source.split("season_actions = Gtk.Box(")[1].split(
            'episodes_title = Gtk.Label(label="Episodes", xalign=0)'
        )[0]
        self.assertIn("season_watched_button", season_block)
        self.assertNotIn("Comments", season_block)
        episode_block = source.split("episode_actions = Adw.WrapBox()")[1].split(
            "self.episode_watched_at_label"
        )[0]
        self.assertIn("episode_watched_button", episode_block)
        self.assertNotIn("Comments", episode_block)
        self.assertNotIn("Check in", episode_block)

    def test_season_page_has_no_redundant_switcher_or_episode_count(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        builder = source.split("def _build_episode_navigation_pages")[1].split(
            "def _detail_navigation_action"
        )[0]

        self.assertNotIn("season_switcher", builder)
        self.assertNotIn("season_episode_count", builder)
        self.assertIn(
            "self.season_detail_box.append(self.season_summary_label)",
            builder,
        )
        self.assertIn("self.season_detail_box.append(episodes_title)", builder)

    def test_profile_avatar_is_a_direct_navigation_button(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        objects = {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

        self.assertEqual(objects["profile_button"], "GtkButton")
        self.assertNotIn("profile_menu_button", objects)
        self.assertNotIn("profile_popover", objects)
        self.assertNotIn("profile_sidebar_list", objects)
        self.assertNotIn("profile_sidebar_row", objects)


class HeaderDataStatusTests(unittest.TestCase):
    @staticmethod
    def _controller() -> gisheh.GishehWindow:
        from gi.repository import Gtk

        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.simkl_connected = False
        controller._simkl_sync_started_at = 0.0
        controller._simkl_sync_error = None
        controller.header_data_status_button = Gtk.Button()
        controller.header_data_status_icon = Gtk.Image()
        controller.header_data_status_spinner = Gtk.Spinner()
        controller.header_data_status_label = Gtk.Label()
        return controller

    def test_header_status_is_a_real_button_with_loading_indicator(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        objects = {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

        self.assertEqual(objects["header_data_status_button"], "GtkButton")
        self.assertEqual(objects["header_data_status_spinner"], "GtkSpinner")

    def test_header_status_reflects_local_syncing_synced_and_failed_states(
        self,
    ) -> None:
        controller = self._controller()

        controller._update_header_data_status()
        self.assertEqual(controller.header_data_status_label.get_label(), "Local")
        self.assertEqual(
            controller.header_data_status_icon.get_icon_name(),
            "drive-harddisk-symbolic",
        )
        self.assertTrue(controller.header_data_status_button.get_sensitive())

        controller.library_mode = gisheh.LIBRARY_MODE_SIMKL
        controller._simkl_sync_started_at = 1.0
        controller._update_header_data_status()
        self.assertEqual(controller.header_data_status_label.get_label(), "Syncing…")
        self.assertTrue(controller.header_data_status_spinner.get_spinning())
        self.assertFalse(controller.header_data_status_button.get_sensitive())

        controller._simkl_sync_started_at = 0.0
        controller.simkl_connected = True
        controller._update_header_data_status()
        self.assertEqual(controller.header_data_status_label.get_label(), "Synced")
        self.assertEqual(
            controller.header_data_status_icon.get_icon_name(),
            "object-select-symbolic",
        )
        self.assertTrue(controller.header_data_status_button.get_sensitive())

        controller._simkl_sync_error = "Network unavailable"
        controller._update_header_data_status()
        self.assertEqual(controller.header_data_status_label.get_label(), "Sync failed")
        self.assertEqual(
            controller.header_data_status_icon.get_icon_name(),
            "dialog-warning-symbolic",
        )

    def test_header_button_runs_the_action_for_the_current_mode(self) -> None:
        controller = self._controller()
        actions: list[str] = []
        controller._on_preferences_clicked = lambda _button: actions.append(
            "preferences"
        )
        controller._on_simkl_button_clicked = lambda _button: actions.append("sync")

        controller._on_header_data_status_clicked(controller.header_data_status_button)
        controller.library_mode = gisheh.LIBRARY_MODE_SIMKL
        controller._on_header_data_status_clicked(controller.header_data_status_button)

        self.assertEqual(actions, ["preferences", "sync"])


class SettingsDialogTests(unittest.TestCase):
    @staticmethod
    def _controller() -> gisheh.GishehWindow:
        controller = object.__new__(gisheh.GishehWindow)
        controller.simkl_connected = False
        controller.simkl_client_id = "public-client-id"
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.tmdb_token = None
        controller.auto_sync = True
        controller.color_scheme = "dark"
        controller.default_media = "Movies"
        controller.preferred_view_mode = "list"
        return controller

    def test_native_preferences_dialog_contains_functional_controls(self) -> None:
        from gi.repository import Adw

        controller = self._controller()

        controller._build_settings_dialog()

        self.assertIsInstance(controller.settings_dialog, Adw.PreferencesDialog)
        self.assertEqual(controller.settings_dialog.get_title(), "Preferences")
        self.assertTrue(controller.settings_dialog.get_search_enabled())
        self.assertEqual(
            controller.settings_dialog.get_visible_page().get_title(),
            "General",
        )
        self.assertEqual(controller.settings_color_scheme_row.get_selected(), 2)
        self.assertFalse(hasattr(controller, "settings_accent_row"))
        self.assertEqual(controller.settings_media_row.get_selected(), 0)
        self.assertEqual(controller.settings_view_row.get_selected(), 0)
        self.assertTrue(controller.settings_auto_sync_row.get_active())
        self.assertEqual(controller.settings_simkl_button.get_label(), "Use Simkl")
        self.assertIn(
            "Local-first",
            controller.settings_library_mode_row.get_subtitle(),
        )
        self.assertEqual(controller.settings_tmdb_button.get_label(), "Developer Setup")
        self.assertFalse(controller.settings_simkl_disconnect_button.get_visible())
        self.assertFalse(controller.settings_tmdb_disconnect_button.get_visible())
        self.assertEqual(
            controller.settings_factory_reset_row.get_title(),
            "Reset Gisheh",
        )
        self.assertTrue(
            controller.settings_factory_reset_button.has_css_class("destructive-action")
        )

    def test_connected_services_are_reflected_in_settings(self) -> None:
        controller = self._controller()
        controller.library_mode = gisheh.LIBRARY_MODE_SIMKL
        controller.simkl_connected = True
        controller.tmdb_token = "secret-token"

        controller._build_settings_dialog()

        self.assertEqual(controller.settings_simkl_button.get_label(), "Sync Now")
        self.assertEqual(controller.settings_tmdb_button.get_label(), "Change Token")
        self.assertTrue(controller.settings_simkl_disconnect_button.get_visible())
        self.assertTrue(controller.settings_tmdb_disconnect_button.get_visible())
        self.assertNotIn("secret-token", controller.settings_tmdb_row.get_subtitle())

    def test_preferences_round_trip_through_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_file = Path(temporary_directory) / "state.json"
            writer = object.__new__(gisheh.GishehWindow)
            writer.state_file = state_file
            writer.bookmarks = set()
            writer.favorites = set()
            writer.completed = set()
            writer.ratings = {}
            writer.status_overrides = {}
            writer.episode_status_overrides = {}
            writer.episode_watched_at = {}
            writer.title_watched_at = {}
            writer.color_scheme = "light"
            writer.auto_sync = False
            writer.default_media = "Anime"
            writer.preferred_view_mode = "grid"
            writer.active_collection = "Dropped"
            writer.collection_selected_ids = {
                collection: ("tmdb-movie-77" if collection == "Dropped" else None)
                for collection in gisheh.COLLECTION_NAMES
            }
            writer.collection_scroll_positions = {
                collection: (32.5 if collection == "Dropped" else 0.0)
                for collection in gisheh.COLLECTION_NAMES
            }
            writer.collection_view_states = {
                collection: {
                    "query": "unfinished" if collection == "Dropped" else "",
                    "genre": "Drama" if collection == "Dropped" else "All genres",
                    "sortKey": "title" if collection == "Dropped" else "recent",
                    "sortReversed": collection == "Dropped",
                }
                for collection in gisheh.COLLECTION_NAMES
            }
            writer._save_user_state()

            reader = object.__new__(gisheh.GishehWindow)
            reader.state_file = state_file
            reader.records_by_id = {}
            reader.simkl_token = None
            reader.simkl_connected = False
            reader.bookmarks = set()
            reader.favorites = set()
            reader.completed = set()
            reader.ratings = {}
            reader.status_overrides = {}
            reader.episode_status_overrides = {}
            reader.episode_watched_at = {}
            reader.title_watched_at = {}
            reader.color_scheme = "dark"
            reader.auto_sync = True
            reader.default_media = "Movies"
            reader.preferred_view_mode = "list"
            reader.active_media = "Movies"
            reader.view_mode = "list"
            reader._load_user_state()

            self.assertEqual(reader.color_scheme, "light")
            self.assertFalse(reader.auto_sync)
            self.assertEqual(reader.default_media, "Anime")
            self.assertEqual(reader.active_media, "Anime")
            self.assertEqual(reader.preferred_view_mode, "grid")
            self.assertEqual(reader.view_mode, "grid")
            self.assertEqual(reader.active_collection, "Dropped")
            self.assertEqual(reader.collection_selected_ids["Dropped"], "tmdb-movie-77")
            self.assertEqual(reader.collection_scroll_positions["Dropped"], 32.5)
            self.assertEqual(
                reader.collection_view_states["Dropped"],
                {
                    "query": "unfinished",
                    "genre": "Drama",
                    "sortKey": "title",
                    "sortReversed": True,
                },
            )


class DataSourceCreditsTests(unittest.TestCase):
    def test_sample_catalog_is_kept_out_of_production_resources(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        resource_manifest = (
            project_root / "src/gisheh/io.github.arashe023.Gisheh.gresource.xml"
        ).read_text(encoding="utf-8")
        meson_source = (project_root / "src/meson.build").read_text(encoding="utf-8")

        self.assertTrue(SAMPLE_DATA.is_file())
        self.assertFalse((project_root / "src/gisheh/library.json").exists())
        self.assertNotIn("library.json", resource_manifest)
        self.assertNotIn("gisheh/library.json", meson_source)

        records, explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        self.assertTrue(records)
        self.assertTrue(explore)

    def test_tmdb_attribution_and_official_logo_are_bundled(self) -> None:
        application_source = (
            Path(__file__).resolve().parents[1] / "src/gisheh/application.py"
        ).read_text(encoding="utf-8")
        resource_manifest = (
            Path(__file__).resolve().parents[1]
            / "src/gisheh/io.github.arashe023.Gisheh.gresource.xml"
        ).read_text(encoding="utf-8")
        logo = Path(__file__).resolve().parents[1] / "src/gisheh/assets/tmdb-logo.svg"

        self.assertIn(
            "This product uses the TMDB API but is not endorsed or certified by TMDB.",
            application_source,
        )
        self.assertIn("https://www.themoviedb.org", application_source)
        self.assertIn("Credits & Data Sources", application_source)
        self.assertIn("assets/tmdb-logo.svg", resource_manifest)
        self.assertTrue(logo.is_file())

    def test_simkl_release_flow_never_asks_users_for_developer_credentials(
        self,
    ) -> None:
        window_source = (
            Path(__file__).resolve().parents[1] / "src/gisheh/window.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Create an app in Simkl Developer Settings", window_source)
        self.assertNotIn("Open Simkl Developer Settings", window_source)
        self.assertNotIn("Enter a Simkl Client ID", window_source)
        self.assertIn("Simkl sign-in started; requesting a PIN.", window_source)


class SeasonProgressTests(unittest.TestCase):
    @staticmethod
    def _record_with_seasons(
        seasons: tuple[gisheh.SeasonInfo, ...],
    ) -> gisheh.TitleRecord:
        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        base = next(record for record in records if record.media_type == "Shows")
        return replace(base, seasons=seasons)

    @staticmethod
    def _controller() -> gisheh.GishehWindow:
        controller = object.__new__(gisheh.GishehWindow)
        controller.completed = set()
        controller.episode_status_overrides = {}
        return controller

    def test_specials_are_excluded_from_regular_next_and_last_episode(self) -> None:
        special = gisheh.SeasonInfo("specials", 0, "Specials", 0, 2)
        regular = gisheh.SeasonInfo("s1", 1, "Season 1", 2, 2)
        record = self._record_with_seasons((special, regular))
        controller = self._controller()

        next_item, last_item = controller._episode_progress_items(record)

        self.assertEqual(gisheh.main_progress_season_indexes(record.seasons), (1,))
        self.assertIsNone(next_item)
        self.assertIsNotNone(last_item)
        assert last_item is not None
        self.assertEqual(controller._episode_code(record, *last_item), "S1E2")

    def test_specials_only_catalog_is_used_as_progress_fallback(self) -> None:
        special = gisheh.SeasonInfo("specials", 0, "Specials", 0, 2)
        record = self._record_with_seasons((special,))
        controller = self._controller()

        next_item, last_item = controller._episode_progress_items(record)

        self.assertEqual(gisheh.main_progress_season_indexes(record.seasons), (0,))
        self.assertIsNone(last_item)
        self.assertIsNotNone(next_item)
        assert next_item is not None
        self.assertEqual(controller._episode_code(record, *next_item), "S0E1")

    def test_watched_special_does_not_move_regular_series_progress(self) -> None:
        special = gisheh.SeasonInfo("specials", 0, "Specials", 0, 1)
        regular = gisheh.SeasonInfo("s1", 1, "Season 1", 0, 2)
        record = self._record_with_seasons((special, regular))
        controller = self._controller()
        controller.episode_status_overrides[f"{record.id}/specials/e1"] = True

        next_item, last_item = controller._episode_progress_items(record)

        self.assertIsNone(last_item)
        self.assertIsNotNone(next_item)
        assert next_item is not None
        self.assertEqual(controller._episode_code(record, *next_item), "S1E1")

    def test_completion_progress_uses_actual_watched_episode_count(self) -> None:
        special = gisheh.SeasonInfo("specials", 0, "Specials", 1, 1)
        first = gisheh.SeasonInfo("s1", 1, "Season 1", 3, 8)
        second = gisheh.SeasonInfo("s2", 2, "Season 2", 2, 4)
        record = self._record_with_seasons((special, first, second))
        controller = self._controller()

        self.assertEqual(controller._series_completion_progress(record), (5, 12))

    def test_completion_progress_reflects_episode_overrides(self) -> None:
        season = gisheh.SeasonInfo("s1", 1, "Season 1", 1, 4)
        record = self._record_with_seasons((season,))
        controller = self._controller()
        controller.episode_status_overrides[f"{record.id}/s1/e2"] = True

        self.assertEqual(controller._series_completion_progress(record), (2, 4))

    def test_completed_series_reports_full_progress(self) -> None:
        season = gisheh.SeasonInfo("s1", 1, "Season 1", 2, 6)
        record = self._record_with_seasons((season,))
        controller = self._controller()
        controller.completed.add(record.id)

        self.assertEqual(controller._series_completion_progress(record), (6, 6))

    def test_activity_card_shows_partial_percentage_and_episode_counts(self) -> None:
        from gi.repository import Adw, Gtk

        season = gisheh.SeasonInfo("s1", 1, "Season 1", 5, 12)
        record = self._record_with_seasons((season,))
        controller = self._controller()
        controller.activity_progress_card = Adw.Bin()
        controller.activity_status = Gtk.Label()
        controller.activity_percentage = Gtk.Label()
        controller.activity_progress = Gtk.ProgressBar()

        controller._update_activity_progress(record)

        self.assertTrue(controller.activity_progress_card.get_visible())
        self.assertEqual(
            controller.activity_status.get_label(),
            "5 of 12 episodes watched",
        )
        self.assertEqual(controller.activity_percentage.get_label(), "42%")
        self.assertAlmostEqual(controller.activity_progress.get_fraction(), 5 / 12)

    def test_exact_simkl_history_preserves_a_gap_between_watched_episodes(self) -> None:
        payload = {
            "movies": [],
            "shows": [
                {
                    "status": "watching",
                    "watched_episodes_count": 9,
                    "total_episodes_count": 10,
                    "show": {"ids": {"simkl": 42, "tmdb": 84}},
                    "seasons": [
                        {
                            "number": 1,
                            "episodes": [
                                {"number": number, "watched_at": "2026-09-01T12:00:00Z"}
                                for number in (*range(1, 6), *range(7, 11))
                            ],
                        }
                    ],
                }
            ],
            "anime": [],
        }
        record = gisheh.title_records_from_simkl(payload)[0]
        record = replace(
            record,
            seasons=(gisheh.SeasonInfo("s1", 1, "Season 1", 9, 10),),
        )
        controller = self._controller()

        next_item, last_item = controller._episode_progress_items(record)

        self.assertTrue(record.episode_history_loaded)
        self.assertEqual(len(record.episode_history), 9)
        assert next_item is not None
        assert last_item is not None
        self.assertEqual(controller._episode_code(record, *next_item), "S1E6")
        self.assertEqual(controller._episode_code(record, *last_item), "S1E10")

    def test_anime_episode_history_uses_tvdb_season_mapping(self) -> None:
        payload = {
            "movies": [],
            "shows": [],
            "anime": [
                {
                    "status": "watching",
                    "watched_episodes_count": 1,
                    "total_episodes_count": 12,
                    "show": {"ids": {"simkl": 50, "tmdb": 100}},
                    "seasons": [
                        {
                            "number": 1,
                            "episodes": [
                                {
                                    "number": 13,
                                    "tvdb": {"season": 2, "episode": 1},
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        record = gisheh.title_records_from_simkl(payload)[0]

        self.assertEqual(
            record.episode_history,
            (gisheh.EpisodeWatch(season=2, episode=1),),
        )


class MediaCollectionTests(unittest.TestCase):
    def test_media_items_keep_primary_first_and_remove_duplicates(self) -> None:
        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first.jpg"
            second = Path(temporary_directory) / "second.jpg"
            first.touch()
            second.touch()
            record = replace(
                records[0],
                poster_file=str(first),
                gallery_posters=(str(first), str(second), "/missing.jpg"),
            )

            items = gisheh.GishehWindow._media_items(record, "posters")

        self.assertEqual([path for path, _label in items], [str(first), str(second)])
        self.assertEqual(items[0][1], f"{record.title} — Poster 1")


class ProfileFormattingTests(unittest.TestCase):
    def test_runtime_minutes_handles_catalog_durations(self) -> None:
        self.assertEqual(gisheh.runtime_minutes("2h 04m"), 124)
        self.assertEqual(gisheh.runtime_minutes("45m"), 45)
        self.assertEqual(gisheh.runtime_minutes("3 seasons"), 0)

    def test_watch_time_and_dates_are_stable(self) -> None:
        self.assertEqual(gisheh.format_watch_time(6502), "4d 12h 22m")
        parsed = gisheh.parse_watched_date("Aug 8, 2026 at 2:49 AM")
        self.assertEqual(parsed.isoformat() if parsed else None, "2026-08-08")


class SimklMappingTests(unittest.TestCase):
    def test_library_payload_maps_movies_shows_and_anime(self) -> None:
        payload = {
            "movies": [
                {
                    "status": "completed",
                    "last_watched_at": "2026-08-30T20:10:00Z",
                    "user_rating": 9,
                    "movie": {
                        "title": "Example Movie",
                        "runtime": 124,
                        "year": 2025,
                        "poster": "12/345",
                        "ids": {"simkl": 101, "tmdb": 201},
                    },
                }
            ],
            "shows": [
                {
                    "status": "watching",
                    "watched_episodes_count": 4,
                    "total_episodes_count": 10,
                    "show": {
                        "title": "Example Show",
                        "runtime": 55,
                        "year": 2024,
                        "ids": {"simkl": 102, "tmdb": 202},
                    },
                }
            ],
            "anime": [
                {
                    "status": "plantowatch",
                    "show": {
                        "title": "Example Anime",
                        "year": 2023,
                        "ids": {"simkl": 103},
                    },
                },
                {
                    "status": "hold",
                    "show": {
                        "title": "Paused Anime",
                        "year": 2022,
                        "ids": {"simkl": 104, "tmdb": 204},
                    },
                },
            ],
        }

        records = gisheh.title_records_from_simkl(payload)

        by_id = {record.id: record for record in records}
        movie = by_id["simkl-movies-101"]
        show = by_id["simkl-shows-102"]
        anime = by_id["simkl-anime-103"]
        paused = by_id["simkl-anime-104"]
        self.assertTrue(all(record.title == "Loading from TMDB…" for record in records))
        self.assertTrue(all(record.year == 0 for record in records))
        self.assertEqual(movie.media_type, "Movies")
        self.assertEqual(movie.status, "Watched")
        self.assertEqual(movie.runtime, "2h 4m")
        self.assertEqual(movie.user_rating, 9)
        self.assertEqual(movie.rating, 0.0)
        self.assertIsNone(movie.poster_file)
        self.assertEqual(movie.tmdb_id, 201)
        self.assertEqual(show.media_type, "Shows")
        self.assertEqual(show.status, "Watching")
        self.assertEqual(show.runtime, "55m")
        self.assertEqual(show.seasons[0].watched, 4)
        self.assertEqual(anime.media_type, "Anime")
        self.assertEqual(anime.status, "Watchlist")
        self.assertEqual(anime.availability, "Plan To Watch")
        self.assertEqual(paused.status, "On Hold")

    def test_watchlist_contains_only_plan_to_watch_items(self) -> None:
        records = gisheh.title_records_from_simkl(
            {
                "movies": [
                    {
                        "status": status,
                        "movie": {
                            "ids": {"simkl": index, "tmdb": index + 100},
                        },
                    }
                    for index, status in enumerate(
                        ("plantowatch", "completed", "dropped"),
                        start=1,
                    )
                ],
                "shows": [
                    {
                        "status": status,
                        "show": {
                            "ids": {"simkl": index, "tmdb": index + 100},
                        },
                    }
                    for index, status in enumerate(
                        ("watching", "hold"),
                        start=10,
                    )
                ],
                "anime": [],
            }
        )

        statuses = {record.id: record.status for record in records}
        self.assertEqual(statuses["simkl-movies-1"], "Watchlist")
        self.assertEqual(statuses["simkl-shows-10"], "Watching")
        self.assertEqual(statuses["simkl-shows-11"], "On Hold")
        self.assertEqual(
            sum(status == "Watchlist" for status in statuses.values()),
            1,
        )

    def test_invalid_simkl_id_is_skipped(self) -> None:
        payload = {
            "movies": [
                {
                    "status": "completed",
                    "movie": {
                        "title": "Invalid",
                        "ids": {"simkl": "not-a-number"},
                    },
                }
            ]
        }
        self.assertEqual(gisheh.title_records_from_simkl(payload), ())

    def test_tmdb_enrichment_preserves_simkl_user_state(self) -> None:
        record = gisheh.title_records_from_simkl(
            {
                "movies": [
                    {
                        "status": "completed",
                        "user_rating": 9,
                        "movie": {
                            "title": "Simkl fallback",
                            "ids": {"simkl": 10, "tmdb": 20},
                        },
                    }
                ]
            }
        )[0]
        summary = {
            "id": 20,
            "title": "TMDB title",
            "release_date": "2025-01-02",
            "runtime": 124,
            "vote_average": 7.8,
            "vote_count": 120,
            "genres": [{"name": "Drama"}],
            "overview": "TMDB overview",
            "poster_path": "/poster.jpg",
        }
        with patch.object(
            gisheh.tmdb_client,
            "cached_image",
            return_value="/cache/poster.jpg",
        ):
            enriched = gisheh.enrich_record_from_tmdb(record, summary)

        self.assertEqual(enriched.title, "TMDB title")
        self.assertEqual(enriched.rating, 7.8)
        self.assertEqual(enriched.genres, ("Drama",))
        self.assertEqual(enriched.poster_file, "/cache/poster.jpg")
        self.assertEqual(enriched.status, "Watched")
        self.assertEqual(enriched.user_rating, 9)
        self.assertEqual(
            enriched.external_ratings,
            (("TMDB", "7.8"), ("Your rating", "9")),
        )

    def test_tv_runtime_falls_back_to_last_episode_when_average_is_missing(
        self,
    ) -> None:
        record = gisheh.title_record_from_tmdb(
            {
                "id": 81356,
                "name": "Sex Education",
                "first_air_date": "2019-01-11",
            },
            "Shows",
            1,
            None,
            None,
        )
        summary = {
            "id": 81356,
            "name": "Sex Education",
            "first_air_date": "2019-01-11",
            "episode_run_time": [],
            "last_episode_to_air": {"runtime": 85},
        }

        enriched = gisheh.enrich_record_from_tmdb(record, summary)

        self.assertEqual(enriched.runtime, "1h 25m")

    def test_stats_refresh_is_skipped_when_activity_is_unchanged(self) -> None:
        self.assertFalse(
            gisheh.should_refresh_simkl_stats(
                has_incremental_state=True,
                repairing_metadata=False,
                cached_stats={"movies": {"completed": 12}},
                activities={"all": "2026-08-31T10:00:00Z"},
                last_sync="2026-08-31T10:00:00Z",
            )
        )
        self.assertTrue(
            gisheh.should_refresh_simkl_stats(
                has_incremental_state=True,
                repairing_metadata=False,
                cached_stats={"movies": {"completed": 12}},
                activities={"all": "2026-08-31T10:05:00Z"},
                last_sync="2026-08-31T10:00:00Z",
            )
        )

    def test_watchlist_removal_executes_the_simkl_remove_request(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        record = gisheh.title_records_from_simkl(
            {
                "movies": [
                    {
                        "status": "plantowatch",
                        "movie": {
                            "title": "Remove me",
                            "ids": {"simkl": 10, "tmdb": 20},
                        },
                    }
                ]
            }
        )[0]
        captured: dict[str, object] = {}

        def capture_mutation(_self, _key, operation, *_args) -> None:
            captured["operation"] = operation

        with (
            patch.object(
                gisheh.GishehWindow,
                "_run_simkl_mutation",
                new=capture_mutation,
            ),
            patch.object(gisheh.simkl_client, "remove_from_library") as remove,
            patch.object(gisheh.simkl_client, "set_list_status") as add,
        ):
            controller._write_simkl_list_change(
                record,
                adding=False,
                on_success=lambda: None,
            )
            operation = captured["operation"]
            assert callable(operation)
            operation()

        remove.assert_called_once_with(
            "client",
            "token",
            "movies",
            {"simkl": 10, "tmdb": 20},
        )
        add.assert_not_called()


class TmdbCertificationTests(unittest.TestCase):
    def test_movie_certification_prefers_us_theatrical_rating(self) -> None:
        payload = {
            "production_countries": [{"iso_3166_1": "FR", "name": "France"}],
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "FR",
                        "release_dates": [{"certification": "U", "type": 3}],
                    },
                    {
                        "iso_3166_1": "US",
                        "release_dates": [
                            {"certification": "PG-13", "type": 4},
                            {"certification": "PG-13", "type": 3},
                        ],
                    },
                ]
            },
        }

        self.assertEqual(
            gisheh.certification_from_tmdb(payload, "movie"),
            "PG-13",
        )

    def test_tv_certification_uses_origin_then_any_available_region(self) -> None:
        origin_payload = {
            "origin_country": ["JP"],
            "content_ratings": {
                "results": [
                    {"iso_3166_1": "DE", "rating": "16"},
                    {"iso_3166_1": "JP", "rating": "G"},
                ]
            },
        }
        fallback_payload = {
            "content_ratings": {"results": [{"iso_3166_1": "DE", "rating": "12"}]}
        }

        self.assertEqual(
            gisheh.certification_from_tmdb(origin_payload, "tv"),
            "G",
        )
        self.assertEqual(
            gisheh.certification_from_tmdb(fallback_payload, "tv"),
            "12",
        )
        self.assertEqual(gisheh.certification_from_tmdb({}, "movie"), "Unrated")


class TmdbProgressiveLoadingTests(unittest.TestCase):
    def test_detail_backdrop_does_not_replace_portrait_card_artwork(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        published: list[gisheh.TitleRecord] = []
        record = gisheh.title_record_from_tmdb(
            {
                "id": 42,
                "title": "Stable cover",
                "release_date": "2026-08-31",
            },
            "Movies",
            1,
            None,
            None,
        )
        payload = {
            "title": "Stable cover",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "credits": {"cast": [], "crew": []},
            "images": {"backdrops": [], "posters": []},
            "videos": {"results": []},
            "recommendations": {"results": []},
        }

        def cached_image(path: str, *, size: str) -> str | None:
            if path == "/poster.jpg" and size == "w500":
                return "/cache/poster.jpg"
            if path == "/backdrop.jpg" and size == "w780":
                return "/cache/backdrop.jpg"
            return None

        def idle_add(callback, *args):
            if callback.__name__ == "_apply_tmdb_details":
                published.append(args[1])
            return 1

        with (
            patch.object(gisheh.tmdb_client, "fetch_details", return_value=payload),
            patch.object(
                gisheh.tmdb_client,
                "cached_image",
                side_effect=cached_image,
            ),
            patch.object(gisheh.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_details_worker(record, "token", 1)

        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].poster_file, "/cache/poster.jpg")
        self.assertEqual(published[0].backdrop_file, "/cache/backdrop.jpg")
        self.assertEqual(published[0].artwork_file, "/cache/poster.jpg")

    def test_simkl_library_record_is_enriched_from_tmdb_before_poster(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        events: list[str] = []
        record = gisheh.title_records_from_simkl(
            {
                "movies": [
                    {
                        "status": "completed",
                        "movie": {
                            "title": "Fallback",
                            "ids": {"simkl": 10, "tmdb": 20},
                        },
                    }
                ]
            }
        )[0]
        summary = {
            "id": 20,
            "title": "TMDB title",
            "poster_path": "/poster.jpg",
        }

        def idle_add(callback, *_args):
            events.append(callback.__name__)
            return 1

        def cache_image(_path: str, *, size: str) -> str:
            events.append(f"download:{size}")
            return "/cache/poster.jpg"

        with (
            patch.object(gisheh.tmdb_client, "load_summary", return_value=None),
            patch.object(gisheh.tmdb_client, "fetch_summary", return_value=summary),
            patch.object(gisheh.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(gisheh.GLib, "idle_add", side_effect=idle_add),
        ):
            loaded = controller._load_tmdb_library_record(record, "token", 1)

        self.assertTrue(loaded)
        self.assertEqual(events[0], "_apply_tmdb_library_summary")
        self.assertEqual(events[1], "download:w500")
        self.assertEqual(events[2], "_apply_tmdb_library_poster")

    def test_explore_records_are_published_before_image_downloads(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        events: list[str] = []
        payload = {
            "Movies": [
                {
                    "id": 42,
                    "title": "Progressive",
                    "release_date": "2026-08-31",
                    "poster_path": "/poster.jpg",
                    "backdrop_path": "/backdrop.jpg",
                }
            ],
            "Shows": [],
            "Anime": [],
        }

        def idle_add(callback, *_args):
            events.append(callback.__name__)
            return 1

        def cache_image(path: str, *, size: str) -> str:
            events.append(f"download:{size}:{path}")
            return f"/cache/{size}-{Path(path).name}"

        with (
            patch.object(gisheh.tmdb_client, "fetch_explore", return_value=payload),
            patch.object(gisheh.tmdb_client, "cached_image", return_value=None),
            patch.object(gisheh.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(gisheh.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_explore_worker("token", 1, "Movies")

        self.assertEqual(events[0], "_apply_tmdb_explore")
        self.assertIn("download:w500:/poster.jpg", events[1:])
        self.assertIn("download:w780:/backdrop.jpg", events[1:])

    def test_detail_metadata_is_published_before_artwork_downloads(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        events: list[str] = []
        record = gisheh.title_record_from_tmdb(
            {
                "id": 42,
                "title": "Progressive details",
                "release_date": "2026-08-31",
            },
            "Movies",
            1,
            None,
            None,
        )
        payload = {
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "overview": "Metadata first.",
            "credits": {
                "cast": [
                    {
                        "name": "Actor",
                        "character": "Lead",
                        "profile_path": "/actor.jpg",
                    }
                ],
                "crew": [],
            },
            "images": {
                "backdrops": [{"file_path": "/gallery-backdrop.jpg"}],
                "posters": [{"file_path": "/gallery-poster.jpg"}],
            },
        }

        def idle_add(callback, *_args):
            events.append(callback.__name__)
            return 1

        def cache_image(path: str, *, size: str) -> str:
            events.append(f"download:{size}:{path}")
            return f"/cache/{size}-{Path(path).name}"

        with (
            patch.object(gisheh.tmdb_client, "fetch_details", return_value=payload),
            patch.object(gisheh.tmdb_client, "cached_image", return_value=None),
            patch.object(gisheh.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(gisheh.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_details_worker(record, "token", 1)

        self.assertEqual(events[0], "_apply_tmdb_details")
        self.assertTrue(any(event.startswith("download:") for event in events[1:]))


if __name__ == "__main__":
    unittest.main()
