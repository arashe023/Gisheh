#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


LINUX_DIR = Path(__file__).resolve().parents[1] / "linux"
sys.path.insert(0, str(LINUX_DIR))
SPEC = importlib.util.spec_from_file_location("cineshelf", LINUX_DIR / "cineshelf.py")
assert SPEC and SPEC.loader
cineshelf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cineshelf
SPEC.loader.exec_module(cineshelf)


class ExploreLayoutTests(unittest.TestCase):
    def test_library_grid_columns_follow_real_card_width(self) -> None:
        self.assertEqual(cineshelf.grid_columns_for_width(120), 1)
        self.assertEqual(cineshelf.grid_columns_for_width(320), 2)
        self.assertEqual(cineshelf.grid_columns_for_width(620), 4)
        self.assertEqual(cineshelf.grid_columns_for_width(820), 5)
        self.assertEqual(cineshelf.grid_columns_for_width(990), 6)
        self.assertEqual(cineshelf.grid_columns_for_width(2000), 6)

    def test_rows_fill_without_using_a_full_width_card(self) -> None:
        for columns in (2, 3, 4, 5):
            for count in range(1, 24):
                plan = cineshelf.build_explore_layout_plan(count, columns, seed=91)
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
        first = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        second = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        self.assertEqual(first, second)
        kinds = {kind for row in first for kind, _span in row}
        self.assertGreaterEqual(len(kinds), 2)


class MediaCollectionTests(unittest.TestCase):
    def test_media_items_keep_primary_first_and_remove_duplicates(self) -> None:
        records, _explore, _totals = cineshelf.load_catalog()
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

            items = cineshelf.CineShelfWindow._media_items(record, "posters")

        self.assertEqual([path for path, _label in items], [str(first), str(second)])
        self.assertEqual(items[0][1], f"{record.title} — Poster 1")

class ProfileFormattingTests(unittest.TestCase):
    def test_runtime_minutes_handles_catalog_durations(self) -> None:
        self.assertEqual(cineshelf.runtime_minutes("2h 04m"), 124)
        self.assertEqual(cineshelf.runtime_minutes("45m"), 45)
        self.assertEqual(cineshelf.runtime_minutes("3 seasons"), 0)

    def test_watch_time_and_dates_are_stable(self) -> None:
        self.assertEqual(cineshelf.format_watch_time(6502), "4d 12h 22m")
        parsed = cineshelf.parse_watched_date("Aug 8, 2026 at 2:49 AM")
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
                }
            ],
        }

        records = cineshelf.title_records_from_simkl(payload)

        by_id = {record.id: record for record in records}
        movie = by_id["simkl-movies-101"]
        show = by_id["simkl-shows-102"]
        anime = by_id["simkl-anime-103"]
        paused = by_id["simkl-anime-104"]
        self.assertTrue(all(record.title == "Loading from TMDB…" for record in records))
        self.assertTrue(all(record.year == 0 for record in records))
        self.assertEqual(movie.media_type, "Movies")
        self.assertEqual(movie.status, "Watched")
        self.assertEqual(movie.user_rating, 9)
        self.assertEqual(movie.rating, 0.0)
        self.assertIsNone(movie.poster_file)
        self.assertEqual(movie.tmdb_id, 201)
        self.assertEqual(show.media_type, "Shows")
        self.assertEqual(show.status, "Watching")
        self.assertEqual(show.seasons[0].watched, 4)
        self.assertEqual(anime.media_type, "Anime")
        self.assertEqual(anime.status, "Watchlist")
        self.assertEqual(anime.availability, "Plan To Watch")
        self.assertEqual(paused.status, "On Hold")

    def test_watchlist_contains_only_plan_to_watch_items(self) -> None:
        records = cineshelf.title_records_from_simkl(
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
        self.assertEqual(cineshelf.title_records_from_simkl(payload), ())

    def test_tmdb_enrichment_preserves_simkl_user_state(self) -> None:
        record = cineshelf.title_records_from_simkl(
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
            "genres": [{"name": "Drama"}],
            "overview": "TMDB overview",
            "poster_path": "/poster.jpg",
        }
        with patch.object(
            cineshelf.tmdb_client,
            "cached_image",
            return_value="/cache/poster.jpg",
        ):
            enriched = cineshelf.enrich_record_from_tmdb(record, summary)

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

    def test_stats_refresh_is_skipped_when_activity_is_unchanged(self) -> None:
        self.assertFalse(
            cineshelf.should_refresh_simkl_stats(
                has_incremental_state=True,
                repairing_metadata=False,
                cached_stats={"movies": {"completed": 12}},
                activities={"all": "2026-08-31T10:00:00Z"},
                last_sync="2026-08-31T10:00:00Z",
            )
        )
        self.assertTrue(
            cineshelf.should_refresh_simkl_stats(
                has_incremental_state=True,
                repairing_metadata=False,
                cached_stats={"movies": {"completed": 12}},
                activities={"all": "2026-08-31T10:05:00Z"},
                last_sync="2026-08-31T10:00:00Z",
            )
        )

    def test_watchlist_removal_executes_the_simkl_remove_request(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"
        record = cineshelf.title_records_from_simkl(
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
                cineshelf.CineShelfWindow,
                "_run_simkl_mutation",
                new=capture_mutation,
            ),
            patch.object(cineshelf.simkl_client, "remove_from_library") as remove,
            patch.object(cineshelf.simkl_client, "set_list_status") as add,
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


class TmdbProgressiveLoadingTests(unittest.TestCase):
    def test_detail_backdrop_does_not_replace_portrait_card_artwork(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
        published: list[cineshelf.TitleRecord] = []
        record = cineshelf.title_record_from_tmdb(
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
            patch.object(cineshelf.tmdb_client, "fetch_details", return_value=payload),
            patch.object(
                cineshelf.tmdb_client,
                "cached_image",
                side_effect=cached_image,
            ),
            patch.object(cineshelf.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_details_worker(record, "token", 1)

        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].poster_file, "/cache/poster.jpg")
        self.assertEqual(published[0].backdrop_file, "/cache/backdrop.jpg")
        self.assertEqual(published[0].artwork_file, "/cache/poster.jpg")

    def test_simkl_library_record_is_enriched_from_tmdb_before_poster(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
        events: list[str] = []
        record = cineshelf.title_records_from_simkl(
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
            patch.object(cineshelf.tmdb_client, "load_summary", return_value=None),
            patch.object(cineshelf.tmdb_client, "fetch_summary", return_value=summary),
            patch.object(cineshelf.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(cineshelf.GLib, "idle_add", side_effect=idle_add),
        ):
            loaded = controller._load_tmdb_library_record(record, "token", 1)

        self.assertTrue(loaded)
        self.assertEqual(events[0], "_apply_tmdb_library_summary")
        self.assertEqual(events[1], "download:w500")
        self.assertEqual(events[2], "_apply_tmdb_library_poster")

    def test_explore_records_are_published_before_image_downloads(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
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
            patch.object(cineshelf.tmdb_client, "fetch_explore", return_value=payload),
            patch.object(cineshelf.tmdb_client, "cached_image", return_value=None),
            patch.object(cineshelf.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(cineshelf.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_explore_worker("token", 1, "Movies")

        self.assertEqual(events[0], "_apply_tmdb_explore")
        self.assertIn("download:w500:/poster.jpg", events[1:])
        self.assertIn("download:w780:/backdrop.jpg", events[1:])

    def test_detail_metadata_is_published_before_artwork_downloads(self) -> None:
        controller = object.__new__(cineshelf.CineShelfWindow)
        events: list[str] = []
        record = cineshelf.title_record_from_tmdb(
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
            patch.object(cineshelf.tmdb_client, "fetch_details", return_value=payload),
            patch.object(cineshelf.tmdb_client, "cached_image", return_value=None),
            patch.object(cineshelf.tmdb_client, "cache_image", side_effect=cache_image),
            patch.object(cineshelf.GLib, "idle_add", side_effect=idle_add),
        ):
            controller._load_tmdb_details_worker(record, "token", 1)

        self.assertEqual(events[0], "_apply_tmdb_details")
        self.assertTrue(any(event.startswith("download:") for event in events[1:]))


if __name__ == "__main__":
    unittest.main()
