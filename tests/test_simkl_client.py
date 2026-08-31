from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))

import simkl_client


class SimklClientTests(unittest.TestCase):
    def test_private_credentials_and_snapshot_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = {
                "XDG_CONFIG_HOME": f"{temporary_directory}/config",
                "XDG_CACHE_HOME": f"{temporary_directory}/cache",
                "SIMKL_CLIENT_ID": "",
                "SIMKL_ACCESS_TOKEN": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                client_path = simkl_client.store_client_id("client-id")
                token_path = simkl_client.store_token("access-token")
                snapshot_path = simkl_client.store_snapshot(
                    {"account": {"id": 7}},
                    {"total_mins": 42},
                    {"movies": []},
                )
                self.assertEqual(simkl_client.read_client_id(), "client-id")
                self.assertEqual(simkl_client.read_token(), "access-token")
                self.assertEqual(
                    simkl_client.load_snapshot(),
                    {
                        "settings": {"account": {"id": 7}},
                        "stats": {"total_mins": 42},
                        "library": {"movies": []},
                        "activities": {},
                    },
                )

            for path in (client_path, token_path, snapshot_path):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_environment_credentials_have_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = {
                "XDG_CONFIG_HOME": temporary_directory,
                "SIMKL_CLIENT_ID": "environment-client",
                "SIMKL_ACCESS_TOKEN": "environment-token",
            }
            with patch.dict(os.environ, environment, clear=False):
                self.assertEqual(
                    simkl_client.read_client_id(),
                    "environment-client",
                )
                self.assertEqual(simkl_client.read_token(), "environment-token")

    def test_request_adds_required_simkl_headers_and_query(self) -> None:
        response = BytesIO(b'{"movies": []}')
        with patch.object(simkl_client, "urlopen", return_value=response) as opener:
            payload = simkl_client._request_json(
                "/sync/all-items",
                client_id="client-id",
                token="access-token",
                params={"language": "en"},
            )

        request = opener.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["app-name"], [simkl_client.APP_NAME])
        self.assertEqual(query["app-version"], [simkl_client.APP_VERSION])
        self.assertEqual(query["language"], ["en"])
        self.assertEqual(request.get_header("Authorization"), "Bearer access-token")
        self.assertEqual(request.get_header("User-agent"), simkl_client.USER_AGENT)
        self.assertEqual(payload, {"movies": []})

    def test_settings_request_uses_post_without_exposing_token(self) -> None:
        response = BytesIO(b'{"account": {"id": 1}}')
        with patch.object(simkl_client, "urlopen", return_value=response) as opener:
            simkl_client.fetch_settings("client-id", "access-token")

        request = opener.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"{}")

        unauthorized = HTTPError("https://api.simkl.com", 401, "", {}, None)
        with patch.object(simkl_client, "urlopen", side_effect=unauthorized):
            with self.assertRaises(simkl_client.SimklError) as raised:
                simkl_client.fetch_settings("client-id", "secret-value")
        self.assertEqual(raised.exception.code, 401)
        self.assertNotIn("secret-value", str(raised.exception))

    def test_pin_response_is_validated(self) -> None:
        with patch.object(
            simkl_client,
            "_request_json",
            return_value={"result": "KO", "message": "Invalid client"},
        ):
            with self.assertRaisesRegex(simkl_client.SimklError, "Invalid client"):
                simkl_client.request_pin("client-id")

    def test_initial_library_fetches_types_sequentially(self) -> None:
        calls: list[str] = []

        def fake_request(path: str, **_kwargs: object) -> dict[str, object]:
            calls.append(path)
            group = path.rsplit("/", 1)[-1]
            return {group: [{"group": group}]}

        with patch.object(simkl_client, "_request_json", side_effect=fake_request):
            library = simkl_client.fetch_library("client-id", "access-token")

        self.assertEqual(
            calls,
            [
                "/sync/all-items/movies",
                "/sync/all-items/shows",
                "/sync/all-items/anime",
            ],
        )
        self.assertEqual(library["anime"], [{"group": "anime"}])

    def test_delta_merge_updates_and_reconciles_removed_items(self) -> None:
        movie = lambda simkl_id, title: {
            "movie": {"title": title, "ids": {"simkl": simkl_id}}
        }
        show = lambda simkl_id, title: {
            "show": {"title": title, "ids": {"simkl": simkl_id}}
        }
        current = {
            "movies": [movie(1, "Old title"), movie(2, "Removed")],
            "shows": [show(3, "Unchanged")],
            "anime": [],
        }
        delta = {
            "movies": [movie(1, "Updated title")],
            "shows": [show(4, "New")],
            "anime": [],
        }
        valid_ids = {
            "movies": {"1"},
            "shows": {"3", "4"},
            "anime": set(),
        }

        merged = simkl_client.merge_library(current, delta, valid_ids)

        self.assertEqual(
            [item["movie"]["title"] for item in merged["movies"]],
            ["Updated title"],
        )
        self.assertEqual(
            [item["show"]["title"] for item in merged["shows"]],
            ["Unchanged", "New"],
        )

    def test_removed_from_list_timestamp_gates_id_reconciliation(self) -> None:
        previous = {"movies": {"removed_from_list": "2026-08-01T00:00:00Z"}}
        unchanged = {"movies": {"removed_from_list": "2026-08-01T00:00:00Z"}}
        changed = {"movies": {"removed_from_list": "2026-08-02T00:00:00Z"}}
        self.assertFalse(simkl_client.removals_changed(previous, unchanged))
        self.assertTrue(simkl_client.removals_changed(previous, changed))


if __name__ == "__main__":
    unittest.main()
