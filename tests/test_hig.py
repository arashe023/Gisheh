"""Behavioral checks for GNOME keyboard, dialog and accessibility conventions."""

from unittest.mock import Mock, patch
import unittest

from gi.repository import Adw, Gdk, Gio, Gtk

from gisheh.window import GishehWindow, UI_FILE


class HigBehaviorTests(unittest.TestCase):
    def controller(self):
        controller = object.__new__(GishehWindow)
        controller.window = Adw.ApplicationWindow()
        self.addCleanup(controller.window.destroy)
        controller._save_user_state = Mock()
        controller._save_window_state = Mock()
        controller.close_background_jobs = Mock()
        controller._toast = Mock()
        controller._app_log = Mock()
        return controller

    def test_close_closes_window_even_with_details_open(self):
        controller = self.controller()
        controller.details_open = True
        controller._set_details_open = Mock()
        self.assertFalse(controller._on_window_close_request(controller.window))
        controller._save_user_state.assert_called_once()
        controller._save_window_state.assert_called_once()
        controller.close_background_jobs.assert_called_once()
        controller._set_details_open.assert_not_called()

    def test_failed_save_still_prevents_close(self):
        controller = self.controller()
        controller._save_user_state.side_effect = OSError("disk full")
        self.assertTrue(controller._on_window_close_request(controller.window))
        controller.close_background_jobs.assert_not_called()
        controller._toast.assert_called_once()

    def test_primary_menu_has_standard_section_and_no_quit(self):
        menu = GishehWindow._primary_menu()
        standard = menu.get_item_link(1, Gio.MENU_LINK_SECTION)
        actions = [
            standard.get_item_attribute_value(
                i, Gio.MENU_ATTRIBUTE_ACTION, None
            ).unpack()
            for i in range(standard.get_n_items())
        ]
        self.assertEqual(actions, ["win.preferences", "win.shortcuts", "app.about"])
        for index in range(menu.get_n_items()):
            section = menu.get_item_link(index, Gio.MENU_LINK_SECTION)
            for item in range(section.get_n_items()):
                self.assertNotEqual(
                    section.get_item_attribute_value(item, "action", None).unpack(),
                    "app.quit",
                )
                self.assertIn(
                    "_", section.get_item_attribute_value(item, "label", None).unpack()
                )

    def test_registered_shortcuts_invoke_their_actions(self):
        controller = self.controller()
        application = Mock()
        controller._on_find_requested = Mock()
        controller._navigate_back = Mock(return_value=True)
        controller._show_shortcuts = Mock()
        controller._install_window_actions(application)
        for action, keys in (
            ("win.find", ["<primary>f"]),
            ("win.shortcuts", ["<primary>question"]),
            ("win.main-menu", ["F10"]),
            ("win.close", ["<primary>w"]),
            ("win.back", ["<Alt>Left"]),
        ):
            application.set_accels_for_action.assert_any_call(action, keys)
        controller.window.lookup_action("find").activate(None)
        controller.window.lookup_action("back").activate(None)
        controller.window.lookup_action("shortcuts").activate(None)
        controller._on_find_requested.assert_called_once()
        controller._navigate_back.assert_called_once()
        controller._show_shortcuts.assert_called_once()
        self.assertIsInstance(controller._shortcuts_dialog(), Adw.ShortcutsDialog)

    def test_close_shortcut_closes_dialog_before_window(self):
        controller = self.controller()
        dialog = Mock()
        with (
            patch.object(controller.window, "get_visible_dialog", return_value=dialog),
            patch.object(controller.window, "close") as close,
        ):
            controller._close_active_surface()
        dialog.close.assert_called_once()
        close.assert_not_called()

    def test_preferences_feedback_is_visible_inside_preferences(self):
        controller = self.controller()
        controller.settings_dialog = Mock()
        controller.settings_dialog.get_visible.return_value = True
        controller.toast_overlay = Mock()
        GishehWindow._toast(controller, "Saved")
        controller.settings_dialog.add_toast.assert_called_once()
        controller.toast_overlay.add_toast.assert_not_called()
        toast = controller.settings_dialog.add_toast.call_args.args[0]
        self.assertEqual(toast.get_timeout(), 5)

    def test_find_uses_current_collection_and_preserves_explore_shortcut(self):
        controller = self.controller()
        controller.search_entry = Mock()
        controller._close_sidebar_overlay = Mock()
        controller._on_search_requested = Mock()
        controller.active_destination = "collection"
        controller._on_find_requested()
        controller.search_entry.grab_focus.assert_called_once()
        controller._on_search_requested.assert_not_called()
        controller.active_destination = "explore"
        controller._on_find_requested()
        controller._on_search_requested.assert_called_once()

    def test_escape_does_not_navigate_under_a_dialog(self):
        controller = self.controller()
        controller._navigate_back = Mock(return_value=True)
        with patch.object(
            controller.window, "get_visible_dialog", return_value=Adw.Dialog()
        ):
            self.assertFalse(
                controller._on_window_key_pressed(None, Gdk.KEY_Escape, 0, 0)
            )
        controller._navigate_back.assert_not_called()
        self.assertTrue(controller._on_window_key_pressed(None, Gdk.KEY_Escape, 0, 0))

    def test_static_icon_controls_have_accessible_names(self):
        builder = Gtk.Builder.new_from_file(str(UI_FILE))
        self.addCleanup(builder.get_object("window").destroy)
        for name in (
            "main_menu_button",
            "profile_button",
            "search_button",
            "bookmark_button",
            "sort_dropdown",
            "explore_search_entry",
        ):
            with self.subTest(name=name):
                self.assertTrue(
                    Gtk.test_accessible_has_property(
                        builder.get_object(name), Gtk.AccessibleProperty.LABEL
                    )
                )

    def test_log_dialog_has_no_fixed_desktop_minimum(self):
        controller = self.controller()
        controller._log_dialog = None
        controller._log_text_view = None
        with (
            patch.object(Adw.Dialog, "present"),
            patch("gisheh.window.read_application_log", return_value="x" * 2000),
        ):
            controller.show_application_log()
        self.assertIsInstance(controller._log_dialog, Adw.Dialog)
        self.assertNotIsInstance(controller._log_dialog, Adw.AlertDialog)
        self.assertEqual(
            controller._log_text_view.get_wrap_mode(), Gtk.WrapMode.WORD_CHAR
        )
        minimum, _, _, _ = controller._log_dialog.get_child().measure(
            Gtk.Orientation.HORIZONTAL, -1
        )
        self.assertLessEqual(minimum, 360)
        controller._on_log_dialog_closed(controller._log_dialog)
        self.assertIsNone(controller._log_text_view)
        self.assertIsNone(controller._log_dialog)

    def test_token_dialog_requires_input_before_connecting(self):
        controller = self.controller()
        controller.settings_dialog = Adw.PreferencesDialog()
        presented = []
        with (
            patch.object(
                Adw.AlertDialog,
                "present",
                new=lambda dialog, parent: presented.append((dialog, parent)),
            ),
            patch("gisheh.window.tmdb_client.token_source", return_value=None),
        ):
            controller._show_tmdb_token_dialog(None)
        dialog, parent = presented[0]
        self.assertIs(parent, controller.settings_dialog)
        self.assertFalse(dialog.get_response_enabled("save"))
        dialog.get_extra_child().set_text("  ")
        self.assertFalse(dialog.get_response_enabled("save"))
        dialog.get_extra_child().set_text("test-token")
        self.assertTrue(dialog.get_response_enabled("save"))
