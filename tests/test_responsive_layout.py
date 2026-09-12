#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace


SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import window as gisheh


class ResponsiveDecisionTests(unittest.TestCase):
    def test_very_wide_width_uses_expanded_sidebar_and_inline_details(self) -> None:
        for width in (1200, 1360, 2000):
            layout = gisheh.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, gisheh.SIDEBAR_EXPANDED)
            self.assertEqual(layout.details_mode, gisheh.DETAILS_INLINE)

    def test_medium_width_uses_hidden_sidebar_and_inline_details(self) -> None:
        for width in (980, 1100, 1199):
            layout = gisheh.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, gisheh.SIDEBAR_HIDDEN)
            self.assertEqual(layout.details_mode, gisheh.DETAILS_INLINE)

    def test_narrow_width_uses_hidden_sidebar_and_overlay_details(self) -> None:
        for width in (720, 900, 979):
            layout = gisheh.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, gisheh.SIDEBAR_HIDDEN)
            self.assertEqual(layout.details_mode, gisheh.DETAILS_OVERLAY)

    def test_very_narrow_width_uses_hidden_sidebar_and_navigation(self) -> None:
        for width in (360, 480, 719):
            layout = gisheh.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, gisheh.SIDEBAR_HIDDEN)
            self.assertEqual(
                layout.details_mode, gisheh.DETAILS_NAVIGATION
            )

    def test_exact_threshold_boundaries(self) -> None:
        self.assertEqual(
            gisheh.responsive_layout_for_width(1200).sidebar_mode,
            gisheh.SIDEBAR_EXPANDED,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(1199).sidebar_mode,
            gisheh.SIDEBAR_HIDDEN,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                980, details_open=True
            ).details_mode,
            gisheh.DETAILS_INLINE,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                979, details_open=True
            ).details_mode,
            gisheh.DETAILS_OVERLAY,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                720, details_open=True
            ).details_mode,
            gisheh.DETAILS_OVERLAY,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(719).sidebar_mode,
            gisheh.SIDEBAR_HIDDEN,
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                719, details_open=True
            ).details_mode,
            gisheh.DETAILS_NAVIGATION,
        )

    def test_compact_mode_never_returned(self) -> None:
        for width in list(range(0, 2001, 7)) + [719, 720, 979, 980, 1199, 1200]:
            for details_open in (False, True):
                layout = gisheh.responsive_layout_for_width(
                    width, details_open=details_open
                )
                self.assertNotEqual(layout.sidebar_mode, "compact")

    def test_decision_is_stable_and_state_free(self) -> None:
        first = gisheh.responsive_layout_for_width(1024, details_open=True)
        second = gisheh.responsive_layout_for_width(1024, details_open=True)
        self.assertEqual(first, second)
        closed = gisheh.responsive_layout_for_width(900, details_open=False)
        opened = gisheh.responsive_layout_for_width(900, details_open=True)
        self.assertEqual(closed.details_mode, gisheh.DETAILS_INLINE)
        self.assertEqual(opened.details_mode, gisheh.DETAILS_OVERLAY)

    def test_docked_sidebar_and_inline_details_require_three_regions(self) -> None:
        required = (
            gisheh.SIDEBAR_EXPANDED_MIN_WIDTH
            + gisheh.DETAILS_INLINE_WIDTH
            + gisheh.EXPLORE_SAFE_CONTENT_WIDTH
            + gisheh.RESPONSIVE_LAYOUT_GAPS
        )
        too_small = gisheh.responsive_layout_for_width(
            required - 1, details_open=True
        )
        large_enough = gisheh.responsive_layout_for_width(
            max(required, gisheh.RESPONSIVE_WIDE_ENTER_WIDTH),
            details_open=True,
        )
        self.assertEqual(too_small.sidebar_mode, gisheh.SIDEBAR_HIDDEN)
        self.assertEqual(large_enough.sidebar_mode, gisheh.SIDEBAR_EXPANDED)
        self.assertEqual(large_enough.details_mode, gisheh.DETAILS_INLINE)

    def test_hysteresis_retains_modes_inside_the_safe_band(self) -> None:
        wide = gisheh.ResponsiveLayout(
            gisheh.SIDEBAR_EXPANDED, gisheh.DETAILS_INLINE
        )
        retained_wide = gisheh.responsive_layout_for_width(
            gisheh.RESPONSIVE_WIDE_EXIT_WIDTH,
            details_open=True,
            current_layout=wide,
        )
        self.assertEqual(retained_wide.sidebar_mode, gisheh.SIDEBAR_EXPANDED)
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                gisheh.RESPONSIVE_WIDE_EXIT_WIDTH - 1,
                details_open=True,
                current_layout=wide,
            ).sidebar_mode,
            gisheh.SIDEBAR_HIDDEN,
        )
        inline = gisheh.ResponsiveLayout(
            gisheh.SIDEBAR_HIDDEN, gisheh.DETAILS_INLINE
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                gisheh.RESPONSIVE_INLINE_EXIT_WIDTH,
                details_open=True,
                current_layout=inline,
            ).details_mode,
            gisheh.DETAILS_INLINE,
        )
        navigation = gisheh.ResponsiveLayout(
            gisheh.SIDEBAR_HIDDEN, gisheh.DETAILS_NAVIGATION
        )
        self.assertEqual(
            gisheh.responsive_layout_for_width(
                gisheh.RESPONSIVE_NARROW_EXIT_WIDTH - 1,
                details_open=True,
                current_layout=navigation,
            ).details_mode,
            gisheh.DETAILS_NAVIGATION,
        )


class DetailsBackActionTests(unittest.TestCase):
    def test_episode_back_returns_to_season(self) -> None:
        self.assertEqual(
            gisheh.details_back_action("episode"), "pop-season"
        )

    def test_season_back_returns_to_title(self) -> None:
        self.assertEqual(
            gisheh.details_back_action("season"), "pop-title"
        )

    def test_title_back_closes_details(self) -> None:
        self.assertEqual(gisheh.details_back_action("title"), "close")
        self.assertEqual(gisheh.details_back_action("other"), "close")


class RecordContextMenuTests(unittest.TestCase):
    @staticmethod
    def _record() -> gisheh.TitleRecord:
        records, _explore, _totals = gisheh.load_catalog(
            include_sample_data=True
        )
        return records[0]

    def test_menu_contains_watch_watchlist_and_rating_controls(self) -> None:
        from gi.repository import Gio, Gtk

        controller = object.__new__(gisheh.GishehWindow)
        controller.completed = set()
        controller.bookmarks = set()
        controller.ratings = {}
        popover = controller._record_context_popover(self._record())
        self.assertIsInstance(popover, Gtk.PopoverMenu)
        model = popover.get_menu_model()
        self.assertEqual(model.get_n_items(), 2)
        labels: list[str] = []
        for section_index in range(model.get_n_items()):
            section = model.get_item_link(section_index, Gio.MENU_LINK_SECTION)
            self.assertIsNotNone(section)
            for item_index in range(section.get_n_items()):
                label = section.get_item_attribute_value(
                    item_index,
                    Gio.MENU_ATTRIBUTE_LABEL,
                    None,
                )
                labels.append(label.get_string())
        self.assertEqual(
            labels,
            ["Mark as watched", "Add to Watchlist", "Rate…  (6/10)"],
        )

    def test_context_actions_target_the_clicked_record(self) -> None:
        record = self._record()
        controller = object.__new__(gisheh.GishehWindow)
        controller.records_by_id = {record.id: record}
        calls: list[tuple[object, ...]] = []
        controller._activate_record_watched = (
            lambda item: calls.append(("watched", item.id))
        )
        controller._set_record_bookmarked = (
            lambda item, adding: calls.append(("watchlist", item.id, adding))
        )
        controller._set_record_rating = (
            lambda item, score: calls.append(("rating", item.id, score))
        )
        controller._show_record_rating_dialog = (
            lambda item: calls.append(("rating-dialog", item.id))
        )

        controller._activate_context_watched(record.id)
        controller._activate_context_watchlist(record.id, True)
        controller._activate_context_rating(record.id)

        self.assertIn(("watched", record.id), calls)
        self.assertIn(("watchlist", record.id, True), calls)
        self.assertIn(("rating-dialog", record.id), calls)

    def test_rating_is_saved_from_a_separate_dialog(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        dialog = source.split("def _show_record_rating_dialog")[1].split(
            "\n    def "
        )[0]
        self.assertIn('dialog.add_response("save", "Save rating")', dialog)
        self.assertIn('dialog.set_response_enabled("save"', dialog)
        self.assertIn("self._set_record_rating(current, score)", dialog)


class ExploreColumnTests(unittest.TestCase):
    def test_very_narrow_width_returns_one_column(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(279), 1
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(200), 1
        )

    def test_narrow_width_returns_two_columns(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(280), 2
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(389), 2
        )

    def test_medium_widths_return_three_or_four_columns(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(390), 3
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(539), 3
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(540), 4
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(759), 4
        )

    def test_wide_width_returns_five_columns(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(760), 5
        )
        self.assertEqual(
            gisheh.GishehWindow._explore_columns_for_width(1200), 5
        )

    def test_card_height_supports_one_column(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller._last_explore_layout_width = 300
        controller.explore_pane = SimpleNamespace(get_width=lambda: 0)
        controller.library_pane = SimpleNamespace(get_width=lambda: 0)
        controller.explore_columns = 1
        for kind in ("poster", "landscape", "hero"):
            height = controller._explore_card_height(kind, 1)
            self.assertGreater(height, 0)

    def test_only_column_changes_rebuild_explore(self) -> None:
        width = {"value": 640}
        rebuilds: list[int] = []
        controller = object.__new__(gisheh.GishehWindow)
        controller._explore_resize_source_id = 1
        controller._details_resize_source_id = 0
        controller._sidebar_resize_source_id = 0
        controller.explore_pane = SimpleNamespace(get_width=lambda: width["value"])
        controller.library_pane = SimpleNamespace(get_width=lambda: 0)
        controller.explore_columns = 4
        controller._last_explore_layout_width = 0
        controller._last_explore_layout_bucket = None
        controller.active_destination = "explore"
        controller.explore_visible_records = (object(),)
        controller.explore_scroller = SimpleNamespace(
            get_vadjustment=lambda: SimpleNamespace(get_value=lambda: 42.0)
        )
        controller._populate_explore_feed = (
            lambda **_kwargs: rebuilds.append(width["value"])
        )
        controller._scroll_to_value = lambda *_args: None

        controller._apply_explore_resize()
        width["value"] = 675
        controller._apply_explore_resize()
        width["value"] = 700
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [])

        width["value"] = 720
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [])

        width["value"] = 760
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [])

        width["value"] = 780
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [780])

        width["value"] = 750
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [780])

        width["value"] = 739
        controller._apply_explore_resize()
        self.assertEqual(rebuilds, [780, 739])

    def test_flexible_artwork_has_no_horizontal_minimum_or_natural_width(self) -> None:
        from gi.repository import Gtk

        record = gisheh.TitleRecord(
            id="measure-test",
            title="Measurement",
            media_type="Movies",
            year=2026,
            status="Watchlist",
            date="2026-01-01",
            runtime="90m",
            rating=7.0,
            user_rating=None,
            genres=(),
            country="",
            creator="",
            description="",
            poster_palette=("#000", "#111", "#222"),
            poster_variant=0,
            order=0,
            certification="",
            language="",
            availability="",
            network="",
            external_ratings=(),
            cast=(),
            seasons=(),
            recommendations=(),
            discover_period="All releases",
            featured=False,
            popularity=0,
            release_rank=0,
            discover_layout="poster",
        )
        artwork = gisheh.PosterWidget(record, 480, 270, flexible_width=True)
        minimum, natural, _minimum_baseline, _natural_baseline = artwork.measure(
            Gtk.Orientation.HORIZONTAL, -1
        )
        self.assertEqual((minimum, natural), (0, 0))

    def test_async_explore_artwork_replacement_stays_horizontally_flexible(self) -> None:
        from gi.repository import Gtk

        records, _explore, _totals = gisheh.load_catalog(
            include_sample_data=True
        )
        record = records[0]
        overlay = Gtk.Overlay()
        overlay.set_child(Gtk.Box())
        button = Gtk.Button(child=overlay)
        controller = object.__new__(gisheh.GishehWindow)
        controller._explore_card_buttons = {record.id: button}
        controller._explore_card_layouts = {record.id: ("hero", 2)}
        controller._explore_card_height = lambda _kind, _span: 180

        controller._update_explore_card_artwork(record)

        artwork = overlay.get_child()
        self.assertIsInstance(artwork, gisheh.PosterWidget)
        minimum, natural, _minimum_baseline, _natural_baseline = artwork.measure(
            Gtk.Orientation.HORIZONTAL, -1
        )
        self.assertEqual((minimum, natural), (0, 0))

    def test_pagination_appends_without_recreating_existing_cards(self) -> None:
        class FakeGrid:
            def __init__(self, parent: object) -> None:
                self.parent = parent
                self.attached: list[tuple[str, int, int, int]] = []

            def get_parent(self) -> object:
                return self.parent

            def attach(
                self, card: object, column: int, row: int, span: int, _height: int
            ) -> None:
                self.attached.append((str(card), column, row, span))

        controller = object.__new__(gisheh.GishehWindow)
        feed = object()
        grid = FakeGrid(feed)
        old_card_a = object()
        old_card_b = object()
        controller.explore_feed_box = feed
        controller.explore_grid = grid
        controller.explore_columns = 2
        controller._explore_rendered_columns = 2
        controller._explore_rendered_ids = ("a", "b")
        controller._explore_grid_row = 1
        controller._explore_grid_column = 0
        controller._explore_layout_seed = 7
        controller._explore_card_buttons = {"a": old_card_a, "b": old_card_b}
        controller._explore_card_layouts = {
            "a": ("poster", 1),
            "b": ("poster", 1),
        }
        controller.explore_visible_records = tuple(
            SimpleNamespace(id=record_id) for record_id in ("a", "b", "c", "d")
        )
        controller._create_explore_card = lambda record, _kind, _span: record.id
        controller._explore_record_visual_signature = lambda record: (record.id,)
        controller._sync_explore_loading_indicator = lambda: None
        controller._sync_explore_selection_style = lambda: None

        controller._populate_explore_feed()

        self.assertIs(controller._explore_card_buttons["a"], old_card_a)
        self.assertIs(controller._explore_card_buttons["b"], old_card_b)
        self.assertEqual([item[0] for item in grid.attached], ["c", "d"])
        self.assertEqual(controller._explore_rendered_ids, ("a", "b", "c", "d"))

    def test_loading_footer_fits_a_single_text_line(self) -> None:
        from gi.repository import Gtk

        footer, _spinner = gisheh.GishehWindow._build_explore_loading_footer()
        footer.set_visible(True)
        minimum, _natural, _min_baseline, _natural_baseline = footer.measure(
            Gtk.Orientation.VERTICAL, -1
        )
        self.assertLessEqual(minimum, 18)
        footer.measure(Gtk.Orientation.HORIZONTAL, 18)


class CompactRemovalTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path(gisheh.__file__).read_text(encoding="utf-8")

    @staticmethod
    def _css() -> str:
        return (Path(gisheh.__file__).parent / "style.css").read_text(
            encoding="utf-8"
        )

    def test_compact_sidebar_constants_are_gone(self) -> None:
        self.assertFalse(hasattr(gisheh, "SIDEBAR_COMPACT"))
        self.assertFalse(
            hasattr(gisheh, "SIDEBAR_COMPACT_MIN_WIDTH")
        )
        self.assertFalse(
            hasattr(gisheh, "SIDEBAR_COMPACT_MAX_WIDTH")
        )

    def test_compact_sidebar_implementation_is_gone(self) -> None:
        self.assertFalse(
            hasattr(gisheh.GishehWindow, "_build_compact_sidebar")
        )
        self.assertFalse(
            hasattr(gisheh.GishehWindow, "_on_compact_rail_clicked")
        )
        self.assertFalse(
            hasattr(gisheh.GishehWindow, "_sync_compact_sidebar_selection")
        )
        source = self._source()
        self.assertNotIn("compact_rail_buttons", source)
        self.assertNotIn("compact_sidebar_page", source)
        self.assertNotIn('"preferredSidebarMode":', source)

    def test_compact_rail_css_is_gone(self) -> None:
        self.assertNotIn(".compact-rail", self._css())


class ResponsiveStructureTests(unittest.TestCase):
    @staticmethod
    def _ui_root() -> ET.Element:
        return ET.parse(gisheh.UI_FILE).getroot()

    @staticmethod
    def _ui_object_classes() -> dict[str, str]:
        root = ET.parse(gisheh.UI_FILE).getroot()
        return {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

    @staticmethod
    def _ui_properties(object_id: str) -> dict[str, str]:
        root = ET.parse(gisheh.UI_FILE).getroot()
        for item in root.iter("object"):
            if item.get("id") == object_id:
                return {
                    prop.get("name", ""): (prop.text or "")
                    for prop in item.findall("property")
                }
        raise AssertionError(f"UI object {object_id} is missing")

    @staticmethod
    def _source() -> str:
        return Path(gisheh.__file__).read_text(encoding="utf-8")

    def test_root_sidebar_is_an_overlay_drawer(self) -> None:
        classes = self._ui_object_classes()
        self.assertEqual(classes.get("workspace"), "AdwOverlaySplitView")

    def test_sidebar_drawer_uses_show_sidebar_api(self) -> None:
        source = self._source()
        self.assertIn("set_show_sidebar", source)
        self.assertIn("get_show_sidebar", source)
        self.assertNotIn("set_show_content", source)
        self.assertNotIn("get_show_content", source)

    def test_sidebar_toggle_is_binary(self) -> None:
        source = self._source()
        self.assertIn("Hide sidebar (Ctrl+B)", source)
        self.assertIn("Show sidebar (Ctrl+B)", source)
        self.assertNotIn("Use compact sidebar", source)

    def test_sidebar_shortcut_uses_the_same_logic(self) -> None:
        source = self._source()
        action = source.split('Gio.SimpleAction.new("toggle-sidebar"')[1].split(
            "\n    def "
        )[0]
        self.assertIn("_set_sidebar_open", action)

    def test_mobile_details_use_a_real_navigation_page(self) -> None:
        source = self._source()
        self.assertIn("content_navigation", source)
        self.assertIn("mobile_details_page", source)
        self.assertIn("mobile_details_host", source)
        self.assertIn("Adw.NavigationView()", source)
        self.assertIn('set_tag("details")', source)
        self.assertIn('set_tag("browser")', source)

    def test_full_page_mode_does_not_hide_the_content_widget(self) -> None:
        source = self._source()
        self.assertNotIn("content_overlay.set_visible", source)

    def test_details_surface_expands_in_navigation_mode(self) -> None:
        source = self._source()
        mover = source.split("def _move_details_to_mobile")[1].split(
            "\n    def "
        )[0]
        self.assertIn("set_hexpand(True)", mover)

    def test_no_separator_in_full_page_path(self) -> None:
        source = self._source()
        builder = source.split("def _build_content_navigation")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("Separator", builder)

    def test_mobile_back_action_targets_content(self) -> None:
        source = self._source()
        self.assertIn("Back to content", source)
        self.assertIn("_on_mobile_title_back", source)
        self.assertNotIn('mobile_back_button.set_label("Back")', source)

    def test_filter_controls_have_no_hard_minimum(self) -> None:
        properties = self._ui_properties("explore_filter_controls")
        self.assertNotIn("width-request", properties)

    def test_details_scroller_has_no_fixed_content_width(self) -> None:
        properties = self._ui_properties("details_scroller")
        self.assertNotIn("min-content-width", properties)
        self.assertNotIn("max-content-width", properties)

    def test_details_surface_has_no_fixed_width(self) -> None:
        properties = self._ui_properties("details_surface")
        self.assertNotIn("width-request", properties)

    def test_details_wrap_hints_fit_the_inline_content_width(self) -> None:
        properties = self._ui_properties("detail_ratings_host")
        self.assertEqual(
            self._ui_object_classes()["detail_ratings_host"], "GtkGrid"
        )
        inner_width = gisheh.DETAILS_INLINE_WIDTH - 32
        natural = int(properties.get("natural-line-length", "0") or 0)
        self.assertLessEqual(natural, inner_width)
        self.assertEqual(properties.get("hexpand"), "true")
        facts = self._ui_properties("detail_facts_row")
        self.assertEqual(facts.get("hexpand"), "true")

    def test_default_window_size_fits_common_desktops(self) -> None:
        properties = self._ui_properties("window")
        self.assertEqual(properties.get("default-width"), "1100")
        self.assertEqual(properties.get("default-height"), "700")

    def test_hard_minimum_window_size_is_removed(self) -> None:
        source = self._source()
        self.assertNotIn("set_size_request(940, 600)", source)

    def test_opening_details_does_not_resize_the_window(self) -> None:
        source = self._source()
        opener = source.split("def _set_details_open")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("set_default_size", opener)
        self.assertNotIn("resize(", opener)
        self.assertNotIn("set_size_request", opener)

    def test_episode_artwork_remains_flexible(self) -> None:
        import inspect

        self.assertIn(
            "flexible_width",
            inspect.signature(gisheh.PosterWidget.__init__).parameters,
        )
        source = self._source()
        self.assertIn("flexible_width=True", source)

    def test_responsive_modes_are_explicit(self) -> None:
        self.assertEqual(gisheh.SIDEBAR_EXPANDED, "expanded")
        self.assertEqual(gisheh.SIDEBAR_HIDDEN, "hidden")
        self.assertEqual(gisheh.DETAILS_INLINE, "inline")
        self.assertEqual(gisheh.DETAILS_OVERLAY, "overlay")
        self.assertEqual(gisheh.DETAILS_NAVIGATION, "navigation")


class PanelWidthTests(unittest.TestCase):
    def test_inline_width_is_constant(self) -> None:
        for available in (0, 200, 360, 1100, 2000):
            self.assertEqual(
                gisheh.GishehWindow._details_panel_preferred_width(
                    gisheh.DETAILS_INLINE, available
                ),
                384,
            )

    def test_inline_width_ignores_media_type(self) -> None:
        widths = {
            gisheh.GishehWindow._details_panel_preferred_width(
                gisheh.DETAILS_INLINE, 480
            )
            for _media_type in ("Movies", "Shows", "Anime")
        }
        self.assertEqual(widths, {384})
        self.assertEqual(gisheh.DETAILS_INLINE_WIDTH, 384)

    def test_overlay_width_is_clamped_to_available_width(self) -> None:
        panel = gisheh.GishehWindow._details_panel_preferred_width
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 0), 280)
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 100), 280)
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 328), 280)
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 329), 281)
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 436), 388)
        self.assertEqual(panel(gisheh.DETAILS_OVERLAY, 2000), 388)

    def test_navigation_mode_applies_no_desktop_panel_width(self) -> None:
        self.assertEqual(
            gisheh.GishehWindow._details_panel_preferred_width(
                gisheh.DETAILS_NAVIGATION, 480
            ),
            0,
        )

    def test_panel_width_does_not_measure_content(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        body = source.split("def _details_panel_preferred_width")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("measure(", body)
        self.assertNotIn("details_surface", body)

    def test_episode_cards_can_wrap(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        builder = source.split("self.episode_cards_box = ")[1].split("\n")[0]
        self.assertIn("WrapBox", builder)
        card = source.split("def _episode_card")[1].split("\n    def ")[0]
        self.assertIn("set_wrap(True)", card)


class FakeNavigation:
    """Minimal stand-in for Adw.NavigationView page tracking."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls: list[tuple[str, object]] = []

    def get_visible_page_tag(self) -> str:
        return self.tag

    def push(self, page: object) -> None:
        self.calls.append(("push", page))
        self.tag = "details"

    def pop_to_tag(self, tag: str) -> None:
        self.calls.append(("pop_to_tag", tag))
        self.tag = tag


class FakeWidget:
    """Minimal stand-in recording container operations."""

    def __init__(self, parent: object = None) -> None:
        self._parent = parent
        self.calls: list[tuple[str, object]] = []

    def get_parent(self) -> object:
        return self._parent

    def set_parent(self, parent: object) -> None:
        self._parent = parent

    def append(self, child: object) -> None:
        self.calls.append(("append", child))
        if isinstance(child, FakeWidget):
            child.set_parent(self)

    def remove(self, child: object) -> None:
        self.calls.append(("remove", child))
        if isinstance(child, FakeWidget):
            child.set_parent(None)

    def add_overlay(self, child: object) -> None:
        self.calls.append(("add_overlay", child))

    def remove_overlay(self, child: object) -> None:
        self.calls.append(("remove_overlay", child))

    def set_size_request(self, width: int, height: int) -> None:
        self.calls.append(("set_size_request", (width, height)))

    def set_hexpand(self, value: bool) -> None:
        self.calls.append(("set_hexpand", value))

    def set_vexpand(self, value: bool) -> None:
        self.calls.append(("set_vexpand", value))

    def set_halign(self, value: object) -> None:
        self.calls.append(("set_halign", value))

    def set_valign(self, value: object) -> None:
        self.calls.append(("set_valign", value))

    def set_reveal_child(self, value: bool) -> None:
        self.calls.append(("set_reveal_child", value))


def _sync_controller(
    *,
    visible_tag: str,
    details_open: bool,
    mode: str,
    revealer_parent: object | None = None,
) -> tuple[
    gisheh.GishehWindow, FakeNavigation, FakeWidget, FakeWidget, list[str]
]:
    controller = object.__new__(gisheh.GishehWindow)
    navigation = FakeNavigation(visible_tag)
    surface = FakeWidget()
    home = FakeWidget()
    mobile_host = FakeWidget()
    revealer = FakeWidget(parent=revealer_parent)
    events: list[str] = []
    controller.details_open = details_open
    controller.effective_details_mode = mode
    controller.mobile_details_page = FakeWidget()  # type: ignore[assignment]
    controller.content_navigation = navigation  # type: ignore[assignment]
    controller.details_surface = surface  # type: ignore[assignment]
    controller.details_panel_layout = home  # type: ignore[assignment]
    controller.mobile_details_host = mobile_host  # type: ignore[assignment]
    controller.details_revealer = revealer  # type: ignore[assignment]
    controller.main_workspace = FakeWidget()  # type: ignore[assignment]
    controller.content_overlay = FakeWidget()  # type: ignore[assignment]
    controller._responsive_window_width = lambda: 480  # type: ignore[method-assign]
    controller._sync_details_mode_chrome = lambda: events.append("chrome")  # type: ignore[method-assign]
    controller._sync_mobile_back_visibility = lambda: events.append("back")  # type: ignore[method-assign]
    surface.set_parent(home if mode != gisheh.DETAILS_NAVIGATION else mobile_host)
    return controller, navigation, surface, revealer, events


class DetailsSyncTests(unittest.TestCase):
    def test_closed_browser_stays_put(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=False,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertEqual(navigation.calls, [])
        self.assertEqual(navigation.tag, "browser")

    def test_open_navigation_pushes_details_once(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=True,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        pushes = [call for call in navigation.calls if call[0] == "push"]
        self.assertEqual(len(pushes), 1)
        self.assertEqual(navigation.tag, "details")

    def test_visible_details_are_not_pushed_twice(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="details",
                details_open=True,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertEqual(navigation.calls, [])

    def test_identical_sync_does_not_reparent_or_restart_reveal(self) -> None:
        controller, _navigation, surface, revealer, _events = _sync_controller(
            visible_tag="browser",
            details_open=True,
            mode=gisheh.DETAILS_OVERLAY,
            revealer_parent=None,
        )
        controller._sync_details_presentation()
        first_surface_calls = list(surface.calls)
        first_revealer_calls = list(revealer.calls)
        controller._sync_details_presentation()
        self.assertEqual(surface.calls, first_surface_calls)
        self.assertEqual(revealer.calls, first_revealer_calls)

    def test_opening_an_already_open_details_panel_does_not_restart_transition(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.details_open = True
        synchronized: list[str] = []
        controller._sync_details_presentation = lambda: synchronized.append("sync")
        controller._set_details_open(True)
        self.assertEqual(synchronized, ["sync"])

    def test_closing_pops_explicitly_to_browser(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="details",
                details_open=False,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertIn(("pop_to_tag", "browser"), navigation.calls)
        self.assertFalse(
            any(call[0] == "pop" for call in navigation.calls)
        )
        self.assertEqual(navigation.tag, "browser")

    def test_stale_open_state_heals(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=True,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertEqual(navigation.tag, "details")

    def test_no_duplicate_pushed_flag_exists(self) -> None:
        self.assertFalse(hasattr(gisheh.GishehWindow, "_mobile_details_pushed"))
        controller = object.__new__(gisheh.GishehWindow)
        self.assertFalse(hasattr(controller, "_mobile_details_pushed"))

    def test_open_path_synchronizes_without_timeout(self) -> None:
        source = Path(gisheh.__file__).read_text(encoding="utf-8")
        opener = source.split("def _set_details_open")[1].split(
            "\n    def "
        )[0]
        self.assertIn("_sync_details_presentation()", opener)

    def test_external_pop_synchronizes_closed_state(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=True,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        restored: list[str] = []
        scheduled: list[str] = []
        controller._restore_details_return_focus = lambda: restored.append("focus")  # type: ignore[method-assign]
        controller._schedule_details_reset = lambda: scheduled.append("reset")  # type: ignore[method-assign]
        controller._on_content_navigation_page_changed(None, None)
        self.assertFalse(controller.details_open)
        self.assertEqual(restored, ["focus"])
        self.assertEqual(scheduled, ["reset"])
        self.assertEqual(navigation.calls, [])

    def test_external_pop_when_already_closed_is_ignored(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=False,
                mode=gisheh.DETAILS_NAVIGATION,
            )
        )
        controller._restore_details_return_focus = lambda: None  # type: ignore[method-assign]
        controller._schedule_details_reset = lambda: (_ for _ in ()).throw(AssertionError("must not schedule"))  # type: ignore[method-assign]
        controller._on_content_navigation_page_changed(None, None)
        self.assertFalse(controller.details_open)

    def test_resize_to_overlay_removes_mobile_page(self) -> None:
        controller, navigation, _surface, revealer, _events = (
            _sync_controller(
                visible_tag="details",
                details_open=True,
                mode=gisheh.DETAILS_OVERLAY,
            )
        )
        revealer.set_parent(controller.main_workspace)
        controller.details_surface.set_parent(controller.mobile_details_host)
        controller._sync_details_presentation()
        self.assertIn(("pop_to_tag", "browser"), navigation.calls)
        self.assertEqual(navigation.tag, "browser")
        self.assertIs(
            controller.details_surface.get_parent(),
            controller.details_panel_layout,
        )


class NarrowSizingTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path(gisheh.__file__).read_text(encoding="utf-8")

    def test_stacks_do_not_enforce_homogeneous_sizing(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        browser_stack = Gtk.Stack()
        browser_stack.set_hhomogeneous(False)
        browser_stack.set_vhomogeneous(False)
        self.assertFalse(browser_stack.get_hhomogeneous())
        self.assertFalse(browser_stack.get_vhomogeneous())
        content_navigation = Adw.NavigationView()
        content_navigation.set_hhomogeneous(False)
        content_navigation.set_vhomogeneous(False)
        self.assertFalse(content_navigation.get_hhomogeneous())
        self.assertFalse(content_navigation.get_vhomogeneous())
        source = self._source()
        browser = source.split("self.browser_stack = Gtk.Stack()")[1].split(
            "\n    def "
        )[0]
        self.assertIn("set_hhomogeneous(False)", browser)
        self.assertIn("set_vhomogeneous(False)", browser)
        navigation = source.split("self.content_navigation = Adw.NavigationView()")[
            1
        ].split("\n    def ")[0]
        self.assertIn("set_hhomogeneous(False)", navigation)
        self.assertIn("set_vhomogeneous(False)", navigation)

    def test_library_controls_can_wrap(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        parents: dict[str, str] = {}
        for item in root.iter("object"):
            for child in item.findall("child"):
                for nested in child.findall("object"):
                    if nested.get("id") in (
                        "search_entry",
                        "sort_dropdown",
                        "genre_dropdown",
                        "view_switcher",
                    ):
                        parents[nested.get("id") or ""] = item.get("class") or ""
        self.assertTrue(parents, "library controls are missing from the UI")
        for control, parent in parents.items():
            self.assertEqual(parent, "AdwWrapBox", control)

    def test_mobile_path_has_no_desktop_width(self) -> None:
        source = self._source()
        builder = source.split("def _build_content_navigation")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("set_size_request", builder)
        self.assertNotIn("388", builder)
        self.assertNotIn("384", builder)
        self.assertNotIn("280", builder)

    def test_detail_hero_fills_the_available_width_and_prefers_backdrop(self) -> None:
        root = ET.parse(gisheh.UI_FILE).getroot()
        host = root.find(".//object[@id='detail_poster_host']")
        self.assertIsNotNone(host)
        properties = {
            item.get("name"): (item.text or "").strip()
            for item in host.findall("property")
        }
        self.assertEqual(properties.get("halign"), "fill")
        self.assertEqual(properties.get("hexpand"), "true")

        source = self._source()
        hero = source.split("def _build_detail_hero")[1].split("\n    def ")[0]
        self.assertIn("overlay.set_hexpand(True)", hero)
        self.assertIn("overlay.set_halign(Gtk.Align.FILL)", hero)
        self.assertLess(
            hero.index("record.backdrop_file"),
            hero.index("trailer_info.thumbnail_file"),
        )


if __name__ == "__main__":
    unittest.main()
