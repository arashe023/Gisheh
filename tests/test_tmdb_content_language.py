"""Tests for the TMDB content-language feature (system/manual/fallback)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gisheh.services import tmdb_client


def _clean_env(*names: str) -> dict[str, str | None]:
    return {name: None for name in names}


class TmdbContentLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        tmdb_client.set_content_language("system")
        self._patcher = patch.dict(os.environ, {}, clear=False)
        self._patcher.start()
        for name in (
            "GISHEH_TMDB_LANGUAGE",
            "GISHEH_LANGUAGE",
            "LANGUAGE",
            "LC_ALL",
            "LC_MESSAGES",
            "LANG",
        ):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        self._patcher.stop()
        tmdb_client.set_content_language("system")
        for name in ("GISHEH_TMDB_LANGUAGE", "GISHEH_LANGUAGE"):
            os.environ.pop(name, None)

    # 1. Default follows the OS language.
    def test_default_follows_system_language(self) -> None:
        with patch.dict(
            os.environ, {"LANG": "fa_IR.UTF-8", "LANGUAGE": ""}, clear=False
        ):
            self.assertEqual(tmdb_client.system_language(), "fa-IR")
            self.assertEqual(tmdb_client.active_language(), "fa-IR")
        with patch.dict(
            os.environ, {"LANG": "de_DE.UTF-8", "LANGUAGE": ""}, clear=False
        ):
            # Other system languages are preserved.
            self.assertEqual(tmdb_client.system_language(), "de-DE")
            self.assertEqual(tmdb_client.active_language(), "de-DE")

    def test_arbitrary_tmdb_languages_and_regions_are_preserved(self):
        for value, expected in (("de", "de"), ("pt_BR", "pt-BR"), ("ja", "ja"), ("en-GB", "en-GB"), ("ar", "ar")):
            with self.subTest(value=value):
                tmdb_client.set_content_language(value)
                self.assertEqual(tmdb_client.active_language(), expected)
                self.assertEqual(tmdb_client._effective_language(value), expected)
        self.assertEqual(tmdb_client.normalize_content_language("../../bad"), "en-US")

    def test_configuration_languages_are_cached_and_validated(self):
        payload = [
            {"iso_639_1": "ja", "english_name": "Japanese", "name": "日本語"},
            {"iso_639_1": "de", "english_name": "German", "name": "Deutsch"},
            {"iso_639_1": "fa", "english_name": "Persian", "name": "فارسی"},
            {"iso_639_1": "../", "name": "Invalid"},
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(tmdb_client, "cache_dir", return_value=Path(directory)), patch.object(tmdb_client, "request_json", return_value=payload) as request:
            result = tmdb_client.fetch_languages("token")
            request.assert_called_once_with("/configuration/languages", token="token", expect_list=True)
            self.assertEqual(set(dict(result)), {"ja", "de", "fa-IR"})
            self.assertIn("日本語", dict(result)["ja"])
            self.assertEqual(tmdb_client.cached_languages(), result)
            with patch.object(tmdb_client, "request_json", return_value={}), self.assertRaises(tmdb_client.TmdbError):
                tmdb_client.fetch_languages("token")
            self.assertEqual(tmdb_client.cached_languages(), result)

    def test_non_persian_language_uses_localized_images_and_english_fallback(self):
        self.assertEqual(tmdb_client.image_language_param("pt-BR"), "pt,en,null")
        self.assertEqual(tmdb_client.image_language_param("ja"), "ja,en,null")
        def response(_path, *, token, params):
            if params["language"] == "de":
                return {"id": 1, "title": "Deutsch", "overview": ""}
            return {"id": 1, "title": "English", "overview": "Fallback"}
        with patch.object(tmdb_client, "request_json", side_effect=response):
            result = tmdb_client.fetch_details("token", "movie", 1, language="de")
        self.assertEqual(result["title"], "Deutsch")
        self.assertEqual(result["overview"], "Fallback")

    # 2. Manual selection has priority over the OS language.
    def test_manual_selection_has_priority_over_system(self) -> None:
        with patch.dict(
            os.environ, {"LANG": "fa_IR.UTF-8", "LANGUAGE": ""}, clear=False
        ):
            tmdb_client.set_content_language("en-US")
            self.assertEqual(tmdb_client.active_language(), "en-US")
            tmdb_client.set_content_language("fa-IR")
            self.assertEqual(tmdb_client.active_language(), "fa-IR")
            tmdb_client.set_content_language("system")
            self.assertEqual(tmdb_client.active_language(), "fa-IR")

    # 3. English version is fetched when the translation is missing.
    def test_english_fallback_when_translation_missing(self) -> None:
        calls: list[str] = []

        def response(_path: str, *, token: str, params: dict) -> dict:
            calls.append(str(params.get("language")))
            if params.get("language") == "fa-IR":
                return {"id": 1, "title": "", "overview": ""}
            return {"id": 1, "title": "English", "overview": "EN overview"}

        with patch.object(tmdb_client, "request_json", side_effect=response):
            payload = tmdb_client.fetch_details(
                "token", "movie", 1, language="fa-IR"
            )
        self.assertEqual(calls, ["fa-IR", "en-US"])
        self.assertEqual(payload["title"], "English")
        self.assertEqual(payload["overview"], "EN overview")

    # 4. Fallback happens per field.
    def test_per_field_fallback_keeps_partial_translation(self) -> None:
        def response(_path: str, *, token: str, params: dict) -> dict:
            if params.get("language") == "fa-IR":
                return {"id": 1, "title": "عنوان فارسی", "overview": "   "}
            return {"id": 1, "title": "English", "overview": "EN overview"}

        with patch.object(tmdb_client, "request_json", side_effect=response):
            payload = tmdb_client.fetch_details(
                "token", "movie", 1, language="fa-IR"
            )
        self.assertEqual(payload["title"], "عنوان فارسی")
        self.assertEqual(payload["overview"], "EN overview")

    # 5. Existing translations are never replaced with English.
    def test_existing_translations_are_preserved(self) -> None:
        def response(_path: str, *, token: str, params: dict) -> dict:
            if params.get("language") == "fa-IR":
                return {
                    "id": 1,
                    "title": "عنوان فارسی",
                    "overview": "توضیح فارسی",
                    "original_title": "Original",
                }
            return {
                "id": 1,
                "title": "English",
                "overview": "EN",
                "original_title": "English Original",
            }

        with patch.object(
            tmdb_client, "request_json", side_effect=response
        ) as requester:
            payload = tmdb_client.fetch_details(
                "token", "movie", 1, language="fa-IR"
            )
        # Complete Persian payload needs no second request at all.
        self.assertEqual(requester.call_count, 1)
        self.assertEqual(payload["title"], "عنوان فارسی")
        self.assertEqual(payload["overview"], "توضیح فارسی")
        self.assertEqual(payload["original_title"], "Original")

    # 6. Correct behaviour for movie, tv, season, episode and person.
    def test_movie_tv_season_episode_and_person(self) -> None:
        seen: list[tuple[str, str]] = []

        def response(path: str, *, token: str, params: dict) -> dict:
            seen.append((path, str(params.get("language"))))
            language = params.get("language")
            if path.startswith("/person/"):
                if language == "fa-IR":
                    return {"id": 5, "name": "نام فارسی", "biography": ""}
                return {"id": 5, "name": "English Name", "biography": "EN bio"}
            if language == "fa-IR":
                return {"id": 7, "title": "فارسی", "name": "فارسی", "overview": ""}
            return {"id": 7, "title": "EN", "name": "EN", "overview": "EN overview"}

        with patch.object(tmdb_client, "request_json", side_effect=response):
            movie = tmdb_client.fetch_details("t", "movie", 7, language="fa-IR")
            tv = tmdb_client.fetch_details("t", "tv", 7, language="fa-IR")
            season = tmdb_client.fetch_season_details("t", 7, 1, language="fa-IR")
            episode = tmdb_client.fetch_episode_details("t", 7, 1, 2, language="fa-IR")
            person = tmdb_client.fetch_person_details("t", 5, language="fa-IR")

        self.assertEqual(movie["title"], "فارسی")
        self.assertEqual(movie["overview"], "EN overview")
        self.assertEqual(tv["name"], "فارسی")
        self.assertEqual(season["overview"], "EN overview")
        self.assertEqual(episode["overview"], "EN overview")
        # Person names are kept; only the empty biography falls back.
        self.assertEqual(person["name"], "نام فارسی")
        self.assertEqual(person["biography"], "EN bio")
        paths = [path for path, _ in seen]
        self.assertIn("/movie/7", paths)
        self.assertIn("/tv/7", paths)
        self.assertIn("/tv/7/season/1", paths)
        self.assertIn("/tv/7/season/1/episode/2", paths)
        self.assertIn("/person/5", paths)

    # 7. Cache is separated by language.
    def test_cache_is_separated_by_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary_directory}, clear=False
        ):
            english = tmdb_client.store_summary(
                "movie", 9, {"title": "EN"}, language="en-US"
            )
            persian = tmdb_client.store_summary(
                "movie", 9, {"title": "FA"}, language="fa-IR"
            )
            self.assertNotEqual(english, persian)
            self.assertEqual(
                tmdb_client.load_summary("movie", 9, language="en-US")["title"],
                "EN",
            )
            self.assertEqual(
                tmdb_client.load_summary("movie", 9, language="fa-IR")["title"],
                "FA",
            )

    # 8. Content updates immediately after the language changes (no restart).
    def test_immediate_update_after_language_change(self) -> None:
        used: list[str] = []

        def response(_path: str, *, token: str, params: dict) -> dict:
            used.append(str(params.get("language")))
            language = params.get("language")
            if language == "fa-IR":
                return {"id": 3, "title": "فارسی", "overview": "توضیح"}
            return {"id": 3, "title": "EN", "overview": "EN"}

        with patch.object(tmdb_client, "request_json", side_effect=response):
            tmdb_client.set_content_language("en-US")
            first = tmdb_client.fetch_summary("t", "movie", 3)
            # Switching the setting applies to the very next request.
            tmdb_client.set_content_language("fa-IR")
            second = tmdb_client.fetch_summary("t", "movie", 3)
        self.assertEqual(first["title"], "EN")
        self.assertEqual(second["title"], "فارسی")
        self.assertEqual(used[:2], ["en-US", "fa-IR"])

    # 9. Image and video language fallback.
    def test_image_and_video_language_fallback(self) -> None:
        def response(_path: str, *, token: str, params: dict) -> dict:
            self.assertEqual(
                params.get("include_image_language"), "fa,en,null"
            )
            if params.get("language") == "fa-IR":
                return {
                    "id": 11,
                    "title": "فارسی",
                    "overview": "توضیح",
                    "poster_path": "/fa.jpg",
                    "images": {
                        "posters": [
                            {"file_path": "/en.jpg", "iso_639_1": "en"},
                            {"file_path": "/none.jpg", "iso_639_1": None},
                            {"file_path": "/fa.jpg", "iso_639_1": "fa"},
                        ]
                    },
                    "videos": {"results": []},
                }
            return {
                "id": 11,
                "title": "EN",
                "overview": "EN",
                "videos": {
                    "results": [
                        {"id": "v1", "name": "Trailer", "key": "abc123"}
                    ]
                },
            }

        with patch.object(tmdb_client, "request_json", side_effect=response):
            payload = tmdb_client.fetch_details("t", "movie", 11, language="fa-IR")
        # Persian poster first, then English, then language-free.
        self.assertEqual(
            [item["file_path"] for item in payload["images"]["posters"]],
            ["/fa.jpg", "/en.jpg", "/none.jpg"],
        )
        self.assertEqual(payload["poster_path"], "/fa.jpg")
        # Empty Persian videos fall back to the English trailer.
        self.assertEqual(payload["videos"]["results"][0]["key"], "abc123")

    # 10. Network errors and invalid responses never break the whole page.
    def test_network_error_still_returns_english_fallback(self) -> None:
        def response(_path: str, *, token: str, params: dict) -> dict:
            if params.get("language") == "fa-IR":
                raise tmdb_client.TmdbError("boom")
            return {"id": 1, "title": "EN", "overview": "EN"}

        with patch.object(tmdb_client, "request_json", side_effect=response):
            payload = tmdb_client.fetch_details("t", "movie", 1, language="fa-IR")
        self.assertEqual(payload["title"], "EN")

        with patch.object(
            tmdb_client,
            "request_json",
            side_effect=tmdb_client.TmdbError("down"),
        ), self.assertRaises(tmdb_client.TmdbError):
            tmdb_client.fetch_details("t", "movie", 1, language="en-US")

    def test_whitespace_and_empty_arrays_count_as_missing(self) -> None:
        self.assertTrue(tmdb_client.is_missing_translation(None))
        self.assertTrue(tmdb_client.is_missing_translation(""))
        self.assertTrue(tmdb_client.is_missing_translation("   "))
        self.assertTrue(tmdb_client.is_missing_translation([]))
        self.assertFalse(tmdb_client.is_missing_translation("فارسی"))
        self.assertFalse(tmdb_client.is_missing_translation(["Drama"]))


if __name__ == "__main__":
    unittest.main()
