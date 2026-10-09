from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
SAMPLE_DATA = Path(__file__).resolve().parent / "fixtures/library.json"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import state_store
from gisheh import window as gisheh
from gisheh.services import simkl_client, tmdb_client


class LibraryModeStateTests(unittest.TestCase):
    def test_first_run_has_no_mode_until_tour_is_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state.json"
            self.assertIsNone(state_store.selected_library_mode(destination))

            state_store.save_library_mode(
                state_store.LIBRARY_MODE_LOCAL,
                destination,
            )

            self.assertEqual(
                state_store.selected_library_mode(destination),
                state_store.LIBRARY_MODE_LOCAL,
            )

    def test_mode_write_preserves_existing_state_and_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "profile" / "state.json"
            state_store.write_state({"bookmarks": ["tmdb-movie-20"]}, destination)
            state_store.save_library_mode(
                state_store.LIBRARY_MODE_SIMKL,
                destination,
            )

            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(payload["bookmarks"], ["tmdb-movie-20"])
            self.assertTrue(payload["onboardingComplete"])
            self.assertEqual(payload["preferences"]["libraryMode"], "simkl")
            self.assertEqual(
                stat.S_IMODE(destination.stat().st_mode),
                0o600,
            )

    def test_invalid_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            state_store.save_library_mode("cloud")


class LocalFirstLibraryTests(unittest.TestCase):
    def test_new_profile_starts_without_sample_library_or_profile_totals(self) -> None:
        records, explore, totals = gisheh.load_catalog()

        self.assertEqual(records, ())
        self.assertEqual(explore, ())
        self.assertEqual(
            totals,
            {
                media_type: {status: 0 for status in gisheh.COLLECTION_NAMES}
                for media_type in gisheh.MEDIA_TYPES
            },
        )

        controller = object.__new__(gisheh.GishehWindow)
        controller.records = records
        controller.completed = set()
        controller.ratings = {}
        controller.episode_watched_at = {}
        controller.title_watched_at = {}
        controller.simkl_stats = {}

        stats = controller._profile_stats()

        self.assertEqual(stats["watched_records"], ())
        self.assertEqual(stats["movie_count"], 0)
        self.assertEqual(stats["episode_count"], 0)
        self.assertEqual(stats["total_minutes"], 0)
        self.assertEqual(stats["rating_count"], 0)
        self.assertFalse(stats["genres"])
        self.assertFalse(stats["activity"])

    def test_factory_reset_removes_state_credentials_caches_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_home = root / "config"
            cache_home = root / "cache"
            state_home = root / "state"
            state_file = state_home / "profile" / "state.json"
            environment = {
                "XDG_CONFIG_HOME": str(config_home),
                "XDG_CACHE_HOME": str(cache_home),
                "XDG_STATE_HOME": str(state_home),
                "TMDB_TOKEN_FILE": str(config_home / "tmdb-token"),
            }
            with (
                patch.dict(gisheh.os.environ, environment, clear=False),
                patch.object(simkl_client, "_clear_keyring_token", return_value=True),
                patch.object(gisheh, "clear_desktop_preferences"),
            ):
                state_store.write_state({"bookmarks": ["one"]}, state_file)
                tmdb_client.store_token("developer-token")
                (tmdb_client.cache_dir() / "poster.jpg").parent.mkdir(parents=True)
                (tmdb_client.cache_dir() / "poster.jpg").write_bytes(b"poster")
                (tmdb_client.metadata_cache_dir() / "movie.json").parent.mkdir(
                    parents=True
                )
                (tmdb_client.metadata_cache_dir() / "movie.json").write_text(
                    "{}", encoding="utf-8"
                )
                simkl_client.config_dir().mkdir(parents=True)
                simkl_client.token_file().write_text("token", encoding="utf-8")
                simkl_client.client_id_file().write_text("client", encoding="utf-8")
                simkl_client.cache_dir().mkdir(parents=True)
                simkl_client.snapshot_file().write_text("{}", encoding="utf-8")
                simkl_client.calendar_cache_dir().mkdir(parents=True)
                (simkl_client.calendar_cache_dir() / "calendar.json").write_text(
                    "{}", encoding="utf-8"
                )
                log_file = gisheh.application_log_file()
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_file.write_text("log", encoding="utf-8")

                gisheh.clear_all_user_data(state_file)

                self.assertFalse(state_file.exists())
                self.assertFalse(tmdb_client.token_file().exists())
                self.assertFalse(tmdb_client.cache_dir().exists())
                self.assertFalse(tmdb_client.metadata_cache_dir().exists())
                self.assertFalse(simkl_client.token_file().exists())
                self.assertFalse(simkl_client.client_id_file().exists())
                self.assertFalse(simkl_client.cache_dir().exists())
                self.assertFalse(simkl_client.calendar_cache_dir().exists())
                self.assertFalse(log_file.exists())

    def test_factory_reset_restart_replaces_the_current_process(self) -> None:
        with (
            patch.object(simkl_client, "close_image_http_client") as close_client,
            patch.object(gisheh.os, "execvpe") as exec_process,
        ):
            gisheh.GishehWindow._restart_application()

        close_client.assert_called_once_with()
        exec_process.assert_called_once()
        executable, arguments, environment = exec_process.call_args.args
        self.assertEqual(executable, gisheh.sys.executable)
        self.assertEqual(arguments[:3], [gisheh.sys.executable, "-m", "gisheh.main"])
        self.assertIn("PYTHONPATH", environment)

    def test_restart_preserves_system_locale(self) -> None:
        with (
            patch.dict(gisheh.os.environ, {"LANGUAGE": "de"}, clear=True),
            patch.object(simkl_client, "close_image_http_client"),
            patch.object(gisheh.os, "execvpe") as exec_process,
        ):
            gisheh.GishehWindow._restart_application()
        environment = exec_process.call_args.args[2]
        self.assertEqual(environment["LANGUAGE"], "de")
        self.assertNotIn("GISHEH_LANGUAGE", environment)

    @staticmethod
    def _controller() -> tuple[gisheh.GishehWindow, gisheh.TitleRecord]:
        records, explore, _totals = gisheh.load_catalog(sample_data_path=SAMPLE_DATA)
        record = explore[0]
        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.records = records
        controller.explore_records = explore
        controller.explore_search_records = ()
        controller.library_ids = {item.id for item in records}
        controller.explore_ids = {item.id for item in explore}
        controller.records_by_id = {item.id: item for item in (*records, *explore)}
        controller.bookmarks = set()
        controller.completed = set()
        controller.ratings = {}
        controller.status_overrides = {}
        controller.local_library_records = {}
        controller._tmdb_record_aliases = {}
        controller._library_records_by_canonical = {item.id: item for item in records}
        controller.toasts = []
        controller._toast = controller.toasts.append
        return controller, record

    def test_local_watchlist_never_calls_simkl_and_promotes_full_record(self) -> None:
        controller, record = self._controller()
        saved: list[str] = []

        def apply() -> None:
            canonical = controller._canonical_record_id(record)
            controller.bookmarks.add(canonical)
            controller._save_user_state = lambda: saved.append("saved")
            controller._save_user_state()

        with patch.object(simkl_client, "set_list_status") as remote_write:
            controller._write_simkl_list_change(
                record,
                adding=True,
                on_success=apply,
            )

        canonical = controller._canonical_record_id(record)
        remote_write.assert_not_called()
        self.assertIn(canonical, controller.bookmarks)
        self.assertIn(canonical, controller.local_library_records)
        self.assertEqual(saved, ["saved"])
        self.assertTrue(any("local" in toast.lower() for toast in controller.toasts))

    def test_local_record_round_trip_preserves_catalog_identity(self) -> None:
        _controller, record = self._controller()
        restored = gisheh.TitleRecord.from_mapping(
            gisheh.title_record_to_mapping(record)
        )

        self.assertEqual(restored.id, record.id)
        self.assertEqual(restored.title, record.title)
        self.assertEqual(restored.media_type, record.media_type)
        self.assertEqual(restored.tmdb_id, record.tmdb_id)
        self.assertEqual(restored.poster_file, record.poster_file)
        self.assertEqual(restored.seasons, record.seasons)

    def test_saved_local_title_is_restored_into_library_after_restart(self) -> None:
        controller, record = self._controller()
        canonical = controller._ensure_local_library_record(record)
        controller.bookmarks.add(canonical)
        controller.favorites = set()
        controller.episode_status_overrides = {}
        controller.episode_watched_at = {}
        controller.title_watched_at = {}
        controller.color_scheme = "system"
        controller.auto_sync = False
        controller.auto_calendar_refresh = False
        controller.default_media = "Movies"
        controller.preferred_view_mode = "list"

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state.json"
            controller.state_file = destination
            controller._save_user_state()

            # A later cloud session may replace the active state, but must not
            # overwrite the independently owned Local-first profile.
            controller.library_mode = gisheh.LIBRARY_MODE_SIMKL
            controller.bookmarks = set()
            controller.completed = set()
            controller.ratings = {}
            controller.status_overrides = {}
            controller._save_user_state()
            cloud_payload = state_store.read_state(destination)
            self.assertTrue(cloud_payload["localLibrary"])
            self.assertIn(canonical, cloud_payload["localProfile"]["bookmarks"])
            state_store.save_library_mode(
                gisheh.LIBRARY_MODE_LOCAL,
                destination,
            )

            records, explore, _totals = gisheh.load_catalog(
                sample_data_path=SAMPLE_DATA
            )
            reader = object.__new__(gisheh.GishehWindow)
            reader.state_file = destination
            reader.library_mode = gisheh.LIBRARY_MODE_LOCAL
            reader.records = records
            reader.explore_records = explore
            reader.explore_search_records = ()
            reader.library_ids = {item.id for item in records}
            reader.records_by_id = {item.id: item for item in (*records, *explore)}
            reader._tmdb_record_aliases = {}
            reader._library_records_by_canonical = {item.id: item for item in records}
            reader.local_library_records = {}
            reader.simkl_token = None
            reader.simkl_connected = False
            reader.bookmarks = set()
            reader.favorites = set()
            reader.completed = set()
            reader.ratings = {}
            reader.status_overrides = {}
            reader.episode_status_overrides = {}
            reader.episode_watched_at = {}
            reader.title_watched_at = {}
            reader.color_scheme = "dark"
            reader.auto_sync = True
            reader.auto_calendar_refresh = True
            reader.default_media = "Anime"
            reader.preferred_view_mode = "grid"
            reader.active_media = "Anime"
            reader.view_mode = "grid"

            reader._load_user_state()

        self.assertIn(canonical, reader.local_library_records)
        self.assertIn(canonical, reader.library_ids)
        self.assertIn(canonical, reader.bookmarks)
        self.assertEqual(reader.records_by_id[canonical].title, record.title)

    def test_local_mode_refuses_background_simkl_sync(self) -> None:
        controller = object.__new__(gisheh.GishehWindow)
        controller.library_mode = gisheh.LIBRARY_MODE_LOCAL
        controller.simkl_client_id = "client"
        controller.simkl_token = "token"

        with patch.object(gisheh.GishehWindow, "_start_worker") as worker:
            controller._start_simkl_sync()

        worker.assert_not_called()


class WelcomeTourStructureTests(unittest.TestCase):
    def test_tour_has_two_steps(self) -> None:
        onboarding = (
            Path(__file__).resolve().parents[1] / "src/gisheh/onboarding.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._page_index = min(1", onboarding)
        self.assertIn("self._page_index < 1", onboarding)
        self.assertNotIn("self._page_index < 2", onboarding)

    def test_tour_explains_both_modes_without_a_main_menu_entry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        onboarding = (root / "src/gisheh/onboarding.py").read_text(encoding="utf-8")
        application = (root / "src/gisheh/application.py").read_text(encoding="utf-8")
        window = (root / "src/gisheh/window.py").read_text(encoding="utf-8")

        self.assertIn("Welcome to Gisheh", onboarding)
        self.assertIn("Local-first", onboarding)
        self.assertIn("Sync with Simkl", onboarding)
        self.assertIn("Adw.Carousel()", onboarding)
        self.assertIn("selected_library_mode()", application)
        self.assertNotIn('menu.append("Welcome Tour", "app.tour")', window)

    def test_tour_uses_bundled_svg_icons_and_body_copy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        onboarding = (root / "src/gisheh/onboarding.py").read_text(encoding="utf-8")
        resources = (
            root / "src/gisheh/io.github.arashe023.Gisheh.gresource.xml"
        ).read_text(encoding="utf-8")

        for emoji in ("🎬", "🔒", "✅", "💾", "☁️"):
            self.assertNotIn(emoji, onboarding)
        for asset in (
            "welcome-media.svg",
            "welcome-privacy.svg",
            "welcome-local.svg",
            "welcome-sync.svg",
        ):
            self.assertIn(asset, resources)
            self.assertTrue((root / "src/gisheh/assets" / asset).is_file())

        self.assertIn("Gtk.Image.new_from_resource", onboarding)
        self.assertNotIn("def _feature_row", onboarding)
        self.assertNotIn("welcome-feature-emoji", onboarding)
        self.assertNotIn("ONE CHOICE BEFORE YOU START", onboarding)
        self.assertIn("Browse with TMDB metadata, track titles", onboarding)
        self.assertIn("Before you start, choose where Gisheh should save", onboarding)

    def test_simkl_choice_requires_pin_authorization_before_completion(self) -> None:
        onboarding = (
            Path(__file__).resolve().parents[1] / "src/gisheh/onboarding.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"Continue to Simkl sign in"', onboarding)
        self.assertIn("GLib.idle_add(self._start_simkl_sign_in)", onboarding)
        self.assertIn("simkl_client.request_pin(client_id)", onboarding)
        self.assertIn("simkl_client.poll_pin(client_id, user_code)", onboarding)
        self.assertIn("simkl_client.store_token(access_token)", onboarding)
        self.assertIn("self._on_complete(LIBRARY_MODE_SIMKL)", onboarding)
        self.assertLess(
            onboarding.index("simkl_client.store_token(access_token)"),
            onboarding.index(
                "self._on_complete(LIBRARY_MODE_SIMKL)",
                onboarding.index("def _on_simkl_authorized"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
