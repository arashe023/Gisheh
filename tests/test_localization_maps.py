"""Tests for the local English→translatable display mappings.

TMDB/Simkl values always arrive in English. They are mapped through the
local tables in ``gisheh.window`` (``localize_*``) so every label shown to
the user enters the gettext catalog and can be translated per language.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh import window as gisheh


class GenreMappingTests(unittest.TestCase):
    def test_english_genre_names_map_to_catalog_labels(self) -> None:
        self.assertEqual(gisheh.localize_genre_name("Science Fiction"), "Science Fiction")
        self.assertEqual(gisheh.localize_genre_name("science fiction"), "Science Fiction")
        self.assertEqual(
            gisheh.localize_genre_name("Action & Adventure"), "Action & Adventure"
        )
        self.assertEqual(gisheh.localize_genre_name("Drama"), "Drama")

    def test_unknown_genre_names_pass_through(self) -> None:
        self.assertEqual(gisheh.localize_genre_name("Cyberpunk"), "Cyberpunk")

    def test_genre_tuples_localize_elementwise(self) -> None:
        self.assertEqual(
            gisheh.localize_genre_names(("Drama", "Mystery")),
            ("Drama", "Mystery"),
        )

    def test_tmdb_record_genres_use_translated_labels(self) -> None:
        record = gisheh.title_record_from_tmdb(
            {
                "id": 1,
                "title": "Sample",
                "genre_ids": [18, 80],
                "origin_country": ["IR"],
            },
            "Movies",
            1,
            None,
            None,
        )
        self.assertEqual(record.genres, ("Drama", "Crime"))
        self.assertEqual(record.country, "Iran")

    def test_enrich_translates_api_genre_names(self) -> None:
        record = gisheh.title_record_from_tmdb(
            {"id": 2, "title": "Sample", "genre_ids": [], "origin_country": []},
            "Movies",
            1,
            None,
            None,
        )
        enriched = gisheh.enrich_record_from_tmdb(
            record,
            {
                "genres": [{"name": "Science Fiction"}, {"name": "Drama"}],
                "production_countries": [{"name": "Japan", "iso_3166_1": "JP"}],
                "status": "Released",
            },
        )
        self.assertEqual(enriched.genres, ("Science Fiction", "Drama"))
        self.assertEqual(enriched.country, "Japan")
        self.assertEqual(enriched.availability, "Released")


class StatusMappingTests(unittest.TestCase):
    def test_tmdb_statuses_localize_case_insensitively(self) -> None:
        self.assertEqual(gisheh.localize_tmdb_status("Released"), "Released")
        self.assertEqual(
            gisheh.localize_tmdb_status("Returning Series"), "Returning Series"
        )
        self.assertEqual(gisheh.localize_tmdb_status("ENDED"), "Ended")

    def test_simkl_statuses_map_to_collection_labels(self) -> None:
        self.assertEqual(gisheh.localize_tmdb_status("watching"), "Watching")
        self.assertEqual(gisheh.localize_tmdb_status("Plan to watch"), "Plan to watch")
        self.assertEqual(gisheh.localize_tmdb_status("hold"), "On Hold")
        self.assertEqual(gisheh.localize_tmdb_status("completed"), "Watched")
        self.assertEqual(gisheh.localize_tmdb_status("dropped"), "Dropped")

    def test_unknown_status_falls_back_to_raw_value(self) -> None:
        self.assertEqual(gisheh.localize_tmdb_status("Rumored"), "Rumored")
        self.assertEqual(gisheh.localize_tmdb_status("", fallback="—"), "—")

    def test_collection_status_localizes_known_names(self) -> None:
        self.assertEqual(gisheh.localize_collection_status("Watched"), "Watched")
        self.assertEqual(gisheh.localize_collection_status("On Hold"), "On Hold")
        self.assertEqual(gisheh.localize_collection_status("Custom"), "Custom")


class CountryMappingTests(unittest.TestCase):
    def test_country_codes_and_names_map_to_labels(self) -> None:
        self.assertEqual(
            gisheh.localize_country_name("US"), "United States of America"
        )
        self.assertEqual(gisheh.localize_country_name("IR"), "Iran")
        self.assertEqual(gisheh.localize_country_name("Iran"), "Iran")

    def test_unknown_countries_pass_through(self) -> None:
        self.assertEqual(gisheh.localize_country_name("Wakanda"), "Wakanda")


class StoredFallbackNormalizationTests(unittest.TestCase):
    def test_known_english_fallbacks_normalize(self) -> None:
        self.assertEqual(
            gisheh._normalize_stored_fallback("Runtime unavailable"),
            "Runtime unavailable",
        )
        self.assertEqual(
            gisheh._normalize_stored_fallback("No overview is available yet."),
            "No overview is available yet.",
        )
        self.assertEqual(
            gisheh._normalize_stored_fallback("A custom note."),
            "A custom note.",
        )

    def test_stored_genres_normalize(self) -> None:
        self.assertEqual(
            gisheh._normalize_stored_genres(("Uncategorized", "Drama")),
            ("Uncategorized", "Drama"),
        )

    def test_stored_country_pairs_normalize(self) -> None:
        self.assertEqual(
            gisheh._normalize_stored_country("US, IR"),
            "United States of America, Iran",
        )


class DurationLocalizationTests(unittest.TestCase):
    def test_compact_english_output_is_unchanged(self) -> None:
        self.assertEqual(gisheh.format_watch_time(104), "1h 44m")
        self.assertEqual(gisheh.format_watch_time(6502), "4d 12h 22m")
        self.assertEqual(gisheh.format_watch_time(0), "0m")

    def test_runtime_minutes_parses_compact_and_translated_units(self) -> None:
        self.assertEqual(gisheh.runtime_minutes("2h 04m"), 124)
        self.assertEqual(gisheh.runtime_minutes("45m"), 45)
        self.assertEqual(gisheh.runtime_minutes("1 ساعت 44 دقیقه"), 104)
        self.assertEqual(gisheh.runtime_minutes("۲ ساعت و ۴۴ دقیقه"), 164)
        self.assertEqual(gisheh.runtime_minutes("3 seasons"), 0)

    def test_watched_timestamp_uses_translatable_template(self) -> None:
        self.assertEqual(
            gisheh.format_watched_iso("2026-09-05T15:04:00+03:30"),
            "Sep 5, 2026 at 3:04 PM",
        )
        self.assertEqual(gisheh.format_watched_iso("not-a-date"), "not-a-date")

    def test_episode_title_helper_is_translatable(self) -> None:
        self.assertIn("Episode {number}", gisheh.N_("Episode {number}"))


if __name__ == "__main__":
    unittest.main()
