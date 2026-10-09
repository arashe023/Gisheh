from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import httpx
from gisheh.services import image_http, tmdb_client


class NetworkFailureTests(unittest.TestCase):
    def test_images_retry_transient_errors_and_keep_existing_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image"
            path.write_bytes(b"old")
            client = Mock()
            client.get.side_effect = [
                httpx.ConnectTimeout("offline"),
                httpx.Response(429),
                httpx.Response(200, content=b"new"),
            ]
            self.assertTrue(
                image_http.download(
                    "https://example.invalid/image",
                    path,
                    client=client,
                    retry_delays=(0, 0, 0),
                )
            )
            self.assertEqual(path.read_bytes(), b"new")
            client.get.side_effect = [httpx.Response(401)]
            self.assertFalse(
                image_http.download(
                    "https://example.invalid/image",
                    path,
                    client=client,
                    retry_delays=(0,),
                )
            )
            self.assertEqual(path.read_bytes(), b"new")

    def test_tmdb_auth_rate_limit_timeout_and_invalid_json_are_reported(self):
        for response in (
            httpx.Response(401),
            httpx.Response(429),
            httpx.Response(200, content=b"not json"),
        ):
            with (
                self.subTest(response=response.status_code),
                patch.object(image_http, "get_client") as client,
            ):
                client.return_value.get.return_value = response
                with self.assertRaises(tmdb_client.TmdbError):
                    tmdb_client.request_json("/movie/1", token="test")
        with patch.object(image_http, "get_client") as client:
            client.return_value.get.side_effect = httpx.ConnectTimeout("offline")
            with self.assertRaises(tmdb_client.TmdbError):
                tmdb_client.request_json("/movie/1", token="test")
