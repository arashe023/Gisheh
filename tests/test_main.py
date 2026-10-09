from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh import main
from gisheh.window import (
    is_rtl_language_selection,
    sidebar_position_for_direction,
)


class ApplicationDirectionTests(unittest.TestCase):
    def test_removed_override_does_not_override_system_english(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_LANGUAGE": "fa", "LANGUAGE": "en"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.LTR,
            )

    def test_system_persian_locale_uses_rtl(self) -> None:
        with patch.dict(
            os.environ,
            {"LANGUAGE": "fa_IR.UTF-8"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.RTL,
            )

    def test_removed_override_does_not_override_system_persian(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_LANGUAGE": "en", "LANGUAGE": "fa"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.RTL,
            )

    def test_direction_is_applied_to_gtk_before_ui_creation(self) -> None:
        with (
            patch.dict(os.environ, {"LANGUAGE": "fa"}, clear=True),
            patch.object(Gtk.Widget, "set_default_direction") as set_direction,
        ):
            main._configure_text_direction()

        set_direction.assert_called_once_with(Gtk.TextDirection.RTL)

    def test_persian_content_does_not_mirror_english_ui(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_TMDB_LANGUAGE": "fa-IR", "LANG": "en_US.UTF-8"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.LTR,
            )

    def test_english_content_does_not_override_persian_ui(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_TMDB_LANGUAGE": "en-US", "LANG": "fa_IR.UTF-8"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.RTL,
            )


class ContentLanguageDirectionTests(unittest.TestCase):
    def test_persian_content_does_not_mirror_english_chrome(self) -> None:
        with patch.object(
            Gtk.Widget,
            "get_default_direction",
            return_value=Gtk.TextDirection.LTR,
        ):
            self.assertFalse(is_rtl_language_selection())

    def test_english_content_does_not_unmirror_persian_chrome(self) -> None:
        with patch.object(
            Gtk.Widget,
            "get_default_direction",
            return_value=Gtk.TextDirection.RTL,
        ):
            self.assertTrue(is_rtl_language_selection())

    def test_sidebar_uses_logical_start_in_both_directions(self) -> None:
        self.assertEqual(
            sidebar_position_for_direction(False),
            Gtk.PackType.START,
        )
        self.assertEqual(
            sidebar_position_for_direction(True),
            Gtk.PackType.START,
        )


class CollectionTranslationsTests(unittest.TestCase):
    def test_collection_msgids_are_in_pot(self) -> None:
        pot = (
            Path(__file__).resolve().parents[1] / "po" / "gisheh.pot"
        ).read_text(encoding="utf-8")
        for msgid in (
            "Watching",
            "Watched",
            "On Hold",
            "Dropped",
            "Watchlist",
            "Collections",
        ):
            self.assertIn(f'msgid "{msgid}"', pot)

    def test_sidebar_row_label_can_be_retranslated_live(self) -> None:
        from gisheh.window import SidebarRow

        row = SidebarRow("Watched", "Watched", "object-select-symbolic")
        row.set_label("تماشاشده")
        self.assertEqual(row.title_label.get_label(), "تماشاشده")


if __name__ == "__main__":
    unittest.main()
