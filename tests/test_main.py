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
from gisheh.window import is_rtl_language_selection


class ApplicationDirectionTests(unittest.TestCase):
    def test_temporary_persian_language_uses_rtl(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_LANGUAGE": "fa", "LANGUAGE": "en"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.RTL,
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

    def test_english_language_uses_ltr(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_LANGUAGE": "en", "LANGUAGE": "fa"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.LTR,
            )

    def test_direction_is_applied_to_gtk_before_ui_creation(self) -> None:
        with (
            patch.dict(os.environ, {"GISHEH_LANGUAGE": "fa"}, clear=True),
            patch.object(Gtk.Widget, "set_default_direction") as set_direction,
        ):
            main._configure_text_direction()

        set_direction.assert_called_once_with(Gtk.TextDirection.RTL)

    def test_content_language_persian_uses_rtl(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_TMDB_LANGUAGE": "fa-IR"},
            clear=True,
        ):
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.RTL,
            )

    def test_content_language_english_uses_ltr(self) -> None:
        with patch.dict(
            os.environ,
            {"GISHEH_TMDB_LANGUAGE": "en-US", "LANG": "fa_IR.UTF-8"},
            clear=True,
        ):
            # Explicit content choice wins over the OS locale for direction.
            self.assertEqual(
                main._application_text_direction(),
                Gtk.TextDirection.LTR,
            )


class ContentLanguageDirectionTests(unittest.TestCase):
    def test_persian_app_language_is_rtl(self) -> None:
        self.assertTrue(is_rtl_language_selection("fa", "system"))
        self.assertTrue(is_rtl_language_selection("fa", "en-US"))

    def test_persian_content_language_is_rtl_live(self) -> None:
        # Experimental content language applies instantly, without restart.
        self.assertTrue(is_rtl_language_selection("system", "fa-IR"))

    def test_english_selection_is_ltr(self) -> None:
        self.assertFalse(is_rtl_language_selection("en", "system"))
        self.assertFalse(is_rtl_language_selection("system", "en-US"))


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
