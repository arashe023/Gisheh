#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace


SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from cineshelf import window as cineshelf


class ResponsiveDecisionTests(unittest.TestCase):
    def test_very_wide_width_uses_expanded_sidebar_and_inline_details(self) -> None:
        for width in (1200, 1360, 2000):
            layout = cineshelf.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, cineshelf.SIDEBAR_EXPANDED)
            self.assertEqual(layout.details_mode, cineshelf.DETAILS_INLINE)

    def test_medium_width_uses_hidden_sidebar_and_inline_details(self) -> None:
        for width in (980, 1100, 1199):
            layout = cineshelf.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, cineshelf.SIDEBAR_HIDDEN)
            self.assertEqual(layout.details_mode, cineshelf.DETAILS_INLINE)

    def test_narrow_width_uses_hidden_sidebar_and_overlay_details(self) -> None:
        for width in (720, 900, 979):
            layout = cineshelf.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, cineshelf.SIDEBAR_HIDDEN)
            self.assertEqual(layout.details_mode, cineshelf.DETAILS_OVERLAY)

    def test_very_narrow_width_uses_hidden_sidebar_and_navigation(self) -> None:
        for width in (360, 480, 719):
            layout = cineshelf.responsive_layout_for_width(
                width, details_open=True
            )
            self.assertEqual(layout.sidebar_mode, cineshelf.SIDEBAR_HIDDEN)
            self.assertEqual(
                layout.details_mode, cineshelf.DETAILS_NAVIGATION
            )

    def test_exact_threshold_boundaries(self) -> None:
        self.assertEqual(
            cineshelf.responsive_layout_for_width(1200).sidebar_mode,
            cineshelf.SIDEBAR_EXPANDED,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(1199).sidebar_mode,
            cineshelf.SIDEBAR_HIDDEN,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(980).details_mode,
            cineshelf.DETAILS_INLINE,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(979).details_mode,
            cineshelf.DETAILS_OVERLAY,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(720).details_mode,
            cineshelf.DETAILS_OVERLAY,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(719).sidebar_mode,
            cineshelf.SIDEBAR_HIDDEN,
        )
        self.assertEqual(
            cineshelf.responsive_layout_for_width(719).details_mode,
            cineshelf.DETAILS_NAVIGATION,
        )

    def test_compact_mode_never_returned(self) -> None:
        for width in list(range(0, 2001, 7)) + [719, 720, 979, 980, 1199, 1200]:
            for details_open in (False, True):
                layout = cineshelf.responsive_layout_for_width(
                    width, details_open=details_open
                )
                self.assertNotEqual(layout.sidebar_mode, "compact")

    def test_decision_is_stable_and_state_free(self) -> None:
        first = cineshelf.responsive_layout_for_width(1024, details_open=True)
        second = cineshelf.responsive_layout_for_width(1024, details_open=True)
        self.assertEqual(first, second)
        closed = cineshelf.responsive_layout_for_width(1024, details_open=False)
        self.assertEqual(first, closed)


class DetailsBackActionTests(unittest.TestCase):
    def test_episode_back_returns_to_season(self) -> None:
        self.assertEqual(
            cineshelf.details_back_action("episode"), "pop-season"
        )

    def test_season_back_returns_to_title(self) -> None:
        self.assertEqual(
            cineshelf.details_back_action("season"), "pop-title"
        )

    def test_title_back_closes_details(self) -> None:
        self.assertEqual(cineshelf.details_back_action("title"), "close")
        self.assertEqual(cineshelf.details_back_action("other"), "close")


class ExploreColumnTests(unittest.TestCase):
    def test_very_narrow_width_returns_one_column(self) -> None:
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(279), 1
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(200), 1
        )

    def test_narrow_width_returns_two_columns(self) -> None:
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(280), 2
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(389), 2
        )

    def test_medium_widths_return_three_or_four_columns(self) -> None:
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(390), 3
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(539), 3
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(540), 4
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(759), 4
        )

    def test_wide_width_returns_five_columns(self) -> None:
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(760), 5
        )
        self.assertEqual(
            cineshelf.CineShelfWindow._explore_columns_for_width(1200), 5
        )

    def test_card_height_supports_one_column(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
        controller._last_explore_layout_width = 300
        controller.explore_pane = SimpleNamespace(get_width=lambda: 0)
        controller.library_pane = SimpleNamespace(get_width=lambda: 0)
        controller.explore_columns = 1
        for kind in ("poster", "landscape", "hero"):
            height = controller._explore_card_height(kind, 1)
            self.assertGreater(height, 0)


class CompactRemovalTests(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        return Path(cineshelf.__file__).read_text(encoding="utf-8")

    @staticmethod
    def _css() -> str:
        return (Path(cineshelf.__file__).parent / "style.css").read_text(
            encoding="utf-8"
        )

    def test_compact_sidebar_constants_are_gone(self) -> None:
        self.assertFalse(hasattr(cineshelf, "SIDEBAR_COMPACT"))
        self.assertFalse(
            hasattr(cineshelf, "SIDEBAR_COMPACT_MIN_WIDTH")
        )
        self.assertFalse(
            hasattr(cineshelf, "SIDEBAR_COMPACT_MAX_WIDTH")
        )

    def test_compact_sidebar_implementation_is_gone(self) -> None:
        self.assertFalse(
            hasattr(cineshelf.CineShelfWindow, "_build_compact_sidebar")
        )
        self.assertFalse(
            hasattr(cineshelf.CineShelfWindow, "_on_compact_rail_clicked")
        )
        self.assertFalse(
            hasattr(cineshelf.CineShelfWindow, "_sync_compact_sidebar_selection")
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
        return ET.parse(cineshelf.UI_FILE).getroot()

    @staticmethod
    def _ui_object_classes() -> dict[str, str]:
        root = ET.parse(cineshelf.UI_FILE).getroot()
        return {
            item.get("id"): item.get("class")
            for item in root.iter("object")
            if item.get("id")
        }

    @staticmethod
    def _ui_properties(object_id: str) -> dict[str, str]:
        root = ET.parse(cineshelf.UI_FILE).getroot()
        for item in root.iter("object"):
            if item.get("id") == object_id:
                return {
                    prop.get("name", ""): (prop.text or "")
                    for prop in item.findall("property")
                }
        raise AssertionError(f"UI object {object_id} is missing")

    @staticmethod
    def _source() -> str:
        return Path(cineshelf.__file__).read_text(encoding="utf-8")

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

    def test_default_window_size_fits_common_desktops(self) -> None:
        properties = self._ui_properties("window")
        self.assertEqual(properties.get("default-width"), "1100")
        self.assertEqual(properties.get("default-height"), "700")

    def test_hard_minimum_window_size_is_removed(self) -> None:
        source = self._source()
        self.assertNotIn("set_size_request(940, 600)", source)

    def test_episode_artwork_remains_flexible(self) -> None:
        import inspect

        self.assertIn(
            "flexible_width",
            inspect.signature(cineshelf.PosterWidget.__init__).parameters,
        )
        source = self._source()
        self.assertIn("flexible_width=True", source)

    def test_responsive_modes_are_explicit(self) -> None:
        self.assertEqual(cineshelf.SIDEBAR_EXPANDED, "expanded")
        self.assertEqual(cineshelf.SIDEBAR_HIDDEN, "hidden")
        self.assertEqual(cineshelf.DETAILS_INLINE, "inline")
        self.assertEqual(cineshelf.DETAILS_OVERLAY, "overlay")
        self.assertEqual(cineshelf.DETAILS_NAVIGATION, "navigation")


class PanelWidthTests(unittest.TestCase):
    def test_inline_width_is_constant(self) -> None:
        for available in (0, 200, 360, 1100, 2000):
            self.assertEqual(
                cineshelf.CineShelfWindow._details_panel_preferred_width(
                    cineshelf.DETAILS_INLINE, available
                ),
                384,
            )

    def test_inline_width_ignores_media_type(self) -> None:
        widths = {
            cineshelf.CineShelfWindow._details_panel_preferred_width(
                cineshelf.DETAILS_INLINE, 480
            )
            for _media_type in ("Movies", "Shows", "Anime")
        }
        self.assertEqual(widths, {384})
        self.assertEqual(cineshelf.DETAILS_INLINE_WIDTH, 384)

    def test_overlay_width_is_clamped_to_available_width(self) -> None:
        panel = cineshelf.CineShelfWindow._details_panel_preferred_width
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 0), 280)
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 100), 280)
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 328), 280)
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 329), 281)
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 436), 388)
        self.assertEqual(panel(cineshelf.DETAILS_OVERLAY, 2000), 388)

    def test_navigation_mode_applies_no_desktop_panel_width(self) -> None:
        self.assertEqual(
            cineshelf.CineShelfWindow._details_panel_preferred_width(
                cineshelf.DETAILS_NAVIGATION, 480
            ),
            0,
        )

    def test_panel_width_does_not_measure_content(self) -> None:
        source = Path(cineshelf.__file__).read_text(encoding="utf-8")
        body = source.split("def _details_panel_preferred_width")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("measure(", body)
        self.assertNotIn("details_surface", body)

    def test_episode_cards_can_wrap(self) -> None:
        source = Path(cineshelf.__file__).read_text(encoding="utf-8")
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
    cineshelf.CineShelfWindow, FakeNavigation, FakeWidget, FakeWidget, list[str]
]:
    controller = object.__new__(cineshelf.CineShelfWindow)
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
    surface.set_parent(home if mode != cineshelf.DETAILS_NAVIGATION else mobile_host)
    return controller, navigation, surface, revealer, events


class DetailsSyncTests(unittest.TestCase):
    def test_closed_browser_stays_put(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=False,
                mode=cineshelf.DETAILS_NAVIGATION,
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
                mode=cineshelf.DETAILS_NAVIGATION,
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
                mode=cineshelf.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertEqual(navigation.calls, [])

    def test_closing_pops_explicitly_to_browser(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="details",
                details_open=False,
                mode=cineshelf.DETAILS_NAVIGATION,
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
                mode=cineshelf.DETAILS_NAVIGATION,
            )
        )
        controller._sync_details_presentation()
        self.assertEqual(navigation.tag, "details")

    def test_no_duplicate_pushed_flag_exists(self) -> None:
        self.assertFalse(hasattr(cineshelf.CineShelfWindow, "_mobile_details_pushed"))
        controller = object.__new__(cineshelf.CineShelfWindow)
        self.assertFalse(hasattr(controller, "_mobile_details_pushed"))

    def test_open_path_synchronizes_without_timeout(self) -> None:
        source = Path(cineshelf.__file__).read_text(encoding="utf-8")
        opener = source.split("def _set_details_open")[1].split(
            "\n    def "
        )[0]
        self.assertIn("_sync_details_presentation()", opener)

    def test_external_pop_synchronizes_closed_state(self) -> None:
        controller, navigation, _surface, _revealer, _events = (
            _sync_controller(
                visible_tag="browser",
                details_open=True,
                mode=cineshelf.DETAILS_NAVIGATION,
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
                mode=cineshelf.DETAILS_NAVIGATION,
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
                mode=cineshelf.DETAILS_OVERLAY,
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
        return Path(cineshelf.__file__).read_text(encoding="utf-8")

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
        root = ET.parse(cineshelf.UI_FILE).getroot()
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


if __name__ == "__main__":
    unittest.main()
