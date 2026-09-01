from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))

import tmdb_client


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

    def test_summary_is_fetched_from_tmdb_and_cached(self) -> None:
        payload = {"id": 42, "title": "TMDB title", "poster_path": "/p.jpg"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
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
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": temporary_directory},
                clear=False,
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

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
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


if __name__ == "__main__":
    unittest.main()
