#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import gi


SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from gisheh import window as gisheh


class DetailDataIntegrityTests(unittest.TestCase):
    @staticmethod
    def _record(**changes: object) -> gisheh.TitleRecord:
        records, _explore, _totals = gisheh.load_catalog(
            include_sample_data=True
        )
        return replace(records[0], **changes)

    def test_rating_sources_do_not_fabricate_fallbacks(self) -> None:
        record = self._record(rating=7.3, external_ratings=())

        self.assertEqual(gisheh.GishehWindow._rating_sources(record), ())

    def test_rating_sources_only_keep_valid_allowed_values_in_ui_order(self) -> None:
        record = self._record(
            external_ratings=(
                ("Your rating", "8"),
                ("IMDb", "7.4"),
                ("TMDB", "7.3"),
                ("Meta", "74"),
                ("TMDB", "9.9"),
                ("Your rating", ""),
            )
        )

        self.assertEqual(
            gisheh.GishehWindow._rating_sources(record),
            (("TMDB", "7.3"), ("Your rating", "8")),
        )

    def test_user_rating_never_becomes_the_tmdb_badge(self) -> None:
        record = self._record(
            external_ratings=(("Your rating", "8"),)
        )

        self.assertIsNone(gisheh.GishehWindow._tmdb_rating_value(record))

    def test_tmdb_payload_without_votes_has_no_public_rating(self) -> None:
        record = gisheh.title_record_from_tmdb(
            {"id": 10, "title": "Unrated", "vote_average": 0, "vote_count": 0},
            "Movies",
            1,
            None,
            None,
        )

        self.assertEqual(record.rating, 0.0)
        self.assertEqual(record.external_ratings, ())

    def test_tmdb_payload_with_votes_preserves_the_real_rating(self) -> None:
        record = gisheh.title_record_from_tmdb(
            {
                "id": 11,
                "title": "Rated",
                "vote_average": 7.65,
                "vote_count": 120,
            },
            "Movies",
            1,
            None,
            None,
        )

        self.assertEqual(record.rating, 7.7)
        self.assertEqual(record.external_ratings, (("TMDB", "7.7"),))

    def test_enrichment_keeps_user_rating_when_tmdb_has_no_votes(self) -> None:
        record = self._record(user_rating=9)

        enriched = gisheh.enrich_record_from_tmdb(
            record,
            {"vote_average": 0, "vote_count": 0},
        )

        self.assertEqual(enriched.external_ratings, (("Your rating", "9"),))

    def test_rating_ui_uses_loading_then_empty_state(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.detail_ratings_host = Gtk.Grid()
        record = self._record(external_ratings=())
        controller._tmdb_details_loading = {record.id}

        controller._populate_detail_ratings(record)
        loading = controller.detail_ratings_host.get_first_child()
        self.assertIsInstance(loading, Gtk.Label)
        assert isinstance(loading, Gtk.Label)
        self.assertEqual(loading.get_label(), "Loading ratings…")

        controller._tmdb_details_loading.clear()
        controller._populate_detail_ratings(record)
        empty = controller.detail_ratings_host.get_first_child()
        self.assertIsInstance(empty, Gtk.Label)
        assert isinstance(empty, Gtk.Label)
        self.assertEqual(
            empty.get_label(), "No rating information is available."
        )

    def test_cast_members_are_real_ordered_and_limited_to_twelve(self) -> None:
        cast = tuple(
            gisheh.CastMember(f"Person {index}", f"Role {index}")
            for index in range(15)
        )
        record = self._record(cast=cast)

        self.assertEqual(
            gisheh.GishehWindow._cast_members(record), cast[:12]
        )
        self.assertEqual(
            gisheh.GishehWindow._cast_members(replace(record, cast=())), ()
        )

    def test_cast_empty_state_can_distinguish_title_and_episode(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller._tmdb_details_loading = set()
        controller._tmdb_cast_images_loading = {}
        record = self._record(cast=())

        title_box = Gtk.Box()
        controller._populate_cast_container(title_box, record)
        title_empty = title_box.get_first_child()
        self.assertIsInstance(title_empty, Gtk.Label)
        assert isinstance(title_empty, Gtk.Label)
        self.assertEqual(
            title_empty.get_label(), "Cast information is unavailable."
        )

        episode_box = Gtk.Box()
        controller._populate_cast_container(
            episode_box,
            record,
            empty_message=(
                "Guest cast information is unavailable for this episode."
            ),
        )
        episode_empty = episode_box.get_first_child()
        self.assertIsInstance(episode_empty, Gtk.Label)
        assert isinstance(episode_empty, Gtk.Label)
        self.assertEqual(
            episode_empty.get_label(),
            "Guest cast information is unavailable for this episode.",
        )

    def test_tmdb_failure_clears_loading_and_refreshes_selected_record(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.selected_id = "record-1"
        controller._tmdb_detail_generations = {"record-1": 3}
        controller._tmdb_details_loading = {"record-1"}
        controller._tmdb_cast_images_loading = {"record-1": {0}}
        controller._tmdb_gallery_images_loading = {"record-1": {"poster": 1}}
        controller._update_details = Mock()

        with contextlib.redirect_stderr(io.StringIO()):
            result = controller._on_tmdb_details_failed(
                "record-1", 3, "Network unavailable"
            )

        self.assertEqual(result, GLib.SOURCE_REMOVE)
        self.assertNotIn("record-1", controller._tmdb_details_loading)
        self.assertNotIn("record-1", controller._tmdb_cast_images_loading)
        self.assertNotIn("record-1", controller._tmdb_gallery_images_loading)
        controller._update_details.assert_called_once_with()

    def test_runtime_has_no_fake_cast_or_see_all_infrastructure(self) -> None:
        source = (SOURCE_DIR / "gisheh/window.py").read_text(encoding="utf-8")

        for forbidden in (
            "Lead Ensemble",
            "Supporting Ensemble",
            "Guest Artist",
            "Open all cast",
            'action_label="See all"',
            "record.rating + 0.1",
            "record.rating * 10",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
