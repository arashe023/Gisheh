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


if __name__ == "__main__":
    unittest.main()
