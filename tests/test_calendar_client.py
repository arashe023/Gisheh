from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from gisheh.services import simkl_client
from gisheh.window import CALENDAR_TIMELINE_PAGE_SIZE, GishehWindow


class CalendarHeaderSimplificationTests(unittest.TestCase):
    """The calendar header keeps only month navigation and refresh."""

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        import gisheh.window as window_module

        return Path(window_module.__file__).read_text(encoding="utf-8")

    def test_scope_switcher_and_filters_are_removed(self) -> None:
        source = self._source()
        for removed in (
            "calendar_scope_switcher",
            "calendar_media_dropdown",
            "calendar_filter_button",
            "calendar_watched_check",
            "calendar_dropped_check",
            "calendar_scope",
            "calendar_media_filter",
            "calendar_include_watched",
            "calendar_include_dropped",
            "_on_calendar_scope_changed",
            "_on_calendar_media_changed",
            "_on_calendar_filter_changed",
            'label=_("My Calendar")',
            "Browse / Simkl",
            "Show watched",
            "Show dropped",
        ):
            self.assertNotIn(removed, source)

    def test_month_navigation_and_refresh_remain(self) -> None:
        source = self._source()
        for kept in (
            "calendar_previous_button",
            "calendar_today_button",
            "calendar_next_button",
            "calendar_refresh_button",
            "_on_calendar_previous",
            "_on_calendar_today",
            "_on_calendar_next",
            "_start_calendar_refresh",
        ):
            self.assertIn(kept, source)

TV_PAYLOAD = {
    "calendar": [
        {
            "simkl_id": 3437,
            "date": "2026-07-20T23:30:00Z",
            "finale_type": 2,
            "episode": {
                "season": 15,
                "episode": 10,
                "title": "Propane Recall",
                "url": "https://simkl.com/episode/10",
            },
        }
    ],
    "metadata": {
        "3437": {
            "title": "King of the Hill",
            "url": "/tv/3437/king-of-the-hill",
            "poster": "12/example",
            "ids": {"simkl_id": 3437, "tmdb": "1434", "tvdb": "73141"},
            "ratings": {"simkl": {"rating": 8.1}},
        }
    },
}


class CalendarUrlTests(unittest.TestCase):
    def test_rolling_urls_are_v2_and_have_required_parameters(self) -> None:
        expected = {
            "movies": "movie_release.json",
            "shows": "tv.json",
            "anime": "anime.json",
        }
        for media, filename in expected.items():
            with self.subTest(media=media):
                url = simkl_client.calendar_url(media, client_id="client")
                parsed = urlsplit(url)
                self.assertEqual(parsed.path, f"/calendar/v2/{filename}")
                self.assertEqual(
                    parse_qs(parsed.query),
                    {
                        "client_id": ["client"],
                        "app-name": ["gisheh"],
                        "app-version": [simkl_client.APP_VERSION],
                    },
                )

    def test_monthly_url_uses_simkl_unpadded_month_segment(self) -> None:
        url = simkl_client.calendar_url("shows", 2026, 7, client_id="client")
        self.assertIn("/calendar/v2/2026/7/tv.json?", url)


class CalendarParsingTests(unittest.TestCase):
    def test_tv_metadata_join_episode_and_timezone_day_shift(self) -> None:
        snapshot = simkl_client.parse_calendar_payload(
            TV_PAYLOAD, "shows", display_timezone="Asia/Tokyo"
        )
        self.assertEqual(len(snapshot.titles), 1)
        event = snapshot.events[0]
        self.assertEqual(event.title.title, "King of the Hill")
        self.assertEqual(event.title.tmdb_id, 1434)
        self.assertEqual(event.season, 15)
        self.assertEqual(event.episode_number, 10)
        self.assertEqual(event.finale_label, "Season finale")
        self.assertEqual(event.utc_datetime.date().isoformat(), "2026-07-20")
        self.assertEqual(event.local_datetime.date().isoformat(), "2026-07-21")

    def test_anime_without_season_and_movie_without_episode(self) -> None:
        anime = {
            "calendar": [
                {
                    "simkl_id": 1,
                    "date": "2026-01-01T00:00:00Z",
                    "finale_type": 3,
                    "episode": {"episode": 12, "title": "Final", "url": "x"},
                }
            ],
            "metadata": {
                "1": {
                    "title": "Anime",
                    "ids": {"simkl_id": 1, "mal": 9},
                    "ratings": {"simkl": {}},
                    "anime_type": "tv",
                }
            },
        }
        movie = {
            "calendar": [
                {
                    "simkl_id": 2,
                    "date": "2026-01-02T00:00:00Z",
                    "finale_type": None,
                }
            ],
            "metadata": {
                "2": {
                    "title": "Movie",
                    "ids": {"simkl_id": 2},
                    "ratings": {"simkl": {}},
                    "dvd_date": "02/03/2026",
                }
            },
        }
        anime_event = simkl_client.parse_calendar_payload(anime, "anime").events[0]
        movie_event = simkl_client.parse_calendar_payload(movie, "movies").events[0]
        self.assertIsNone(anime_event.season)
        self.assertEqual(anime_event.episode_number, 12)
        self.assertEqual(anime_event.finale_label, "Series finale")
        self.assertIsNone(movie_event.episode)
        self.assertEqual(movie_event.title.dvd_date, "02/03/2026")

    def test_sparse_metadata_null_date_and_orphan_are_safe(self) -> None:
        payload = {
            "calendar": [
                {"simkl_id": 1, "date": None, "finale_type": 1},
                {"simkl_id": 999, "date": "bad", "finale_type": 2},
            ],
            "metadata": {"1": {"title": "Sparse", "ids": {}}},
        }
        with self.assertLogs(simkl_client.LOGGER, level="WARNING"):
            snapshot = simkl_client.parse_calendar_payload(payload, "shows")
        self.assertEqual(len(snapshot.events), 1)
        self.assertIsNone(snapshot.events[0].utc_datetime)
        self.assertEqual(snapshot.events[0].title.genres, ())

    def test_all_finale_types(self) -> None:
        payload = {
            "calendar": [
                {
                    "simkl_id": value,
                    "date": "2026-01-01T00:00:00Z",
                    "finale_type": value,
                }
                for value in (1, 2, 3)
            ],
            "metadata": {
                str(value): {"title": str(value), "ids": {"simkl_id": value}}
                for value in (1, 2, 3)
            },
        }
        labels = [
            event.finale_label
            for event in simkl_client.parse_calendar_payload(payload, "shows").events
        ]
        self.assertEqual(
            labels, ["Mid-season finale", "Season finale", "Series finale"]
        )

    def test_merge_keeps_all_episodes_but_only_one_title(self) -> None:
        second = json.loads(json.dumps(TV_PAYLOAD))
        second["calendar"][0]["episode"]["episode"] = 11
        second["calendar"][0]["date"] = "2026-07-21T23:30:00Z"
        merged = simkl_client.merge_calendar_snapshots(
            [
                simkl_client.parse_calendar_payload(TV_PAYLOAD, "shows"),
                simkl_client.parse_calendar_payload(second, "shows"),
            ]
        )
        self.assertEqual(len(merged.events), 2)
        self.assertEqual(len(merged.titles), 1)


class CalendarIdentityAndFilterTests(unittest.TestCase):
    @staticmethod
    def record(record_id: str, *, tmdb_id: int | None, status: str):
        return SimpleNamespace(
            id=record_id,
            tmdb_id=tmdb_id,
            tmdb_media_type="tv",
            simkl_id=(3437 if record_id.startswith("simkl-") else None),
            imdb_id="tt0118375",
            tvdb_id=73141,
            mal_id=None,
            media_type="Shows",
            status=status,
            title="King of the Hill",
        )

    def controller(self):
        controller = GishehWindow.__new__(GishehWindow)
        library = self.record("simkl-shows-3437", tmdb_id=1434, status="Watching")
        explore = self.record("tmdb-tv-1434", tmdb_id=1434, status="Watchlist")
        controller.records = (library,)
        controller.explore_records = (explore,)
        controller.records_by_id = {library.id: library, explore.id: explore}
        controller.library_ids = {library.id}
        controller._tmdb_record_aliases = {("tv", 1434): library.id}
        controller._library_records_by_canonical = {library.id: library}
        controller.bookmarks = set()
        controller.completed = set()
        controller.status_overrides = {}
        controller.calendar_snapshot = simkl_client.parse_calendar_payload(
            TV_PAYLOAD, "shows", display_timezone=timezone.utc
        )
        controller.calendar_month = date(2026, 7, 1)
        return controller, library, explore

    def test_simkl_identity_wins_and_my_calendar_includes_watching(self) -> None:
        controller, library, _explore = self.controller()
        event = controller.calendar_snapshot.events[0]
        self.assertIs(controller._calendar_record(event), library)
        self.assertEqual(controller._calendar_events(), (event,))

    def test_tmdb_fallback_uses_canonical_library_alias(self) -> None:
        controller, library, _explore = self.controller()
        controller.records_by_id.pop(library.id)
        event = controller.calendar_snapshot.events[0]
        self.assertIs(controller._calendar_record(event), library)

    def test_external_id_fallback_matches_library_record(self) -> None:
        controller, library, _explore = self.controller()
        controller.records_by_id = {}
        controller._tmdb_record_aliases = {}
        library.simkl_id = None
        library.id = "legacy-library-title"
        source = controller.calendar_snapshot.events[0]
        event = replace(source, title=replace(source.title, tmdb_id=None))
        self.assertIs(controller._calendar_record(event), library)

    def test_watched_and_dropped_are_always_hidden(self) -> None:
        controller, library, _explore = self.controller()
        controller.status_overrides[library.id] = "Watched"
        self.assertEqual(controller._calendar_events(), ())
        controller.status_overrides[library.id] = "Dropped"
        self.assertEqual(controller._calendar_events(), ())
        self.assertFalse(hasattr(controller, "calendar_include_watched"))
        self.assertFalse(hasattr(controller, "calendar_include_dropped"))

    def test_title_outside_library_is_hidden_from_my_calendar(self) -> None:
        controller, _library, explore = self.controller()
        controller.records = ()
        controller.records_by_id = {explore.id: explore}
        controller.library_ids = set()
        controller._library_records_by_canonical = {}
        controller._tmdb_record_aliases = {}
        self.assertEqual(controller._calendar_events(), ())

    def test_timeline_groups_events_by_local_day_in_chronological_order(self) -> None:
        controller, _library, _explore = self.controller()
        original = controller.calendar_snapshot.events[0]
        earlier = replace(
            original,
            simkl_id=2,
            local_datetime=datetime(2026, 7, 19, 21, 0, tzinfo=timezone.utc),
        )
        later_same_day = replace(
            original,
            simkl_id=3,
            local_datetime=datetime(2026, 7, 20, 23, 45, tzinfo=timezone.utc),
        )
        groups = controller._calendar_events_by_day((later_same_day, original, earlier))
        self.assertEqual(
            [day for day, _events in groups], [date(2026, 7, 19), date(2026, 7, 20)]
        )
        self.assertEqual(groups[1][1], (original, later_same_day))

    def test_timeline_day_heading_has_relative_date_week_and_weekday(self) -> None:
        heading = GishehWindow._calendar_day_heading(
            date(2026, 9, 5), today=date(2026, 9, 5)
        )
        self.assertEqual(
            heading,
            "Today • September 5, 2026 • Week 36 • Saturday",
        )

    def test_timeline_pagination_never_splits_a_day_group(self) -> None:
        controller, _library, _explore = self.controller()
        event = controller.calendar_snapshot.events[0]
        groups = (
            (date(2026, 7, 20), (event,) * 80),
            (date(2026, 7, 21), (event,) * 60),
            (date(2026, 7, 22), (event,) * 10),
        )
        visible, shown = controller._calendar_timeline_page(groups, 120)
        self.assertEqual(visible, groups[:2])
        self.assertEqual(shown, 140)

    def test_timeline_event_opens_local_details_before_simkl_url(self) -> None:
        controller, library, _explore = self.controller()
        event = controller.calendar_snapshot.events[0]
        opened: list[object] = []
        controller._open_calendar_record = opened.append
        controller._open_calendar_uri = lambda uri: opened.append(uri)
        controller._open_calendar_event(event)
        self.assertEqual(opened, [library])

    def test_timeline_row_reuses_library_list_card_styles(self) -> None:
        from gi.repository import Gtk

        controller, _library, _explore = self.controller()
        event = controller.calendar_snapshot.events[0]
        controller._calendar_record = lambda _event: None
        controller._calendar_poster_overlay = lambda _title, _width, _height: (
            Gtk.Overlay()
        )
        controller._simkl_writable = lambda: False
        row = controller._calendar_event_row(event)
        self.assertIn("movie-row-content", row.get_css_classes())
        copy = row.get_first_child().get_next_sibling()
        title = copy.get_first_child().get_next_sibling()
        self.assertIn("title-3", title.get_css_classes())

    def test_month_navigation_supersedes_an_inflight_refresh(self) -> None:
        controller, _library, _explore = self.controller()
        controller._calendar_refresh_inflight = True
        controller._calendar_generation = 4
        controller.calendar_snapshot = object()
        controller.calendar_timeline_limit = 999
        refreshes: list[tuple[bool, bool]] = []

        def start_refresh(force: bool = False, *, supersede: bool = False) -> bool:
            refreshes.append((force, supersede))
            return False

        controller._start_calendar_refresh = start_refresh
        controller._on_calendar_next(mock.Mock())

        self.assertEqual(controller.calendar_month, date(2026, 8, 1))
        self.assertEqual(controller.calendar_selected_date, date(2026, 8, 1))
        self.assertIsNone(controller.calendar_snapshot)
        self.assertEqual(
            controller.calendar_timeline_limit, CALENDAR_TIMELINE_PAGE_SIZE
        )
        self.assertEqual(refreshes, [(False, True)])

    def test_superseding_refresh_invalidates_old_generation_and_starts_new_worker(
        self,
    ) -> None:
        controller, _library, _explore = self.controller()
        controller._calendar_refresh_inflight = True
        controller._calendar_generation = 4
        controller.library_mode = "simkl"
        controller.active_destination = "calendar"
        controller.simkl_client_id = "client"
        controller.simkl_settings = {}
        controller.calendar_refresh_button = mock.Mock()

        with mock.patch.object(GishehWindow, "_start_worker") as thread:
            result = controller._start_calendar_refresh(False, supersede=True)

        self.assertFalse(result)
        self.assertTrue(controller._calendar_refresh_inflight)
        self.assertEqual(controller._calendar_generation, 6)
        controller.calendar_refresh_button.set_sensitive.assert_called_once_with(False)
        controller.calendar_refresh_button.set_icon_name.assert_called_once_with(
            "process-working-symbolic"
        )
        thread.assert_called_once()
        self.assertEqual(thread.call_args.args[0], "simkl-calendar")


class CalendarCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            "os.environ", {"XDG_CACHE_HOME": self.temporary.name}
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temporary.cleanup()

    def test_cache_round_trip_is_atomic_and_calendar_only_clear(self) -> None:
        path = simkl_client.store_calendar_cache(
            "shows",
            TV_PAYLOAD,
            source_url="https://example/calendar",
            fetched_at=datetime.now(timezone.utc),
            last_modified="stamp",
            year=2026,
            month=7,
        )
        self.assertTrue(path.is_file())
        self.assertFalse(any(path.parent.glob("*.tmp*")))
        loaded = simkl_client.load_calendar_cache("shows", year=2026, month=7)
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded[0].from_cache)
        account_file = simkl_client.cache_dir() / "snapshot.json"
        account_file.parent.mkdir(parents=True, exist_ok=True)
        account_file.write_text("{}")
        simkl_client.clear_calendar_cache()
        self.assertFalse(path.exists())
        self.assertTrue(account_file.exists())

    def test_corrupt_cache_is_ignored_and_removed(self) -> None:
        path = simkl_client.calendar_cache_dir() / "shows-2026-07.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json")
        self.assertIsNone(simkl_client.load_calendar_cache("shows", year=2026, month=7))
        self.assertFalse(path.exists())

    def test_304_reuses_cache_and_never_sends_authorization(self) -> None:
        simkl_client.store_calendar_cache(
            "shows",
            TV_PAYLOAD,
            source_url="https://example/calendar",
            fetched_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            last_modified="Mon, 01 Jan 2020 00:00:00 GMT",
            year=2026,
            month=7,
        )

        def not_modified(request, timeout):
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(
                request.headers.get("If-modified-since"),
                "Mon, 01 Jan 2020 00:00:00 GMT",
            )
            raise HTTPError(request.full_url, 304, "Not Modified", {}, None)

        with mock.patch.object(simkl_client, "urlopen", side_effect=not_modified):
            snapshot = simkl_client.fetch_calendar(
                "shows", client_id="client", year=2026, month=7
            )
        self.assertTrue(snapshot.from_cache)
        self.assertEqual(len(snapshot.events), 1)

    def test_monthly_404_is_unavailable(self) -> None:
        with mock.patch.object(
            simkl_client,
            "urlopen",
            side_effect=HTTPError("url", 404, "missing", {}, None),
        ):
            snapshot = simkl_client.fetch_calendar(
                "anime", client_id="client", year=2027, month=1, force=True
            )
        self.assertTrue(snapshot.unavailable)


if __name__ == "__main__":
    unittest.main()
