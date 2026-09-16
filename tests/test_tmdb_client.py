from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh.services import tmdb_client


class TmdbClientTests(unittest.TestCase):
    def test_request_uses_bearer_authorization(self) -> None:
        response = BytesIO(b'{"success": true}')
        with patch.object(tmdb_client, "urlopen", return_value=response) as opener:
            payload = tmdb_client.request_json("/test", token="test-token")

        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertTrue(payload["success"])

    def test_environment_token_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "token"
            token_path.write_text("file-token\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "TMDB_READ_TOKEN": "environment-token",
                    "TMDB_TOKEN_FILE": str(token_path),
                },
                clear=False,
            ):
                self.assertEqual(tmdb_client.read_token(), "environment-token")

    def test_bundled_token_is_used_when_no_developer_override_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "missing-token"
            with (
                patch.dict(
                    os.environ,
                    {"TMDB_READ_TOKEN": "", "TMDB_TOKEN_FILE": str(token_path)},
                    clear=False,
                ),
                patch.object(
                    tmdb_client,
                    "BUNDLED_TMDB_READ_TOKEN",
                    "bundled-token",
                ),
            ):
                self.assertEqual(tmdb_client.read_token(), "bundled-token")
                self.assertEqual(tmdb_client.token_source(), "bundled")

    def test_store_token_uses_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "config" / "token"
            with patch.dict(
                os.environ,
                {"TMDB_READ_TOKEN": "", "TMDB_TOKEN_FILE": str(token_path)},
                clear=False,
            ):
                tmdb_client.store_token("stored-token")
                self.assertEqual(tmdb_client.read_token(), "stored-token")
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_clear_token_removes_only_the_stored_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "config" / "token"
            with patch.dict(
                os.environ,
                {"TMDB_READ_TOKEN": "", "TMDB_TOKEN_FILE": str(token_path)},
                clear=False,
            ):
                tmdb_client.store_token("stored-token")
                tmdb_client.clear_token()
                self.assertIsNone(tmdb_client.read_token())
                tmdb_client.clear_token()

    def test_clear_cache_removes_image_and_metadata_directories(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
            ),
        ):
            image = tmdb_client.cache_dir() / "poster.jpg"
            metadata = tmdb_client.metadata_cache_dir() / "movie-1.json"
            image.parent.mkdir(parents=True)
            metadata.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            metadata.write_text("{}", encoding="utf-8")

            tmdb_client.clear_cache()

            self.assertFalse(tmdb_client.cache_dir().exists())
            self.assertFalse(tmdb_client.metadata_cache_dir().exists())

    def test_fetch_explore_uses_expected_endpoints(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_request(
            path: str,
            *,
            token: str,
            params: dict[str, object] | None = None,
            timeout: float = 15,
        ) -> dict[str, object]:
            self.assertEqual(token, "test-token")
            self.assertEqual(timeout, 15)
            calls.append((path, params or {}))
            return {"results": [{"id": len(calls)}]}

        with patch.object(tmdb_client, "request_json", side_effect=fake_request):
            result = tmdb_client.fetch_explore("test-token")

        self.assertEqual(
            [path for path, _params in calls],
            ["/trending/movie/week", "/trending/tv/week", "/discover/tv"],
        )
        self.assertEqual(calls[2][1]["with_genres"], 16)
        self.assertEqual(len(result["Movies"]), 1)
        self.assertEqual(len(result["Shows"]), 1)
        self.assertEqual(len(result["Anime"]), 1)

    def test_fetch_explore_page_preserves_tmdb_pagination(self) -> None:
        with patch.object(
            tmdb_client,
            "request_json",
            return_value={
                "page": 3,
                "total_pages": 12,
                "results": [{"id": 31}, "invalid", {"id": 32}],
            },
        ) as requester:
            result = tmdb_client.fetch_explore_page("token", "Movies", 3)

        self.assertEqual(result["page"], 3)
        self.assertEqual(result["total_pages"], 12)
        self.assertEqual(result["results"], [{"id": 31}, {"id": 32}])
        requester.assert_called_once_with(
            "/trending/movie/week",
            token="token",
            params={"language": "en-US", "page": 3},
        )

    def test_search_titles_uses_tmdb_search_and_filters_anime(self) -> None:
        payload = {
            "page": 2,
            "total_pages": 7,
            "results": [
                {"id": 1, "name": "Animated", "genre_ids": [16, 18]},
                {"id": 2, "name": "Live action", "genre_ids": [18]},
            ],
        }
        with patch.object(
            tmdb_client,
            "request_json",
            return_value=payload,
        ) as requester:
            result = tmdb_client.search_titles_page(
                "token",
                "Anime",
                "  title  ",
                2,
            )

        requester.assert_called_once_with(
            "/search/tv",
            token="token",
            params={
                "query": "title",
                "include_adult": "false",
                "language": "en-US",
                "page": 2,
            },
        )
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["total_pages"], 7)
        self.assertEqual([item["id"] for item in result["results"]], [1])

    def test_details_request_includes_the_correct_certification_resource(self) -> None:
        with patch.object(
            tmdb_client,
            "request_json",
            return_value={},
        ) as requester:
            tmdb_client.fetch_details("token", "movie", 10)
            tmdb_client.fetch_details("token", "tv", 20)

        movie_params = requester.call_args_list[0].kwargs["params"]
        tv_params = requester.call_args_list[1].kwargs["params"]
        self.assertIn("release_dates", movie_params["append_to_response"])
        self.assertNotIn("content_ratings", movie_params["append_to_response"])
        self.assertIn("content_ratings", tv_params["append_to_response"])
        self.assertNotIn("release_dates", tv_params["append_to_response"])

    def test_episode_details_use_the_episode_specific_tmdb_endpoint(self) -> None:
        with patch.object(
            tmdb_client,
            "request_json",
            return_value={"id": 99, "name": "The Missing Episode"},
        ) as requester:
            payload = tmdb_client.fetch_episode_details("token", 20, 3, 6)

        self.assertEqual(payload["id"], 99)
        requester.assert_called_once_with(
            "/tv/20/season/3/episode/6",
            token="token",
            params={"language": "en-US"},
        )

    def test_season_details_use_the_season_level_tmdb_endpoint(self) -> None:
        with patch.object(
            tmdb_client,
            "request_json",
            return_value={"id": 99, "episodes": []},
        ) as requester:
            payload = tmdb_client.fetch_season_details("test-token", 20, 3)

        self.assertEqual(payload, {"id": 99, "episodes": []})
        requester.assert_called_once_with(
            "/tv/20/season/3",
            token="test-token",
            params={"language": "en-US"},
        )

    def test_empty_tmdb_search_does_not_make_a_request(self) -> None:
        with patch.object(tmdb_client, "request_json") as requester:
            result = tmdb_client.search_titles_page("token", "Movies", "   ")

        requester.assert_not_called()
        self.assertEqual(result, {"page": 1, "total_pages": 0, "results": []})

    def test_summary_is_fetched_from_tmdb_and_cached(self) -> None:
        payload = {"id": 42, "title": "TMDB title", "poster_path": "/p.jpg"}
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
            ),
            patch.object(
                tmdb_client,
                "request_json",
                return_value=payload,
            ) as requester,
        ):
            result = tmdb_client.fetch_summary("token", "movie", 42)
            cached = tmdb_client.load_summary("movie", 42)

        self.assertEqual(result, payload)
        self.assertEqual(cached, payload)
        requester.assert_called_once_with(
            "/movie/42",
            token="token",
            params={"language": "en-US"},
        )

    def test_cached_image_only_returns_complete_existing_file(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
            ),
        ):
            self.assertIsNone(tmdb_client.cached_image("/poster.jpg", size="w500"))
            destination = tmdb_client.cache_dir() / "w500-poster.jpg"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"image")
            self.assertEqual(
                tmdb_client.cached_image("/poster.jpg", size="w500"),
                str(destination),
            )

    def test_cache_image_uses_shared_pooled_transport(self) -> None:
        def download(url: str, destination: Path, **kwargs: object) -> bool:
            self.assertEqual(
                url,
                "https://image.tmdb.org/t/p/w500/poster.jpg",
            )
            self.assertEqual(kwargs["max_bytes"], 8 * 1024 * 1024)
            destination.write_bytes(b"image")
            return True

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
            ),
            patch.object(
                tmdb_client.image_http,
                "download",
                side_effect=download,
            ) as downloader,
        ):
            cached = tmdb_client.cache_image("/poster.jpg", size="w500")
        self.assertIsNotNone(cached)
        downloader.assert_called_once()

    def test_cache_youtube_thumbnail_uses_safe_cached_filename(self) -> None:
        def download(url: str, destination: Path, **kwargs: object) -> bool:
            self.assertEqual(url, "https://i.ytimg.com/vi/abc_123-XYZ/hqdefault.jpg")
            self.assertEqual(kwargs["max_bytes"], 4 * 1024 * 1024)
            destination.write_bytes(b"image")
            return True

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
            ),
            patch.object(
                tmdb_client.image_http,
                "download",
                side_effect=download,
            ),
        ):
            cached = tmdb_client.cache_youtube_thumbnail("abc_123-XYZ")
            self.assertEqual(
                cached,
                str(tmdb_client.cache_dir() / "youtube-abc_123-XYZ.jpg"),
            )
            self.assertEqual(
                tmdb_client.cached_youtube_thumbnail("abc_123-XYZ"),
                cached,
            )

        self.assertIsNone(tmdb_client.cache_youtube_thumbnail("../../unsafe"))


if __name__ == "__main__":
    unittest.main()
