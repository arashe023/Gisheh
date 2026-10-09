from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures/library.json"

from gisheh import window as gisheh
from gisheh.services import tmdb_client


def _parent(media_type: str = "Movies") -> gisheh.TitleRecord:
    records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
    base = next(record for record in records if record.media_type == media_type)
    namespace = "movie" if media_type == "Movies" else "tv"
    return replace(base, tmdb_id=10, tmdb_media_type=namespace)


def _item(
    tmdb_id: int,
    title: str,
    *,
    media_type: str = "movie",
    year: str = "2024-05-01",
    rating: float = 7.5,
) -> dict[str, object]:
    return {
        "id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "name": title,
        "release_date": year if media_type == "movie" else "",
        "first_air_date": "" if media_type == "movie" else year,
        "overview": f"Overview of {title}",
        "vote_average": rating,
        "vote_count": 100,
        "genre_ids": [28, 12],
        "poster_path": f"/poster{tmdb_id}.jpg",
        "backdrop_path": f"/backdrop{tmdb_id}.jpg",
        "popularity": 10.0,
    }


class RecommendationNormalizationTests(unittest.TestCase):
    def test_results_become_openable_records(self) -> None:
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            records = gisheh.recommendation_records_from_tmdb(
                [_item(21, "First"), _item(22, "Second")], parent
            )
        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first.tmdb_id, 21)
        self.assertEqual(first.tmdb_media_type, "movie")
        self.assertEqual(first.media_type, "Movies")
        self.assertEqual(first.title, "First")
        self.assertEqual(first.year, 2024)
        self.assertEqual(first.rating, 7.5)
        self.assertIn("Action", first.genres)
        self.assertTrue(first.id.startswith("tmdb-movie-"))

    def test_tv_namespace_is_preserved_for_shows_and_anime(self) -> None:
        for media_type in ("Shows", "Anime"):
            parent = _parent(media_type)
            with patch.object(tmdb_client, "cached_image", return_value=None):
                records = gisheh.recommendation_records_from_tmdb(
                    [_item(31, "Series", media_type="tv")], parent
                )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].media_type, media_type)
            self.assertEqual(records[0].tmdb_media_type, "tv")

    def test_youtube_videos_include_cached_thumbnails_and_playable_urls(self) -> None:
        with patch.object(
            tmdb_client,
            "cached_youtube_thumbnail",
            side_effect=lambda key: f"/cache/{key}.jpg",
        ):
            videos = gisheh.video_infos_from_tmdb(
                [
                    {"site": "YouTube", "key": "trailer_123", "name": "Trailer"},
                    {"site": "Vimeo", "key": "ignored", "name": "Ignored"},
                    {"site": "YouTube", "key": "trailer_123", "name": "Duplicate"},
                ]
            )

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].thumbnail_file, "/cache/trailer_123.jpg")
        self.assertEqual(
            videos[0].url,
            "https://www.youtube.com/watch?v=trailer_123",
        )

    def test_movie_item_under_show_parent_uses_movie_namespace(self) -> None:
        parent = _parent("Shows")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            records = gisheh.recommendation_records_from_tmdb(
                [_item(41, "Film", media_type="movie")], parent
            )
        self.assertEqual(records[0].media_type, "Movies")
        self.assertEqual(records[0].tmdb_media_type, "movie")

    def test_parent_duplicate_and_malformed_items_excluded(self) -> None:
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            records = gisheh.recommendation_records_from_tmdb(
                [
                    {"id": 10, "media_type": "movie", "title": "Parent"},
                    _item(51, "Kept"),
                    _item(51, "Duplicate"),
                    {"id": "nan", "title": "Broken"},
                    "not-a-dict",
                    {"title": "Missing id"},
                ],
                parent,
            )
        self.assertEqual([record.tmdb_id for record in records], [51])

    def test_order_preserved_and_capped_at_twelve(self) -> None:
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            records = gisheh.recommendation_records_from_tmdb(
                [_item(100 + index, f"Title {index}") for index in range(20)],
                parent,
            )
        self.assertEqual(len(records), 12)
        self.assertEqual(
            [record.tmdb_id for record in records],
            list(range(100, 112)),
        )

    def test_poster_and_backdrop_use_cached_images(self) -> None:
        parent = _parent("Movies")

        def fake_cached(path: str, *, size: str = "w780") -> str | None:
            if not path:
                return None
            return f"/cache/{size}-{path.strip('/')}"

        with patch.object(tmdb_client, "cached_image", side_effect=fake_cached):
            records = gisheh.recommendation_records_from_tmdb(
                [_item(61, "Poster")], parent
            )
        self.assertEqual(records[0].poster_file, "/cache/w342-poster61.jpg")
        self.assertEqual(records[0].backdrop_file, "/cache/w780-backdrop61.jpg")


def _controller() -> gisheh.GishehWindow:
    controller = object.__new__(gisheh.GishehWindow)
    controller.records_by_id = {}
    controller.library_ids = set()
    controller._tmdb_recommendations = {}
    controller._tmdb_detail_generations = {}
    controller.detail_record_id = None
    controller.selected_id = None
    return controller


class RecommendationCacheTests(unittest.TestCase):
    def test_no_local_fallback_without_tmdb_data(self) -> None:
        controller = _controller()
        records, _explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        first = records[0]
        controller.records_by_id = {record.id: record for record in records}
        self.assertEqual(controller._related_records(first), ())

    def test_cached_recommendations_resolve_in_order(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            items = gisheh.recommendation_records_from_tmdb(
                [_item(71, "One"), _item(72, "Two")], parent
            )
        controller.records_by_id = {parent.id: parent}
        for item in items:
            controller.records_by_id[item.id] = item
        controller._tmdb_recommendations[parent.id] = tuple(item.id for item in items)
        self.assertEqual(
            [record.id for record in controller._related_records(parent)],
            [item.id for item in items],
        )

    def test_apply_registers_without_touching_library(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        controller.records_by_id = {parent.id: parent}
        controller.library_ids = {parent.id}
        controller.detail_record_id = parent.id
        controller.selected_id = parent.id
        controller._tmdb_detail_generations[parent.id] = 3
        controller._populate_recommendations = lambda record: None  # type: ignore[method-assign]
        with patch.object(tmdb_client, "cached_image", return_value=None):
            items = gisheh.recommendation_records_from_tmdb(
                [_item(81, "Cached")], parent
            )
        result = controller._apply_tmdb_recommendations(parent.id, 3, items)

        self.assertFalse(result)
        for item in items:
            self.assertIn(item.id, controller.records_by_id)
            self.assertNotIn(item.id, controller.library_ids)
        self.assertEqual(
            controller._tmdb_recommendations[parent.id],
            tuple(item.id for item in items),
        )

    def test_stale_generation_discards_results(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        controller.records_by_id = {parent.id: parent}
        controller._tmdb_detail_generations[parent.id] = 4
        with patch.object(tmdb_client, "cached_image", return_value=None):
            items = gisheh.recommendation_records_from_tmdb(
                [_item(91, "Stale")], parent
            )
        controller._apply_tmdb_recommendations(parent.id, 3, items)
        self.assertNotIn(items[0].id, controller.records_by_id)
        self.assertNotIn(parent.id, controller._tmdb_recommendations)

    def test_artwork_failure_is_contained(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        controller.records_by_id = {parent.id: parent}
        controller._tmdb_detail_generations[parent.id] = 1
        result = controller._apply_tmdb_recommendation_artwork(
            parent.id, 1, "missing-id", "/cache/poster.jpg"
        )

        self.assertFalse(result)

    def test_downloaded_artwork_is_immediately_used_by_the_card(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            item = gisheh.recommendation_records_from_tmdb(
                [_item(92, "Artwork")], parent
            )[0]
        controller.records_by_id = {parent.id: parent, item.id: item}
        controller._tmdb_detail_generations[parent.id] = 1
        controller.library_ids = {parent.id}
        controller.detail_record_id = None
        controller.selected_id = None

        controller._apply_tmdb_recommendation_artwork(
            parent.id, 1, item.id, "/cache/poster.jpg"
        )

        updated = controller.records_by_id[item.id]
        self.assertEqual(updated.poster_file, "/cache/poster.jpg")
        self.assertEqual(updated.artwork_file, "/cache/poster.jpg")

    def test_recommendation_click_opens_details(self) -> None:
        controller = _controller()
        parent = _parent("Movies")
        with patch.object(tmdb_client, "cached_image", return_value=None):
            items = gisheh.recommendation_records_from_tmdb(
                [_item(101, "Open me")], parent
            )
        item = items[0]
        controller.records_by_id = {parent.id: parent, item.id: item}
        calls: list[str] = []
        controller._update_details = lambda: calls.append("details")  # type: ignore[method-assign]
        controller._set_details_open = lambda value: calls.append(f"open={value}")  # type: ignore[method-assign]
        controller._load_tmdb_details_async = lambda record: calls.append(
            f"load={record.id}"
        )  # type: ignore[method-assign]
        controller._on_recommendation_clicked(item.id)
        self.assertEqual(controller.selected_id, item.id)
        self.assertEqual(calls, ["details", "open=True", f"load={item.id}"])

    def test_recommendation_click_with_unknown_id_is_ignored(self) -> None:
        controller = _controller()
        controller._on_recommendation_clicked("missing")
        self.assertIsNone(controller.selected_id)


class RecommendationRequestTests(unittest.TestCase):
    def test_movie_details_request_recommendations(self) -> None:
        with patch.object(tmdb_client, "request_json", return_value={}) as requester:
            tmdb_client.fetch_details("token", "movie", 10)
        params = requester.call_args.kwargs["params"]
        self.assertIn("recommendations", params["append_to_response"])
        self.assertEqual(requester.call_args.args[0], "/movie/10")

    def test_tv_details_request_recommendations(self) -> None:
        with patch.object(tmdb_client, "request_json", return_value={}) as requester:
            tmdb_client.fetch_details("token", "tv", 20)
        params = requester.call_args.kwargs["params"]
        self.assertIn("recommendations", params["append_to_response"])
        self.assertEqual(requester.call_args.args[0], "/tv/20")


if __name__ == "__main__":
    unittest.main()
