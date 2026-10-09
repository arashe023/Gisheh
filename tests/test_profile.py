from unittest.mock import Mock
import unittest

from gi.repository import Adw, Gtk
from gisheh.profile import ProfileView
from profile_samples import profile_stats


class ProfileViewTests(unittest.TestCase):
    def setUp(self):
        self.preferences = Mock()
        self.explore = Mock()
        self.view = ProfileView(
            on_preferences=self.preferences, on_explore=self.explore
        )

    def test_new_profile_has_an_actionable_empty_state(self):
        self.view.update(profile_stats(empty=True))
        self.assertTrue(self.view.empty.get_visible())
        self.assertFalse(self.view.activity.get_visible())
        self.view.empty.get_child().emit("clicked")
        self.explore.assert_called_once()

    def test_month_and_year_display_distinct_values(self):
        self.view.update(profile_stats())
        self.assertFalse(self.view.empty.get_visible())
        self.assertEqual(
            [label.get_label() for label in self.view.metric_values], ["3", "12", "1"]
        )
        self.assertFalse(self.view.year_group.get_visible())
        self.view.period.set_active_name("year")
        self.assertEqual(
            [label.get_label() for label in self.view.metric_values],
            ["23", "104", "61"],
        )
        self.assertTrue(self.view.year_group.get_visible())

    def test_refresh_preserves_period_and_expanded_details(self):
        self.view.update(profile_stats())
        self.view.period.set_active_name("year")
        self.view._expanders["ratings"].set_expanded(True)
        self.view._expanders["months"].set_expanded(True)
        self.view.update(profile_stats())
        self.assertEqual(self.view.period.get_active_name(), "year")
        self.assertTrue(self.view._expanders["ratings"].get_expanded())
        self.assertTrue(self.view._expanders["months"].get_expanded())

    def test_identity_treats_names_as_plain_text(self):
        self.view.set_identity("Alex <&> Morgan", "Local profile")
        self.assertEqual(self.view.name_label.get_label(), "Alex <&> Morgan")
        self.assertFalse(self.view.name_label.get_use_markup())
        self.assertEqual(self.view.avatar.get_text(), "Alex <&> Morgan")

    def test_long_name_does_not_force_a_desktop_width(self):
        self.view.set_identity("Name" * 40, "Local profile")
        self.view.update(profile_stats())
        minimum, _, _, _ = self.view.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertLessEqual(minimum, 324)

    def test_statistics_rows_have_explicit_accessible_names(self):
        row = self.view._row("Completed titles", 48)
        self.assertTrue(
            Gtk.test_accessible_has_property(row, Gtk.AccessibleProperty.LABEL)
        )


class ProfileNavigationTests(unittest.TestCase):
    def test_profile_has_a_header_title_and_restores_media_controls(self):
        from gisheh.window import GishehWindow

        controller = object.__new__(GishehWindow)
        controller.header_bar = Adw.HeaderBar()
        controller.media_switcher = Adw.ToggleGroup()
        controller.active_destination = "profile"
        controller._set_media_switcher_available(False)
        self.assertEqual(
            controller.header_bar.get_title_widget().get_title(), "Profile"
        )
        controller._set_media_switcher_available(True)
        self.assertIs(
            controller.header_bar.get_title_widget(), controller.media_switcher
        )
