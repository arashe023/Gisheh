"""Gisheh: a lightweight native GTK4/libadwaita movie library."""

from __future__ import annotations

import logging
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import as_completed
from dataclasses import replace
from datetime import date, datetime
from getpass import getuser
from gettext import gettext as _
from gettext import ngettext
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .services import simkl_client, tmdb_client
from .state_store import (
    LIBRARY_MODE_LOCAL,
    LIBRARY_MODE_SIMKL,
    LIBRARY_MODES,
    clear_state,
    read_state,
    write_state,
)
from .state_store import (
    user_state_file as persistent_user_state_file,
)
from .version import APP_VERSION


# Explicit compatibility exports for existing callers.
from .app_logging import (
    PrivateRotatingFileHandler as PrivateRotatingFileHandler,
    _APP_LOGGER as _APP_LOGGER,
    application_log_file as application_log_file,
    application_logger as application_logger,
    clear_application_logs as clear_application_logs,
    read_application_log as read_application_log,
)
from .constants import (
    APP_ID as APP_ID,
    APP_NAME as APP_NAME,
    CALENDAR_TIMELINE_PAGE_SIZE as CALENDAR_TIMELINE_PAGE_SIZE,
    COLLECTIONS as COLLECTIONS,
    COLLECTION_NAMES as COLLECTION_NAMES,
    COLOR_SCHEMES as COLOR_SCHEMES,
    COLOR_SCHEME_LABELS as COLOR_SCHEME_LABELS,
    EXPLORE_PERIODS as EXPLORE_PERIODS,
    EXPLORE_SORT_OPTIONS as EXPLORE_SORT_OPTIONS,
    GRID_CARD_HEIGHT as GRID_CARD_HEIGHT,
    GRID_CARD_WIDTH as GRID_CARD_WIDTH,
    GRID_COLUMN_GAP as GRID_COLUMN_GAP,
    GRID_HORIZONTAL_PADDING as GRID_HORIZONTAL_PADDING,
    GRID_MAX_COLUMNS as GRID_MAX_COLUMNS,
    GRID_ROW_HEIGHT as GRID_ROW_HEIGHT,
    MEDIA_TYPES as MEDIA_TYPES,
    N_ as N_,
    SORT_OPTIONS as SORT_OPTIONS,
)
from .layout import (
    COMPACT_MEDIA_SWITCHER_WIDTH as COMPACT_MEDIA_SWITCHER_WIDTH,
    DETAILS_INLINE as DETAILS_INLINE,
    DETAILS_INLINE_WIDTH as DETAILS_INLINE_WIDTH,
    DETAILS_NARROW_SAFE_MARGIN as DETAILS_NARROW_SAFE_MARGIN,
    DETAILS_NAVIGATION as DETAILS_NAVIGATION,
    DETAILS_OVERLAY as DETAILS_OVERLAY,
    DETAILS_OVERLAY_MAX_WIDTH as DETAILS_OVERLAY_MAX_WIDTH,
    DETAILS_OVERLAY_MIN_WIDTH as DETAILS_OVERLAY_MIN_WIDTH,
    EXPLORE_COLUMN_HYSTERESIS as EXPLORE_COLUMN_HYSTERESIS,
    EXPLORE_SAFE_CONTENT_WIDTH as EXPLORE_SAFE_CONTENT_WIDTH,
    RESPONSIVE_INLINE_ENTER_WIDTH as RESPONSIVE_INLINE_ENTER_WIDTH,
    RESPONSIVE_INLINE_EXIT_WIDTH as RESPONSIVE_INLINE_EXIT_WIDTH,
    RESPONSIVE_LAYOUT_GAPS as RESPONSIVE_LAYOUT_GAPS,
    RESPONSIVE_MEDIUM_WIDTH as RESPONSIVE_MEDIUM_WIDTH,
    RESPONSIVE_NARROW_ENTER_WIDTH as RESPONSIVE_NARROW_ENTER_WIDTH,
    RESPONSIVE_NARROW_EXIT_WIDTH as RESPONSIVE_NARROW_EXIT_WIDTH,
    RESPONSIVE_NARROW_WIDTH as RESPONSIVE_NARROW_WIDTH,
    RESPONSIVE_SIDEBAR_ENTER_WIDTH as RESPONSIVE_SIDEBAR_ENTER_WIDTH,
    RESPONSIVE_SIDEBAR_EXIT_WIDTH as RESPONSIVE_SIDEBAR_EXIT_WIDTH,
    RESPONSIVE_WIDE_ENTER_WIDTH as RESPONSIVE_WIDE_ENTER_WIDTH,
    RESPONSIVE_WIDE_EXIT_WIDTH as RESPONSIVE_WIDE_EXIT_WIDTH,
    RESPONSIVE_WIDE_WIDTH as RESPONSIVE_WIDE_WIDTH,
    ResponsiveLayout as ResponsiveLayout,
    SIDEBAR_EXPANDED as SIDEBAR_EXPANDED,
    SIDEBAR_EXPANDED_MAX_WIDTH as SIDEBAR_EXPANDED_MAX_WIDTH,
    SIDEBAR_EXPANDED_MIN_WIDTH as SIDEBAR_EXPANDED_MIN_WIDTH,
    SIDEBAR_HIDDEN as SIDEBAR_HIDDEN,
    build_explore_layout_plan as build_explore_layout_plan,
    details_back_action as details_back_action,
    grid_columns_for_width as grid_columns_for_width,
    preserve_explore_page_prefix as preserve_explore_page_prefix,
    responsive_layout_for_width as responsive_layout_for_width,
    should_refresh_simkl_stats as should_refresh_simkl_stats,
)
from .localization import (
    STORED_FALLBACK_LABELS as STORED_FALLBACK_LABELS,
    TMDB_COUNTRY_LABELS as TMDB_COUNTRY_LABELS,
    TMDB_GENRES as TMDB_GENRES,
    TMDB_GENRE_EN_NAME_TO_ID as TMDB_GENRE_EN_NAME_TO_ID,
    TMDB_STATUS_LABELS as TMDB_STATUS_LABELS,
    _normalize_stored_country as _normalize_stored_country,
    _normalize_stored_fallback as _normalize_stored_fallback,
    _normalize_stored_genres as _normalize_stored_genres,
    localize_collection_status as localize_collection_status,
    localize_countries as localize_countries,
    localize_country_name as localize_country_name,
    localize_genre_name as localize_genre_name,
    localize_genre_names as localize_genre_names,
    localize_tmdb_status as localize_tmdb_status,
)
from .models import (
    CastMember as CastMember,
    EpisodeInfo as EpisodeInfo,
    EpisodeWatch as EpisodeWatch,
    SeasonInfo as SeasonInfo,
    TitleRecord as TitleRecord,
    VideoInfo as VideoInfo,
    _tmdb_palette as _tmdb_palette,
    certification_from_tmdb as certification_from_tmdb,
    enrich_record_from_tmdb as enrich_record_from_tmdb,
    enrich_records_from_tmdb_cache as enrich_records_from_tmdb_cache,
    format_watch_time as format_watch_time,
    format_watched_iso as format_watched_iso,
    is_episode_group_complete as is_episode_group_complete,
    load_catalog as load_catalog,
    main_progress_season_indexes as main_progress_season_indexes,
    merge_tmdb_season_episodes as merge_tmdb_season_episodes,
    parse_watched_date as parse_watched_date,
    parse_watched_datetime as parse_watched_datetime,
    recommendation_records_from_tmdb as recommendation_records_from_tmdb,
    runtime_from_tmdb as runtime_from_tmdb,
    runtime_minutes as runtime_minutes,
    should_show_completion_progress as should_show_completion_progress,
    simkl_history_changed as simkl_history_changed,
    title_record_from_tmdb as title_record_from_tmdb,
    title_record_to_mapping as title_record_to_mapping,
    title_records_from_simkl as title_records_from_simkl,
    tmdb_rating_from_payload as tmdb_rating_from_payload,
    validate_watched_iso as validate_watched_iso,
    video_infos_from_tmdb as video_infos_from_tmdb,
    watched_datetime_from_parts as watched_datetime_from_parts,
    watched_now_iso as watched_now_iso,
)
from .widgets import (
    build_calendar_row,
    build_library_row,
    GeneratedPosterWidget as GeneratedPosterWidget,
    MediaViewer as MediaViewer,
    PosterWidget as PosterWidget,
    SidebarRow as SidebarRow,
    _hex_to_rgb as _hex_to_rgb,
    _rounded_rectangle as _rounded_rectangle,
)

RESOURCE_DIR = Path(__file__).resolve().parent
RESOURCE_PREFIX = "/io/github/arashe023/Gisheh"
UI_RESOURCE = f"{RESOURCE_PREFIX}/ui/window.ui"
CSS_RESOURCE = f"{RESOURCE_PREFIX}/style.css"
UI_FILE = RESOURCE_DIR / "ui" / "window.ui"
CSS_FILE = RESOURCE_DIR / "style.css"


def is_rtl_language_selection() -> bool:
    """Only the system-derived GTK direction controls application layout."""
    return Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL


def sidebar_position_for_direction(rtl: bool) -> Gtk.PackType:
    """Use the leading edge: GTK mirrors START to the right in RTL locales."""
    return Gtk.PackType.START


def set_calendar_date(calendar: Gtk.Calendar, selected: GLib.DateTime) -> None:
    """Select a calendar date across the supported GTK 4 versions."""
    setter = getattr(calendar, "set_date", None)
    if setter is not None:
        setter(selected)
        return
    calendar.select_day(selected)


# English TMDB/Simkl status values mapped to translatable labels. Keys are
# normalized (casefolded/stripped) English strings as received from the APIs;
# values are marked with N_() so every status can enter the translation
# catalog and be rendered per language at display time.

# Common production-country names/codes mapped to translatable labels.
# Unknown values fall through untranslated (proper nouns stay as-is).


# English fallback sentences stored in older state files, mapped to their
# translatable equivalents so previously saved records also display per
# language. Keys are the exact English strings; values are marked with N_().


def clear_desktop_preferences() -> None:
    """Reset any GSettings values left by this or an earlier Gisheh build."""
    settings = application_settings()
    if settings is None:
        return
    schema = settings.props.settings_schema
    for key in schema.list_keys():
        settings.reset(key)
    Gio.Settings.sync()


def application_settings() -> Gio.Settings | None:
    """Return the installed application settings, if its schema is available."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(APP_ID, True) if source is not None else None
    if schema is None:
        return None
    return Gio.Settings.new_full(schema, None, None)


def clear_all_user_data(state_file: Path | None = None) -> None:
    """Delete personal state, credentials, downloads and diagnostic logs."""
    failures: list[str] = []
    operations = (
        ("personal state", lambda: clear_state(state_file)),
        ("TMDB developer token", tmdb_client.clear_token),
        ("TMDB cache", tmdb_client.clear_cache),
        ("Simkl data", simkl_client.clear_all_user_data),
        ("desktop preferences", clear_desktop_preferences),
        ("application logs", clear_application_logs),
    )
    for label, operation in operations:
        try:
            operation()
        except (OSError, tmdb_client.TmdbError, simkl_client.SimklError) as error:
            failures.append(f"{label}: {error}")
    if failures:
        raise OSError("; ".join(failures))


def user_state_file() -> Path:
    """Compatibility wrapper for callers that imported this from window."""
    return persistent_user_state_file()


# Explore must keep enough room for a useful card grid.  This is deliberately
# part of the responsive contract rather than an accidental consequence of a
# card's natural size request.

# The enter/exit pairs provide a small stable band around each transition.
# They are intentionally named separately: a layout entered at the upper
# threshold is not immediately abandoned when allocation changes by a few
# pixels during a revealer animation.

# Compatibility names used by callers and older tests.  New decisions use the
# explicit enter/exit values above.


from .controllers import CalendarController, ExploreController, DetailsController, SyncController
from .jobs import BackgroundJobs
from .transactions import persisted_change


class GishehWindow:
    def _guard_state_callback(self, callback):
        def invoke(_self, *args, **kwargs):
            return callback(*args, **kwargs)
        wrapped = persisted_change(invoke)
        return lambda *args, **kwargs: wrapped(self, *args, **kwargs)

    def _background_jobs(self):
        if not hasattr(self, '_jobs'):
            self._jobs = BackgroundJobs(GLib.idle_add)
        return self._jobs

    def _start_worker(self, name, target, *args):
        if getattr(self, '_closed', False):
            return None
        return self._background_jobs().submit(name, target, *args)

    def _image_executor(self):
        return self._background_jobs().image_executor()

    def _post_ui(self, callback, *args):
        if getattr(self, '_closed', False):
            return 0
        return self._background_jobs().post(callback, *args)

    def _invalidate_background_jobs(self):
        if hasattr(self, '_jobs'):
            self._jobs.invalidate()
        for name in (
            '_tmdb_details_loading', '_tmdb_cast_images_loading',
            '_tmdb_gallery_images_loading', '_tmdb_episode_details_loading',
            '_tmdb_season_details_loading', '_tmdb_explore_pages_loading',
            '_simkl_mutations_inflight',
        ):
            value = getattr(self, name, None)
            if value is not None:
                value.clear()
        self._tmdb_search_loading = False
        self._calendar_refresh_inflight = False
        self._simkl_poll_cancelled = True

    def close_background_jobs(self):
        self._closed = True
        for name in (
            '_details_reset_source_id', '_details_resize_source_id',
            '_explore_resize_source_id', '_explore_search_debounce_source_id',
            '_responsive_layout_source_id', '_sidebar_resize_source_id',
            '_tmdb_library_refresh_source_id',
        ):
            source_id = getattr(self, name, 0)
            if source_id:
                if GLib.MainContext.default().find_source_by_id(source_id) is not None:
                    GLib.source_remove(source_id)
                setattr(self, name, 0)
        if hasattr(self, 'data_actions'):
            self.data_actions.cancellable.cancel()
        if hasattr(self, '_jobs'):
            self._jobs.close()


    """Controller for the Gtk.Builder-defined window."""

    def __init__(
        self,
        application: Adw.Application,
        *,
        library_mode: str = LIBRARY_MODE_LOCAL,
    ) -> None:
        self.library_mode = (
            library_mode if library_mode in LIBRARY_MODES else LIBRARY_MODE_LOCAL
        )
        self.records, self.explore_records, self.totals = load_catalog()
        self.simkl_client_id = simkl_client.read_client_id()
        self.simkl_token = (
            simkl_client.read_token()
            if self.library_mode == LIBRARY_MODE_SIMKL
            else None
        )
        self.tmdb_token = tmdb_client.read_token()
        self.simkl_settings: dict[str, Any] = {}
        self.simkl_stats: dict[str, Any] = {}
        self.simkl_connected = False
        self.simkl_snapshot_needs_repair = False
        if (
            self.library_mode == LIBRARY_MODE_SIMKL
            and self.simkl_client_id
            and self.simkl_token
        ):
            snapshot = simkl_client.load_snapshot()
            if snapshot is not None:
                library_payload = (
                    snapshot.get("library", {})
                    if isinstance(snapshot.get("library"), dict)
                    else {}
                )
                if simkl_client.library_has_user_state(library_payload):
                    simkl_records = title_records_from_simkl(library_payload)
                    self.records = enrich_records_from_tmdb_cache(simkl_records)
                    if not simkl_client.library_has_episode_history(library_payload):
                        self.simkl_snapshot_needs_repair = True
                else:
                    self.simkl_snapshot_needs_repair = True
                self.simkl_settings = (
                    snapshot.get("settings", {})
                    if isinstance(snapshot.get("settings"), dict)
                    else {}
                )
                self.simkl_stats = (
                    snapshot.get("stats", {})
                    if isinstance(snapshot.get("stats"), dict)
                    else {}
                )
                self.simkl_connected = bool(self.simkl_settings)
        self.library_ids = {record.id for record in self.records}
        self.explore_ids = {record.id for record in self.explore_records}
        if self.library_ids & self.explore_ids:
            raise ValueError("Library and Explore record IDs must be unique")
        self.records_by_id = {
            record.id: record for record in (*self.records, *self.explore_records)
        }
        self._tmdb_record_aliases: dict[tuple[str, int], str] = {}
        self._library_records_by_canonical: dict[str, TitleRecord] = {}
        self._rebuild_record_aliases()

        self.active_destination = "collection"
        self.active_media = "Movies"
        self.active_collection = "Watched"
        today = datetime.now().astimezone().date()
        self.calendar_month = today.replace(day=1)
        self.calendar_selected_date = today
        self.calendar_snapshot: simkl_client.CalendarSnapshot | None = None
        self._calendar_refresh_inflight = False
        self._calendar_generation = 0
        self._calendar_posters_loading: set[int] = set()
        self.calendar_timeline_limit = CALENDAR_TIMELINE_PAGE_SIZE
        self.genre = "All genres"
        self.sort_key = "recent"
        self.sort_reversed = False
        self.view_mode = "list"
        default_record = next(
            (record for record in self.records if record.status == "Watched"),
            self.records[0] if self.records else None,
        )
        self.selected_id: str | None = (
            default_record.id if default_record is not None else None
        )
        self.collection_selected_ids: dict[str, str | None] = {
            collection: next(
                (record.id for record in self.records if record.status == collection),
                None,
            )
            for collection in COLLECTION_NAMES
        }
        self.collection_selected_ids[self.active_collection] = self.selected_id
        self.collection_scroll_positions = {
            collection: 0.0 for collection in COLLECTION_NAMES
        }
        self.collection_view_states: dict[str, dict[str, Any]] = {
            collection: {
                "query": "",
                "genre": "All genres",
                "sortKey": "recent",
                "sortReversed": False,
            }
            for collection in COLLECTION_NAMES
        }
        self.explore_selected_id: str | None = None
        self.visible_records: tuple[TitleRecord, ...] = ()
        self.explore_visible_records: tuple[TitleRecord, ...] = ()
        self.explore_sort_key = "trending"
        self.explore_period = "This month"
        self.explore_genre = "All genres"
        self.explore_columns = 4
        self._explore_layout_seed = random.SystemRandom().randrange(1 << 63)
        self._explore_resize_source_id = 0
        self._details_resize_source_id = 0
        self._sidebar_resize_source_id = 0
        self._last_explore_layout_width = 0
        self._last_explore_layout_bucket: tuple[int, int] | None = None

        self.bookmarks = {
            self._canonical_record_id(record)
            for record in self.records
            if record.status == "Watchlist"
        }
        self.favorites: set[str] = set()
        self.completed = {
            self._canonical_record_id(record)
            for record in self.records
            if record.status == "Watched"
        }
        self.ratings = {
            self._canonical_record_id(record): record.user_rating
            for record in self.records
            if record.user_rating is not None
        }
        self.status_overrides: dict[str, str] = {}
        self.local_library_records: dict[str, TitleRecord] = {}
        self.episode_status_overrides: dict[str, bool] = {}
        self.episode_watched_at: dict[str, str] = {
            f"{self._canonical_record_id(record)}/s{item.season}/e{item.episode}": item.watched_at
            for record in self.records
            for item in record.episode_history
            if self.simkl_connected and item.watched_at
        }
        self.title_watched_at: dict[str, str] = {}
        self._tmdb_details_loading: set[str] = set()
        self._tmdb_details_loaded: set[str] = set()
        self._tmdb_detail_generations: dict[str, int] = {}
        self._tmdb_cast_images_loading: dict[str, set[int]] = {}
        self._tmdb_gallery_images_loading: dict[str, dict[str, int]] = {}
        self._tmdb_recommendations: dict[str, tuple[str, ...]] = {}
        self._tmdb_episode_details_loading: set[str] = set()
        self._tmdb_episode_details_loaded: set[str] = set()
        self._tmdb_season_details_loading: set[str] = set()
        self._tmdb_season_details_loaded: set[str] = set()
        self._tmdb_explore_generation = 0
        self._tmdb_explore_pages = {media_type: 1 for media_type in MEDIA_TYPES}
        self._tmdb_explore_has_more = {media_type: True for media_type in MEDIA_TYPES}
        self._tmdb_explore_pages_loading: set[str] = set()
        self.explore_search_records: tuple[TitleRecord, ...] = ()
        self.explore_search_ids: set[str] = set()
        self._tmdb_search_generation = 0
        self._tmdb_search_query = ""
        self._tmdb_search_media = ""
        self._tmdb_search_page = 0
        self._tmdb_search_total_pages = 0
        self._tmdb_search_loading = False
        self._explore_search_debounce_source_id = 0
        self._tmdb_library_generation = 0
        self._tmdb_library_refresh_source_id = 0
        self._log_dialog: Adw.Dialog | None = None
        self._log_text_view: Gtk.TextView | None = None
        self._simkl_sync_started_at = 0.0
        self._simkl_sync_error: str | None = None
        self._simkl_mutations_inflight: set[str] = set()
        self._simkl_state_generation = 0
        self.color_scheme = "system"
        self.content_language = "system"
        self.auto_sync = True
        self.auto_calendar_refresh = True
        self.default_media = "Movies"
        self.preferred_view_mode = "list"
        self.settings = application_settings()
        self.state_file = user_state_file()
        self._load_user_state()
        try:
            tmdb_client.set_content_language(self.content_language)
        except (AttributeError, ValueError):
            pass
        self._load_view_mode_preference()
        self._apply_color_scheme()
        application_logger().info("Gisheh %s started", APP_VERSION)

        self._updating = False
        self._updating_details = False
        self._updating_sidebar_toggle = False
        self._applying_responsive = False
        self.details_open = False
        self._collection_results_dirty = False
        self.detail_record_id: str | None = None
        self.current_season_index = 0
        self.current_episode_index = 0
        self.collection_rows: dict[str, SidebarRow] = {}
        self._sidebar_docked = True
        self.effective_details_mode = DETAILS_INLINE
        self._responsive_layout_source_id = 0
        self._details_reset_source_id = 0
        self._details_return_focus: Gtk.Widget | None = None
        self._details_revealed_state: bool | None = None
        self._last_applied_details_presentation: tuple[str, bool] | None = None
        self._pending_details_mode: str | None = None
        self._details_chrome_focus_mode: str | None = None
        self._media_switcher_available = True
        self.details_overlay_close: Gtk.Button | None = None
        self.content_navigation: Adw.NavigationView | None = None
        self.main_browser_page: Adw.NavigationPage | None = None
        self.mobile_details_page: Adw.NavigationPage | None = None
        self.mobile_details_host: Gtk.Box | None = None
        self.mobile_header_bar: Adw.HeaderBar | None = None
        self.details_panel_layout: Gtk.Box | None = None
        self.details_home: Gtk.Box | None = None

        try:
            self.builder = Gtk.Builder.new_from_resource(UI_RESOURCE)
        except GLib.Error:
            self.builder = Gtk.Builder.new_from_file(str(UI_FILE))
        self.window: Adw.ApplicationWindow = self._object("window")
        self.window.set_application(application)
        self._restore_window_state()
        self._apply_text_direction()

        self._load_css()
        self._bind_objects()
        self._update_header_data_status()
        self._build_media_viewer()
        self._build_browser_stack()
        self._configure_accessibility()
        self._build_header_controls()
        self._build_sidebar()
        self._build_result_views()
        self._build_explore_view()
        self._build_calendar_view()
        self._build_profile_view()
        self._build_settings_dialog()
        self._build_detail_sections()
        self._connect_signals(application)
        self._update_genre_model()
        initial_collection_scroll = self._restore_active_collection_state()
        self._refresh_results()
        self._scroll_to_value(self.results_scroller, initial_collection_scroll)
        if self.tmdb_token:
            self._load_tmdb_explore_async()
        if (
            self.library_mode == LIBRARY_MODE_SIMKL
            and self.auto_sync
            and self.simkl_client_id
            and self.simkl_token
        ):
            if self.simkl_snapshot_needs_repair:
                self._app_log(
                    "Incomplete Simkl snapshot detected; scheduling state repair.",
                    level=logging.WARNING,
                )
            else:
                self._app_log("Scheduling Simkl user-state refresh.")
            self._post_ui(self._start_simkl_sync)
        if (
            self.library_mode == LIBRARY_MODE_SIMKL
            and self.auto_calendar_refresh
            and self.simkl_client_id
        ):
            self._post_ui(self._start_calendar_refresh, False)

    def _object(self, name: str) -> Any:
        obj = self.builder.get_object(name)
        if obj is None:
            raise RuntimeError(f"The UI is missing required object '{name}'")
        return obj

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_resource(CSS_RESOURCE)
        except GLib.Error:
            provider.load_from_path(str(CSS_FILE))
        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _bind_objects(self) -> None:
        names = (
            "toast_overlay",
            "workspace",
            "header_bar",
            "header_data_status_button",
            "header_data_status_icon",
            "header_data_status_spinner",
            "header_data_status_label",
            "media_switcher",
            "compact_media_bar",
            "compact_media_switcher",
            "main_menu_button",
            "search_button",
            "destination_list",
            "collection_list",
            "profile_button",
            "sidebar_profile_avatar",
            "main_workspace",
            "collection_pane",
            "section_title",
            "search_entry",
            "sort_dropdown",
            "genre_dropdown",
            "view_switcher",
            "result_count",
            "result_description",
            "sort_direction_button",
            "results_scroller",
            "details_surface",
            "detail_navigation",
            "title_detail_page",
            "details_scroller",
            "detail_box",
            "detail_poster_host",
            "detail_status_label",
            "detail_overline",
            "detail_title",
            "community_rating",
            "detail_ratings_host",
            "watched_button",
            "rating_button",
            "bookmark_button",
            "rating_popover",
            "runtime_label",
            "genres_label",
            "overview_label",
            "creator_row",
            "release_row",
            "country_row",
            "activity_row",
            "activity_progress_card",
            "activity_status",
            "activity_percentage",
            "activity_progress",
            "rating_value",
            "rating_grid",
            "detail_extra_sections",
            "explore_pane",
            "explore_header",
            "explore_filter_bar",
            "explore_search_entry",
            "explore_sort_dropdown",
            "explore_period_dropdown",
            "explore_genre_dropdown",
            "explore_calendar_button",
            "explore_scroller",
            "explore_feed_box",
        )
        for name in names:
            setattr(self, name, self._object(name))

    def _build_browser_stack(self) -> None:
        """Place the content pages beside an animated end details panel."""
        self.main_workspace.remove(self.collection_pane)
        self.main_workspace.remove(self.details_surface)
        divider = self.main_workspace.get_last_child()
        if isinstance(divider, Gtk.Separator):
            self.main_workspace.remove(divider)

        self.browser_stack = Gtk.Stack()
        self.browser_stack.set_hexpand(True)
        self.browser_stack.set_vexpand(True)
        self.browser_stack.set_hhomogeneous(False)
        self.browser_stack.set_vhomogeneous(False)
        self.browser_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.browser_stack.set_transition_duration(160)
        self.browser_stack.add_named(self.collection_pane, "collection")
        self.browser_stack.add_named(self.explore_pane, "explore")
        self.browser_stack.set_visible_child_name("collection")

        self.content_overlay = Gtk.Overlay()
        self.content_overlay.set_hexpand(True)
        self.content_overlay.set_vexpand(True)
        self.content_overlay.set_child(self.browser_stack)
        self.main_workspace.prepend(self.content_overlay)

        self.details_surface.set_child(None)
        details_layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        details_layout.add_css_class("detail-panel-layout")
        details_layout.set_halign(Gtk.Align.FILL)
        details_layout.set_valign(Gtk.Align.FILL)
        details_layout.set_hexpand(True)
        details_layout.set_vexpand(True)
        details_layout.append(self.detail_navigation)
        self.details_home = details_layout
        self.details_surface.set_halign(Gtk.Align.FILL)
        self.details_surface.set_valign(Gtk.Align.FILL)
        self.details_surface.set_vexpand(True)
        self.detail_navigation.set_halign(Gtk.Align.FILL)
        self.detail_navigation.set_valign(Gtk.Align.FILL)
        self.detail_navigation.set_hexpand(True)
        self.detail_navigation.set_vexpand(True)
        self.detail_navigation.connect(
            "notify::visible-page", self._on_inner_details_page_changed
        )
        self.details_surface.set_child(details_layout)
        self.details_surface.set_visible(True)

        panel_layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        panel_layout.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        panel_layout.append(self.details_surface)
        self.details_panel_layout = panel_layout

        self.details_revealer = Gtk.Revealer()
        self.details_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.details_revealer.set_transition_duration(220)
        self.details_revealer.set_reveal_child(False)
        self.details_revealer.set_child(panel_layout)
        self.main_workspace.append(self.details_revealer)

        self.details_overlay_close = Gtk.Button.new_from_icon_name(
            "window-close-symbolic"
        )
        self.details_overlay_close.set_tooltip_text(_("Close details (Escape)"))
        self.details_overlay_close.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Close details"],
        )
        self.details_overlay_close.add_css_class("circular")
        self.details_overlay_close.add_css_class("osd")
        self.details_overlay_close.set_halign(Gtk.Align.END)
        self.details_overlay_close.set_valign(Gtk.Align.START)
        self.details_overlay_close.set_margin_top(12)
        self.details_overlay_close.set_margin_end(12)
        self.details_overlay_close.set_visible(False)
        self.details_overlay_close.connect(
            "clicked", lambda *_args: self._set_details_open(False)
        )
        self.content_overlay.add_overlay(self.details_overlay_close)

        self._build_content_navigation()

    def _build_content_navigation(self) -> None:
        """Wrap content in a navigation view for full-page mobile details."""
        self.mobile_details_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.mobile_details_host.set_halign(Gtk.Align.FILL)
        self.mobile_details_host.set_valign(Gtk.Align.FILL)
        self.mobile_details_host.set_hexpand(True)
        self.mobile_details_host.set_vexpand(True)

        self.mobile_header_bar = Adw.HeaderBar()
        self.mobile_header_bar.set_show_start_title_buttons(False)
        self.mobile_header_bar.set_show_end_title_buttons(False)
        mobile_back_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        mobile_back_button.set_tooltip_text(_("Back to content"))
        mobile_back_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Back to content"],
        )
        mobile_back_button.connect("clicked", self._on_mobile_title_back)
        self.mobile_header_bar.pack_start(mobile_back_button)
        mobile_title = Adw.WindowTitle(title=_("Details"), subtitle="")
        self.mobile_header_bar.set_title_widget(mobile_title)

        mobile_toolbar = Adw.ToolbarView()
        mobile_toolbar.add_top_bar(self.mobile_header_bar)
        mobile_toolbar.set_content(self.mobile_details_host)

        self.mobile_details_page = Adw.NavigationPage.new(mobile_toolbar, "Details")
        self.mobile_details_page.set_tag("details")

        self.content_navigation = Adw.NavigationView()
        self.content_navigation.set_hexpand(True)
        self.content_navigation.set_vexpand(True)
        self.content_navigation.set_hhomogeneous(False)
        self.content_navigation.set_vhomogeneous(False)
        self.content_navigation.connect(
            "notify::visible-page",
            self._on_content_navigation_page_changed,
        )
        previous_content = self.workspace.get_content()
        self.workspace.set_content(self.content_navigation)
        self.main_browser_page = previous_content
        self.main_browser_page.set_tag("browser")
        self.content_navigation.push(self.main_browser_page)
        self._sync_mobile_back_visibility()

    def _build_media_viewer(self) -> None:
        """Layer the media viewer over the existing app without leaving the window."""
        content = self.toast_overlay.get_child()
        if content is None:
            raise RuntimeError("The application has no root content for Media Viewer")
        self.toast_overlay.set_child(None)
        self.application_overlay = Gtk.Overlay()
        self.application_overlay.set_child(content)
        self.media_viewer = MediaViewer(self.window)
        self.application_overlay.add_overlay(self.media_viewer)
        self.toast_overlay.set_child(self.application_overlay)

    @staticmethod
    def _media_items(
        record: TitleRecord,
        mode: str,
    ) -> tuple[tuple[str, str], ...]:
        if mode == "posters":
            candidates = (record.poster_file, *record.gallery_posters)
            kind = _("Poster")
        else:
            candidates = (record.backdrop_file, *record.gallery_backdrops)
            kind = _("Backdrop")
        paths = tuple(
            dict.fromkeys(
                path for path in candidates if path is not None and Path(path).is_file()
            )
        )
        return tuple(
            (path, f"{record.title} — {kind} {index}")
            for index, path in enumerate(paths, start=1)
        )

    def _open_record_media(
        self,
        record: TitleRecord,
        mode: str,
        position: int = 0,
    ) -> None:
        items = self._media_items(record, mode)
        if not items:
            self._toast(
                _("No {mode} available for {title}").format(
                    mode=(
                        _("posters")
                        if mode == "posters"
                        else _("backdrops") if mode == "backdrops" else mode
                    ),
                    title=record.title,
                )
            )
            return
        self.media_viewer.open(items, position)

    def _configure_accessibility(self) -> None:
        self.activity_progress.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Watch progress")],
        )

    def _load_user_state(self, payload=None) -> None:
        payload = read_state(self.state_file) if payload is None else payload
        if not payload:
            return

        preferences = payload.get("preferences", {})
        if isinstance(preferences, dict):
            saved_library_mode = preferences.get("libraryMode")
            if saved_library_mode in LIBRARY_MODES:
                self.library_mode = str(saved_library_mode)

        loaded_local_records: dict[str, TitleRecord] = {}
        for raw in payload.get("localLibrary", ()):
            if not isinstance(raw, dict):
                continue
            try:
                record = TitleRecord.from_mapping(raw)
            except (KeyError, TypeError, ValueError):
                continue
            # The persisted local ID is already canonical for the local
            # profile. Do not remap it through a currently loaded Simkl
            # library, or switching modes would change ownership keys.
            canonical = record.id
            local_record = replace(record, id=canonical)
            loaded_local_records[canonical] = local_record
        self.local_library_records = loaded_local_records

        if getattr(self, "library_mode", LIBRARY_MODE_SIMKL) == LIBRARY_MODE_LOCAL:
            for canonical, local_record in loaded_local_records.items():
                if canonical not in self._library_records_by_canonical:
                    self.records += (local_record,)
            if loaded_local_records:
                self.library_ids = {record.id for record in self.records}
                self.records_by_id.update(
                    {record.id: record for record in loaded_local_records.values()}
                )
                self._rebuild_record_aliases()

        personal_state = payload
        if self.library_mode == LIBRARY_MODE_LOCAL:
            stored_local_profile = payload.get("localProfile")
            if isinstance(stored_local_profile, dict):
                personal_state = stored_local_profile

        valid_ids = set(self.records_by_id)

        def canonical_saved_id(value: object) -> str:
            record_id = str(value)
            record = self.records_by_id.get(record_id)
            return (
                self._canonical_record_id(record) if record is not None else record_id
            )

        def is_valid_id(value: object) -> bool:
            record_id = str(value)
            return (
                record_id in valid_ids
                or record_id.startswith("tmdb-")
                or (bool(self.simkl_token) and record_id.startswith("simkl-"))
            )

        self.bookmarks = {
            canonical_saved_id(value)
            for value in personal_state.get("bookmarks", self.bookmarks)
            if is_valid_id(value)
        }
        self.favorites = {
            value
            for value in personal_state.get("favorites", self.favorites)
            if is_valid_id(value)
        }
        self.completed = {
            canonical_saved_id(value)
            for value in personal_state.get("completed", self.completed)
            if is_valid_id(value)
        }
        self.ratings = {
            canonical_saved_id(record_id): int(score)
            for record_id, score in personal_state.get("ratings", self.ratings).items()
            if is_valid_id(record_id) and isinstance(score, int) and 1 <= score <= 10
        }
        self.status_overrides = {
            canonical_saved_id(record_id): status
            for record_id, status in personal_state.get("statusOverrides", {}).items()
            if is_valid_id(record_id) and status in COLLECTION_NAMES
        }
        if not self.simkl_connected:
            self.episode_status_overrides = {
                str(key): value
                for key, value in personal_state.get(
                    "episodeStatusOverrides", {}
                ).items()
                if isinstance(value, bool) and is_valid_id(str(key).split("/", 1)[0])
            }
            self.episode_watched_at = {
                str(key): str(value)
                for key, value in personal_state.get("episodeWatchedAt", {}).items()
                if isinstance(value, str) and is_valid_id(str(key).split("/", 1)[0])
            }
        self.title_watched_at = {
            canonical_saved_id(key): str(value)
            for key, value in personal_state.get("titleWatchedAt", {}).items()
            if isinstance(value, str) and is_valid_id(str(key))
        }
        if not hasattr(self, "active_collection"):
            self.active_collection = "Watched"
        if not hasattr(self, "collection_selected_ids"):
            self.collection_selected_ids = {
                collection: None for collection in COLLECTION_NAMES
            }
        if not hasattr(self, "collection_scroll_positions"):
            self.collection_scroll_positions = {
                collection: 0.0 for collection in COLLECTION_NAMES
            }
        if not hasattr(self, "collection_view_states"):
            self.collection_view_states = {
                collection: {
                    "query": "",
                    "genre": "All genres",
                    "sortKey": "recent",
                    "sortReversed": False,
                }
                for collection in COLLECTION_NAMES
            }
        collection_state = payload.get("collectionState", {})
        if isinstance(collection_state, dict):
            active_collection = collection_state.get("active")
            if active_collection in COLLECTION_NAMES:
                self.active_collection = str(active_collection)
            views = collection_state.get("views", {})
            if isinstance(views, dict):
                valid_sort_keys = {key for key, _label in SORT_OPTIONS}
                for collection in COLLECTION_NAMES:
                    raw_view = views.get(collection)
                    if not isinstance(raw_view, dict):
                        continue
                    selected_id = raw_view.get("selectedId")
                    if selected_id is None or is_valid_id(selected_id):
                        self.collection_selected_ids[collection] = (
                            str(selected_id) if selected_id is not None else None
                        )
                    scroll = raw_view.get("scroll")
                    if isinstance(scroll, (int, float)) and scroll >= 0:
                        self.collection_scroll_positions[collection] = float(scroll)
                    query = raw_view.get("query")
                    if isinstance(query, str):
                        self.collection_view_states[collection]["query"] = query
                    genre = raw_view.get("genre")
                    if isinstance(genre, str):
                        self.collection_view_states[collection]["genre"] = genre
                    sort_key = raw_view.get("sortKey")
                    if sort_key in valid_sort_keys:
                        self.collection_view_states[collection]["sortKey"] = sort_key
                    sort_reversed = raw_view.get("sortReversed")
                    if isinstance(sort_reversed, bool):
                        self.collection_view_states[collection]["sortReversed"] = (
                            sort_reversed
                        )
        self.selected_id = self.collection_selected_ids[self.active_collection]
        if isinstance(preferences, dict):
            color_scheme = preferences.get("colorScheme")
            if color_scheme in COLOR_SCHEMES:
                self.color_scheme = str(color_scheme)
            content_language = preferences.get("contentLanguage", "system")
            if isinstance(content_language, str):
                self.content_language = tmdb_client.normalize_content_language(content_language)
                try:
                    tmdb_client.set_content_language(self.content_language)
                except (AttributeError, ValueError):
                    pass
            auto_sync = preferences.get("autoSync")
            if isinstance(auto_sync, bool):
                self.auto_sync = auto_sync
            auto_calendar = preferences.get("autoCalendarRefresh")
            if isinstance(auto_calendar, bool):
                self.auto_calendar_refresh = auto_calendar
            default_media = preferences.get("defaultMedia")
            if default_media in MEDIA_TYPES:
                self.default_media = str(default_media)
                self.active_media = self.default_media
            library_view = preferences.get("libraryView")
            if library_view in ("list", "grid"):
                self.preferred_view_mode = str(library_view)
                self.view_mode = self.preferred_view_mode
        # Obsolete "preferredSidebarMode" keys from older state files are
        # ignored on purpose; the sidebar no longer has a stored preference.

        for record_id, status in self.status_overrides.items():
            if status == "Watched":
                self.completed.add(record_id)
            else:
                self.completed.discard(record_id)

    def _save_user_state(self, *, remember_collection: bool = True) -> None:
        if (
            remember_collection
            and getattr(self, "active_destination", None) == "collection"
            and hasattr(self, "results_scroller")
        ):
            self._remember_active_collection_state()
        payload = read_state(self.state_file)
        personal_state = {
            "bookmarks": sorted(self.bookmarks),
            "favorites": sorted(self.favorites),
            "completed": sorted(self.completed),
            "ratings": dict(sorted(self.ratings.items())),
            "statusOverrides": dict(sorted(self.status_overrides.items())),
            "episodeStatusOverrides": dict(
                sorted(self.episode_status_overrides.items())
            ),
            "episodeWatchedAt": dict(sorted(self.episode_watched_at.items())),
            "titleWatchedAt": dict(sorted(self.title_watched_at.items())),
        }
        payload.update(personal_state)
        if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
            payload["localProfile"] = {**payload.get("localProfile", {}), **personal_state}
        payload["localLibrary"] = [
            title_record_to_mapping(record)
            for _record_id, record in sorted(
                getattr(self, "local_library_records", {}).items()
            )
        ]
        payload["preferences"] = {
            **payload.get("preferences", {}),
            "colorScheme": self.color_scheme,
            "contentLanguage": getattr(self, "content_language", "system"),
            "autoSync": self.auto_sync,
            "autoCalendarRefresh": getattr(self, "auto_calendar_refresh", True),
            "defaultMedia": self.default_media,
            "libraryView": self.preferred_view_mode,
            "libraryMode": getattr(self, "library_mode", LIBRARY_MODE_LOCAL),
        }
        active_collection = getattr(self, "active_collection", "Watched")
        selected_ids = getattr(
            self,
            "collection_selected_ids",
            {collection: None for collection in COLLECTION_NAMES},
        )
        scroll_positions = getattr(
            self,
            "collection_scroll_positions",
            {collection: 0.0 for collection in COLLECTION_NAMES},
        )
        view_states = getattr(
            self,
            "collection_view_states",
            {
                collection: {
                    "query": "",
                    "genre": "All genres",
                    "sortKey": "recent",
                    "sortReversed": False,
                }
                for collection in COLLECTION_NAMES
            },
        )
        payload["collectionState"] = {
            "active": active_collection,
            "views": {
                collection: {
                    "selectedId": selected_ids.get(collection),
                    "scroll": scroll_positions.get(collection, 0.0),
                    **view_states.get(collection, {}),
                }
                for collection in COLLECTION_NAMES
            },
        }
        write_state(payload, self.state_file)

    def _load_view_mode_preference(self) -> None:
        """Load the library view from GSettings, migrating the legacy JSON value."""
        settings = getattr(self, "settings", None)
        if settings is None:
            return
        if settings.get_user_value("view-mode") is None:
            # Before GSettings was wired up, this preference lived in state.json.
            # Preserve a non-default legacy value instead of silently losing it.
            if self.preferred_view_mode != "list":
                settings.set_string("view-mode", self.preferred_view_mode)
            return
        view_mode = settings.get_string("view-mode")
        if view_mode in ("list", "grid"):
            self.preferred_view_mode = view_mode
            self.view_mode = view_mode

    def _save_view_mode_preference(self) -> None:
        settings = getattr(self, "settings", None)
        if settings is not None:
            settings.set_string("view-mode", self.preferred_view_mode)

    def _restore_window_state(self) -> None:
        """Apply the last normal size and maximized state to the GTK window."""
        width, height, maximized = 1100, 700, False
        settings = getattr(self, "settings", None)
        if settings is not None:
            width = settings.get_int("window-width")
            height = settings.get_int("window-height")
            maximized = settings.get_boolean("window-maximized")
        self.window.set_default_size(width, height)
        if maximized:
            self.window.maximize()

    def _save_window_state(self) -> None:
        """Persist the normal window size without replacing it while maximized."""
        settings = getattr(self, "settings", None)
        if settings is None:
            return
        maximized = self.window.is_maximized()
        settings.set_boolean("window-maximized", maximized)
        if maximized:
            return
        width = self.window.get_width()
        height = self.window.get_height()
        if width > 0 and height > 0:
            settings.set_int("window-width", width)
            settings.set_int("window-height", height)

    def _build_header_controls(self) -> None:
        self.sidebar_toggle_button = Gtk.ToggleButton(icon_name="sidebar-show-symbolic")
        self.sidebar_toggle_button.set_active(True)
        self.sidebar_toggle_button.set_tooltip_text(_("Hide Sidebar (Ctrl+B)"))
        self.sidebar_toggle_button.add_css_class("flat")
        self.sidebar_toggle_button.add_css_class("circular")
        self.sidebar_toggle_button.connect(
            "toggled",
            self._on_sidebar_toggled,
        )
        self.header_bar.pack_start(self.sidebar_toggle_button)

        for media_type in MEDIA_TYPES:
            self.media_switcher.add(
                Adw.Toggle(name=media_type.lower(), label=_(media_type))
            )
            self.compact_media_switcher.add(
                Adw.Toggle(name=media_type.lower(), label=_(media_type))
            )
        self.media_switcher.set_active_name(self.active_media.lower())
        self.compact_media_switcher.set_active_name(self.active_media.lower())

        self.view_switcher.add(
            Adw.Toggle(
                name="list",
                icon_name="view-list-symbolic",
                tooltip=_("List View"),
            )
        )
        self.view_switcher.add(
            Adw.Toggle(
                name="grid",
                icon_name="view-grid-symbolic",
                tooltip=_("Grid View"),
            )
        )
        self.view_switcher.set_active_name(self.view_mode)

        self.rating_buttons: dict[int, Gtk.ToggleButton] = {}
        rating_leader: Gtk.ToggleButton | None = None
        for score in range(1, 11):
            button = Gtk.ToggleButton(label=str(score))
            button.set_tooltip_text(_("{score} out of 10").format(score=score))
            if rating_leader is None:
                rating_leader = button
            else:
                button.set_group(rating_leader)
            button.connect("toggled", self._on_rating_button_toggled, score)
            self.rating_grid.attach(button, (score - 1) % 5, (score - 1) // 5, 1, 1)
            self.rating_buttons[score] = button

        sort_labels = [_(label) for _key, label in SORT_OPTIONS]
        self.sort_dropdown.set_model(Gtk.StringList.new(sort_labels))
        self.sort_dropdown.set_selected(0)

        explore_sort_labels = [_(label) for _key, label in EXPLORE_SORT_OPTIONS]
        self.explore_sort_dropdown.set_model(Gtk.StringList.new(explore_sort_labels))
        self.explore_sort_dropdown.set_selected(0)
        self.explore_period_dropdown.set_model(
            Gtk.StringList.new([_(period) for period in EXPLORE_PERIODS])
        )
        self.explore_period_dropdown.set_selected(0)

        self.main_menu_button.set_menu_model(self._primary_menu())

    @staticmethod
    def _primary_menu() -> Gio.Menu:
        menu = Gio.Menu()
        tools = Gio.Menu()
        tools.append(_("Application _Log"), "app.logs")
        tools.append(_("_Credits & Data Sources"), "app.credits")
        menu.append_section(None, tools)
        standard = Gio.Menu()
        standard.append(_("_Preferences"), "win.preferences")
        standard.append(_("_Keyboard Shortcuts"), "win.shortcuts")
        standard.append(_("_About Gisheh"), "app.about")
        menu.append_section(None, standard)
        return menu

    @staticmethod
    def _shortcuts_dialog() -> Adw.ShortcutsDialog:
        dialog = Adw.ShortcutsDialog()
        general = Adw.ShortcutsSection(title=_("General"))
        for title, action in (
            (_("Main Menu"), "win.main-menu"),
            (_("Preferences"), "win.preferences"),
            (_("Keyboard Shortcuts"), "win.shortcuts"),
            (_("Close Window"), "win.close"),
            (_("Quit"), "app.quit"),
        ):
            general.add(Adw.ShortcutsItem(title=title, action_name=action))
        dialog.add(general)
        navigation = Adw.ShortcutsSection(title=_("Navigation"))
        for title, action in (
            (_("Search"), "win.find"),
            (_("Search Explore"), "win.search"),
            (_("Show or Hide Sidebar"), "win.toggle-sidebar"),
            (_("Go Back"), "win.back"),
        ):
            navigation.add(Adw.ShortcutsItem(title=title, action_name=action))
        navigation.add(
            Adw.ShortcutsItem(title=_("Dismiss or Go Back"), accelerator="Escape")
        )
        dialog.add(navigation)
        return dialog

    def _show_shortcuts(self, *_args) -> None:
        dialog = self._shortcuts_dialog()
        dialog.present(self.window)

    def _show_main_menu(self, *_args) -> None:
        self._set_sidebar_open(True)
        self.main_menu_button.popup()

    def _build_sidebar(self) -> None:
        self.explore_row = SidebarRow(
            "explore",
            _("Explore"),
            "find-location-symbolic",
        )
        self.calendar_row = SidebarRow(
            "calendar",
            _("Calendar"),
            "x-office-calendar-symbolic",
        )
        self.destination_list.append(self.explore_row)
        self.destination_list.append(self.calendar_row)

        for collection, icon_name in COLLECTIONS:
            row = SidebarRow(
                collection,
                _(collection),
                icon_name,
            )
            self.collection_rows[collection] = row
            self.collection_list.append(row)

        self._updating = True
        self.destination_list.unselect_all()
        self.collection_list.select_row(self.collection_rows[self.active_collection])
        self._updating = False

    def _build_result_views(self) -> None:
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_activate_on_single_click(True)
        self.list_box.set_show_separators(True)
        self.list_box.add_css_class("boxed-list")

        self.grid_box = Gtk.FlowBox()
        self.grid_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.grid_box.set_activate_on_single_click(True)
        self.grid_box.set_homogeneous(True)
        self.grid_box.set_min_children_per_line(1)
        self.grid_box.set_max_children_per_line(GRID_MAX_COLUMNS)
        self.grid_box.set_row_spacing(10)
        self.grid_box.set_column_spacing(GRID_COLUMN_GAP)
        self.grid_box.set_hexpand(True)
        self.grid_box.set_halign(Gtk.Align.FILL)
        self.grid_box.set_valign(Gtk.Align.START)
        self.grid_box.add_css_class("movie-grid")

        self.empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title=_("No titles found"),
            description=_("Try a different search term or clear the genre filter."),
        )
        self.empty_page.add_css_class("empty-status")
        self.empty_clear_button = Gtk.Button(label=_("Clear filters"))
        self.empty_clear_button.set_halign(Gtk.Align.CENTER)
        self.empty_clear_button.add_css_class("pill")
        self.empty_clear_button.connect("clicked", self._on_clear_filters)
        self.empty_page.set_child(self.empty_clear_button)

        self.empty_explore_button = Gtk.Button(label=_("Explore Titles"))
        self.empty_explore_button.set_halign(Gtk.Align.CENTER)
        self.empty_explore_button.add_css_class("pill")
        self.empty_explore_button.add_css_class("suggested-action")
        self.empty_explore_button.connect("clicked", self._on_empty_explore_clicked)

    def _build_explore_view(self) -> None:
        self.explore_empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title=_("Nothing new here yet"),
            description=_("Try another search, period, or genre."),
        )
        self.explore_empty_page.add_css_class("empty-status")
        reset_button = Gtk.Button(label=_("Reset Explore filters"))
        reset_button.set_halign(Gtk.Align.CENTER)
        reset_button.add_css_class("pill")
        reset_button.connect("clicked", self._on_clear_explore_filters)
        self.explore_empty_page.set_child(reset_button)

        self.explore_grid = Gtk.Grid()
        self.explore_grid.set_column_homogeneous(True)
        self.explore_grid.set_column_spacing(10)
        self.explore_grid.set_row_spacing(10)
        self.explore_grid.set_hexpand(True)
        self.explore_grid.set_valign(Gtk.Align.START)
        self.explore_grid.add_css_class("explore-grid")

        (
            self.explore_loading_box,
            self.explore_loading_spinner,
        ) = self._build_explore_loading_footer()

        self.explore_loading_view = self._build_explore_loading_view()

        self._update_explore_genre_model()

    @staticmethod
    def _build_explore_loading_footer() -> tuple[Gtk.Box, Gtk.Spinner]:
        """Build a one-line footer that can safely be measured at text height."""
        footer = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        footer.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(16, 16)
        footer.append(spinner)
        loading_label = Gtk.Label(label=_("Loading more from TMDB…"))
        loading_label.add_css_class("dim-label")
        loading_label.add_css_class("caption")
        footer.append(loading_label)
        footer.set_visible(False)
        return footer, spinner

    @staticmethod
    def _build_explore_loading_view() -> Gtk.Box:
        """Build a stable content skeleton for an initially empty Explore feed."""
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        view.set_margin_top(24)
        view.set_margin_bottom(24)
        view.set_hexpand(True)
        view.add_css_class("explore-loading-view")

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_tooltip_text(_("Loading recommendations from TMDB"))
        status.append(spinner)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=_("Loading recommendations"), xalign=0)
        title.add_css_class("heading")
        subtitle = Gtk.Label(
            label=_("Finding films and series you might enjoy…"), xalign=0
        )
        subtitle.add_css_class("caption")
        subtitle.add_css_class("dim-label")
        copy.append(title)
        copy.append(subtitle)
        status.append(copy)
        view.append(status)

        placeholders = Gtk.FlowBox()
        placeholders.set_selection_mode(Gtk.SelectionMode.NONE)
        placeholders.set_homogeneous(True)
        placeholders.set_min_children_per_line(2)
        placeholders.set_max_children_per_line(5)
        placeholders.set_column_spacing(12)
        placeholders.set_row_spacing(12)
        placeholders.set_halign(Gtk.Align.CENTER)
        for _index in range(5):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            card.set_size_request(148, 236)
            card.add_css_class("content-skeleton-card")
            poster = Gtk.Box()
            poster.set_size_request(-1, 178)
            poster.set_vexpand(True)
            poster.add_css_class("content-skeleton-media")
            card.append(poster)
            first_line = Gtk.Box()
            first_line.set_size_request(108, 10)
            first_line.add_css_class("content-skeleton-line")
            card.append(first_line)
            second_line = Gtk.Box()
            second_line.set_size_request(72, 8)
            second_line.add_css_class("content-skeleton-line")
            second_line.add_css_class("short")
            card.append(second_line)
            placeholders.append(card)
        view.append(placeholders)
        return view

    def _build_calendar_view(self) -> None:
        """Build Calendar as a first-class content destination."""
        self.calendar_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.calendar_pane.set_hexpand(True)
        self.calendar_pane.set_vexpand(True)
        self.calendar_pane.add_css_class("main-content-pane")
        self.calendar_pane.add_css_class("calendar-pane")

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        header.set_margin_top(16)
        header.set_margin_bottom(14)
        header.set_margin_start(24)
        header.set_margin_end(24)
        title = Gtk.Label(label=_("Calendar"), xalign=0)
        title.add_css_class("title-1")
        header.append(title)

        controls = Adw.WrapBox(child_spacing=6, line_spacing=6)
        controls.set_hexpand(True)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls.append(spacer)
        self.calendar_previous_button = Gtk.Button(
            icon_name="go-previous-symbolic", tooltip_text=_("Previous month")
        )
        self.calendar_today_button = Gtk.Button(
            label=_("Today"), tooltip_text=_("Go to today")
        )
        self.calendar_next_button = Gtk.Button(
            icon_name="go-next-symbolic", tooltip_text=_("Next month")
        )
        self.calendar_refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text=_("Refresh Calendar")
        )
        for button in (
            self.calendar_previous_button,
            self.calendar_today_button,
            self.calendar_next_button,
            self.calendar_refresh_button,
        ):
            button.update_property([Gtk.AccessibleProperty.LABEL], [button.get_tooltip_text()])
            button.add_css_class("flat")
            controls.append(button)
        header.append(controls)

        month_bar = Gtk.CenterBox()
        month_bar.set_margin_start(24)
        month_bar.set_margin_end(24)
        month_bar.set_margin_bottom(10)
        self.calendar_month_label = Gtk.Label()
        self.calendar_month_label.add_css_class("title-2")
        month_bar.set_center_widget(self.calendar_month_label)
        self.calendar_updated_label = Gtk.Label(xalign=1)
        self.calendar_updated_label.add_css_class("caption")
        self.calendar_updated_label.add_css_class("dim-label")
        month_bar.set_end_widget(self.calendar_updated_label)
        header.append(month_bar)
        self.calendar_pane.append(header)
        self.calendar_pane.append(Gtk.Separator())

        self.calendar_scroller = Gtk.ScrolledWindow()
        self.calendar_scroller.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC
        )
        self.calendar_scroller.set_vexpand(True)
        self.calendar_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18
        )
        self.calendar_content.set_margin_top(16)
        self.calendar_content.set_margin_bottom(24)
        self.calendar_content.set_margin_start(24)
        self.calendar_content.set_margin_end(24)
        self.calendar_scroller.set_child(self.calendar_content)
        self.calendar_pane.append(self.calendar_scroller)

        self.calendar_previous_button.connect("clicked", self._on_calendar_previous)
        self.calendar_today_button.connect("clicked", self._on_calendar_today)
        self.calendar_next_button.connect("clicked", self._on_calendar_next)
        self.calendar_refresh_button.connect(
            "clicked", lambda *_args: self._start_calendar_refresh(True)
        )
        self.browser_stack.add_named(self.calendar_pane, "calendar")
        self._render_calendar()

    def _calendar_display_timezone(self) -> str | None:
        account = self.simkl_settings.get("account", {})
        if isinstance(account, dict):
            value = account.get("timezone")
            return str(value) if value else None
        return None

    def _start_calendar_refresh(
        self,
        force: bool = False,
        *,
        supersede: bool = False,
    ) -> bool:
        if self._calendar_refresh_inflight:
            if not supersede:
                return GLib.SOURCE_REMOVE
            # Month navigation must not be blocked by a request for the month
            # that was previously visible. Invalidate that request so its
            # eventual result cannot replace the newly selected month.
            self._calendar_generation += 1
            self._calendar_refresh_inflight = False
        if self.library_mode == LIBRARY_MODE_LOCAL:
            if self.active_destination == "calendar":
                self._render_calendar()
            return GLib.SOURCE_REMOVE
        if not self.simkl_client_id:
            if self.active_destination == "calendar":
                self._render_calendar()
            return GLib.SOURCE_REMOVE
        self._calendar_refresh_inflight = True
        self._calendar_generation += 1
        generation = self._calendar_generation
        self.calendar_refresh_button.set_sensitive(False)
        self.calendar_refresh_button.set_icon_name("process-working-symbolic")
        if self.calendar_snapshot is None:
            self._render_calendar(loading=True)
        year, month = self.calendar_month.year, self.calendar_month.month
        client_id = self.simkl_client_id
        display_timezone = self._calendar_display_timezone()

        def worker() -> None:
            try:
                result, warning = CalendarController(simkl_client).fetch_month(
                    client_id or "", year, month, display_timezone, force
                )
                self._post_ui(
                    self._finish_calendar_refresh, generation, result, warning
                )
            except simkl_client.SimklError as error:
                self._post_ui(
                    self._finish_calendar_refresh, generation, None, str(error)
                )

        self._start_worker('simkl-calendar', worker, *())
        return GLib.SOURCE_REMOVE

    @persisted_change
    def _finish_calendar_refresh(
        self,
        generation: int,
        snapshot: simkl_client.CalendarSnapshot | None,
        error: str | None,
    ) -> bool:
        if generation != self._calendar_generation:
            return GLib.SOURCE_REMOVE
        self._calendar_refresh_inflight = False
        self.calendar_refresh_button.set_sensitive(True)
        self.calendar_refresh_button.set_icon_name("view-refresh-symbolic")
        if snapshot is not None:
            self.calendar_snapshot = snapshot
            self.settings_calendar_cache_row.set_subtitle(
                self._calendar_cache_subtitle()
            )
        if error:
            self._app_log("Calendar refresh failed: %s", error, level=logging.WARNING)
            if self.calendar_snapshot is not None:
                self._toast(_("Calendar refresh failed; showing cached schedule"))
        self._render_calendar(error=error)
        return GLib.SOURCE_REMOVE

    def _reset_calendar_timeline(self) -> None:
        self.calendar_timeline_limit = CALENDAR_TIMELINE_PAGE_SIZE

    @staticmethod
    def _shift_month(month: date, offset: int) -> date:
        index = month.year * 12 + month.month - 1 + offset
        return date(index // 12, index % 12 + 1, 1)

    @persisted_change
    def _on_calendar_previous(self, _button: Gtk.Button) -> None:
        self.calendar_month = self._shift_month(self.calendar_month, -1)
        self.calendar_selected_date = self.calendar_month
        self._reset_calendar_timeline()
        self.calendar_snapshot = None
        self._start_calendar_refresh(False, supersede=True)

    @persisted_change
    def _on_calendar_next(self, _button: Gtk.Button) -> None:
        self.calendar_month = self._shift_month(self.calendar_month, 1)
        self.calendar_selected_date = self.calendar_month
        self._reset_calendar_timeline()
        self.calendar_snapshot = None
        self._start_calendar_refresh(False, supersede=True)

    @persisted_change
    def _on_calendar_today(self, _button: Gtk.Button) -> None:
        today = datetime.now().astimezone().date()
        month_changed = self.calendar_month != today.replace(day=1)
        self.calendar_month = today.replace(day=1)
        self.calendar_selected_date = today
        self._reset_calendar_timeline()
        if month_changed:
            self.calendar_snapshot = None
            self._start_calendar_refresh(False, supersede=True)
        else:
            self._render_calendar()

    def _calendar_record(self, event: simkl_client.CalendarEvent) -> TitleRecord | None:
        group = event.media_type
        expected = f"simkl-{group}-{event.simkl_id}"
        record = self.records_by_id.get(expected)
        if record is not None:
            return record
        for candidate in self.records:
            if getattr(candidate, "simkl_id", None) == event.simkl_id or (
                candidate.id.startswith("simkl-")
                and candidate.id.endswith(f"-{event.simkl_id}")
            ):
                return candidate
        title = event.title
        if title.tmdb_id is not None:
            namespace = "movie" if group == "movies" else "tv"
            canonical = self._tmdb_record_aliases.get((namespace, title.tmdb_id))
            if canonical:
                return self._record_for_canonical_id(canonical)
            tmdb_record = next(
                (
                    item
                    for item in (*self.records, *self.explore_records)
                    if self._tmdb_identity(item) == (namespace, title.tmdb_id)
                ),
                None,
            )
            if tmdb_record is not None:
                return tmdb_record
        candidates = (*self.records, *self.explore_records)
        external_matches = (
            ("imdb_id", title.imdb_id),
            ("tvdb_id", title.tvdb_id),
            ("mal_id", title.mal_id),
        )
        for attribute, value in external_matches:
            if value is None:
                continue
            match = next(
                (
                    item
                    for item in candidates
                    if getattr(item, attribute, None) == value
                    and (
                        (group == "movies" and item.media_type == "Movies")
                        or (group == "shows" and item.media_type == "Shows")
                        or (group == "anime" and item.media_type == "Anime")
                    )
                ),
                None,
            )
            if match is not None:
                return match
        normalized_title = " ".join(title.title.casefold().split())
        return next(
            (
                item
                for item in candidates
                if " ".join(item.title.casefold().split()) == normalized_title
                and (
                    (group == "movies" and item.media_type == "Movies")
                    or (group == "shows" and item.media_type == "Shows")
                    or (group == "anime" and item.media_type == "Anime")
                )
            ),
            None,
        )

    def _calendar_events(self):
        return CalendarController.visible_events(
            self.calendar_snapshot, self.calendar_month, self._calendar_record,
            self._calendar_record_is_in_library, self._effective_status,
        )

    def _calendar_record_is_in_library(self, record: TitleRecord) -> bool:
        canonical = self._canonical_record_id(record)
        return (
            record.id in self.library_ids
            or canonical in self._library_records_by_canonical
            or canonical in self.bookmarks
            or canonical in self.completed
            or canonical in self.status_overrides
        )

    def _calendar_eligible_library_count(self) -> int:
        seen: set[str] = set()
        for record in self.records:
            status = self._effective_status(record)
            if status in {"Watching", "Watchlist", "On Hold"}:
                seen.add(self._canonical_record_id(record))
        return len(seen)

    @staticmethod
    def _calendar_events_by_day(events):
        return CalendarController.group_days(events)

    @staticmethod
    def _calendar_day_heading(day: date, *, today: date | None = None) -> str:
        reference = today or datetime.now().astimezone().date()
        relative = {
            -1: _("Yesterday"),
            0: _("Today"),
            1: _("Tomorrow"),
        }.get((day - reference).days)
        absolute = day.strftime("%B %-d, %Y")
        week = day.isocalendar().week
        parts = [absolute, _("Week {week}").format(week=week), day.strftime("%A")]
        if relative:
            parts.insert(0, relative)
        return " • ".join(parts)

    @staticmethod
    def _calendar_day_summary(
        events: tuple[simkl_client.CalendarEvent, ...],
    ) -> str:
        count = len(events)
        minutes = sum(runtime_minutes(event.title.runtime or "") for event in events)
        releases = ngettext("{count} release", "{count} releases", count).format(count=count)
        if not minutes:
            return releases
        hours, remainder = divmod(minutes, 60)
        duration = (
            _("{hours}h {minutes:02d}m").format(hours=hours, minutes=remainder)
            if hours and remainder
            else _("{hours}h").format(hours=hours)
            if hours
            else _("{minutes}m").format(minutes=remainder)
        )
        return f"{releases} • {duration}"

    @staticmethod
    def _calendar_timeline_page(groups, limit):
        return CalendarController.page(groups, limit)

    def _calendar_skeleton(self) -> Gtk.Box:
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_accessible_role(Gtk.AccessibleRole.STATUS)
        for _index in range(6):
            row = Gtk.Box()
            row.set_size_request(-1, 64)
            row.add_css_class("calendar-skeleton")
            shell.append(row)
        return shell

    def _calendar_status(
        self,
        icon: str,
        title: str,
        description: str,
        action: str | None = None,
        callback: Any = None,
    ) -> Gtk.Box:
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        shell.set_halign(Gtk.Align.CENTER)
        shell.set_valign(Gtk.Align.CENTER)
        shell.set_vexpand(True)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(64)
        image.add_css_class("dim-label")
        shell.append(image)
        heading = Gtk.Label(label=title)
        heading.add_css_class("title-2")
        shell.append(heading)
        body = Gtk.Label(label=description, justify=Gtk.Justification.CENTER, wrap=True)
        body.set_max_width_chars(48)
        body.add_css_class("dim-label")
        shell.append(body)
        if action and callback:
            button = Gtk.Button(label=action)
            button.set_halign(Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.connect("clicked", callback)
            shell.append(button)
        return shell

    def _open_preferences_from_calendar(self, _button: Gtk.Button) -> None:
        self.settings_dialog.present(self.window)

    def _open_explore_from_calendar(self, _button: Gtk.Button) -> None:
        self.destination_list.select_row(self.explore_row)

    def _calendar_timeline(
        self, events: tuple[simkl_client.CalendarEvent, ...]
    ) -> Gtk.Box:
        """Build one responsive timeline, grouped by each event's local day."""
        timeline = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        timeline.add_css_class("calendar-timeline")
        groups = self._calendar_events_by_day(events)
        limit = max(
            CALENDAR_TIMELINE_PAGE_SIZE,
            getattr(self, "calendar_timeline_limit", CALENDAR_TIMELINE_PAGE_SIZE),
        )
        visible_groups, shown = self._calendar_timeline_page(groups, limit)
        for day, day_events in visible_groups:
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
            section.add_css_class("calendar-day-section")

            header = Gtk.Box(spacing=8)
            header.add_css_class("calendar-day-header")
            heading = Gtk.Label(
                label=self._calendar_day_heading(day),
                xalign=0,
            )
            heading.set_hexpand(True)
            heading.set_wrap(True)
            heading.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            heading.add_css_class("heading")
            if day == datetime.now().astimezone().date():
                heading.add_css_class("accent")
            header.append(heading)
            summary = Gtk.Label(
                label=self._calendar_day_summary(day_events),
                xalign=1,
            )
            summary.add_css_class("caption")
            summary.add_css_class("dim-label")
            summary.set_valign(Gtk.Align.CENTER)
            header.append(summary)
            section.append(header)
            section.append(Gtk.Separator())

            releases = Gtk.ListBox()
            releases.set_selection_mode(Gtk.SelectionMode.NONE)
            releases.set_show_separators(True)
            releases.add_css_class("boxed-list")
            releases.add_css_class("calendar-release-list")
            row_events: dict[Gtk.ListBoxRow, simkl_client.CalendarEvent] = {}
            for event in day_events:
                list_row = Gtk.ListBoxRow()
                list_row.set_activatable(True)
                list_row.set_selectable(False)
                list_row.add_css_class("calendar-timeline-row")
                list_row.set_child(self._calendar_event_row(event))
                releases.append(list_row)
                row_events[list_row] = event
            releases.connect(
                "row-activated",
                lambda _list, row, values=row_events: self._open_calendar_event(
                    values[row]
                ),
            )
            section.append(releases)
            timeline.append(section)

        if shown < len(events):
            remaining = len(events) - shown
            load_more = Gtk.Button(label=_("Load more releases ({remaining} remaining)").format(remaining=remaining))
            load_more.set_halign(Gtk.Align.CENTER)
            load_more.add_css_class("pill")
            load_more.connect("clicked", self._on_calendar_load_more)
            timeline.append(load_more)
        self.calendar_timeline_visible_count = shown
        return timeline

    @persisted_change
    def _on_calendar_load_more(self, _button: Gtk.Button) -> None:
        self.calendar_timeline_limit = (
            getattr(self, "calendar_timeline_limit", CALENDAR_TIMELINE_PAGE_SIZE)
            + CALENDAR_TIMELINE_PAGE_SIZE
        )
        self._render_calendar()

    def _calendar_event_row(self, event):
        record = self._calendar_record(event)
        library_record = record if record is not None and self._calendar_record_is_in_library(record) else None
        poster = self._create_poster_overlay(record, 76, 114) if record is not None else self._calendar_poster_overlay(event.title, 76, 114)
        return build_calendar_row(
            event, record, library_record, poster,
            configure_label=self._configure_bounded_card_label,
            effective_status=self._effective_status,
            can_add=self._simkl_writable(), on_add=self._add_calendar_watchlist,
        )

    def _open_calendar_event(self, event: simkl_client.CalendarEvent) -> None:
        record = self._calendar_record(event)
        if record is not None:
            self._open_calendar_record(record)
        elif event.title.url:
            self._open_calendar_uri(event.title.url)

    def _calendar_poster_overlay(
        self,
        title: simkl_client.CalendarTitle,
        width: int,
        height: int,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        overlay.set_size_request(width, height)
        overlay.set_hexpand(False)
        overlay.set_halign(Gtk.Align.CENTER)
        overlay.set_valign(Gtk.Align.START)
        overlay.set_child(self._calendar_poster(title, width, height))
        if title.rating is not None:
            rating = Gtk.Label(label=f"{title.rating:.1f}")
            rating.set_halign(Gtk.Align.START)
            rating.set_valign(Gtk.Align.START)
            rating.set_margin_top(4)
            rating.set_margin_start(4)
            rating.add_css_class("row-rating")
            rating.add_css_class("numeric")
            overlay.add_overlay(rating)
        return overlay

    def _calendar_poster(
        self,
        title: simkl_client.CalendarTitle,
        width: int,
        height: int,
    ) -> Gtk.Widget:
        picture = Gtk.Picture()
        picture.set_size_request(width, height)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.add_css_class("calendar-poster")
        picture.add_css_class("rounded-media")
        picture.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Poster artwork for {title}").format(title=title.title)]
        )
        cached = simkl_client.cached_calendar_poster(title)
        if cached:
            picture.set_filename(cached)
            return picture
        if title.simkl_id in self._calendar_posters_loading:
            return picture
        self._calendar_posters_loading.add(title.simkl_id)

        def worker() -> None:
            path = simkl_client.fetch_calendar_poster(title)
            self._post_ui(finish, path)

        def finish(path: str | None) -> bool:
            self._calendar_posters_loading.discard(title.simkl_id)
            if path and picture.get_root() is not None:
                picture.set_filename(path)
            return GLib.SOURCE_REMOVE

        self._start_worker(f'calendar-poster-{title.simkl_id}', worker, *())
        return picture

    def _open_calendar_record(self, record: TitleRecord) -> None:
        self.selected_id = record.id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(record)

    def _open_calendar_uri(self, uri: str) -> None:
        if not uri:
            return
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as error:
            self._app_log(
                "Could not open Calendar link: %s", error, level=logging.WARNING
            )
            self._toast(_("Could not open this Simkl page"))

    def _open_external_uri_with_warning(
        self,
        uri: str,
        *,
        heading: str,
        body: str,
    ) -> None:
        if not uri:
            return
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("open", _("Open in Browser"))
        dialog.set_close_response("cancel")
        dialog.set_default_response("open")
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)

        def respond(_dialog: Adw.AlertDialog, response: str) -> None:
            if response != "open":
                return
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            except GLib.Error as error:
                self._app_log(
                    "Could not open external link: %s",
                    error,
                    level=logging.WARNING,
                )
                self._toast(_("Could not open the link in your browser"))

        dialog.connect("response", respond)
        dialog.present(self.window)

    def _add_calendar_watchlist(
        self, button: Gtk.Button, event: simkl_client.CalendarEvent
    ) -> None:
        if not self._simkl_writable():
            self._toast(_("Connect Simkl to add this title"))
            return
        button.set_sensitive(False)
        group = {"movies": "movies", "shows": "shows", "anime": "anime"}[
            event.media_type
        ]
        self._run_simkl_mutation(
            f"calendar-{group}-{event.simkl_id}:watchlist",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.set_list_status(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    group,
                    {"simkl": event.simkl_id},
                    "plantowatch",
                )
            ),
            lambda: self._start_simkl_sync(),
            _("Added to Simkl watchlist"),
        )

    def _render_calendar(
        self, *, loading: bool = False, error: str | None = None
    ) -> None:
        if not hasattr(self, "calendar_content"):
            return
        self._clear_container(self.calendar_content)
        self.calendar_month_label.set_label(self.calendar_month.strftime("%B %Y"))
        snapshot = self.calendar_snapshot
        if snapshot is not None:
            updated = _("Updated {date}").format(date=snapshot.fetched_at.astimezone().strftime("%x %X"))
            if snapshot.stale:
                updated = _("Showing cached schedule · {updated}").format(updated=updated)
            self.calendar_updated_label.set_label(updated)
            self.calendar_updated_label.set_tooltip_text(
                self._calendar_cache_subtitle()
            )
        else:
            self.calendar_updated_label.set_label("")
        if self.library_mode == LIBRARY_MODE_LOCAL:
            action = _("Use Simkl") if self.simkl_client_id else None
            callback = (
                (lambda *_args: self.set_library_mode(LIBRARY_MODE_SIMKL))
                if self.simkl_client_id
                else None
            )
            self.calendar_content.append(
                self._calendar_status(
                    "drive-harddisk-symbolic",
                    _("Local-first mode is active"),
                    _(
                        "Calendar downloads use Simkl. Your local library remains fully "
                        "available without connecting an account."
                    ),
                    action,
                    callback,
                )
            )
            return
        if not self.simkl_client_id:
            self.calendar_content.append(
                self._calendar_status(
                    "dialog-error-symbolic",
                    _("Simkl integration is unavailable"),
                    _(
                        "This build does not include Gisheh's public Simkl application ID."
                    ),
                )
            )
            return
        if loading and snapshot is None:
            self.calendar_content.append(self._calendar_skeleton())
            return
        if snapshot is None:
            self.calendar_content.append(
                self._calendar_status(
                    "network-offline-symbolic",
                    _("Calendar is unavailable"),
                    error
                    or _(
                        "No cached schedule is available. "
                        "Check your connection and try again."
                    ),
                    _("Retry"),
                    lambda *_args: self._start_calendar_refresh(True),
                )
            )
            return
        if snapshot.unavailable:
            self.calendar_content.append(
                self._calendar_status(
                    "x-office-calendar-symbolic",
                    _("Schedule not published"),
                    _("Simkl has not published this month yet."),
                )
            )
            return
        events = self._calendar_events()
        if not events:
            eligible_count = self._calendar_eligible_library_count()
            self.calendar_content.append(
                self._calendar_status(
                    "bookmark-new-symbolic",
                    _("Nothing scheduled in My Calendar"),
                    _(
                        "No events are published this month for the matching titles "
                        "in your library ({count}). Watching, Watchlist, and On Hold "
                        "titles appear as soon as Simkl schedules them."
                    ).format(count=eligible_count),
                    _("Open Explore"),
                    self._open_explore_from_calendar,
                )
            )
            return
        self.calendar_timeline_view = self._calendar_timeline(events)
        self.calendar_content.append(self.calendar_timeline_view)

    def _build_profile_view(self) -> None:
        from .profile import ProfileView

        self.profile_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.profile_pane.add_css_class("main-content-pane")
        self.profile_scroller = Gtk.ScrolledWindow(vexpand=True)
        self.profile_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.profile_pane.append(self.profile_scroller)
        clamp = Adw.Clamp(maximum_size=680, tightening_threshold=520)
        for side in ("start", "end"):
            getattr(clamp, f"set_margin_{side}")(18)
        clamp.set_margin_top(32)
        clamp.set_margin_bottom(36)
        self.profile_scroller.set_child(clamp)
        self.profile_view = ProfileView(
            on_preferences=lambda: self._on_preferences_clicked(None),
            on_explore=lambda: self.destination_list.select_row(self.explore_row),
        )
        clamp.set_child(self.profile_view)
        self._update_profile_identity()
        self.browser_stack.add_named(self.profile_pane, "profile")
        self._refresh_profile()

    def _build_settings_dialog(self) -> None:
        """Build a native searchable GNOME preferences dialog."""
        self.settings_dialog = Adw.PreferencesDialog(title=_("Preferences"))
        self.settings_dialog.set_search_enabled(True)

        general_page = Adw.PreferencesPage(
            title=_("General"),
            icon_name="applications-system-symbolic",
        )
        services_page = Adw.PreferencesPage(
            title=_("Services"),
            icon_name="network-workgroup-symbolic",
        )

        ownership = Adw.PreferencesGroup(
            title=_("Data ownership"),
            description=_("Choose where Gisheh keeps your personal library state."),
        )
        self.settings_library_mode_row = Adw.ActionRow(title=_("Library mode"))
        self.settings_library_mode_button = Gtk.Button(label=_("Change…"))
        self.settings_library_mode_button.set_valign(Gtk.Align.CENTER)
        self.settings_library_mode_button.connect(
            "clicked", self._on_change_library_mode_clicked
        )
        self.settings_library_mode_row.add_suffix(self.settings_library_mode_button)
        ownership.add(self.settings_library_mode_row)
        general_page.add(ownership)
        from .data_actions import LibraryDataActions
        self.data_actions = LibraryDataActions(self)
        self.data_actions.add_to(general_page)

        appearance = Adw.PreferencesGroup(
            title=_("Appearance"),
            description=_("Choose how Gisheh looks on this device."),
        )
        self.settings_color_scheme_row = Adw.ComboRow(
            title=_("Color scheme"),
            subtitle=_("Use the system style or override it for Gisheh."),
        )
        self.settings_color_scheme_row.set_model(
            Gtk.StringList.new([_(label) for label in COLOR_SCHEME_LABELS])
        )
        self.settings_color_scheme_row.set_selected(
            COLOR_SCHEMES.index(self.color_scheme)
        )
        self.settings_color_scheme_row.connect(
            "notify::selected", self._on_settings_color_scheme_changed
        )
        appearance.add(self.settings_color_scheme_row)

        general_page.add(appearance)

        content = Adw.PreferencesGroup(
            title=_("TMDB content"),
            description=_("Choose the language of titles and descriptions. The interface follows your system language."),
        )
        self.settings_content_language_row = Adw.ComboRow(
            title=_("Content language"),
            subtitle=_("Missing translations fall back to English. Changes apply immediately."),
            enable_search=True,
        )
        self._content_languages_loading = False
        self._content_language_options = []
        self._set_content_language_options(tmdb_client.cached_languages())
        self.settings_content_language_row.connect(
            "notify::selected", self._on_settings_content_language_changed
        )
        content.add(self.settings_content_language_row)
        self.settings_languages_status_row = Adw.ActionRow(title=_("TMDB languages"))
        retry_languages = Gtk.Button(label=_("Refresh"), valign=Gtk.Align.CENTER)
        retry_languages.connect("clicked", lambda _button: self._load_content_languages())
        self.settings_languages_status_row.add_suffix(retry_languages)
        content.add(self.settings_languages_status_row)
        general_page.add(content)
        self.settings_dialog.connect("notify::visible", self._on_preferences_visible)

        library = Adw.PreferencesGroup(
            title=_("Library"),
            description=_("Set the view Gisheh uses when it starts."),
        )
        self.settings_media_row = Adw.ComboRow(
            title=_("Default media type"),
            subtitle=_("Open this catalog first on the next launch."),
        )
        self.settings_media_row.set_model(
            Gtk.StringList.new([_(media) for media in MEDIA_TYPES])
        )
        self.settings_media_row.set_selected(MEDIA_TYPES.index(self.default_media))
        self.settings_media_row.connect(
            "notify::selected", self._on_settings_default_media_changed
        )
        library.add(self.settings_media_row)

        self.settings_view_row = Adw.ComboRow(
            title=_("Library layout"),
            subtitle=_("Choose between the compact list and poster grid."),
        )
        self.settings_view_row.set_model(Gtk.StringList.new(["List", "Grid"]))
        self.settings_view_row.set_selected(
            0 if self.preferred_view_mode == "list" else 1
        )
        self.settings_view_row.connect(
            "notify::selected", self._on_settings_view_changed
        )
        library.add(self.settings_view_row)
        general_page.add(library)

        accounts = Adw.PreferencesGroup(
            title=_("Accounts &amp; Sync"),
            description=_("Gisheh uses Simkl for your library and TMDB for metadata."),
        )
        self.settings_auto_sync_row = Adw.SwitchRow(
            title=_("Sync Simkl on startup"),
            subtitle=_("Refresh cloud library state whenever Gisheh starts."),
        )
        self.settings_auto_sync_row.set_active(self.auto_sync)
        self.settings_auto_sync_row.connect(
            "notify::active", self._on_settings_auto_sync_changed
        )
        accounts.add(self.settings_auto_sync_row)

        self.settings_auto_calendar_row = Adw.SwitchRow(
            title=_("Refresh Calendar automatically"),
            subtitle=_("Use a fresh local schedule cache and update it when needed."),
        )
        self.settings_auto_calendar_row.set_active(
            getattr(self, "auto_calendar_refresh", True)
        )
        self.settings_auto_calendar_row.connect(
            "notify::active", self._on_settings_auto_calendar_changed
        )
        accounts.add(self.settings_auto_calendar_row)

        self.settings_simkl_row = Adw.ActionRow(title=_("Simkl"))
        self.settings_simkl_button = Gtk.Button()
        self.settings_simkl_button.set_valign(Gtk.Align.CENTER)
        self.settings_simkl_button.connect("clicked", self._on_simkl_button_clicked)
        self.settings_simkl_disconnect_button = Gtk.Button.new_from_icon_name(
            "system-log-out-symbolic"
        )
        self.settings_simkl_disconnect_button.set_valign(Gtk.Align.CENTER)
        self.settings_simkl_disconnect_button.set_tooltip_text(_("Disconnect Simkl"))
        self.settings_simkl_disconnect_button.add_css_class("flat")
        self.settings_simkl_disconnect_button.add_css_class("circular")
        self.settings_simkl_disconnect_button.connect(
            "clicked", self._on_simkl_disconnect_clicked
        )
        self.settings_simkl_row.add_suffix(self.settings_simkl_button)
        self.settings_simkl_row.add_suffix(self.settings_simkl_disconnect_button)
        accounts.add(self.settings_simkl_row)

        self.settings_tmdb_row = Adw.ActionRow(title=_("TMDB"))
        self.settings_tmdb_button = Gtk.Button()
        self.settings_tmdb_button.set_valign(Gtk.Align.CENTER)
        self.settings_tmdb_button.connect("clicked", self._on_tmdb_settings_clicked)
        self.settings_tmdb_disconnect_button = Gtk.Button.new_from_icon_name(
            "edit-delete-symbolic"
        )
        self.settings_tmdb_disconnect_button.set_valign(Gtk.Align.CENTER)
        self.settings_tmdb_disconnect_button.set_tooltip_text(_("Remove TMDB token"))
        self.settings_tmdb_disconnect_button.add_css_class("flat")
        self.settings_tmdb_disconnect_button.add_css_class("circular")
        self.settings_tmdb_disconnect_button.connect(
            "clicked", self._on_tmdb_disconnect_clicked
        )
        self.settings_tmdb_row.add_suffix(self.settings_tmdb_button)
        self.settings_tmdb_row.add_suffix(self.settings_tmdb_disconnect_button)
        accounts.add(self.settings_tmdb_row)
        services_page.add(accounts)

        data = Adw.PreferencesGroup(
            title=_("Data &amp; Diagnostics"),
            description=_(
                "Manage reproducible downloads and troubleshooting information."
            ),
        )
        self.settings_cache_row = Adw.ActionRow(
            title=_("Downloaded TMDB data"),
            subtitle=_("Posters, backdrops, cast photos and metadata cache."),
        )
        clear_cache = Gtk.Button(label=_("Clear Cache"))
        clear_cache.set_valign(Gtk.Align.CENTER)
        clear_cache.connect("clicked", self._on_clear_cache_clicked)
        self.settings_cache_row.add_suffix(clear_cache)
        self.settings_cache_row.set_activatable_widget(clear_cache)
        data.add(self.settings_cache_row)

        self.settings_calendar_cache_row = Adw.ActionRow(
            title=_("Calendar cache"),
            subtitle=self._calendar_cache_subtitle(),
        )
        clear_calendar_cache = Gtk.Button(label=_("Clear Cache"))
        clear_calendar_cache.set_valign(Gtk.Align.CENTER)
        clear_calendar_cache.connect("clicked", self._on_clear_calendar_cache_clicked)
        self.settings_calendar_cache_row.add_suffix(clear_calendar_cache)
        self.settings_calendar_cache_row.set_activatable_widget(clear_calendar_cache)
        data.add(self.settings_calendar_cache_row)

        log_row = Adw.ActionRow(
            title=_("Application Log"),
            subtitle=_("Review sync, loading and recoverable error messages."),
        )
        log_button = Gtk.Button(label=_("Open Log"))
        log_button.set_valign(Gtk.Align.CENTER)
        log_button.connect("clicked", lambda *_args: self.show_application_log())
        log_row.add_suffix(log_button)
        log_row.set_activatable_widget(log_button)
        data.add(log_row)
        services_page.add(data)

        reset_group = Adw.PreferencesGroup(
            title=_("Reset"),
            description=_("Erase local Gisheh data and return to first-run setup."),
        )
        self.settings_factory_reset_row = Adw.ActionRow(
            title=_("Reset Gisheh"),
            subtitle=_("Delete your library, preferences, accounts, caches and logs."),
        )
        self.settings_factory_reset_button = Gtk.Button(label=_("Reset…"))
        self.settings_factory_reset_button.set_valign(Gtk.Align.CENTER)
        self.settings_factory_reset_button.add_css_class("destructive-action")
        self.settings_factory_reset_button.connect(
            "clicked", self._on_factory_reset_clicked
        )
        self.settings_factory_reset_row.add_suffix(self.settings_factory_reset_button)
        self.settings_factory_reset_row.set_activatable_widget(
            self.settings_factory_reset_button
        )
        reset_group.add(self.settings_factory_reset_row)
        services_page.add(reset_group)

        self._update_settings_account_rows()
        self.settings_dialog.add(general_page)
        self.settings_dialog.add(services_page)
        self.settings_dialog.set_focus(self.settings_library_mode_button)

    def _apply_color_scheme(self) -> None:
        schemes = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        Adw.StyleManager.get_default().set_color_scheme(
            schemes.get(self.color_scheme, Adw.ColorScheme.DEFAULT)
        )

    def _refresh_sidebar_labels(self) -> None:
        """Retranslate sidebar rows so a live language switch updates them."""
        try:
            self.explore_row.set_label(_("Explore"))
            self.calendar_row.set_label(_("Calendar"))
        except AttributeError:
            pass
        for collection, _icon_name in COLLECTIONS:
            row = getattr(self, "collection_rows", {}).get(collection)
            if row is not None:
                row.set_label(_(collection))
        # Section title also follows the active collection.
        try:
            self.section_title.set_label(_(self.active_collection))
        except AttributeError:
            pass

    def _apply_text_direction(self) -> None:
        """Let navigation and child widgets follow the system text direction."""
        try:
            rtl = is_rtl_language_selection()
            direction = (
                Gtk.TextDirection.RTL if rtl else Gtk.TextDirection.LTR
            )
            Gtk.Widget.set_default_direction(direction)
            window = getattr(self, "window", None)
            if window is not None:
                window.set_direction(direction)
            workspace = getattr(self, "workspace", None)
            if workspace is None:
                workspace = self.builder.get_object("workspace")
            if workspace is not None:
                workspace.set_sidebar_position(
                    sidebar_position_for_direction(rtl)
                )
        except (AttributeError, RuntimeError):
            pass
        self._refresh_sidebar_labels()

    def _update_settings_account_rows(self, *, syncing: bool = False) -> None:
        if not hasattr(self, "settings_simkl_row"):
            return
        local_mode = (
            getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL
        )
        if hasattr(self, "settings_library_mode_row"):
            self.settings_library_mode_row.set_subtitle(
                _("Local-first · Personal data stays on this device")
                if local_mode
                else _("Simkl sync · Simkl manages lists, ratings and watch history")
            )
        if local_mode:
            simkl_subtitle = _("Not active · Local-first mode is managing this library")
        elif self.simkl_connected:
            simkl_subtitle = _("Connected · Library and watch state sync enabled")
        elif getattr(self, "simkl_client_id", None):
            simkl_subtitle = _("Ready to connect · Sign in with a Simkl PIN")
        else:
            simkl_subtitle = _("Unavailable · This build has no Simkl application ID")
        self.settings_simkl_row.set_subtitle(simkl_subtitle)
        self.settings_simkl_button.set_label(
            _("Syncing…")
            if syncing
            else (
                _("Use Simkl")
                if local_mode and getattr(self, "simkl_client_id", None)
                else _("Unavailable")
                if local_mode
                else _("Sync Now")
                if self.simkl_connected
                else (
                    _("Connect")
                    if getattr(self, "simkl_client_id", None)
                    else _("Unavailable")
                )
            )
        )
        self.settings_simkl_button.set_sensitive(
            not syncing and bool(getattr(self, "simkl_client_id", None))
        )
        self.settings_simkl_disconnect_button.set_visible(
            self.simkl_connected and not local_mode
        )
        self.settings_simkl_disconnect_button.set_sensitive(not syncing)

        tmdb_source = (
            tmdb_client.token_source() if getattr(self, "tmdb_token", None) else None
        )
        if getattr(self, "tmdb_token", None) and tmdb_source is None:
            tmdb_source = "user"
        if tmdb_source == "bundled":
            tmdb_subtitle = _("Connected · Credential provided by this build")
        elif tmdb_source == "environment":
            tmdb_subtitle = _("Connected · Developer environment override")
        elif tmdb_source == "user":
            tmdb_subtitle = _("Connected · Developer token stored for this user")
        else:
            tmdb_subtitle = _("Unavailable · This build has no TMDB credential")
        self.settings_tmdb_row.set_subtitle(tmdb_subtitle)
        self.settings_tmdb_button.set_label(
            _("Data Source")
            if tmdb_source in {"bundled", "environment"}
            else (_("Change Token") if tmdb_source == "user" else _("Developer Setup"))
        )
        self.settings_tmdb_disconnect_button.set_visible(tmdb_source == "user")

    @persisted_change
    def _on_settings_color_scheme_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        self.color_scheme = COLOR_SCHEMES[row.get_selected()]
        self._apply_color_scheme()
        self._save_user_state()

    @persisted_change
    def _on_change_library_mode_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Choose how your library is managed"),
            body=(
                _(
                    "Local-first keeps lists, ratings and watch history on this device. "
                    "Simkl sync uses your Simkl account as the shared library source. "
                    "Changing mode does not delete the saved local copy."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("local", _("Use Local-first"))
        if self.simkl_client_id:
            dialog.add_response("simkl", _("Use Simkl"))
        dialog.set_close_response("cancel")
        dialog.set_default_response(
            self.library_mode
            if self.library_mode == LIBRARY_MODE_LOCAL or self.simkl_client_id
            else LIBRARY_MODE_LOCAL
        )

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response in LIBRARY_MODES:
                self.set_library_mode(response)

        dialog.connect("response", on_response)
        dialog.present(self.settings_dialog)

    @persisted_change
    def _on_settings_default_media_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        self.default_media = MEDIA_TYPES[row.get_selected()]
        self._save_user_state()

    def _on_preferences_visible(self, dialog, _parameter) -> None:
        if dialog.get_visible():
            self._load_content_languages()

    def _set_content_language_options(self, languages) -> None:
        selected = getattr(self, "content_language", "system")
        options = [("system", _("System Language")), *languages]
        if selected not in {code for code, _label in options}:
            options.append((selected, selected))
        self._updating_content_languages = True
        try:
            self._content_language_options = [code for code, _label in options]
            self.settings_content_language_row.set_model(
                Gtk.StringList.new([label for _code, label in options])
            )
            self.settings_content_language_row.set_selected(
                self._content_language_options.index(selected)
            )
        finally:
            self._updating_content_languages = False

    def _load_content_languages(self) -> None:
        if self._content_languages_loading:
            return
        token = self.tmdb_token
        if not token:
            self.settings_languages_status_row.set_subtitle(_("Connect TMDB to load its language list."))
            return
        self._content_languages_loading = True
        self.settings_languages_status_row.set_subtitle(_("Loading languages…"))

        def worker():
            try:
                languages = tmdb_client.fetch_languages(token)
            except tmdb_client.TmdbError:
                self._post_ui(finish, None)
            else:
                self._post_ui(finish, languages)

        def finish(languages):
            self._content_languages_loading = False
            if languages is None:
                self.settings_languages_status_row.set_subtitle(_("Could not load languages. Check your connection and try again."))
            else:
                self._set_content_language_options(languages)
                self.settings_languages_status_row.set_subtitle(_("Language list updated from TMDB."))
            return GLib.SOURCE_REMOVE

        self._start_worker("gisheh-tmdb-languages", worker)

    @persisted_change
    def _on_settings_content_language_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        """Apply the TMDB content language without changing the interface."""
        if getattr(self, "_updating_content_languages", False):
            return
        try:
            language = self._content_language_options[row.get_selected()]
        except IndexError:
            return
        if language == getattr(self, "content_language", "system"):
            return
        previous = getattr(self, "content_language", "system")
        self.content_language = language
        try:
            tmdb_client.set_content_language(language)
        except (AttributeError, ValueError):
            pass
        # Persist only the new content language; all other preferences stay
        # untouched because _save_user_state rewrites the same payload shape.
        try:
            self._save_user_state()
        except OSError:
            self.content_language = previous
            try:
                tmdb_client.set_content_language(previous)
            except (AttributeError, ValueError):
                pass
            row.set_selected(self._content_language_options.index(previous))
            self._toast(_("Could not save the content language"))
            return
        self._refresh_tmdb_content_language()
        self._toast(_("Content language updated"))

    def _refresh_tmdb_content_language(self) -> None:
        """Reload language-dependent TMDB data after a content-language change.

        The on-disk metadata cache is already keyed by
        resource ID + content type + language, so differently localized
        payloads coexist. Here we only invalidate the in-memory language
        state and re-request every active page in the new language.
        """
        for name in (
            "_tmdb_details_loading",
            "_tmdb_details_loaded",
            "_tmdb_episode_details_loading",
            "_tmdb_episode_details_loaded",
            "_tmdb_season_details_loading",
            "_tmdb_season_details_loaded",
        ):
            try:
                getattr(self, name).clear()
            except AttributeError:
                pass
        # Invalidate in-flight generations so stale-language workers are dropped.
        self._tmdb_library_generation += 1
        self._tmdb_search_generation += 1
        self._tmdb_explore_generation += 1
        for record_id in list(getattr(self, "_tmdb_detail_generations", {})):
            self._tmdb_detail_generations[record_id] += 1
        try:
            self._app_log(
                "TMDB content language changed to %s; reloading active pages.",
                tmdb_client.active_language(),
            )
        except AttributeError:
            pass
        if getattr(self, "tmdb_token", None):
            try:
                self._load_tmdb_explore_async()
            except (AttributeError, RuntimeError, TypeError):
                pass
            # Re-enrich the visible library summaries in the new language.
            try:
                records = tuple(
                    record
                    for record in getattr(self, "records", ())
                    if getattr(record, "tmdb_id", None) is not None
                )[:24]
                if records:
                    self._load_tmdb_library_async(records)
            except (AttributeError, RuntimeError, TypeError):
                pass
        # Reload the open details page, if any, in the new language.
        try:
            record_id = getattr(self, "detail_record_id", None) or getattr(
                self, "selected_id", None
            )
            record = (getattr(self, "records_by_id", {}) or {}).get(record_id)
            if record is not None:
                self._load_tmdb_details_async(record)
        except (AttributeError, RuntimeError, TypeError):
            pass

    @persisted_change
    def _on_settings_view_changed(self, row: Adw.ComboRow, _parameter: Any) -> None:
        self.preferred_view_mode = ("list", "grid")[row.get_selected()]
        self.view_mode = self.preferred_view_mode
        self._updating = True
        self.view_switcher.set_active_name(self.view_mode)
        self._updating = False
        self._refresh_results()
        self._save_view_mode_preference()
        self._save_user_state()

    @persisted_change
    def _on_settings_auto_sync_changed(
        self, row: Adw.SwitchRow, _parameter: Any
    ) -> None:
        self.auto_sync = row.get_active()
        self._save_user_state()

    @persisted_change
    def _on_settings_auto_calendar_changed(
        self, row: Adw.SwitchRow, _parameter: Any
    ) -> None:
        self.auto_calendar_refresh = row.get_active()
        self._save_user_state()

    def _calendar_cache_subtitle(self) -> str:
        snapshot = getattr(self, "calendar_snapshot", None)
        if snapshot is None:
            return _("No schedule has been cached yet.")
        local = snapshot.fetched_at.astimezone()
        return _("Last refreshed {date}").format(date=local.strftime("%x %X"))

    def _on_clear_calendar_cache_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Clear Calendar cache?"),
            body=(
                _(
                    "Downloaded Simkl schedules will be removed. Gisheh can "
                    "download them again when Calendar is opened."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear Cache"))
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_calendar_cache_response)
        dialog.present(self.settings_dialog)

    @persisted_change
    def _on_clear_calendar_cache_response(
        self, _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "clear":
            return
        try:
            simkl_client.clear_calendar_cache()
        except simkl_client.SimklError as error:
            self._app_log(
                "Could not clear Calendar cache: %s", error, level=logging.ERROR
            )
            self._toast(_("Could not clear the Calendar cache"))
            return
        self.calendar_snapshot = None
        self.settings_calendar_cache_row.set_subtitle(self._calendar_cache_subtitle())
        if self.active_destination == "calendar":
            self._render_calendar()
        self._toast(_("Calendar cache cleared"))

    def _on_clear_cache_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Clear downloaded TMDB data?"),
            body=(
                _(
                    "Downloaded posters, backdrops, cast photos and metadata will "
                    "be removed. Gisheh can download them again when needed."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear Cache"))
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_cache_response)
        dialog.present(self.settings_dialog)

    def _on_clear_cache_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "clear":
            return
        try:
            tmdb_client.clear_cache()
        except tmdb_client.TmdbError as error:
            self._app_log("Could not clear TMDB cache: %s", error, level=logging.ERROR)
            self._toast(_("Could not clear the TMDB cache"))
            return
        self._tmdb_details_loaded.clear()
        self._tmdb_episode_details_loaded.clear()
        self._tmdb_season_details_loaded.clear()
        self._app_log("Downloaded TMDB image and metadata cache cleared.")
        self._toast(_("TMDB cache cleared"))

    def _on_factory_reset_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Reset Gisheh completely?"),
            body=(
                _(
                    "Your local library, watch history, ratings, preferences, "
                    "connected accounts, downloaded artwork, metadata, Calendar "
                    "cache and application logs will be permanently deleted. "
                    "Gisheh will restart at the Welcome screen."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Delete Everything & Restart"))
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_factory_reset_response)
        dialog.present(self.settings_dialog)

    def _on_factory_reset_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
    ) -> None:
        if response != "reset":
            return
        self.settings_factory_reset_button.set_sensitive(False)
        try:
            clear_all_user_data(self.state_file)
        except OSError as error:
            self.settings_factory_reset_button.set_sensitive(True)
            failure = Adw.AlertDialog(
                heading=_("Gisheh could not be fully reset"),
                body=str(error),
            )
            failure.add_response("close", _("Close"))
            failure.present(self.settings_dialog)
            return
        try:
            self._restart_application()
        except OSError as error:
            self.settings_factory_reset_button.set_sensitive(True)
            failure = Adw.AlertDialog(
                heading=_("Gisheh was reset but could not restart"),
                body=_("Close and open Gisheh again.\n\n{error}").format(error=error),
            )
            failure.add_response("close", _("Close"))
            failure.present(self.settings_dialog)

    @staticmethod
    def _restart_application() -> None:
        """Replace this process, preserving the system locale."""
        simkl_client.close_image_http_client()
        environment = os.environ.copy()
        python_paths = [entry for entry in sys.path if entry]
        inherited = environment.get("PYTHONPATH", "")
        if inherited:
            python_paths.append(inherited)
        environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
        arguments = [
            sys.executable,
            "-m",
            "gisheh.main",
            *sys.argv[1:],
        ]
        os.execvpe(sys.executable, arguments, environment)

    def _profile_stats(self) -> dict[str, Any]:
        watched_records = tuple(
            record for record in self.records if self._is_record_completed(record)
        )
        watched_movies = tuple(
            record for record in watched_records if record.media_type == "Movies"
        )
        movie_minutes = sum(
            runtime_minutes(record.runtime) for record in watched_movies
        )

        episode_count = 0
        television_minutes = 0
        for record in self.records:
            if record.media_type == "Movies":
                continue
            watched_for_record = 0
            seasons = self._series_seasons(record)
            for season_index in main_progress_season_indexes(seasons):
                watched_for_record += self._season_watched_count(
                    record,
                    season_index,
                )
            episode_count += watched_for_record
            per_episode = runtime_minutes(record.runtime)
            if per_episode == 0:
                per_episode = 24 if record.media_type == "Anime" else 45
            television_minutes += watched_for_record * per_episode

        activity: Counter[date] = Counter()
        episode_events: list[tuple[date, int]] = []
        movie_events: list[tuple[date, int]] = []
        for key, watched_at in self.episode_watched_at.items():
            watched_date = parse_watched_date(watched_at)
            if watched_date is not None:
                activity[watched_date] += 1
                record = self._record_for_canonical_id(key.split("/", 1)[0])
                if record is not None:
                    per_episode = runtime_minutes(record.runtime)
                    if per_episode == 0:
                        per_episode = 24 if record.media_type == "Anime" else 45
                    episode_events.append((watched_date, per_episode))
        for record_id, watched_at in self.title_watched_at.items():
            watched_date = parse_watched_date(watched_at)
            if watched_date is not None:
                activity[watched_date] += 1
                record = self._record_for_canonical_id(record_id)
                if record is not None:
                    minutes = runtime_minutes(record.runtime)
                    if record.media_type == "Movies":
                        movie_events.append((watched_date, minutes))
                    else:
                        if minutes == 0:
                            minutes = 24 if record.media_type == "Anime" else 45
                        episode_events.append((watched_date, minutes))

        today = datetime.now().astimezone().date()
        month_activity = {
            active_day: count
            for active_day, count in activity.items()
            if active_day.year == today.year and active_day.month == today.month
        }
        in_current_month = lambda watched_date: (
            watched_date.year == today.year and watched_date.month == today.month
        )
        in_current_year = lambda watched_date: watched_date.year == today.year
        month_episode_count = sum(
            1
            for watched_date, _minutes in episode_events
            if in_current_month(watched_date)
        )
        month_movie_count = sum(
            1
            for watched_date, _minutes in movie_events
            if in_current_month(watched_date)
        )
        year_episode_count = sum(
            1
            for watched_date, _minutes in episode_events
            if in_current_year(watched_date)
        )
        year_movie_count = sum(
            1
            for watched_date, _minutes in movie_events
            if in_current_year(watched_date)
        )
        month_minutes = sum(
            minutes
            for watched_date, minutes in (*episode_events, *movie_events)
            if in_current_month(watched_date)
        )
        year_minutes = sum(
            minutes
            for watched_date, minutes in (*episode_events, *movie_events)
            if in_current_year(watched_date)
        )
        year_month_activity = Counter(
            watched_date.month
            for watched_date, _minutes in (*episode_events, *movie_events)
            if in_current_year(watched_date)
        )
        rating_histogram = Counter(self.ratings.values())
        genres = Counter(
            genre
            for record in watched_records
            for genre in record.genres
            if genre not in {"Synced", _("Synced")}
        )
        if self.simkl_stats:
            movies_stats = self.simkl_stats.get("movies", {})
            tv_stats = self.simkl_stats.get("tv", {})
            anime_stats = self.simkl_stats.get("anime", {})

            def watched_episodes(group: Any) -> int:
                if not isinstance(group, dict):
                    return 0
                return sum(
                    int(bucket.get("watched_episodes_count") or 0)
                    for bucket in group.values()
                    if isinstance(bucket, dict)
                )

            if isinstance(movies_stats, dict):
                movie_minutes = int(movies_stats.get("total_mins") or movie_minutes)
                completed_movies = movies_stats.get("completed", {})
                if isinstance(completed_movies, dict):
                    watched_movies_count = int(
                        completed_movies.get("count") or len(watched_movies)
                    )
                else:
                    watched_movies_count = len(watched_movies)
            else:
                watched_movies_count = len(watched_movies)
            television_minutes = (
                sum(
                    int(group.get("total_mins") or 0)
                    for group in (tv_stats, anime_stats)
                    if isinstance(group, dict)
                )
                or television_minutes
            )
            episode_count = watched_episodes(tv_stats) + watched_episodes(anime_stats)
            total_minutes = int(
                self.simkl_stats.get("total_mins") or movie_minutes + television_minutes
            )
        else:
            watched_movies_count = len(watched_movies)
            total_minutes = movie_minutes + television_minutes
        return {
            "watched_records": watched_records,
            "movie_count": watched_movies_count,
            "episode_count": episode_count,
            "movie_minutes": movie_minutes,
            "television_minutes": television_minutes,
            "total_minutes": total_minutes,
            "rating_histogram": rating_histogram,
            "rating_count": len(self.ratings),
            "genres": genres,
            "activity": activity,
            "month_activity": month_activity,
            "month_episode_count": month_episode_count,
            "month_movie_count": month_movie_count,
            "month_minutes": month_minutes,
            "year_episode_count": year_episode_count,
            "year_movie_count": year_movie_count,
            "year_minutes": year_minutes,
            "year_month_activity": year_month_activity,
            "active_days_year": sum(
                1 for active_day in activity if active_day.year == today.year
            ),
        }

    def _refresh_profile(self) -> None:
        self.profile_view.update(self._profile_stats())

    @persisted_change
    def begin_simkl_connection(self) -> bool:
        """Enter Simkl mode and start its PIN or refresh flow."""
        self.library_mode = LIBRARY_MODE_SIMKL
        self._simkl_sync_error = None
        if not self.simkl_token:
            self.simkl_token = simkl_client.read_token()
        self._save_user_state()
        self._update_settings_account_rows()
        self._update_profile_identity()
        if self.simkl_token:
            self._start_simkl_sync()
        else:
            self._on_simkl_button_clicked(None)
        return GLib.SOURCE_REMOVE

    @persisted_change
    def set_library_mode(self, mode: str) -> None:
        """Apply an explicit data-ownership choice without deleting either copy."""
        if mode not in LIBRARY_MODES:
            raise ValueError(f"Unsupported library mode: {mode}")
        if mode != self.library_mode:
            self._invalidate_background_jobs()
        if mode == self.library_mode:
            if mode == LIBRARY_MODE_SIMKL and not self.simkl_connected:
                self.begin_simkl_connection()
            return

        self._simkl_sync_error = None

        if mode == LIBRARY_MODE_LOCAL:
            self._simkl_sync_started_at = 0.0
            stored_state = read_state(self.state_file)
            self.library_mode = mode
            stored_state["preferences"] = {**stored_state.get("preferences", {}), "libraryMode": mode}
            if isinstance(stored_state.get("localProfile"), dict):
                records, _explore, _totals = load_catalog()
                self._replace_library(records)
                self.bookmarks = {
                    self._canonical_record_id(record)
                    for record in records
                    if record.status == "Watchlist"
                }
                self.favorites = set()
                self.completed = {
                    self._canonical_record_id(record)
                    for record in records
                    if record.status == "Watched"
                }
                self.ratings = {
                    self._canonical_record_id(record): record.user_rating
                    for record in records
                    if record.user_rating is not None
                }
                self.status_overrides = {}
                self.episode_status_overrides = {}
                self.episode_watched_at = {}
                self.title_watched_at = {}
                self.local_library_records = {}
                self._load_user_state(stored_state)
            else:
                for record in tuple(self.records):
                    canonical = self._canonical_record_id(record)
                    if (
                        canonical in self.bookmarks
                        or canonical in self.completed
                        or canonical in self.ratings
                        or canonical in self.status_overrides
                    ):
                        self._ensure_local_library_record(record)
            self._save_user_state()
            self._refresh_results()
            if self.active_destination == "profile":
                self._refresh_profile()
            self._render_calendar()
            self._update_settings_account_rows()
            self._update_profile_identity()
            self._toast(_("Local-first mode enabled"))
            return

        self._save_user_state()
        self.library_mode = mode
        self._update_settings_account_rows()
        self._update_profile_identity()
        self.begin_simkl_connection()

    @persisted_change
    def _on_simkl_button_clicked(self, _button: Gtk.Button | None) -> None:
        if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
            self.set_library_mode(LIBRARY_MODE_SIMKL)
            return
        if self.simkl_connected and self.simkl_client_id and self.simkl_token:
            self._app_log("Manual Simkl refresh requested.")
            self._start_simkl_sync()
            return
        if not self.simkl_client_id:
            self._app_log(
                "Simkl connection is unavailable because this build has no Client ID.",
                level=logging.WARNING,
            )
            dialog = Adw.AlertDialog(
                heading=_("Simkl is unavailable in this build"),
                body=(
                    _(
                        "The distributor must register Gisheh with Simkl and include "
                        "the public Client ID when building the application. You never "
                        "need to create a developer app or enter a Client Secret."
                    )
                ),
            )
            dialog.add_response("close", _("Close"))
            dialog.set_close_response("close")
            dialog.present(self.window)
            return
        self._simkl_sync_started_at = 0.0
        client_id = self.simkl_client_id
        self._app_log("Simkl sign-in started; requesting a PIN.")
        self._update_settings_account_rows(syncing=True)
        self._start_worker('gisheh-simkl-pin', self._simkl_pin_worker, *(client_id,))

    def _simkl_pin_worker(self, client_id: str) -> None:
        started_at = time.monotonic()
        try:
            payload = simkl_client.request_pin(client_id)
        except simkl_client.SimklError as error:
            self._post_ui(self._on_simkl_failed, str(error), error.code)
            return
        self._app_log(
            "Simkl PIN received in %.1fs.",
            time.monotonic() - started_at,
        )
        self._post_ui(self._present_simkl_pin, client_id, payload)

    def _present_simkl_pin(
        self,
        client_id: str,
        payload: dict[str, Any],
    ) -> bool:
        user_code = str(payload["user_code"])
        verification_uri = str(
            payload.get("verification_uri") or "https://simkl.com/pin"
        )
        interval = max(5, int(payload.get("interval") or 5))
        expires_in = max(60, int(payload.get("expires_in") or 900))

        dialog = Adw.AlertDialog(
            heading=_("Enter this code on Simkl"),
            body=(
                _(
                    "The browser has been opened. Sign in to Simkl and enter the "
                    "code below. Gisheh will finish automatically after approval."
                )
            ),
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        code = Gtk.Label(label=user_code)
        code.set_selectable(True)
        code.add_css_class("simkl-pin-code")
        content.append(code)
        waiting = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        waiting.set_halign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner(spinning=True)
        waiting.append(spinner)
        waiting.append(Gtk.Label(label=_("Waiting for approval…")))
        content.append(waiting)
        dialog.set_extra_child(content)
        dialog.add_response("cancel", _("Cancel"))
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_simkl_pin_dialog_response)
        self.simkl_pin_dialog = dialog
        self._simkl_poll_cancelled = False
        self._app_log(
            "Waiting for Simkl authorization; the PIN expires in %d minutes.",
            max(1, expires_in // 60),
        )
        dialog.present(self.window)
        try:
            Gio.AppInfo.launch_default_for_uri(verification_uri, None)
        except GLib.Error as error:
            self._app_log(
                "Could not open the Simkl authorization page: %s",
                error,
                level=logging.WARNING,
            )
        self._start_worker('gisheh-simkl-poll', self._simkl_poll_worker, *(client_id, user_code, interval, expires_in))
        return GLib.SOURCE_REMOVE

    def _on_simkl_pin_dialog_response(
        self,
        _dialog: Adw.AlertDialog,
        _response: str,
    ) -> None:
        was_waiting = not self._simkl_poll_cancelled
        self._simkl_poll_cancelled = True
        self._update_settings_account_rows()
        if was_waiting:
            self._app_log("Simkl PIN authorization cancelled by the user.")

    def _simkl_poll_worker(
        self,
        client_id: str,
        user_code: str,
        interval: int,
        expires_in: int,
    ) -> None:
        deadline = time.monotonic() + expires_in
        while time.monotonic() < deadline and not self._simkl_poll_cancelled:
            time.sleep(interval)
            if self._simkl_poll_cancelled:
                return
            try:
                payload = simkl_client.poll_pin(client_id, user_code)
            except simkl_client.SimklError as error:
                self._post_ui(self._on_simkl_failed, str(error), error.code)
                return
            if self._simkl_poll_cancelled:
                return
            access_token = str(payload.get("access_token") or "")
            if payload.get("result") == "OK" and access_token:
                self._post_ui(self._on_simkl_authorized, access_token)
                return
            if payload.get("device_code"):
                self._post_ui(
                    self._on_simkl_failed,
                    "The Simkl PIN expired. Request a new code.",
                    None,
                )
                return
        if not self._simkl_poll_cancelled:
            self._post_ui(
                self._on_simkl_failed,
                "The Simkl PIN expired. Request a new code.",
                None,
            )

    def _on_simkl_authorized(self, access_token: str) -> bool:
        self._simkl_poll_cancelled = True
        self._simkl_sync_error = None
        try:
            simkl_client.clear_account_cache()
            storage = simkl_client.store_token(access_token)
        except simkl_client.SimklError as error:
            return self._on_simkl_failed(str(error), error.code)
        self.simkl_token = access_token
        location = (
            "the system keyring"
            if storage == "keyring"
            else "a private local file with 0600 permissions"
        )
        self._app_log(
            "Simkl authorization approved; access token stored in %s.", location
        )
        if getattr(self, "simkl_pin_dialog", None) is not None:
            self.simkl_pin_dialog.close()
        self._toast(_("Simkl connected — syncing your library…"))
        self._start_simkl_sync()
        return GLib.SOURCE_REMOVE

    def _start_simkl_sync(self) -> None:
        if (
            self.library_mode != LIBRARY_MODE_SIMKL
            or not self.simkl_client_id
            or not self.simkl_token
        ):
            return
        self._simkl_sync_error = None
        self._simkl_sync_started_at = time.monotonic()
        self._app_log("Simkl sync started.")
        self._update_header_data_status()
        self._update_settings_account_rows(syncing=True)
        generation = self._simkl_state_generation
        self._start_worker('gisheh-simkl-sync', self._simkl_sync_worker, *(self.simkl_client_id, self.simkl_token, generation))

    def _simkl_sync_worker(self, client_id: str, token: str, generation: int) -> None:
        try:
            snapshot = simkl_client.load_snapshot()
            cached_activities = (
                snapshot.get("activities", {})
                if isinstance(snapshot, dict)
                and isinstance(snapshot.get("activities"), dict)
                else {}
            )
            cached_library = (
                snapshot.get("library", {})
                if isinstance(snapshot, dict)
                and isinstance(snapshot.get("library"), dict)
                else None
            )
            cached_settings = (
                snapshot.get("settings", {})
                if isinstance(snapshot, dict)
                and isinstance(snapshot.get("settings"), dict)
                else {}
            )
            cached_stats = (
                snapshot.get("stats", {})
                if isinstance(snapshot, dict)
                and isinstance(snapshot.get("stats"), dict)
                else {}
            )
            last_sync = str(cached_activities.get("all") or "")
            user_state_is_valid = (
                cached_library is not None
                and simkl_client.library_has_user_state(cached_library)
            )
            state_is_valid = (
                user_state_is_valid
                and simkl_client.library_has_episode_history(cached_library)
            )
            has_incremental_state = state_is_valid and bool(last_sync)
            repairing_metadata = (
                cached_library is not None and bool(last_sync) and not state_is_valid
            )
            if has_incremental_state:
                phase_started = time.monotonic()
                self._app_log("Checking Simkl activity timestamps.")
                activities = simkl_client.fetch_activities(client_id, token)
                self._app_log(
                    "Activity check finished in %.1fs.",
                    time.monotonic() - phase_started,
                )
                previous_settings_activity = cached_activities.get("settings", {})
                current_settings_activity = activities.get("settings", {})
                previous_settings_timestamp = (
                    previous_settings_activity.get("all")
                    if isinstance(previous_settings_activity, dict)
                    else None
                )
                current_settings_timestamp = (
                    current_settings_activity.get("all")
                    if isinstance(current_settings_activity, dict)
                    else None
                )
                settings_changed = (
                    not cached_settings
                    or previous_settings_timestamp != current_settings_timestamp
                )
                settings = (
                    simkl_client.fetch_settings(client_id, token)
                    if settings_changed
                    else cached_settings
                )
                self._app_log(
                    "Account settings %s.",
                    "refreshed" if settings_changed else "loaded from cache",
                )
            elif repairing_metadata:
                activities = cached_activities
                if cached_settings:
                    settings = cached_settings
                    self._app_log("State repair: account settings loaded from cache.")
                else:
                    self._app_log("State repair: fetching missing account settings.")
                    settings = simkl_client.fetch_settings(client_id, token)
            else:
                activities = {}
                self._app_log("Initial sync: fetching Simkl account settings.")
                settings = simkl_client.fetch_settings(client_id, token)
            account = settings.get("account", {})
            try:
                user_id = (
                    int(account.get("id") or 0) if isinstance(account, dict) else 0
                )
            except (TypeError, ValueError):
                user_id = 0
            if user_id <= 0:
                raise simkl_client.SimklError(
                    "Simkl did not return a valid account ID."
                )
            refresh_stats = should_refresh_simkl_stats(
                has_incremental_state=has_incremental_state,
                repairing_metadata=repairing_metadata,
                cached_stats=cached_stats,
                activities=activities,
                last_sync=last_sync,
            )
            if not refresh_stats:
                stats = cached_stats
                self._app_log("Watch statistics loaded from cache.")
            else:
                phase_started = time.monotonic()
                self._app_log("Fetching Simkl watch statistics.")
                stats = simkl_client.fetch_stats(client_id, token, user_id)
                self._app_log(
                    "Watch statistics received in %.1fs.",
                    time.monotonic() - phase_started,
                )
            library = SyncController(simkl_client).library(
                client_id, token, cached_library=cached_library,
                cached_activities=cached_activities, activities=activities,
                last_sync=last_sync, incremental=has_incremental_state,
            )
            if not has_incremental_state and not repairing_metadata:
                activities = simkl_client.fetch_activities(client_id, token)
            if not simkl_client.library_has_user_state(library):
                raise simkl_client.SimklError(
                    "Simkl returned an incomplete user-state response."
                )
            if not simkl_client.library_has_episode_history(library):
                raise simkl_client.SimklError(
                    "Simkl returned an incomplete episode-history response."
                )
            group_counts = {
                group: len(library.get(group, ()))
                for group in ("movies", "shows", "anime")
            }
            self._app_log(
                "Library contains %d movies, %d shows, and %d anime titles.",
                group_counts["movies"],
                group_counts["shows"],
                group_counts["anime"],
            )
            simkl_client.store_snapshot(settings, stats, library, activities)
            self._app_log("Secure local Simkl snapshot updated.")
            records = enrich_records_from_tmdb_cache(title_records_from_simkl(library))
        except simkl_client.SimklError as error:
            self._post_ui(self._on_simkl_failed, str(error), error.code)
            return
        # This worker boundary must report unforeseen failures on GTK's main
        # loop; otherwise the daemon thread would terminate silently.
        except Exception as error:  # noqa: BLE001
            self._app_log(
                "Unexpected Simkl sync failure: %s",
                type(error).__name__,
                level=logging.ERROR,
            )
            self._post_ui(
                self._on_simkl_failed,
                "Unexpected Simkl sync error. Open Application Log for details.",
                None,
            )
            return
        self._post_ui(
            self._apply_simkl_sync,
            settings,
            stats,
            records,
            generation,
        )

    def _replace_library(self, records: tuple[TitleRecord, ...]) -> None:
        self.records = records
        self.library_ids = {record.id for record in records}
        self._rebuild_record_aliases()
        self._tmdb_recommendations = {}
        self.records_by_id = {
            record.id: record
            for record in (
                *records,
                *self.explore_records,
                *self.explore_search_records,
            )
        }
        default_record = next(
            (record for record in records if record.status == "Watched"),
            records[0] if records else None,
        )
        self.selected_id = default_record.id if default_record is not None else None
        valid_record_ids = {record.id for record in records}
        for collection in COLLECTION_NAMES:
            selected_id = self.collection_selected_ids.get(collection)
            if selected_id not in valid_record_ids:
                self.collection_selected_ids[collection] = next(
                    (record.id for record in records if record.status == collection),
                    None,
                )
        self.selected_id = self.collection_selected_ids[self.active_collection]
        valid_canonical_ids = set(self._library_records_by_canonical)
        self.status_overrides = {
            record_id: status
            for record_id, status in self.status_overrides.items()
            if record_id in valid_canonical_ids
        }

    @persisted_change
    def _apply_simkl_sync(
        self,
        settings: dict[str, Any],
        stats: dict[str, Any],
        records: tuple[TitleRecord, ...],
        generation: int | None = None,
    ) -> bool:
        if self.library_mode != LIBRARY_MODE_SIMKL:
            self._app_log(
                "Ignoring Simkl sync result while Local-first mode is active."
            )
            return GLib.SOURCE_REMOVE
        if generation is not None and generation != self._simkl_state_generation:
            self._app_log("Discarding a Simkl snapshot that predates a local mutation.")
            return GLib.SOURCE_REMOVE
        self.simkl_settings = settings
        self.simkl_stats = stats
        self.simkl_connected = True
        self.simkl_snapshot_needs_repair = False
        self._replace_library(records)
        self.completed = {
            self._canonical_record_id(record)
            for record in records
            if record.status == "Watched"
        }
        self.bookmarks = {
            self._canonical_record_id(record)
            for record in records
            if record.status == "Watchlist"
        }
        self.ratings = {
            self._canonical_record_id(record): record.user_rating
            for record in records
            if record.user_rating is not None
        }
        self.title_watched_at = {
            self._canonical_record_id(record): record.date
            for record in records
            if record.status == "Watched"
            and parse_watched_date(record.date) is not None
        }
        self.episode_watched_at = {
            f"{self._canonical_record_id(record)}/s{item.season}/e{item.episode}": item.watched_at
            for record in records
            for item in record.episode_history
            if item.watched_at
        }
        self.episode_status_overrides = {}
        self.favorites.intersection_update(self.library_ids)
        self._save_user_state()
        self._tmdb_details_loading.clear()
        self._tmdb_details_loaded.clear()
        self._tmdb_episode_details_loading.clear()
        self._tmdb_episode_details_loaded.clear()
        self._tmdb_season_details_loading.clear()
        self._tmdb_season_details_loaded.clear()
        self._update_profile_identity()
        self._update_settings_account_rows(syncing=True)
        self._update_genre_model()
        self._refresh_results()
        self._refresh_profile()
        if self.active_destination == "calendar":
            self._render_calendar()
        user = settings.get("user", {})
        avatar_url = (
            str(user.get("avatar") or "") or None if isinstance(user, dict) else None
        )
        if avatar_url and simkl_client.cached_avatar() is None:
            self._start_worker('gisheh-simkl-avatar', self._cache_simkl_avatar, *(avatar_url,))
        elapsed = (
            time.monotonic() - self._simkl_sync_started_at
            if self._simkl_sync_started_at
            else 0.0
        )
        self._app_log(
            "Simkl library data ready: %d titles in %.1fs.",
            len(records),
            elapsed,
        )
        if self.tmdb_token:
            self._toast(
                _("Synced {count} Simkl states — loading catalog from TMDB").format(count=len(records))
            )
            self._load_tmdb_library_async(records)
        else:
            self._toast(
                _("Simkl state synced — connect TMDB to load titles and artwork")
            )
        self._finish_simkl_sync(len(records))
        return GLib.SOURCE_REMOVE

    def _cache_simkl_avatar(self, avatar_url: str) -> None:
        avatar_file = simkl_client.cache_avatar(avatar_url)
        if avatar_file is not None:
            self._post_ui(self._apply_simkl_avatar, avatar_file)

    def _apply_simkl_avatar(self, avatar_file: str) -> bool:
        if not self.simkl_connected:
            return GLib.SOURCE_REMOVE
        try:
            texture = Gdk.Texture.new_from_filename(avatar_file)
            self.sidebar_profile_avatar.set_custom_image(texture)
            if hasattr(self, "profile_view"):
                self.profile_view.avatar.set_custom_image(texture)
        except GLib.Error:
            pass
        return GLib.SOURCE_REMOVE

    def _library_artwork_priorities(self) -> dict[str, int]:
        """Prioritize the current viewport, its look-ahead rows, then the library."""
        records = self.visible_records
        if not records:
            return {}
        adjustment = self.results_scroller.get_vadjustment()
        scroll_value = adjustment.get_value()
        page_size = adjustment.get_page_size()
        if page_size <= 1.0:
            page_size = 600.0
        if self.view_mode == "grid":
            columns = grid_columns_for_width(self.results_scroller.get_width())
            row_height = GRID_ROW_HEIGHT
            start = int(scroll_value // row_height) * columns
            visible_count = max(columns, math.ceil(page_size / row_height) * columns)
        else:
            row_height = 126
            start = int(scroll_value // row_height)
            visible_count = max(1, math.ceil(page_size / row_height))
        visible = records[start : start + visible_count + 2]
        near_visible = records[
            start + visible_count + 2 : start + (visible_count * 3) + 2
        ]
        priorities = {record.id: 10 for record in near_visible}
        priorities.update({record.id: 0 for record in visible})
        if self.selected_id is not None:
            priorities[self.selected_id] = -10
        if self.detail_record_id is not None:
            priorities[self.detail_record_id] = -10
        return priorities

    def _finish_simkl_sync(
        self,
        title_count: int,
    ) -> bool:
        elapsed = (
            time.monotonic() - self._simkl_sync_started_at
            if self._simkl_sync_started_at
            else 0.0
        )
        self._app_log(
            "Simkl user-state sync completed for %d titles in %.1fs.",
            title_count,
            elapsed,
        )
        self._simkl_sync_started_at = 0.0
        self._simkl_sync_error = None
        self._update_profile_identity()
        self._update_settings_account_rows()
        return GLib.SOURCE_REMOVE

    def _update_profile_identity(self) -> None:
        local = getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL
        user = self.simkl_settings.get("user", {})
        name = str(user.get("name") or getuser()) if not local and isinstance(user, dict) else getuser()
        texture = None
        cached_avatar = simkl_client.cached_avatar() if not local else None
        if cached_avatar:
            try:
                texture = Gdk.Texture.new_from_filename(cached_avatar)
            except GLib.Error:
                pass
        self.sidebar_profile_avatar.set_text(name)
        self.sidebar_profile_avatar.set_custom_image(texture)
        if hasattr(self, "profile_view"):
            source = _("Local profile · Stored on this device") if local else (
                _("Connected to Simkl") if self.simkl_connected else _("Simkl profile · Not connected")
            )
            self.profile_view.set_identity(name, source, texture)
        self._update_header_data_status()
        self._update_settings_account_rows()

    def _update_header_data_status(self) -> None:
        if not hasattr(self, "header_data_status_label"):
            return
        syncing = (
            self.library_mode == LIBRARY_MODE_SIMKL
            and bool(getattr(self, "_simkl_sync_started_at", 0.0))
        )
        sync_error = getattr(self, "_simkl_sync_error", None)
        self.header_data_status_icon.set_visible(not syncing)
        self.header_data_status_spinner.set_visible(syncing)
        self.header_data_status_spinner.set_spinning(syncing)
        self.header_data_status_button.set_sensitive(not syncing)
        self.header_data_status_icon.remove_css_class("success")
        self.header_data_status_icon.remove_css_class("accent")

        if self.library_mode == LIBRARY_MODE_LOCAL:
            self.header_data_status_icon.set_from_icon_name("drive-harddisk-symbolic")
            self.header_data_status_icon.add_css_class("accent")
            self.header_data_status_label.set_label(_("Local"))
            tooltip = _("Local-first · Personal library data stays on this device")
        elif syncing:
            self.header_data_status_label.set_label(_("Syncing…"))
            tooltip = _("Refreshing your Simkl library")
        elif sync_error:
            self.header_data_status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.header_data_status_label.set_label(_("Sync failed"))
            tooltip = _("Sync failed. Click to try again.")
        elif self.simkl_connected:
            self.header_data_status_icon.set_from_icon_name("object-select-symbolic")
            self.header_data_status_icon.add_css_class("success")
            self.header_data_status_label.set_label(_("Synced"))
            tooltip = _("Synced with Simkl. Click to refresh now.")
        else:
            self.header_data_status_icon.set_from_icon_name("network-offline-symbolic")
            self.header_data_status_label.set_label(_("Not synced"))
            tooltip = _("Simkl is not connected. Click to connect.")

        self.header_data_status_button.set_tooltip_text(tooltip)
        self.header_data_status_button.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [self.header_data_status_label.get_label(), tooltip],
        )

    @persisted_change
    def _on_header_data_status_clicked(self, _button: Gtk.Button) -> None:
        """Make the header status a direct action for its current state."""
        if self.library_mode == LIBRARY_MODE_LOCAL:
            self._on_preferences_clicked(None)
            return
        self._on_simkl_button_clicked(None)

    def _on_simkl_failed(self, message: str, code: int | None) -> bool:
        elapsed = (
            time.monotonic() - self._simkl_sync_started_at
            if self._simkl_sync_started_at
            else 0.0
        )
        self._app_log(
            "Simkl operation failed after %.1fs: %s",
            elapsed,
            message,
            level=logging.ERROR,
        )
        self._simkl_sync_started_at = 0.0
        self._simkl_sync_error = message
        self._simkl_poll_cancelled = True
        if code == 401:
            try:
                simkl_client.clear_token()
            except simkl_client.SimklError:
                pass
            self.simkl_token = None
            self.simkl_connected = False
        if getattr(self, "simkl_pin_dialog", None) is not None:
            self.simkl_pin_dialog.close()
        self._update_profile_identity()
        self._toast(message)
        return GLib.SOURCE_REMOVE

    def _on_simkl_disconnect_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Disconnect Simkl?"),
            body=(
                _(
                    "The local access token will be removed. Your Simkl account "
                    "and cloud library will not be changed."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("disconnect", _("Disconnect"))
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "disconnect",
            Adw.ResponseAppearance.DESTRUCTIVE,
        )
        dialog.connect("response", self._on_simkl_disconnect_response)
        dialog.present(self.window)

    @persisted_change
    def _on_simkl_disconnect_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
    ) -> None:
        if response != "disconnect":
            return
        try:
            simkl_client.clear_token()
        except simkl_client.SimklError as error:
            self._toast(str(error))
            return
        try:
            simkl_client.clear_account_cache()
        except simkl_client.SimklError as error:
            self._app_log(
                "Could not clear the Simkl cache: %s",
                error,
                level=logging.WARNING,
            )
        self._invalidate_background_jobs()
        self.simkl_token = None
        self.simkl_connected = False
        self._simkl_sync_error = None
        self.simkl_settings = {}
        self.simkl_stats = {}
        records, _explore, _totals = load_catalog()
        self._replace_library(records)
        self.completed = {
            self._canonical_record_id(record)
            for record in records
            if record.status == "Watched"
        }
        self.bookmarks = {
            self._canonical_record_id(record)
            for record in records
            if record.status == "Watchlist"
        }
        self.ratings = {
            self._canonical_record_id(record): record.user_rating
            for record in records
            if record.user_rating is not None
        }
        self.favorites.intersection_update(self.library_ids)
        self.status_overrides = {}
        self.episode_status_overrides = {}
        self.episode_watched_at = {}
        self._tmdb_episode_details_loading.clear()
        self._tmdb_episode_details_loaded.clear()
        self._tmdb_season_details_loading.clear()
        self._tmdb_season_details_loaded.clear()
        self.title_watched_at = {
            self._canonical_record_id(record): record.date
            for record in records
            if record.status == "Watched"
            and parse_watched_date(record.date) is not None
        }
        self._save_user_state()
        self._update_profile_identity()
        self._update_genre_model()
        self._refresh_results()
        self._refresh_profile()
        self._app_log(
            "Simkl disconnected; local credentials and account cache removed."
        )
        self._toast(_("Simkl disconnected"))

    def _build_detail_sections(self) -> None:
        self.image_mode = "backdrops"

        self.cast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cast_scroller = self._horizontal_scroller(self.cast_box, 116)
        self.cast_section = self._detail_section(
            _("Cast & Crew"),
            self.cast_scroller,
        )

        self.episode_cards_box = Adw.WrapBox()
        self.episode_cards_box.set_child_spacing(8)
        self.episode_cards_box.set_line_spacing(8)
        self.seasons_list = Gtk.ListBox()
        self.seasons_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.seasons_list.set_show_separators(True)
        self.seasons_list.add_css_class("boxed-list")
        series_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        series_content.append(self.episode_cards_box)
        series_content.append(self.seasons_list)
        self.series_section = self._detail_section(
            _("Episodes & Seasons"), series_content
        )

        self.videos_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.videos_scroller = self._horizontal_scroller(self.videos_box, 126)
        self.videos_section = self._detail_section(
            _("Videos"),
            self.videos_scroller,
        )

        self.images_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.image_switcher = Adw.ToggleGroup()
        self.image_switcher.add(Adw.Toggle(name="backdrops", label=_("Backdrops")))
        self.image_switcher.add(Adw.Toggle(name="posters", label=_("Posters")))
        self.image_switcher.set_active_name("backdrops")
        self.images_scroller = self._horizontal_scroller(self.images_box, 154)
        self.images_section = self._detail_section(
            _("Images"),
            self.images_scroller,
            end_widget=self.image_switcher,
        )

        self.recommendations_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )
        self.recommendations_scroller = self._horizontal_scroller(
            self.recommendations_box,
            186,
        )
        self.recommendations_section = self._detail_section(
            _("More like this"),
            self.recommendations_scroller,
        )

        for section in (
            self.cast_section,
            self.series_section,
            self.videos_section,
            self.images_section,
            self.recommendations_section,
        ):
            self.detail_extra_sections.append(section)

        self._build_episode_navigation_pages()

    def _build_episode_navigation_pages(self) -> None:
        self.season_header_title = Adw.WindowTitle(title=_("Season"), subtitle="")
        season_header = Adw.HeaderBar()
        season_header.set_show_start_title_buttons(False)
        season_header.set_show_end_title_buttons(False)
        season_header.set_show_back_button(True)
        season_header.set_title_widget(self.season_header_title)

        self.season_summary_label = Gtk.Label(xalign=0)
        self.season_summary_label.add_css_class("dim-label")

        season_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            homogeneous=False,
        )
        season_actions.set_halign(Gtk.Align.START)
        self.season_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        season_actions.append(self.season_watched_button)

        episodes_title = Gtk.Label(label=_("Episodes"), xalign=0)
        episodes_title.add_css_class("title-4")

        self.season_episodes_list = Gtk.ListBox()
        self.season_episodes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.season_episodes_list.set_activate_on_single_click(True)
        self.season_episodes_list.set_show_separators(True)
        self.season_episodes_list.add_css_class("boxed-list")
        self.season_episodes_list.add_css_class("episode-list")

        self.season_detail_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.season_detail_box.set_vexpand(True)
        self.season_detail_box.set_margin_top(16)
        self.season_detail_box.set_margin_bottom(28)
        self.season_detail_box.set_margin_start(16)
        self.season_detail_box.set_margin_end(16)
        self.season_detail_box.add_css_class("detail-page")
        self.season_detail_box.add_css_class("detail-subpage-content")
        self.season_detail_box.append(self.season_summary_label)
        self.season_detail_box.append(season_actions)
        self.season_detail_box.append(Gtk.Separator())
        self.season_detail_box.append(episodes_title)
        self.season_detail_box.append(self.season_episodes_list)

        self.season_details_scroller = Gtk.ScrolledWindow()
        self.season_details_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.season_details_scroller.set_vexpand(True)
        self.season_details_scroller.add_css_class("detail-tint-surface")
        self.season_details_scroller.set_child(self.season_detail_box)

        season_toolbar = Adw.ToolbarView()
        season_toolbar.add_css_class("detail-subpage-toolbar")
        season_toolbar.add_top_bar(season_header)
        season_toolbar.set_content(self.season_details_scroller)
        self.season_detail_page = Adw.NavigationPage.new_with_tag(
            season_toolbar,
            "Season",
            "season",
        )

        self.episode_header_title = Adw.WindowTitle(title=_("Episode"), subtitle="")
        episode_header = Adw.HeaderBar()
        episode_header.set_show_start_title_buttons(False)
        episode_header.set_show_end_title_buttons(False)
        episode_header.set_show_back_button(True)
        episode_header.set_title_widget(self.episode_header_title)

        self.episode_hero_host = Gtk.Box()
        self.episode_hero_host.set_halign(Gtk.Align.CENTER)
        self.episode_hero_host.set_hexpand(True)
        self.episode_hero_host.set_size_request(-1, 198)

        self.episode_status_label = Gtk.Label(label=_("Watched"))
        self.episode_status_label.set_halign(Gtk.Align.CENTER)
        self.episode_status_label.add_css_class("pill")
        self.episode_status_label.add_css_class("status-pill")
        self.episode_status_label.set_visible(False)

        self.episode_title_label = Gtk.Label(xalign=0)
        self.episode_title_label.set_wrap(True)
        self.episode_title_label.set_max_width_chars(28)
        self.episode_title_label.add_css_class("title-2")
        self.episode_date_label = Gtk.Label(xalign=0)
        self.episode_date_label.set_wrap(True)
        self.episode_date_label.set_max_width_chars(40)
        self.episode_date_label.add_css_class("caption")
        self.episode_date_label.add_css_class("dim-label")

        episode_identity = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=3,
        )
        episode_identity.append(self.episode_date_label)
        episode_identity.append(self.episode_title_label)

        episode_actions = Adw.WrapBox()
        episode_actions.set_child_spacing(7)
        episode_actions.set_line_spacing(7)
        episode_actions.set_halign(Gtk.Align.START)
        self.episode_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        episode_actions.append(self.episode_watched_button)

        self.episode_watched_at_label = Gtk.Label(xalign=0)
        self.episode_watched_at_label.set_wrap(True)
        self.episode_watched_at_label.add_css_class("caption")
        self.episode_watched_at_label.add_css_class("dim-label")

        self.episode_runtime_label = Gtk.Label(xalign=0)
        self.episode_runtime_label.add_css_class("dim-label")
        episode_fact_separator = Gtk.Label(label="•")
        episode_fact_separator.add_css_class("dim-label")
        self.episode_series_label = Gtk.Label(xalign=0)
        self.episode_series_label.set_wrap(True)
        self.episode_series_label.set_max_width_chars(28)
        self.episode_series_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.episode_series_label.add_css_class("dim-label")
        episode_facts = Adw.WrapBox()
        episode_facts.set_child_spacing(7)
        episode_facts.set_line_spacing(4)
        episode_facts.set_hexpand(True)
        episode_facts.append(self.episode_runtime_label)
        episode_facts.append(episode_fact_separator)
        episode_facts.append(self.episode_series_label)

        overview_title = Gtk.Label(label=_("Overview"), xalign=0)
        overview_title.add_css_class("heading")
        self.episode_overview_label = Gtk.Label(xalign=0)
        self.episode_overview_label.set_wrap(True)
        self.episode_overview_label.set_wrap_mode(Pango.WrapMode.WORD)
        self.episode_overview_label.set_max_width_chars(-1)
        self.episode_overview_label.set_hexpand(True)
        self.episode_overview_label.set_halign(Gtk.Align.FILL)
        self.episode_overview_label.set_justify(Gtk.Justification.FILL)
        self.episode_overview_label.add_css_class("dim-label")
        episode_overview = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=7,
        )
        episode_overview.append(overview_title)
        episode_overview.append(self.episode_overview_label)

        self.episode_cast_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        self.episode_cast_scroller = self._horizontal_scroller(
            self.episode_cast_box,
            116,
        )
        self.episode_cast_section = self._detail_section(
            _("Cast & Crew"),
            self.episode_cast_scroller,
        )

        self.episode_detail_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.episode_detail_box.set_vexpand(True)
        self.episode_detail_box.set_margin_top(12)
        self.episode_detail_box.set_margin_bottom(28)
        self.episode_detail_box.set_margin_start(16)
        self.episode_detail_box.set_margin_end(16)
        self.episode_detail_box.add_css_class("detail-page")
        self.episode_detail_box.add_css_class("detail-tint-content")
        self.episode_detail_box.append(self.episode_hero_host)
        self.episode_detail_box.append(self.episode_status_label)
        self.episode_detail_box.append(episode_identity)
        self.episode_detail_box.append(episode_actions)
        self.episode_detail_box.append(self.episode_watched_at_label)
        self.episode_detail_box.append(episode_facts)
        self.episode_detail_box.append(episode_overview)
        self.episode_detail_box.append(self.episode_cast_section)

        self.episode_details_scroller = Gtk.ScrolledWindow()
        self.episode_details_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.episode_details_scroller.set_vexpand(True)
        self.episode_details_scroller.add_css_class("detail-tint-surface")
        self.episode_details_scroller.set_child(self.episode_detail_box)

        episode_toolbar = Adw.ToolbarView()
        episode_toolbar.add_css_class("detail-subpage-toolbar")
        episode_toolbar.add_top_bar(episode_header)
        episode_toolbar.set_content(self.episode_details_scroller)
        self.episode_detail_page = Adw.NavigationPage.new_with_tag(
            episode_toolbar,
            "Episode",
            "episode",
        )

        self.detail_navigation.add(self.season_detail_page)
        self.detail_navigation.add(self.episode_detail_page)

    @staticmethod
    def _detail_navigation_action(icon_name: str, label: str) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        caption = Gtk.Label(label=label)
        content.append(icon)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.set_tooltip_text(label)
        button.action_icon = icon
        button.action_label = caption
        return button

    def _detail_section(
        self,
        title: str,
        content: Gtk.Widget,
        *,
        end_widget: Gtk.Widget | None = None,
    ) -> Gtk.Box:
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        section.add_css_class("detail-section")

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=title, xalign=0)
        label.set_hexpand(True)
        label.add_css_class("heading")
        heading.append(label)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if end_widget is not None:
            end_box.append(end_widget)
        if isinstance(content, Gtk.ScrolledWindow):
            end_box.append(self._carousel_controls(content, title))
        if end_box.get_first_child() is not None:
            heading.append(end_box)

        section.append(heading)
        section.append(content)
        return section

    def _carousel_controls(
        self,
        scroller: Gtk.ScrolledWindow,
        title: str,
    ) -> Gtk.Box:
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        controls.add_css_class("linked")

        previous = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        previous.set_tooltip_text(_("Previous {title}").format(title=title.lower()))
        previous.add_css_class("flat")
        previous.connect(
            "clicked",
            lambda _button: self._scroll_carousel_page(scroller, -1),
        )

        following = Gtk.Button.new_from_icon_name("go-next-symbolic")
        following.set_tooltip_text(_("Next {title}").format(title=title.lower()))
        following.add_css_class("flat")
        following.connect(
            "clicked",
            lambda _button: self._scroll_carousel_page(scroller, 1),
        )

        controls.append(previous)
        controls.append(following)
        scroller._carousel_controls = controls
        scroller._carousel_previous_button = previous
        scroller._carousel_next_button = following
        adjustment = scroller.get_hadjustment()

        def update_visibility(*_args: Any) -> None:
            scrollable = (
                adjustment.get_upper() - adjustment.get_page_size()
                > adjustment.get_lower() + 1
            )
            controls.set_visible(scrollable)

        adjustment.connect("changed", update_visibility)
        update_visibility()
        self._post_ui(lambda: (update_visibility(), GLib.SOURCE_REMOVE)[1])
        return controls

    @staticmethod
    def _scroll_carousel_page(
        scroller: Gtk.ScrolledWindow,
        direction: int,
    ) -> None:
        adjustment = scroller.get_hadjustment()
        lower = adjustment.get_lower()
        maximum = max(lower, adjustment.get_upper() - adjustment.get_page_size())
        current = adjustment.get_value()
        step = max(1.0, adjustment.get_page_size() * 0.88)

        if direction < 0:
            target = maximum if current <= lower + 1 else max(lower, current - step)
        else:
            target = lower if current >= maximum - 1 else min(maximum, current + step)

        previous_animation = getattr(scroller, "_carousel_animation", None)
        if previous_animation is not None:
            previous_animation.pause()
        target_property = Adw.PropertyAnimationTarget.new(adjustment, "value")
        animation = Adw.TimedAnimation.new(
            scroller,
            current,
            target,
            240,
            target_property,
        )
        animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        scroller._carousel_animation = animation
        animation.play()

    @staticmethod
    def _horizontal_scroller(child: Gtk.Widget, height: int) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        scroller.set_min_content_height(height)
        scroller.set_propagate_natural_width(False)
        scroller.set_propagate_natural_height(True)
        scroller.set_hexpand(True)
        scroller.set_child(child)
        return scroller

    @staticmethod
    def _configure_bounded_card_label(
        label: Gtk.Label,
        width_chars: int,
        *,
        lines: int = 2,
    ) -> None:
        """Keep long carousel captions inside their card's natural width."""
        label.set_wrap(lines != 1)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_lines(lines)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_width_chars(width_chars)
        label.set_max_width_chars(width_chars)
        label.set_hexpand(False)

    def _connect_signals(self, application: Adw.Application) -> None:
        self.media_switcher.connect("notify::active-name", self._on_media_changed)
        self.compact_media_switcher.connect(
            "notify::active-name", self._on_media_changed
        )
        self.view_switcher.connect("notify::active-name", self._on_view_changed)
        self.destination_list.connect(
            "row-selected",
            self._on_destination_selected,
        )
        self.collection_list.connect(
            "row-selected",
            self._on_collection_selected,
        )
        self.list_box.connect("row-selected", self._on_list_selected)
        self.list_box.connect("row-activated", self._on_list_activated)
        self.grid_box.connect("selected-children-changed", self._on_grid_selected)
        self.grid_box.connect("child-activated", self._on_grid_activated)
        self.seasons_list.connect("row-activated", self._on_season_activated)
        self.season_episodes_list.connect(
            "row-activated",
            self._on_episode_activated,
        )

        self.search_entry.connect("search-changed", self._on_search_changed)
        self.explore_search_entry.connect(
            "search-changed",
            self._on_explore_search_changed,
        )
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        self.genre_dropdown.connect("notify::selected", self._on_genre_changed)
        self.explore_sort_dropdown.connect(
            "notify::selected",
            self._on_explore_sort_changed,
        )
        self.explore_period_dropdown.connect(
            "notify::selected",
            self._on_explore_period_changed,
        )
        self.explore_genre_dropdown.connect(
            "notify::selected",
            self._on_explore_genre_changed,
        )
        self.explore_calendar_button.connect(
            "clicked",
            lambda *_args: self.destination_list.select_row(self.calendar_row),
        )
        self.sort_direction_button.connect("clicked", self._on_reverse_sort)
        self.image_switcher.connect("notify::active-name", self._on_image_mode_changed)
        self.search_button.connect("clicked", self._on_search_requested)
        self.profile_button.connect("clicked", self._on_profile_clicked)
        self.header_data_status_button.connect(
            "clicked", self._on_header_data_status_clicked
        )
        self.watched_button.connect("clicked", self._on_watched_clicked)
        self.bookmark_button.connect("toggled", self._on_bookmark_toggled)
        self.detail_title.set_wrap(True)
        self.detail_title.set_wrap_mode(Pango.WrapMode.WORD)
        self.detail_title.set_max_width_chars(28)
        self.detail_title.set_xalign(0)
        self.season_watched_button.connect(
            "clicked",
            self._on_season_watched_clicked,
        )
        self.episode_watched_button.connect(
            "clicked",
            self._on_episode_watched_clicked,
        )

        self._install_window_actions(application)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_search_key_pressed)
        self.search_entry.add_controller(key_controller)

        explore_search_key_controller = Gtk.EventControllerKey()
        explore_search_key_controller.connect(
            "key-pressed",
            self._on_explore_search_key_pressed,
        )
        self.explore_search_entry.add_controller(explore_search_key_controller)

        explore_adjustment = self.explore_scroller.get_vadjustment()
        explore_adjustment.connect("value-changed", self._on_explore_scroll_changed)
        explore_adjustment.connect("changed", self._on_explore_scroll_changed)

        window_key_controller = Gtk.EventControllerKey()
        window_key_controller.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        window_key_controller.connect("key-pressed", self._on_window_key_pressed)
        self.window.add_controller(window_key_controller)

        self.window.connect("close-request", self._on_window_close_request)
        self.window.connect("realize", self._on_window_realized)

    def _install_window_actions(self, application: Adw.Application) -> None:
        """Keep discoverable shortcuts and actual actions in one place."""
        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", self._on_search_requested)
        self.window.add_action(search_action)
        application.set_accels_for_action("win.search", ["<primary>k"])

        sidebar_action = Gio.SimpleAction.new("toggle-sidebar", None)
        sidebar_action.connect(
            "activate",
            lambda *_args: self._set_sidebar_open(not self._sidebar_is_open()),
        )
        self.window.add_action(sidebar_action)
        application.set_accels_for_action("win.toggle-sidebar", ["<primary>b"])

        settings_action = Gio.SimpleAction.new("preferences", None)
        settings_action.connect(
            "activate",
            lambda *_args: self._on_preferences_clicked(None),
        )
        self.window.add_action(settings_action)
        application.set_accels_for_action("win.preferences", ["<primary>comma"])

        for name, callback, shortcuts in (
            ("find", self._on_find_requested, ["<primary>f"]),
            ("shortcuts", self._show_shortcuts, ["<primary>question"]),
            ("main-menu", self._show_main_menu, ["F10"]),
            ("back", lambda *_args: self._navigate_back(), ["<Alt>Left"]),
            ("close", self._close_active_surface, ["<primary>w"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.window.add_action(action)
            application.set_accels_for_action(f"win.{name}", shortcuts)

    def _close_active_surface(self, *_args) -> None:
        dialog = self.window.get_visible_dialog()
        if dialog is not None:
            dialog.close()
        else:
            self.window.close()

    def _on_window_realized(self, window: Gtk.Window) -> None:
        surface = window.get_surface()
        if surface is None:
            return
        surface.connect("notify::width", self._on_surface_width_changed)
        self._queue_responsive_layout()

    def _on_surface_width_changed(
        self,
        _surface: Gdk.Surface,
        _parameter: Any,
    ) -> None:
        self._queue_responsive_layout()

    def _queue_explore_resize(self) -> None:
        """Coalesce allocations into one relayout after GTK has settled."""
        if self._explore_resize_source_id:
            return
        self._explore_resize_source_id = self._post_ui(
            self._apply_explore_resize,
        )

    def _apply_explore_resize(self) -> bool:
        self._explore_resize_source_id = 0
        # During a sidebar/revealer transition the allocation is deliberately
        # intermediate.  The completion callback queues exactly one fresh
        # pass, so cards are never measured against a guessed future pane.
        if self._details_resize_source_id or self._sidebar_resize_source_id:
            return GLib.SOURCE_REMOVE
        width = self.explore_pane.get_width() or self.collection_pane.get_width()
        if width <= 0:
            return GLib.SOURCE_REMOVE
        columns = self._stable_explore_columns_for_width(
            width,
            self.explore_columns,
        )
        columns_changed = columns != self.explore_columns
        self._last_explore_layout_width = width
        self.explore_columns = columns
        self._last_explore_layout_bucket = (columns, 0)
        if (
            self.active_destination == "explore"
            and self.explore_visible_records
            and columns_changed
        ):
            scroll_value = self.explore_scroller.get_vadjustment().get_value()
            self._populate_explore_feed(force_relayout=True)
            self._scroll_to_value(self.explore_scroller, scroll_value)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _explore_columns_for_width(width: int) -> int:
        if width >= 760:
            return 5
        if width >= 540:
            return 4
        if width >= 390:
            return 3
        if width >= 280:
            return 2
        return 1

    @classmethod
    def _stable_explore_columns_for_width(
        cls,
        width: int,
        current_columns: int,
    ) -> int:
        """Keep small allocation changes from flipping the grid repeatedly."""
        target = cls._explore_columns_for_width(width)
        if current_columns < 1 or target == current_columns:
            return target
        thresholds = {2: 280, 3: 390, 4: 540, 5: 760}
        if target > current_columns:
            target_threshold = thresholds.get(target, 0)
            if width < target_threshold + EXPLORE_COLUMN_HYSTERESIS:
                return current_columns
        else:
            current_threshold = thresholds.get(current_columns, 0)
            if width >= current_threshold - EXPLORE_COLUMN_HYSTERESIS:
                return current_columns
        return target

    def _explore_layout_metrics(self) -> tuple[float, int]:
        """Return the column width and column count for Explore cards."""
        pane_width = (
            self.explore_pane.get_width()
            or self.collection_pane.get_width()
            or self._last_explore_layout_width
            or 620
        )
        content_width = max(120, pane_width - 48)
        columns = max(1, self.explore_columns)
        column_width = max(88, (content_width - 10 * (columns - 1)) / columns)
        return column_width, columns

    def _explore_card_height(self, kind: str, span: int) -> int:
        """Size a card from its real grid span instead of its child request."""
        column_width, _columns = self._explore_layout_metrics()
        card_width = column_width * span + 10 * (span - 1)

        if kind == "poster":
            return round(card_width * 3 / 2)
        return round(card_width * 9 / 16)

    def _update_genre_model(self, *, preserve: bool = False) -> None:
        previous_genre = self.genre
        genres = sorted(
            {
                genre
                for record in self.records
                if record.media_type == self.active_media
                for genre in record.genres
            }
        )
        self.genre_options = ("All genres", *genres)
        selected_genre = (
            previous_genre
            if preserve and previous_genre in self.genre_options
            else "All genres"
        )
        self._updating = True
        self.genre_dropdown.set_model(
            Gtk.StringList.new(
                [
                    _("All genres") if option == "All genres" else option
                    for option in self.genre_options
                ]
            )
        )
        self.genre_dropdown.set_selected(self.genre_options.index(selected_genre))
        self.genre = selected_genre
        self._updating = False

    def _update_explore_genre_model(self, *, preserve: bool = True) -> None:
        previous_genre = self.explore_genre
        genres = sorted(
            {
                genre
                for record in self.explore_records
                if record.media_type == self.active_media
                for genre in record.genres
            }
        )
        self.explore_genre_options = ("All genres", *genres)
        selected_genre = (
            previous_genre
            if preserve and previous_genre in self.explore_genre_options
            else "All genres"
        )
        self._updating = True
        self.explore_genre_dropdown.set_model(
            Gtk.StringList.new(
                [
                    _("All genres") if option == "All genres" else option
                    for option in self.explore_genre_options
                ]
            )
        )
        self.explore_genre_dropdown.set_selected(
            self.explore_genre_options.index(selected_genre)
        )
        self.explore_genre = selected_genre
        self._updating = False

    def _load_tmdb_library_async(
        self,
        records: tuple[TitleRecord, ...],
    ) -> None:
        token = self.tmdb_token
        if not token:
            self._app_log(
                "TMDB token is missing; Simkl state is available but catalog metadata cannot load.",
                level=logging.WARNING,
            )
            return
        candidates = tuple(
            record
            for record in records
            if record.tmdb_id is not None and record.tmdb_media_type is not None
        )
        missing_matches = len(records) - len(candidates)
        if missing_matches:
            self._app_log(
                "%d Simkl titles have no TMDB ID and will keep placeholders.",
                missing_matches,
                level=logging.WARNING,
            )
        if not candidates:
            self._app_log("TMDB catalog enrichment skipped: no eligible titles.")
            return
        self._tmdb_library_generation += 1
        generation = self._tmdb_library_generation
        priorities = self._library_artwork_priorities()
        ordered = tuple(
            sorted(
                candidates,
                key=lambda record: (priorities.get(record.id, 100), -record.order),
            )
        )
        self._app_log(
            "Scheduling TMDB catalog enrichment for %d titles (language=%s).",
            len(ordered),
            tmdb_client.active_language(),
        )
        self._start_worker('gisheh-tmdb-library', self._load_tmdb_library_worker, *(ordered, token, generation))

    def _load_tmdb_library_worker(
        self,
        records: tuple[TitleRecord, ...],
        token: str,
        generation: int,
    ) -> None:
        started_at = time.monotonic()
        completed = 0
        with self._image_executor() as executor:
            futures = [
                executor.submit(
                    self._load_tmdb_library_record,
                    record,
                    token,
                    generation,
                )
                for record in records
            ]
            for future in as_completed(futures):
                if future.result():
                    completed += 1
        self._app_log(
            "TMDB catalog enrichment finished: %d/%d titles in %.1fs.",
            completed,
            len(records),
            time.monotonic() - started_at,
        )
        self._post_ui(
            self._finish_tmdb_library_enrichment,
            generation,
            completed,
            len(records),
        )

    def _load_tmdb_library_record(
        self,
        record: TitleRecord,
        token: str,
        generation: int,
    ) -> bool:
        if record.tmdb_id is None or record.tmdb_media_type is None:
            return False
        summary = tmdb_client.load_summary(
            record.tmdb_media_type,
            record.tmdb_id,
            max_age_seconds=24 * 60 * 60,
        )
        if summary is None:
            try:
                summary = tmdb_client.fetch_summary(
                    token,
                    record.tmdb_media_type,
                    record.tmdb_id,
                )
            except tmdb_client.TmdbError as error:
                self._app_log(
                    "TMDB metadata failed for %s: %s",
                    record.title,
                    error,
                    level=logging.WARNING,
                )
                return False
        self._post_ui(
            self._apply_tmdb_library_summary,
            generation,
            record.id,
            summary,
        )
        poster_path = str(summary.get("poster_path") or "")
        if poster_path:
            poster_file = tmdb_client.cache_image(poster_path, size="w500")
            if poster_file is not None:
                self._post_ui(
                    self._apply_tmdb_library_poster,
                    generation,
                    record.id,
                    poster_file,
                )
        return True

    def _apply_tmdb_library_summary(
        self,
        generation: int,
        record_id: str,
        summary: dict[str, Any],
    ) -> bool:
        if generation != self._tmdb_library_generation:
            return GLib.SOURCE_REMOVE
        record = getattr(self, "records_by_id", {}).get(record_id)
        if record is None or record_id not in self.library_ids:
            return GLib.SOURCE_REMOVE
        self._store_tmdb_record(enrich_record_from_tmdb(record, summary))
        self._schedule_tmdb_library_refresh()
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_library_poster(
        self,
        generation: int,
        record_id: str,
        poster_file: str,
    ) -> bool:
        if generation != self._tmdb_library_generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or record_id not in self.library_ids:
            return GLib.SOURCE_REMOVE
        self._store_tmdb_record(
            replace(
                record,
                artwork_file=poster_file,
                poster_file=poster_file,
            )
        )
        self._schedule_tmdb_library_refresh()
        return GLib.SOURCE_REMOVE

    def _schedule_tmdb_library_refresh(self) -> None:
        if self._tmdb_library_refresh_source_id:
            return
        self._tmdb_library_refresh_source_id = GLib.timeout_add(
            50,
            self._refresh_tmdb_library_ui,
        )

    def _refresh_tmdb_library_ui(self) -> bool:
        self._tmdb_library_refresh_source_id = 0
        if self.active_destination == "collection":
            scroll_position = self.results_scroller.get_vadjustment().get_value()
            self._refresh_results()
            self._scroll_to_value(self.results_scroller, scroll_position)
        elif self.active_destination == "profile":
            self._refresh_profile()
        return GLib.SOURCE_REMOVE

    @persisted_change
    def _finish_tmdb_library_enrichment(
        self,
        generation: int,
        completed: int,
        total: int,
    ) -> bool:
        if generation != self._tmdb_library_generation:
            return GLib.SOURCE_REMOVE
        self._update_genre_model(preserve=True)
        if self.active_destination == "collection":
            scroll_position = self.results_scroller.get_vadjustment().get_value()
            self._refresh_results()
            self._scroll_to_value(self.results_scroller, scroll_position)
        self._toast(
            _("TMDB catalog ready for {completed}/{total} titles").format(
                completed=completed, total=total
            )
        )
        return GLib.SOURCE_REMOVE

    def _load_tmdb_explore_async(self) -> None:
        token = self.tmdb_token
        if not token:
            self._app_log(
                "TMDB Explore skipped: no credential is available.",
                level=logging.WARNING,
            )
            return
        self._tmdb_explore_generation += 1
        generation = self._tmdb_explore_generation
        self._tmdb_explore_pages_loading.update(MEDIA_TYPES)
        self._sync_explore_loading_indicator()
        self._app_log(
            "Scheduling TMDB Explore request (language=%s, credential=%s).",
            tmdb_client.active_language(),
            tmdb_client.token_source() or "unknown",
        )
        self._start_worker('gisheh-tmdb-explore', self._load_tmdb_explore_worker, *(token, generation, self.active_media))

    def _load_tmdb_explore_worker(
        self,
        token: str,
        generation: int,
        active_media: str,
    ) -> None:
        started_at = time.monotonic()
        self._app_log(
            "TMDB Explore request started (language=%s).",
            tmdb_client.active_language(),
        )
        try:
            collections = ExploreController(tmdb_client).fetch(token)
            records: list[TitleRecord] = []
            image_work: list[tuple[int, int, str, str, str, str]] = []
            work_items = [
                (media_type, position, raw)
                for media_type in MEDIA_TYPES
                for position, raw in enumerate(
                    collections.get(media_type, ()),
                    start=1,
                )
            ]
            for media_type, position, raw in work_items:
                poster_path = str(raw.get("poster_path") or "")
                backdrop_path = str(raw.get("backdrop_path") or "")
                poster_file = tmdb_client.cached_image(poster_path, size="w500")
                backdrop_file = tmdb_client.cached_image(backdrop_path, size="w780")
                record = title_record_from_tmdb(
                    raw,
                    media_type,
                    position,
                    poster_file,
                    backdrop_file,
                )
                records.append(record)
                media_priority = 0 if media_type == active_media else 100
                viewport_priority = 0 if position <= 8 else 10
                if poster_path and poster_file is None:
                    image_work.append(
                        (
                            media_priority + viewport_priority,
                            position,
                            record.id,
                            "poster",
                            poster_path,
                            "w500",
                        )
                    )
                if backdrop_path and backdrop_file is None:
                    image_work.append(
                        (
                            media_priority + viewport_priority + 1,
                            position,
                            record.id,
                            "backdrop",
                            backdrop_path,
                            "w780",
                        )
                    )
            if not records:
                raise tmdb_client.TmdbError("TMDB returned no titles.")
        except (KeyError, OSError, TypeError, ValueError, tmdb_client.TmdbError) as error:
            self._post_ui(
                self._on_tmdb_explore_failed,
                generation,
                str(error),
            )
            return
        self._post_ui(self._apply_tmdb_explore, generation, tuple(records))
        self._app_log(
            "TMDB Explore metadata received: %d titles in %.1fs.",
            len(records),
            time.monotonic() - started_at,
        )

        image_work.sort(key=lambda item: (item[0], item[1]))
        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): (
                    record_id,
                    kind,
                )
                for _priority, _position, record_id, kind, path, size in image_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is None:
                    continue
                record_id, kind = futures[future]
                self._post_ui(
                    self._apply_tmdb_explore_image,
                    generation,
                    record_id,
                    kind,
                    image_file,
                )

    def _apply_tmdb_explore(
        self,
        generation: int,
        records: tuple[TitleRecord, ...],
    ) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_explore_pages = {media_type: 1 for media_type in MEDIA_TYPES}
        self._tmdb_explore_has_more = {
            media_type: any(record.media_type == media_type for record in records)
            for media_type in MEDIA_TYPES
        }
        self._tmdb_explore_pages_loading.difference_update(MEDIA_TYPES)
        self.explore_records = records
        self.explore_ids = {record.id for record in records}
        self.records_by_id = {
            record.id: record
            for record in (
                *self.records,
                *self.explore_records,
                *self.explore_search_records,
            )
        }
        self.explore_selected_id = None
        self._update_explore_genre_model(preserve=False)
        if self.active_destination == "explore":
            self._refresh_explore()
        self._sync_explore_loading_indicator()
        self._toast(_("Live TMDB data loaded"))
        return GLib.SOURCE_REMOVE

    def _load_next_tmdb_explore_page(self) -> None:
        if self.explore_search_entry.get_text().strip():
            self._load_next_tmdb_search_page()
            return
        media_type = self.active_media
        if (
            not self.tmdb_token
            or media_type in self._tmdb_explore_pages_loading
            or not self._tmdb_explore_has_more.get(media_type, True)
        ):
            return
        page = self._tmdb_explore_pages.get(media_type, 1) + 1
        generation = self._tmdb_explore_generation
        self._tmdb_explore_pages_loading.add(media_type)
        self._sync_explore_loading_indicator()
        self._start_worker(f'gisheh-tmdb-explore-{media_type.lower()}-{page}', self._load_next_tmdb_explore_page_worker, *(self.tmdb_token, generation, media_type, page))

    def _load_next_tmdb_explore_page_worker(
        self,
        token: str,
        generation: int,
        media_type: str,
        page: int,
    ) -> None:
        try:
            payload = ExploreController(tmdb_client).page(token, media_type, page)
            raw_records = payload.get("results", ())
            records: list[TitleRecord] = []
            image_work: list[tuple[str, str, str]] = []
            for position, raw in enumerate(raw_records, start=1):
                if not isinstance(raw, dict):
                    continue
                poster_path = str(raw.get("poster_path") or "")
                backdrop_path = str(raw.get("backdrop_path") or "")
                poster_file = tmdb_client.cached_image(poster_path, size="w500")
                backdrop_file = tmdb_client.cached_image(backdrop_path, size="w780")
                absolute_position = (page - 1) * 20 + position
                record = title_record_from_tmdb(
                    raw,
                    media_type,
                    absolute_position,
                    poster_file,
                    backdrop_file,
                )
                records.append(record)
                if poster_path and poster_file is None:
                    image_work.append((record.id, "poster", poster_path))
                if backdrop_path and backdrop_file is None:
                    image_work.append((record.id, "backdrop", backdrop_path))
            total_pages = int(payload.get("total_pages") or page)
        except tmdb_client.TmdbError as error:
            self._post_ui(
                self._on_next_tmdb_explore_page_failed,
                generation,
                media_type,
                str(error),
            )
            return

        self._post_ui(
            self._apply_next_tmdb_explore_page,
            generation,
            media_type,
            page,
            total_pages,
            tuple(records),
        )
        with self._image_executor() as executor:
            futures = {
                executor.submit(
                    tmdb_client.cache_image,
                    path,
                    size="w500" if kind == "poster" else "w780",
                ): (record_id, kind)
                for record_id, kind, path in image_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is None:
                    continue
                record_id, kind = futures[future]
                self._post_ui(
                    self._apply_tmdb_explore_image,
                    generation,
                    record_id,
                    kind,
                    image_file,
                )

    def _apply_next_tmdb_explore_page(
        self,
        generation: int,
        media_type: str,
        page: int,
        total_pages: int,
        records: tuple[TitleRecord, ...],
    ) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        existing_ids = {record.id for record in self.explore_records}
        additions = tuple(record for record in records if record.id not in existing_ids)
        self.explore_records = (*self.explore_records, *additions)
        self.explore_ids.update(record.id for record in additions)
        self.records_by_id.update({record.id: record for record in additions})
        self._tmdb_explore_pages[media_type] = page
        self._tmdb_explore_has_more[media_type] = bool(records) and page < total_pages
        self._tmdb_explore_pages_loading.discard(media_type)
        self._update_explore_genre_model(preserve=True)
        if self.active_destination == "explore" and self.active_media == media_type:
            self._refresh_explore(
                reset_scroll=False,
                preserve_existing_order=True,
            )
        self._sync_explore_loading_indicator()
        return GLib.SOURCE_REMOVE

    def _on_next_tmdb_explore_page_failed(
        self,
        generation: int,
        media_type: str,
        message: str,
    ) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_explore_pages_loading.discard(media_type)
        self._sync_explore_loading_indicator()
        self._app_log("Could not load the next TMDB Explore page: %s", message)
        self._toast(_("Could not load more titles from TMDB"))
        return GLib.SOURCE_REMOVE

    def _queue_tmdb_explore_search(self) -> None:
        if self._explore_search_debounce_source_id:
            GLib.source_remove(self._explore_search_debounce_source_id)
            self._explore_search_debounce_source_id = 0
        self._tmdb_search_generation += 1
        generation = self._tmdb_search_generation
        query = self.explore_search_entry.get_text().strip()
        self._tmdb_search_query = query
        self._tmdb_search_media = self.active_media
        self._tmdb_search_page = 0
        self._tmdb_search_total_pages = 0
        self.explore_search_records = ()
        self.explore_search_ids = set()
        self._tmdb_search_loading = bool(query and self.tmdb_token)
        if not query:
            self.records_by_id = {
                record.id: record for record in (*self.records, *self.explore_records)
            }
            self._refresh_explore()
            self._sync_explore_loading_indicator()
            return
        self._set_details_open(False)
        self._refresh_explore()
        self._sync_explore_loading_indicator()
        if not self.tmdb_token:
            self._toast(_("Connect TMDB to search its catalog"))
            return
        self._explore_search_debounce_source_id = GLib.timeout_add(
            350,
            self._start_tmdb_explore_search,
            generation,
            query,
            self.active_media,
        )

    def _start_tmdb_explore_search(
        self,
        generation: int,
        query: str,
        media_type: str,
    ) -> bool:
        self._explore_search_debounce_source_id = 0
        if (
            generation != self._tmdb_search_generation
            or query != self.explore_search_entry.get_text().strip()
            or media_type != self.active_media
            or not self.tmdb_token
        ):
            return GLib.SOURCE_REMOVE
        self._start_worker(f'gisheh-tmdb-search-{media_type.lower()}', self._load_tmdb_search_page_worker, *(self.tmdb_token, generation, media_type, query, 1))
        return GLib.SOURCE_REMOVE

    def _load_next_tmdb_search_page(self) -> None:
        if (
            not self.tmdb_token
            or not self._tmdb_search_query
            or self._tmdb_search_loading
            or self._tmdb_search_page >= self._tmdb_search_total_pages
        ):
            return
        page = self._tmdb_search_page + 1
        self._tmdb_search_loading = True
        self._sync_explore_loading_indicator()
        self._start_worker(f'gisheh-tmdb-search-{self.active_media.lower()}-{page}', self._load_tmdb_search_page_worker, *(self.tmdb_token, self._tmdb_search_generation, self.active_media, self._tmdb_search_query, page))

    def _load_tmdb_search_page_worker(
        self,
        token: str,
        generation: int,
        media_type: str,
        query: str,
        page: int,
    ) -> None:
        try:
            payload = ExploreController(tmdb_client).search(
                token,
                media_type,
                query,
                page,
            )
            raw_records = payload.get("results", ())
            records: list[TitleRecord] = []
            image_work: list[tuple[str, str, str]] = []
            for position, raw in enumerate(raw_records, start=1):
                if not isinstance(raw, dict):
                    continue
                poster_path = str(raw.get("poster_path") or "")
                backdrop_path = str(raw.get("backdrop_path") or "")
                poster_file = tmdb_client.cached_image(poster_path, size="w500")
                backdrop_file = tmdb_client.cached_image(backdrop_path, size="w780")
                absolute_position = (page - 1) * 20 + position
                record = title_record_from_tmdb(
                    raw,
                    media_type,
                    absolute_position,
                    poster_file,
                    backdrop_file,
                )
                records.append(record)
                if poster_path and poster_file is None:
                    image_work.append((record.id, "poster", poster_path))
                if backdrop_path and backdrop_file is None:
                    image_work.append((record.id, "backdrop", backdrop_path))
            total_pages = int(payload.get("total_pages") or page)
        except tmdb_client.TmdbError as error:
            self._post_ui(
                self._on_tmdb_search_failed,
                generation,
                media_type,
                query,
                str(error),
            )
            return

        self._post_ui(
            self._apply_tmdb_search_page,
            generation,
            media_type,
            query,
            page,
            total_pages,
            tuple(records),
        )
        with self._image_executor() as executor:
            futures = {
                executor.submit(
                    tmdb_client.cache_image,
                    path,
                    size="w500" if kind == "poster" else "w780",
                ): (record_id, kind)
                for record_id, kind, path in image_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is None:
                    continue
                record_id, kind = futures[future]
                self._post_ui(
                    self._apply_tmdb_search_image,
                    generation,
                    record_id,
                    kind,
                    image_file,
                )

    def _apply_tmdb_search_page(
        self,
        generation: int,
        media_type: str,
        query: str,
        page: int,
        total_pages: int,
        records: tuple[TitleRecord, ...],
    ) -> bool:
        if (
            generation != self._tmdb_search_generation
            or media_type != self.active_media
            or query != self.explore_search_entry.get_text().strip()
        ):
            return GLib.SOURCE_REMOVE
        existing_ids = {record.id for record in self.explore_search_records}
        additions = tuple(record for record in records if record.id not in existing_ids)
        self.explore_search_records = (
            additions if page == 1 else (*self.explore_search_records, *additions)
        )
        self.explore_search_ids = {record.id for record in self.explore_search_records}
        self.records_by_id.update(
            {record.id: record for record in self.explore_search_records}
        )
        self._tmdb_search_page = page
        self._tmdb_search_total_pages = total_pages
        self._tmdb_search_loading = False
        if self.active_destination == "explore":
            self._refresh_explore(
                reset_scroll=page == 1,
                preserve_existing_order=page > 1,
            )
        self._sync_explore_loading_indicator()
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_search_image(
        self,
        generation: int,
        record_id: str,
        kind: str,
        image_file: str,
    ) -> bool:
        if generation != self._tmdb_search_generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or record_id not in self.explore_search_ids:
            return GLib.SOURCE_REMOVE
        updated = replace(
            record,
            artwork_file=record.artwork_file or image_file,
            poster_file=image_file if kind == "poster" else record.poster_file,
            backdrop_file=(image_file if kind == "backdrop" else record.backdrop_file),
        )
        self.explore_search_records = tuple(
            updated if item.id == record_id else item
            for item in self.explore_search_records
        )
        self.explore_visible_records = tuple(
            updated if item.id == record_id else item
            for item in self.explore_visible_records
        )
        self.records_by_id[record_id] = updated
        self._update_explore_card_artwork(updated)
        if self.detail_record_id == record_id:
            self._update_details()
        return GLib.SOURCE_REMOVE

    def _on_tmdb_search_failed(
        self,
        generation: int,
        media_type: str,
        query: str,
        message: str,
    ) -> bool:
        if (
            generation != self._tmdb_search_generation
            or media_type != self.active_media
            or query != self.explore_search_entry.get_text().strip()
        ):
            return GLib.SOURCE_REMOVE
        self._tmdb_search_loading = False
        self._sync_explore_loading_indicator()
        self._app_log("TMDB search failed: %s", message, level=logging.WARNING)
        self._toast(_("Could not search TMDB"))
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_explore_image(
        self,
        generation: int,
        record_id: str,
        kind: str,
        image_file: str,
    ) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or record_id not in self.explore_ids:
            return GLib.SOURCE_REMOVE
        updated = replace(
            record,
            artwork_file=record.artwork_file or image_file,
            poster_file=image_file if kind == "poster" else record.poster_file,
            backdrop_file=(image_file if kind == "backdrop" else record.backdrop_file),
        )
        self.explore_records = tuple(
            updated if item.id == record_id else item for item in self.explore_records
        )
        self.explore_visible_records = tuple(
            updated if item.id == record_id else item
            for item in self.explore_visible_records
        )
        self.records_by_id[record_id] = updated
        self._update_explore_card_artwork(updated)
        if self.detail_record_id == record_id:
            self._update_details()
        return GLib.SOURCE_REMOVE

    def _update_explore_card_artwork(self, record: TitleRecord) -> None:
        button = getattr(self, "_explore_card_buttons", {}).get(record.id)
        layout = getattr(self, "_explore_card_layouts", {}).get(record.id)
        if button is None or layout is None:
            return
        kind, span = layout
        overlay = button.get_child()
        if not isinstance(overlay, Gtk.Overlay):
            return
        preferred_artwork = (
            record.backdrop_file
            if kind in ("hero", "landscape")
            else record.poster_file
        )
        artwork_record = replace(
            record,
            artwork_file=preferred_artwork or record.artwork_file,
        )
        art_width = 480 if kind == "hero" else 320 if kind == "landscape" else 160
        artwork = PosterWidget(
            artwork_record,
            art_width,
            self._explore_card_height(kind, span),
            variant_offset=1 if kind == "landscape" else 0,
            show_text=False,
            flexible_width=True,
        )
        artwork.set_hexpand(True)
        artwork.set_vexpand(True)
        artwork.set_size_request(-1, -1)
        overlay.set_child(artwork)

    def _on_tmdb_explore_failed(self, generation: int, message: str) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_explore_pages_loading.difference_update(MEDIA_TYPES)
        self._sync_explore_loading_indicator()
        self._app_log("TMDB Explore failed: %s", message, level=logging.WARNING)
        self._toast(_("TMDB is unavailable — Explore could not be loaded"))
        return GLib.SOURCE_REMOVE

    def _load_tmdb_details_async(self, record: TitleRecord) -> None:
        if not self.tmdb_token:
            self._app_log(
                "TMDB details skipped for %s: no credential is available.",
                record.title,
                level=logging.WARNING,
            )
            return
        if (
            record.tmdb_id is None
            or record.tmdb_media_type is None
            or record.id in self._tmdb_details_loading
            or record.id in self._tmdb_details_loaded
        ):
            return
        self._tmdb_details_loading.add(record.id)
        if self.selected_id == record.id:
            self._update_details()
        generation = self._tmdb_detail_generations.get(record.id, 0) + 1
        self._tmdb_detail_generations[record.id] = generation
        self._app_log(
            "Scheduling TMDB details request for %s (%s/%s, language=%s).",
            record.title,
            record.tmdb_media_type,
            record.tmdb_id,
            tmdb_client.active_language(),
        )
        self._start_worker(f'gisheh-tmdb-{record.tmdb_id}', self._load_tmdb_details_worker, *(record, self.tmdb_token, generation))

    def _load_tmdb_details_worker(
        self,
        record: TitleRecord,
        token: str,
        generation: int,
    ) -> None:
        started_at = time.monotonic()
        self._app_log(
            "TMDB details request started for %s (%s/%s).",
            record.title,
            record.tmdb_media_type,
            record.tmdb_id,
        )
        try:
            payload = DetailsController(tmdb_client).fetch(
                token,
                record.tmdb_media_type or "movie",
                record.tmdb_id or 0,
            )
            poster_path = str(payload.get("poster_path") or "")
            backdrop_path = str(payload.get("backdrop_path") or "")
            poster_file = tmdb_client.cached_image(poster_path, size="w500")
            backdrop_file = tmdb_client.cached_image(backdrop_path, size="w780")
            genres = (
                localize_genre_names(
                    tuple(
                        str(item["name"])
                        for item in payload.get("genres", ())
                        if isinstance(item, dict) and item.get("name")
                    )
                )
                or record.genres
            )
            cast_items = [
                item
                for item in payload.get("credits", {}).get("cast", ())[:12]
                if isinstance(item, dict)
            ]
            backdrop_items = [
                item
                for item in payload.get("images", {}).get("backdrops", ())[:8]
                if isinstance(item, dict) and item.get("file_path")
            ]
            poster_items = [
                item
                for item in payload.get("images", {}).get("posters", ())[:8]
                if isinstance(item, dict) and item.get("file_path")
            ]
            cast = tuple(
                CastMember(
                    str(item.get("name", "—")),
                    str(item.get("character") or _("Cast")),
                    tmdb_client.cached_image(
                        str(item.get("profile_path") or ""),
                        size="w185",
                    ),
                )
                for item in cast_items
            )
            gallery_backdrops = tuple(
                cached
                for item in backdrop_items
                for cached in (
                    tmdb_client.cached_image(
                        str(item["file_path"]),
                        size="w500",
                    ),
                )
                if cached is not None
            )
            gallery_posters = tuple(
                cached
                for item in poster_items
                for cached in (
                    tmdb_client.cached_image(
                        str(item["file_path"]),
                        size="w342",
                    ),
                )
                if cached is not None
            )
            if record.tmdb_media_type == "movie":
                directors = [
                    str(item.get("name"))
                    for item in payload.get("credits", {}).get("crew", ())
                    if isinstance(item, dict) and item.get("job") == "Director"
                ]
                creator = ", ".join(directors[:2]) or record.creator
                seasons: tuple[SeasonInfo, ...] = ()
            else:
                creators = [
                    str(item.get("name"))
                    for item in payload.get("created_by", ())
                    if isinstance(item, dict) and item.get("name")
                ]
                creator = ", ".join(creators[:2]) or record.creator
                progress_indexes = main_progress_season_indexes(record.seasons)
                total_watched = sum(
                    record.seasons[index].watched for index in progress_indexes
                )
                season_rows = [
                    item
                    for item in payload.get("seasons", ())
                    if isinstance(item, dict)
                ]
                existing_episode_items = {
                    season.number: season.episode_items
                    for season in record.seasons
                    if season.episode_items
                }
                watched_by_number: dict[int, int] = {}
                remaining_watched = total_watched
                for item in sorted(
                    season_rows,
                    key=lambda value: int(value.get("season_number") or 0),
                ):
                    season_number = int(item.get("season_number") or 0)
                    if season_number <= 0:
                        watched_by_number[season_number] = 0
                        continue
                    episode_count = int(item.get("episode_count") or 0)
                    watched_by_number[season_number] = min(
                        episode_count,
                        remaining_watched,
                    )
                    remaining_watched = max(0, remaining_watched - episode_count)
                seasons = tuple(
                    SeasonInfo(
                        id=f"s{int(item.get('season_number', position))}",
                        number=int(item.get("season_number", position)),
                        title=str(
                            item.get("name")
                            or _("Season {number}").format(number=position)
                        ),
                        watched=watched_by_number.get(
                            int(item.get("season_number", position)),
                            0,
                        ),
                        episodes=int(item.get("episode_count") or 0),
                        episode_items=existing_episode_items.get(
                            int(item.get("season_number", position)),
                            (),
                        ),
                    )
                    for position, item in enumerate(season_rows, start=1)
                )
            runtime = runtime_from_tmdb(payload, record.runtime)
            countries = [
                str(item.get("name"))
                for item in payload.get("production_countries", ())
                if isinstance(item, dict) and item.get("name")
            ]
            networks = [
                str(item.get("name"))
                for item in payload.get("networks", ())
                if isinstance(item, dict) and item.get("name")
            ]
            raw_videos = payload.get("videos", {})
            raw_videos = (
                raw_videos.get("results", ()) if isinstance(raw_videos, dict) else ()
            )
            videos = video_infos_from_tmdb(raw_videos)
            video_titles = tuple(item.title for item in videos)
            recommendation_ids = tuple(
                f"tmdb-{record.tmdb_media_type}-{int(item['id'])}"
                for item in payload.get("recommendations", {}).get("results", ())[:12]
                if isinstance(item, dict) and item.get("id") is not None
            )
            tmdb_record = enrich_record_from_tmdb(
                record,
                payload,
                poster_file=poster_file,
                backdrop_file=backdrop_file,
            )
            updated = replace(
                tmdb_record,
                runtime=runtime,
                genres=genres,
                country=", ".join(localize_countries(tuple(countries[:2])))
                or record.country,
                creator=creator,
                description=str(payload.get("overview") or record.description),
                availability=localize_tmdb_status(
                    str(payload.get("status") or record.availability),
                    fallback=record.availability,
                ),
                network=", ".join(networks[:2]) or record.network,
                cast=cast or record.cast,
                seasons=seasons or record.seasons,
                recommendations=recommendation_ids or record.recommendations,
                # The canonical card artwork stays portrait. Landscape views
                # opt into backdrop_file explicitly when they render.
                artwork_file=poster_file or backdrop_file or record.artwork_file,
                poster_file=poster_file or record.poster_file,
                backdrop_file=backdrop_file or record.backdrop_file,
                gallery_backdrops=gallery_backdrops,
                gallery_posters=gallery_posters,
                video_titles=video_titles,
                videos=videos,
            )
        except (KeyError, OSError, TypeError, ValueError, tmdb_client.TmdbError) as error:
            self._post_ui(
                self._on_tmdb_details_failed,
                record.id,
                generation,
                str(error),
            )
            return
        self._app_log(
            "TMDB details metadata received for %s in %.1fs.",
            record.title,
            time.monotonic() - started_at,
        )
        profile_work = [
            (index, str(item.get("profile_path") or ""))
            for index, item in enumerate(cast_items)
            if item.get("profile_path") and cast[index].profile_file is None
        ]
        gallery_work = [
            ("backdrop", str(item["file_path"]), "w500")
            for item in backdrop_items
            if tmdb_client.cached_image(str(item["file_path"]), size="w500") is None
        ] + [
            ("poster", str(item["file_path"]), "w342")
            for item in poster_items
            if tmdb_client.cached_image(str(item["file_path"]), size="w342") is None
        ]
        gallery_pending = {
            kind: sum(work_kind == kind for work_kind, _path, _size in gallery_work)
            for kind in ("backdrop", "poster")
        }
        self._post_ui(
            self._apply_tmdb_details,
            generation,
            updated,
            tuple(index for index, _path in profile_work),
            gallery_pending,
        )

        # Recommendations are visible in the first details viewport, so add
        # their records and prioritize their posters before secondary cast and
        # gallery downloads.
        raw_recommendations = payload.get("recommendations", {})
        raw_recommendations = (
            raw_recommendations.get("results", ())
            if isinstance(raw_recommendations, dict)
            else ()
        )
        recommendations = recommendation_records_from_tmdb(raw_recommendations, updated)
        self._post_ui(
            self._apply_tmdb_recommendations,
            record.id,
            generation,
            recommendations,
        )
        poster_by_tmdb: dict[int, str] = {}
        if isinstance(raw_recommendations, (list, tuple)):
            for raw_item in raw_recommendations:
                if not isinstance(raw_item, dict):
                    continue
                try:
                    raw_id = int(raw_item["id"])
                except (TypeError, ValueError, KeyError):
                    continue
                raw_path = str(raw_item.get("poster_path") or "")
                if raw_path and raw_id not in poster_by_tmdb:
                    poster_by_tmdb[raw_id] = raw_path
        recommendation_work = [
            (item.id, poster_by_tmdb[item.tmdb_id])
            for item in recommendations
            if item.poster_file is None
            and item.tmdb_id is not None
            and poster_by_tmdb.get(item.tmdb_id)
        ]
        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size="w342"): item_id
                for item_id, path in recommendation_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file:
                    self._post_ui(
                        self._apply_tmdb_recommendation_artwork,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

        main_images = [
            ("poster", poster_path, "w500")
            if poster_path and poster_file is None
            else None,
            ("backdrop", backdrop_path, "w780")
            if backdrop_path and backdrop_file is None
            else None,
        ]
        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): kind
                for job in main_images
                if job is not None
                for kind, path, size in (job,)
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is not None:
                    self._post_ui(
                        self._apply_tmdb_detail_artwork,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size="w185"): index
                for index, path in profile_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                self._post_ui(
                    self._apply_tmdb_cast_artwork,
                    record.id,
                    generation,
                    futures[future],
                    image_file,
                )

        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): kind
                for kind, path, size in gallery_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                self._post_ui(
                    self._apply_tmdb_gallery_artwork,
                    record.id,
                    generation,
                    futures[future],
                    image_file,
                )

        video_work = [
            (index, item.key)
            for index, item in enumerate(videos)
            if item.thumbnail_file is None
        ]
        with self._image_executor() as executor:
            futures = {
                executor.submit(tmdb_client.cache_youtube_thumbnail, key): index
                for index, key in video_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file:
                    self._post_ui(
                        self._apply_tmdb_video_thumbnail,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

    def _apply_tmdb_details(
        self,
        generation: int,
        updated: TitleRecord,
        cast_pending: tuple[int, ...],
        gallery_pending: dict[str, int],
    ) -> bool:
        if self._tmdb_detail_generations.get(updated.id) != generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_details_loading.discard(updated.id)
        self._tmdb_details_loaded.add(updated.id)
        self._tmdb_cast_images_loading[updated.id] = set(cast_pending)
        self._tmdb_gallery_images_loading[updated.id] = gallery_pending
        self._store_tmdb_record(updated)
        self._app_log("TMDB details applied for %s.", updated.title)
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_recommendations(
        self,
        record_id: str,
        generation: int,
        recommendations: tuple[TitleRecord, ...],
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        for item in recommendations:
            if item.id not in self.library_ids:
                self.records_by_id[item.id] = item
        self._tmdb_recommendations[record_id] = tuple(
            item.id for item in recommendations
        )
        record = self.records_by_id.get(record_id)
        if (
            record is not None
            and self.detail_record_id == record_id
            and self.selected_id == record_id
        ):
            self._populate_recommendations(record)
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_recommendation_artwork(
        self,
        record_id: str,
        generation: int,
        item_id: str,
        image_file: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        item = self.records_by_id.get(item_id)
        if item is None or item.id in self.library_ids:
            return GLib.SOURCE_REMOVE
        self.records_by_id[item_id] = replace(
            item,
            artwork_file=image_file,
            poster_file=image_file,
        )
        record = self.records_by_id.get(record_id)
        if (
            record is not None
            and self.detail_record_id == record_id
            and self.selected_id == record_id
        ):
            self._populate_recommendations(record)
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_video_thumbnail(
        self,
        record_id: str,
        generation: int,
        index: int,
        image_file: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or index >= len(record.videos):
            return GLib.SOURCE_REMOVE
        videos = tuple(
            replace(item, thumbnail_file=image_file) if position == index else item
            for position, item in enumerate(record.videos)
        )
        self._store_tmdb_record(replace(record, videos=videos))
        return GLib.SOURCE_REMOVE

    def _store_tmdb_record(
        self,
        updated: TitleRecord,
        *,
        refresh_details: bool = True,
    ) -> None:
        canonical = self._canonical_record_id(updated)
        if canonical in getattr(self, "local_library_records", {}):
            local_updated = replace(updated, id=canonical)
            self.local_library_records[canonical] = local_updated
            self.records = tuple(
                local_updated
                if self._canonical_record_id(record) == canonical
                else record
                for record in self.records
            )
        self.records_by_id[updated.id] = updated
        self.records = tuple(
            updated if record.id == updated.id else record for record in self.records
        )
        self.explore_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_records
        )
        self.explore_search_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_search_records
        )
        self.visible_records = tuple(
            updated if record.id == updated.id else record
            for record in self.visible_records
        )
        self.explore_visible_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_visible_records
        )
        if updated.id in self.explore_ids or updated.id in self.explore_search_ids:
            self._update_explore_card_artwork(updated)
        if refresh_details and self.selected_id == updated.id:
            self._update_details()

    def _replace_episode_info(
        self,
        record_id: str,
        season_number: int,
        episode_number: int,
        transform: Any,
    ) -> TitleRecord | None:
        record = self.records_by_id.get(record_id)
        if record is None:
            return None
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None:
            return None
        episodes = self._episodes_for_season(record, season_index)
        if not any(episode.number == episode_number for episode in episodes):
            return None
        episodes = tuple(
            transform(episode) if episode.number == episode_number else episode
            for episode in episodes
        )
        updated_season = replace(seasons[season_index], episode_items=episodes)
        updated_seasons = tuple(
            updated_season if index == season_index else season
            for index, season in enumerate(seasons)
        )
        return replace(record, seasons=updated_seasons)

    @staticmethod
    def _tmdb_season_cache_key(record_id: str, season_number: int) -> str:
        return f"{record_id}:s{season_number}"

    def _season_episode_details_ready(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> bool:
        """Whether opening an episode can use a complete season response."""
        seasons = self._series_seasons(record)
        if not seasons:
            return False
        season_index = max(0, min(season_index, len(seasons) - 1))
        if not getattr(self, "tmdb_token", None) or record.tmdb_id is None:
            # No richer remote representation exists for this title, so its
            # locally available episode data is the complete representation.
            return True
        key = self._tmdb_season_cache_key(
            record.id,
            seasons[season_index].number,
        )
        return key in getattr(self, "_tmdb_season_details_loaded", set())

    def _load_tmdb_season_details_async(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons or not self.tmdb_token or record.tmdb_id is None:
            return
        season = seasons[max(0, min(season_index, len(seasons) - 1))]
        season_key = self._tmdb_season_cache_key(record.id, season.number)
        if (
            season_key in self._tmdb_season_details_loading
            or season_key in self._tmdb_season_details_loaded
        ):
            return
        self._tmdb_season_details_loading.add(season_key)
        token = self.tmdb_token
        assert token is not None
        self._start_worker(f'gisheh-tmdb-season-{record.tmdb_id}-{season.number}', self._load_tmdb_season_details_worker, *(record.id, token, record.tmdb_id, season.number, season_key))

    def _load_tmdb_season_details_worker(
        self,
        record_id: str,
        token: str,
        tmdb_id: int,
        season_number: int,
        season_key: str,
    ) -> None:
        try:
            payload = DetailsController(tmdb_client).season(
                token,
                tmdb_id,
                season_number,
            )
            raw_episodes = payload.get("episodes", ())
            if not isinstance(raw_episodes, (list, tuple)):
                raw_episodes = ()
            updates: list[tuple[int, str, str, str, str, Any, str | None]] = []
            pending_stills: list[tuple[int, str]] = []
            for item in raw_episodes:
                if not isinstance(item, dict):
                    continue
                try:
                    episode_number = int(item.get("episode_number"))
                except (TypeError, ValueError):
                    continue
                try:
                    title = str(item.get("name") or "").strip()
                    air_date = str(item.get("air_date") or "").strip()
                    overview = str(item.get("overview") or "").strip()
                    try:
                        runtime_value = int(item.get("runtime") or 0)
                    except (TypeError, ValueError):
                        runtime_value = 0
                    runtime = (
                        format_watch_time(runtime_value) if runtime_value > 0 else ""
                    )
                    guest_stars = item.get("guest_stars")
                    if isinstance(guest_stars, list) and guest_stars:
                        cast_items: list[CastMember] = []
                        for member in guest_stars[:12]:
                            if not isinstance(member, dict):
                                continue
                            profile_path = str(member.get("profile_path") or "")
                            try:
                                profile_file = (
                                    tmdb_client.cached_image(profile_path, size="w185")
                                    if profile_path
                                    else None
                                )
                            except OSError:
                                profile_file = None
                            cast_items.append(
                                CastMember(
                                    name=str(member.get("name") or _("Unknown")),
                                    role=str(member.get("character") or _("Guest star")),
                                    profile_file=profile_file,
                                )
                            )
                        cast: tuple[CastMember, ...] = tuple(cast_items)
                    else:
                        cast = ()
                    still_path = str(item.get("still_path") or "").strip()
                    cached_still: str | None = None
                    if still_path:
                        try:
                            cached_still = tmdb_client.cached_image(
                                still_path, size="w780"
                            )
                        except OSError:
                            cached_still = None
                        if cached_still is None:
                            pending_stills.append((episode_number, still_path))
                    updates.append(
                        (
                            episode_number,
                            title,
                            air_date,
                            overview,
                            runtime,
                            cast,
                            cached_still,
                        )
                    )
                except (
                    AttributeError,
                    KeyError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as error:
                    self._app_log(
                        "Skipping malformed TMDB season episode: %s",
                        error,
                        level=logging.WARNING,
                    )
                    continue
            downloaded_stills: dict[int, str] = {}
            for episode_number, still_path in pending_stills:
                try:
                    image_file = tmdb_client.cache_image(still_path, size="w780")
                except (OSError, tmdb_client.TmdbError) as error:
                    self._app_log(
                        "TMDB season still failed: %s",
                        error,
                        level=logging.WARNING,
                    )
                    continue
                if image_file:
                    downloaded_stills[episode_number] = image_file
            complete_updates = tuple(
                (
                    episode_number,
                    title,
                    air_date,
                    overview,
                    runtime,
                    cast,
                    downloaded_stills.get(episode_number, cached_still),
                )
                for (
                    episode_number,
                    title,
                    air_date,
                    overview,
                    runtime,
                    cast,
                    cached_still,
                ) in updates
            )
            # Publish the season only after every pending still has either
            # loaded or failed. Until this callback runs, episode rows remain
            # non-activatable and cannot open with partial data.
            self._post_ui(
                self._apply_tmdb_season_details,
                record_id,
                season_number,
                season_key,
                complete_updates,
            )
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            tmdb_client.TmdbError,
        ) as error:
            self._post_ui(self._on_tmdb_season_details_failed, season_key, str(error))

    def _apply_tmdb_season_details(
        self,
        record_id: str,
        season_number: int,
        season_key: str,
        updates: tuple[tuple[int, str, str, str, str, Any, str | None], ...],
    ) -> bool:
        self._tmdb_season_details_loading.discard(season_key)
        record = self.records_by_id.get(record_id)
        if record is None:
            return GLib.SOURCE_REMOVE
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None:
            return GLib.SOURCE_REMOVE
        season = seasons[season_index]
        base_episodes = self._episodes_for_season(record, season_index)
        by_number = {entry[0]: entry for entry in updates}
        merged: list[EpisodeInfo] = []
        for episode in base_episodes:
            entry = by_number.get(episode.number)
            if entry is None:
                merged.append(episode)
                continue
            _number, title, air_date, overview, runtime, cast, cached_still = entry
            new_cast = cast if isinstance(cast, tuple) and cast else episode.cast
            if not isinstance(new_cast, tuple):
                new_cast = episode.cast
            merged.append(
                replace(
                    episode,
                    title=title or episode.title,
                    date=air_date or episode.date,
                    description=overview or episode.description,
                    runtime=runtime or episode.runtime,
                    cast=new_cast,
                    artwork_file=cached_still or episode.artwork_file,
                )
            )
        updated_season = replace(season, episode_items=tuple(merged))
        updated_seasons = tuple(
            updated_season if index == season_index else item
            for index, item in enumerate(seasons)
        )
        updated = replace(record, seasons=updated_seasons)
        self._tmdb_season_details_loaded.add(season_key)
        for episode in merged:
            self._tmdb_episode_details_loaded.add(
                f"{record_id}:s{season_number}:e{episode.number}"
            )
        self._store_tmdb_record(updated, refresh_details=False)
        self._refresh_visible_season_page(updated, season_number)
        self._refresh_visible_episode_for_season(updated, season_number)
        return GLib.SOURCE_REMOVE

    def _refresh_visible_season_page(
        self,
        record: TitleRecord,
        season_number: int,
    ) -> None:
        if (
            self.detail_record_id != record.id
            or self.detail_navigation.get_visible_page_tag() != "season"
        ):
            return
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None:
            return
        if self.current_season_index != season_index:
            return
        scroll_value = self.season_details_scroller.get_vadjustment().get_value()
        self._populate_season_page(record, season_index, reset_scroll=False)
        self._scroll_to_value(self.season_details_scroller, scroll_value)

    def _refresh_visible_season_artwork(
        self,
        record: TitleRecord,
        season_number: int,
        episode_number: int,
    ) -> None:
        """Replace one loaded still without rebuilding or reordering the list."""
        if self.detail_record_id != record.id:
            return
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None or self.current_season_index != season_index:
            return
        episode = next(
            (
                item
                for item in self._episodes_for_season(record, season_index)
                if item.number == episode_number
            ),
            None,
        )
        if episode is None:
            return
        row = self.season_episodes_list.get_first_child()
        while row is not None:
            if getattr(row, "episode_number", None) == episode_number:
                previous = getattr(row, "episode_artwork", None)
                if previous is not None:
                    row.remove(previous)
                artwork = self._episode_artwork(record, episode, 112, 63)
                row.episode_artwork = artwork
                row.add_prefix(artwork)
                return
            row = row.get_next_sibling()

    def _refresh_visible_episode_for_season(
        self,
        record: TitleRecord,
        season_number: int,
    ) -> None:
        if (
            self.detail_record_id != record.id
            or self.detail_navigation.get_visible_page_tag() != "episode"
        ):
            return
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None:
            return
        if self.current_season_index != season_index:
            return
        episodes = self._episodes_for_season(record, season_index)
        if not episodes:
            return
        episode_index = max(0, min(self.current_episode_index, len(episodes) - 1))
        self._populate_episode_page(
            record, season_index, episode_index, reset_scroll=False
        )

    def _on_tmdb_season_details_failed(self, season_key: str, message: str) -> bool:
        self._tmdb_season_details_loading.discard(season_key)
        self._app_log("TMDB season details failed: %s", message, level=logging.WARNING)
        self._toast(_("Season details could not be loaded from TMDB"))
        return GLib.SOURCE_REMOVE

    def _load_tmdb_episode_details_async(
        self,
        record: TitleRecord,
        season_index: int,
        episode_index: int,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons or not self.tmdb_token or record.tmdb_id is None:
            return
        season = seasons[max(0, min(season_index, len(seasons) - 1))]
        episodes = self._episodes_for_season(record, season_index)
        if not episodes:
            return
        episode = episodes[max(0, min(episode_index, len(episodes) - 1))]
        season_key = self._tmdb_season_cache_key(record.id, season.number)
        if (
            season_key in self._tmdb_season_details_loading
            or season_key in self._tmdb_season_details_loaded
        ):
            return
        key = f"{record.id}:s{season.number}:e{episode.number}"
        if (
            key in self._tmdb_episode_details_loading
            or key in self._tmdb_episode_details_loaded
        ):
            return
        self._tmdb_episode_details_loading.add(key)
        token = self.tmdb_token
        assert token is not None
        self._start_worker(f'gisheh-tmdb-episode-{record.tmdb_id}-{season.number}-{episode.number}', self._load_tmdb_episode_details_worker, *(record.id, token, record.tmdb_id, season.number, episode.number, key))

    def _load_tmdb_episode_details_worker(
        self,
        record_id: str,
        token: str,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        key: str,
    ) -> None:
        try:
            payload = DetailsController(tmdb_client).episode(
                token,
                tmdb_id,
                season_number,
                episode_number,
            )
            runtime_value = int(payload.get("runtime") or 0)
            runtime = format_watch_time(runtime_value) if runtime_value else ""
            guest_stars = payload.get("guest_stars")
            if not isinstance(guest_stars, list):
                guest_stars = []
            cast = tuple(
                CastMember(
                    name=str(item.get("name") or _("Unknown")),
                    role=str(item.get("character") or _("Guest star")),
                    profile_file=tmdb_client.cached_image(
                        str(item.get("profile_path") or ""),
                        size="w185",
                    ),
                )
                for item in guest_stars[:12]
                if isinstance(item, dict)
            )
            still_path = str(payload.get("still_path") or "")
            cached_still = tmdb_client.cached_image(still_path, size="w780")
            self._post_ui(
                self._apply_tmdb_episode_details,
                record_id,
                season_number,
                episode_number,
                key,
                str(
                    payload.get("name")
                    or _("Episode {number}").format(number=episode_number)
                ),
                str(payload.get("air_date") or _("Air date unavailable")),
                str(
                    payload.get("overview")
                    or _("No episode overview is available.")
                ),
                runtime,
                cast,
                cached_still,
            )
            if still_path and cached_still is None:
                image_file = tmdb_client.cache_image(still_path, size="w780")
                if image_file:
                    self._post_ui(
                        self._apply_tmdb_episode_artwork,
                        record_id,
                        season_number,
                        episode_number,
                        image_file,
                    )
        except (tmdb_client.TmdbError, TypeError, ValueError) as error:
            self._post_ui(self._on_tmdb_episode_details_failed, key, str(error))

    def _apply_tmdb_episode_details(
        self,
        record_id: str,
        season_number: int,
        episode_number: int,
        key: str,
        title: str,
        date_value: str,
        description: str,
        runtime: str,
        cast: tuple[CastMember, ...],
        artwork_file: str | None,
    ) -> bool:
        self._tmdb_episode_details_loading.discard(key)
        updated = self._replace_episode_info(
            record_id,
            season_number,
            episode_number,
            lambda episode: replace(
                episode,
                title=title,
                date=date_value,
                description=description,
                runtime=runtime,
                cast=cast,
                artwork_file=artwork_file or episode.artwork_file,
            ),
        )
        if updated is not None:
            self._tmdb_episode_details_loaded.add(key)
            self._store_tmdb_record(updated, refresh_details=False)
            if artwork_file:
                self._refresh_visible_season_artwork(
                    updated,
                    season_number,
                    episode_number,
                )
            self._refresh_visible_episode_page(updated, season_number, episode_number)
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_episode_artwork(
        self,
        record_id: str,
        season_number: int,
        episode_number: int,
        image_file: str,
    ) -> bool:
        updated = self._replace_episode_info(
            record_id,
            season_number,
            episode_number,
            lambda episode: replace(episode, artwork_file=image_file),
        )
        if updated is not None:
            self._store_tmdb_record(updated, refresh_details=False)
            self._refresh_visible_season_artwork(
                updated,
                season_number,
                episode_number,
            )
            self._refresh_visible_episode_page(updated, season_number, episode_number)
        return GLib.SOURCE_REMOVE

    def _refresh_visible_episode_page(
        self,
        record: TitleRecord,
        season_number: int,
        episode_number: int,
    ) -> None:
        if (
            self.detail_record_id != record.id
            or self.detail_navigation.get_visible_page_tag() != "episode"
        ):
            return
        seasons = self._series_seasons(record)
        season_index = next(
            (
                index
                for index, season in enumerate(seasons)
                if season.number == season_number
            ),
            None,
        )
        if season_index is None:
            return
        if self.current_season_index != season_index:
            return
        episodes = self._episodes_for_season(record, season_index)
        if not (0 <= self.current_episode_index < len(episodes)):
            return
        # Artwork/detail callbacks may arrive for several episodes. Refresh
        # only the episode the user actually opened; otherwise every callback
        # would navigate the page to its own episode number.
        if episodes[self.current_episode_index].number != episode_number:
            return
        episode_index = next(
            (
                index
                for index, episode in enumerate(episodes)
                if episode.number == episode_number
            ),
            None,
        )
        if episode_index is not None:
            self._populate_episode_page(
                record,
                season_index,
                episode_index,
                reset_scroll=False,
            )

    def _on_tmdb_episode_details_failed(self, key: str, message: str) -> bool:
        self._tmdb_episode_details_loading.discard(key)
        self._app_log("TMDB episode details failed: %s", message, level=logging.WARNING)
        self._toast(_("Episode details could not be loaded from TMDB"))
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_detail_artwork(
        self,
        record_id: str,
        generation: int,
        kind: str,
        image_file: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None:
            return GLib.SOURCE_REMOVE
        poster_file = image_file if kind == "poster" else record.poster_file
        backdrop_file = image_file if kind == "backdrop" else record.backdrop_file
        self._store_tmdb_record(
            replace(
                record,
                artwork_file=poster_file or backdrop_file or record.artwork_file,
                poster_file=poster_file,
                backdrop_file=backdrop_file,
            )
        )
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_cast_artwork(
        self,
        record_id: str,
        generation: int,
        index: int,
        image_file: str | None,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or index >= len(record.cast):
            return GLib.SOURCE_REMOVE
        self._tmdb_cast_images_loading.setdefault(record_id, set()).discard(index)
        if image_file is None:
            if self.selected_id == record_id:
                self._update_details()
            return GLib.SOURCE_REMOVE
        cast = tuple(
            replace(member, profile_file=image_file) if position == index else member
            for position, member in enumerate(record.cast)
        )
        self._store_tmdb_record(replace(record, cast=cast))
        return GLib.SOURCE_REMOVE

    def _apply_tmdb_gallery_artwork(
        self,
        record_id: str,
        generation: int,
        kind: str,
        image_file: str | None,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None:
            return GLib.SOURCE_REMOVE
        pending = self._tmdb_gallery_images_loading.setdefault(record_id, {})
        pending[kind] = max(0, pending.get(kind, 0) - 1)
        if image_file is None:
            if self.selected_id == record_id:
                self._update_details()
            return GLib.SOURCE_REMOVE
        if kind == "poster":
            gallery = tuple(dict.fromkeys((*record.gallery_posters, image_file)))
            updated = replace(record, gallery_posters=gallery)
        else:
            gallery = tuple(dict.fromkeys((*record.gallery_backdrops, image_file)))
            updated = replace(record, gallery_backdrops=gallery)
        self._store_tmdb_record(updated)
        return GLib.SOURCE_REMOVE

    def _on_tmdb_details_failed(
        self,
        record_id: str,
        generation: int,
        message: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_details_loading.discard(record_id)
        self._tmdb_cast_images_loading.pop(record_id, None)
        self._tmdb_gallery_images_loading.pop(record_id, None)
        record = getattr(self, "records_by_id", {}).get(record_id)
        self._app_log(
            "TMDB details failed for %s: %s",
            record.title if record is not None else record_id,
            message,
            level=logging.WARNING,
        )
        if self.selected_id == record_id:
            self._update_details()
        return GLib.SOURCE_REMOVE

    def _on_preferences_clicked(self, _button: Gtk.Button | None) -> None:
        self._update_settings_account_rows()
        self._close_sidebar_overlay()
        self.settings_dialog.present(self.window)

    def _on_tmdb_settings_clicked(self, button: Gtk.Button) -> None:
        if tmdb_client.token_source() in {"bundled", "environment"}:
            application = self.window.get_application()
            if application is not None:
                application.activate_action("credits", None)
            return
        self._show_tmdb_token_dialog(button)

    def _show_tmdb_token_dialog(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=(
                _("Change TMDB developer override")
                if tmdb_client.token_source() == "user"
                else _("Configure this development build")
            ),
            body=(
                _(
                    "Public releases should include Gisheh's approved TMDB credential. "
                    "For local development only, you can enter your own API Read Access "
                    "Token; it will be stored only for this user."
                )
            ),
        )
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_tooltip_text(_("TMDB API Read Access Token"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save and connect"))
        dialog.set_response_enabled("save", False)
        entry.connect(
            "changed",
            lambda field: dialog.set_response_enabled(
                "save", bool(field.get_text().strip())
            ),
        )
        dialog.set_focus(entry)
        entry.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("TMDB API Read Access Token")]
        )
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_tmdb_token_response, entry)
        dialog.present(self.settings_dialog)

    def _on_tmdb_token_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
        entry: Gtk.PasswordEntry,
    ) -> None:
        if response != "save":
            return
        token = entry.get_text().strip()
        if not token:
            self._toast(_("Enter a TMDB Read Access Token"))
            return
        try:
            tmdb_client.store_token(token)
        except tmdb_client.TmdbError as error:
            print(f"Gisheh TMDB token: {error}", file=sys.stderr)
            self._toast(_("Could not save the TMDB token"))
            return

        self.tmdb_token = token
        self._update_settings_account_rows()
        self._tmdb_details_loading.clear()
        self._tmdb_details_loaded.clear()
        self._tmdb_episode_details_loading.clear()
        self._tmdb_episode_details_loaded.clear()
        self._tmdb_season_details_loading.clear()
        self._tmdb_season_details_loaded.clear()
        self._tmdb_cast_images_loading.clear()
        self._tmdb_gallery_images_loading.clear()
        self._toast(_("Connecting to TMDB…"))
        if self.simkl_connected:
            self._load_tmdb_library_async(self.records)
        self._load_tmdb_explore_async()

    def _on_tmdb_disconnect_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Remove the TMDB connection?"),
            body=(
                _(
                    "The locally stored read token will be removed. Downloaded "
                    "artwork remains available until you clear the cache."
                )
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove Token"))
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_tmdb_disconnect_response)
        dialog.present(self.settings_dialog)

    def _on_tmdb_disconnect_response(
        self, _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "remove":
            return
        try:
            tmdb_client.clear_token()
        except tmdb_client.TmdbError as error:
            self._app_log("Could not remove TMDB token: %s", error, level=logging.ERROR)
            self._toast(_("Could not remove the TMDB token"))
            return
        self.tmdb_token = tmdb_client.read_token()
        self._update_settings_account_rows()
        if self.tmdb_token:
            self._toast(_("The TMDB token is provided by the environment"))
            return
        self._app_log("Locally stored TMDB read token removed.")
        self._toast(_("TMDB disconnected"))

    @staticmethod
    def _tmdb_identity(record: TitleRecord) -> tuple[str, int] | None:
        if record.tmdb_id is None:
            return None
        media_type = record.tmdb_media_type or (
            "movie" if record.media_type == "Movies" else "tv"
        )
        return (media_type, record.tmdb_id)

    def _rebuild_record_aliases(self) -> None:
        """Index TMDB faces of Simkl library records by their canonical ID."""
        aliases: dict[tuple[str, int], str] = {}
        library: dict[str, TitleRecord] = {}
        for record in self.records:
            canonical = record.id
            library[canonical] = record
            identity = self._tmdb_identity(record)
            if identity is not None:
                aliases[identity] = canonical
        self._tmdb_record_aliases = aliases
        self._library_records_by_canonical = library

    def _canonical_record_id(self, record: TitleRecord) -> str:
        """Return one identity for Library, Explore, and search title faces."""
        identity = self._tmdb_identity(record)
        alias = getattr(self, "_tmdb_record_aliases", {}).get(identity)
        if alias is not None:
            return alias
        if record.id.startswith("simkl-"):
            return record.id
        if identity is not None:
            return f"tmdb-{identity[0]}-{identity[1]}"
        return record.id

    def _record_alias_ids(self, record: TitleRecord) -> set[str]:
        """All state keys that may represent this title, including legacy IDs."""
        canonical = self._canonical_record_id(record)
        aliases = {canonical, record.id}
        identity = self._tmdb_identity(record)
        if identity is not None:
            aliases.add(f"tmdb-{identity[0]}-{identity[1]}")
        return aliases

    def _record_for_canonical_id(self, canonical: str) -> TitleRecord | None:
        record = self.records_by_id.get(canonical)
        if record is not None:
            return record
        record = getattr(self, "_library_records_by_canonical", {}).get(canonical)
        if record is not None:
            return record
        return next(
            (
                item
                for item in getattr(self, "records", ())
                if self._canonical_record_id(item) == canonical
            ),
            None,
        )

    def _is_record_completed(self, record: TitleRecord) -> bool:
        return self._canonical_record_id(record) in self.completed

    def _is_record_bookmarked(self, record: TitleRecord) -> bool:
        return self._canonical_record_id(record) in self.bookmarks

    def _record_has_watched_episode(self, record: TitleRecord) -> bool:
        if not isinstance(record, TitleRecord) or record.media_type == "Movies":
            return False
        return any(
            self._episode_is_watched(record, season_index, episode)
            for season_index, _season in enumerate(self._series_seasons(record))
            for episode in self._episodes_for_season(record, season_index)
        )

    def _effective_record_rating(self, record: TitleRecord) -> int | None:
        return self.ratings.get(self._canonical_record_id(record), record.user_rating)

    def _effective_status(self, record: TitleRecord) -> str:
        canonical = self._canonical_record_id(record)
        if self._is_record_completed(record):
            return "Watched"
        if self._local_mode_active() and self._record_has_watched_episode(record):
            return "Watching"
        override = self.status_overrides.get(canonical)
        if override is not None:
            return override
        library_record = getattr(self, "_library_records_by_canonical", {}).get(
            canonical
        )
        return library_record.status if library_record is not None else record.status

    def _status_total(self, media_type: str, status: str) -> int:
        seen: set[str] = set()
        total = 0
        for is_explore, source in (
            (False, self.records),
            (True, self.explore_records),
        ):
            for record in source:
                canonical = self._canonical_record_id(record)
                if canonical in seen:
                    continue
                if is_explore and not (
                    self._is_record_bookmarked(record)
                    or self._is_record_completed(record)
                ):
                    continue
                seen.add(canonical)
                if (
                    record.media_type == media_type
                    and self._effective_status(record) == status
                ):
                    total += 1
        return total

    def _explore_total(self, media_type: str) -> int:
        return sum(record.media_type == media_type for record in self.explore_records)

    def _library_total(self, media_type: str) -> int:
        return sum(
            self._status_total(media_type, status) for status in COLLECTION_NAMES
        )

    def _filtered_explore_records(self) -> tuple[TitleRecord, ...]:
        query = self.explore_search_entry.get_text().strip()
        source_records = self.explore_search_records if query else self.explore_records
        records = []
        for record in source_records:
            if record.media_type != self.active_media:
                continue
            if (
                not query
                and self.explore_period == "This month"
                and record.discover_period != "This month"
            ):
                continue
            if (
                not query
                and self.explore_period == "This year"
                and record.discover_period not in ("This month", "This year")
            ):
                continue
            if (
                self.explore_genre != "All genres"
                and self.explore_genre not in record.genres
            ):
                continue
            records.append(record)

        if query and self.explore_sort_key == "trending":
            return tuple(records)
        if self.explore_sort_key == "rating":
            key_function = lambda item: (item.rating, item.order)
            reverse = True
        elif self.explore_sort_key == "popular":
            key_function = lambda item: (item.popularity, item.order)
            reverse = True
        elif self.explore_sort_key == "upcoming":
            key_function = lambda item: (item.release_rank, -item.order)
            reverse = False
        else:
            key_function = lambda item: item.order
            reverse = True
        records.sort(key=key_function, reverse=reverse)
        return tuple(records)

    def _library_records(self) -> tuple[TitleRecord, ...]:
        present = {self._canonical_record_id(record) for record in self.records}
        promoted = tuple(
            record
            for record in self.explore_records
            if (self._is_record_bookmarked(record) or self._is_record_completed(record))
            and self._canonical_record_id(record) not in present
        )
        return (*self.records, *promoted)

    def _filtered_collection_records(self) -> tuple[TitleRecord, ...]:
        query = self.search_entry.get_text().strip().casefold()
        records = []
        for record in self._library_records():
            haystack = " ".join(
                (record.title, record.description, record.creator, *record.genres)
            ).casefold()
            if record.media_type != self.active_media:
                continue
            if self._effective_status(record) != self.active_collection:
                continue
            if self.genre != "All genres" and self.genre not in record.genres:
                continue
            if query and query not in haystack:
                continue
            records.append(record)

        if self.sort_key == "title":
            key_function = lambda item: item.title.casefold()
            base_reverse = False
        elif self.sort_key == "rating":
            key_function = lambda item: item.rating
            base_reverse = True
        elif self.sort_key == "year":
            key_function = lambda item: item.year
            base_reverse = True
        else:
            key_function = lambda item: item.order
            base_reverse = True

        records.sort(
            key=key_function,
            reverse=base_reverse ^ self.sort_reversed,
        )
        return tuple(records)

    def _refresh_results(self) -> None:
        self.visible_records = self._filtered_collection_records()
        visible_ids = {record.id for record in self.visible_records}
        if self.selected_id not in visible_ids:
            self.selected_id = (
                self.visible_records[0].id if self.visible_records else None
            )
        self.collection_selected_ids[self.active_collection] = self.selected_id

        self._clear_container(self.list_box)
        self._clear_container(self.grid_box)

        list_rows: dict[str, Gtk.ListBoxRow] = {}
        grid_children: dict[str, Gtk.FlowBoxChild] = {}
        if self.view_mode == "grid":
            for record in self.visible_records:
                child = self._create_grid_child(record)
                grid_children[record.id] = child
                self.grid_box.append(child)
        else:
            for record in self.visible_records:
                row = self._create_list_row(record)
                list_rows[record.id] = row
                self.list_box.append(row)

        self._list_rows = list_rows
        self._grid_children = grid_children
        self._sync_results_child()

        self._updating = True
        if self.selected_id is not None:
            if self.selected_id in list_rows:
                self.list_box.select_row(list_rows[self.selected_id])
            if self.selected_id in grid_children:
                self.grid_box.select_child(grid_children[self.selected_id])
        self._updating = False

        sample_count = len(self.visible_records)
        has_filters = (
            bool(self.search_entry.get_text().strip()) or self.genre != "All genres"
        )
        if has_filters:
            description = ngettext(
                "{count} matching title",
                "{count} matching titles",
                sample_count,
            ).format(count=sample_count)
            self.empty_page.set_icon_name("system-search-symbolic")
            self.empty_page.set_title(_("No titles found"))
            self.empty_page.set_description(
                _("Try a different search term or clear the genre filter.")
            )
        else:
            description = ngettext(
                "Showing {count} recent entry",
                "Showing {count} recent entries",
                sample_count,
            ).format(count=sample_count)
            empty_copy = {
                "Watching": _("Start watching a title to see it here."),
                "Watched": _("Titles you finish will appear here."),
                "On Hold": _("Titles you pause will appear here."),
                "Dropped": _("Titles you stop watching will appear here."),
                "Watchlist": _("Bookmark a title to save it for later."),
            }
            self.empty_page.set_icon_name(dict(COLLECTIONS)[self.active_collection])
            self.empty_page.set_title(
                _("No {collection} titles").format(
                    collection=_(self.active_collection).lower()
                )
            )
            self.empty_page.set_description(empty_copy[self.active_collection])
        self.empty_page.set_child(
            self.empty_clear_button if has_filters else self.empty_explore_button
        )

        self.section_title.set_label(_(self.active_collection))
        self.result_count.set_label(_("All"))
        self.result_description.set_label(description)
        self.search_entry.set_placeholder_text(
            _("Search {media}…").format(media=_(self.active_media).lower())
        )
        self._update_sort_icon()
        self._update_details()

    def _refresh_explore(
        self,
        *,
        reset_scroll: bool = True,
        preserve_existing_order: bool = False,
    ) -> None:
        scroll_value = self.explore_scroller.get_vadjustment().get_value()
        query = self.explore_search_entry.get_text().strip()
        filtered_records = self._filtered_explore_records()
        if preserve_existing_order and self.explore_visible_records:
            self.explore_visible_records = preserve_explore_page_prefix(
                self.explore_visible_records,
                filtered_records,
            )
        else:
            self.explore_visible_records = filtered_records
        visible_ids = {record.id for record in self.explore_visible_records}
        if self.explore_selected_id not in visible_ids:
            self.explore_selected_id = (
                self.explore_visible_records[0].id
                if self.explore_visible_records
                else None
            )
        self.selected_id = self.explore_selected_id

        if query:
            self.explore_empty_page.set_icon_name("system-search-symbolic")
            self.explore_empty_page.set_title(
                _("Searching TMDB…")
                if self._tmdb_search_loading
                else _("No TMDB matches")
            )
            self.explore_empty_page.set_description(
                _("Searching the complete TMDB catalog for “{query}”.").format(
                    query=query
                )
                if self._tmdb_search_loading
                else _(
                    "No {media} matched “{query}” on TMDB."
                ).format(media=_(self.active_media).lower(), query=query)
            )
        else:
            self.explore_empty_page.set_icon_name("system-search-symbolic")
            self.explore_empty_page.set_title(_("Nothing new here yet"))
            self.explore_empty_page.set_description(
                _("Try another search, period, or genre.")
            )
        self._populate_explore_feed()
        self._update_details()
        if reset_scroll:
            self._scroll_to_top(self.explore_scroller)
        else:
            self._scroll_to_value(self.explore_scroller, scroll_value)

    def _populate_explore_feed(self, *, force_relayout: bool = False) -> None:
        """Render Explore, appending pagination results whenever possible.

        A TMDB next-page result is a strict extension of the currently shown
        records.  In that case existing cards stay parented and only new cards
        are attached.  A filter/order/column change still performs one full
        rebuild because existing grid coordinates genuinely changed.
        """
        records = tuple(self.explore_visible_records)
        record_ids = tuple(record.id for record in records)
        visual_signatures = tuple(
            self._explore_record_visual_signature(record) for record in records
        )
        rendered_ids = getattr(self, "_explore_rendered_ids", ())
        rendered_signatures = getattr(self, "_explore_rendered_signatures", ())
        rendered_columns = getattr(self, "_explore_rendered_columns", 0)
        is_extension = (
            not force_relayout
            and bool(rendered_ids)
            and self.explore_columns == rendered_columns
            and len(record_ids) >= len(rendered_ids)
            and record_ids[: len(rendered_ids)] == rendered_ids
            and visual_signatures[: len(rendered_signatures)] == rendered_signatures
            and self.explore_grid.get_parent() is self.explore_feed_box
        )

        if is_extension:
            additions = records[len(rendered_ids) :]
            if additions:
                self._append_explore_cards(additions)
                self._explore_rendered_ids = record_ids
                self._explore_rendered_signatures = visual_signatures
            self._sync_explore_loading_indicator()
            self._sync_explore_selection_style()
            return

        self._clear_container(self.explore_feed_box)
        self._clear_container(self.explore_grid)
        self._explore_card_buttons: dict[str, Gtk.Button] = {}
        self._explore_card_layouts: dict[str, tuple[str, int]] = {}
        self._explore_rendered_ids: tuple[str, ...] = ()
        self._explore_rendered_signatures: tuple[tuple[Any, ...], ...] = ()
        self._explore_rendered_columns = self.explore_columns
        self._explore_grid_row = 0
        self._explore_grid_column = 0

        if not records:
            if self._explore_is_loading():
                self.explore_feed_box.append(self.explore_loading_view)
            else:
                self.explore_feed_box.append(self.explore_empty_page)
            self._sync_explore_loading_indicator()
            return

        self._append_explore_cards(records)
        self._explore_rendered_ids = record_ids
        self._explore_rendered_signatures = visual_signatures
        self.explore_feed_box.append(self.explore_grid)
        if any(record.tmdb_id is not None for record in records):
            attribution = Gtk.Label(label=_("Data & images provided by TMDB"))
            attribution.set_halign(Gtk.Align.START)
            attribution.set_wrap(True)
            attribution.set_margin_top(2)
            attribution.add_css_class("caption")
            attribution.add_css_class("dim-label")
            self.explore_feed_box.append(attribution)
        self.explore_feed_box.append(self.explore_loading_box)
        self._sync_explore_loading_indicator()
        self._sync_explore_selection_style()

    def _explore_record_visual_signature(
        self,
        record: TitleRecord,
    ) -> tuple[Any, ...]:
        """Return only the fields whose changes require recreating a card."""
        return (
            record.id,
            record.title,
            record.year,
            record.rating,
            record.genres,
            self._is_record_bookmarked(record),
        )

    def _append_explore_cards(
        self,
        records: tuple[TitleRecord, ...],
    ) -> None:
        """Attach records after the existing stable grid prefix."""
        columns = max(1, self.explore_columns)
        row = self._explore_grid_row
        column = self._explore_grid_column
        record_index = 0

        # Pagination can end on a partial row.  Fill that row with one-span
        # cards before starting the next deterministic varied row.
        while column and column < columns and record_index < len(records):
            record = records[record_index]
            record_index += 1
            card = self._create_explore_card(record, "poster", 1)
            self.explore_grid.attach(card, column, row, 1, 1)
            self._explore_card_buttons[record.id] = card
            self._explore_card_layouts[record.id] = ("poster", 1)
            column += 1
            if column == columns:
                row += 1
                column = 0

        remaining = records[record_index:]
        layout_seed = self._explore_layout_seed ^ (columns << 24) ^ (row << 8)
        layout = build_explore_layout_plan(len(remaining), columns, layout_seed)
        remaining_index = 0
        for pattern in layout:
            for kind, span in pattern:
                record = remaining[remaining_index]
                remaining_index += 1
                card = self._create_explore_card(record, kind, span)
                self.explore_grid.attach(card, column, row, span, 1)
                self._explore_card_buttons[record.id] = card
                self._explore_card_layouts[record.id] = (kind, span)
                column += span
            if column >= columns:
                row += 1
                column = 0

        self._explore_grid_row = row
        self._explore_grid_column = column

    def _explore_is_loading(self) -> bool:
        return (
            self._tmdb_search_loading
            if self.explore_search_entry.get_text().strip()
            else self.active_media in self._tmdb_explore_pages_loading
        )

    def _sync_explore_loading_indicator(self) -> None:
        if not hasattr(self, "explore_loading_box"):
            return
        loading = self._explore_is_loading()
        self.explore_loading_box.set_visible(loading)
        self.explore_loading_spinner.set_spinning(loading)
        if hasattr(self, "explore_loading_view"):
            self.explore_loading_view.set_visible(loading)

    def _on_explore_scroll_changed(self, adjustment: Gtk.Adjustment) -> None:
        if self.active_destination != "explore":
            return
        if (
            self.explore_search_entry.get_text().strip()
            and not self.explore_visible_records
        ):
            return
        remaining = (
            adjustment.get_upper() - adjustment.get_page_size() - adjustment.get_value()
        )
        if remaining <= max(360.0, adjustment.get_page_size() * 0.65):
            self._load_next_tmdb_explore_page()

    def _create_explore_card(
        self,
        record: TitleRecord,
        kind: str,
        span: int,
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_vexpand(False)
        # The grid owns the horizontal span.  A poster, title, or badge must
        # never turn a card's natural width into a window minimum width.
        button.set_size_request(0, -1)
        button.set_tooltip_text(_("Open {title}").format(title=record.title))
        button.set_overflow(Gtk.Overflow.HIDDEN)
        button.add_css_class("flat")
        button.add_css_class("explore-card")
        button.add_css_class(f"explore-card-{kind}")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"{record.title}, {record.year}, rated {record.rating:.1f}"],
        )

        overlay = Gtk.Overlay()
        card_height = self._explore_card_height(kind, span)
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        overlay.set_size_request(0, card_height)
        column_width, _columns = self._explore_layout_metrics()
        art_width = round(column_width * span + 10 * (span - 1))
        art_height = card_height
        preferred_artwork = (
            record.backdrop_file
            if kind in ("hero", "landscape")
            else record.poster_file
        )
        artwork_record = replace(
            record,
            artwork_file=preferred_artwork or record.artwork_file,
        )
        artwork = PosterWidget(
            artwork_record,
            art_width,
            art_height,
            variant_offset=1 if kind == "landscape" else 0,
            show_text=False,
            flexible_width=True,
        )
        artwork.set_hexpand(True)
        artwork.set_vexpand(True)
        artwork.set_size_request(-1, -1)
        overlay.set_child(artwork)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_halign(Gtk.Align.FILL)
        copy.set_valign(Gtk.Align.END)
        copy.set_hexpand(True)
        copy.set_size_request(0, -1)
        copy.add_css_class("explore-card-copy")

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        title.set_size_request(0, -1)
        title.add_css_class("explore-card-title")
        if kind == "hero":
            title.add_css_class("title-3")
        else:
            title.add_css_class("heading")
        copy.append(title)

        if kind != "poster":
            subtitle = Gtk.Label(
                label=f"{record.year}  ·  {' · '.join(record.genres[:2])}",
                xalign=0,
            )
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle.set_hexpand(True)
            subtitle.set_size_request(0, -1)
            subtitle.add_css_class("caption")
            subtitle.add_css_class("explore-card-subtitle")
            copy.append(subtitle)
        overlay.add_overlay(copy)
        # Captions are painted inside a card whose dimensions are owned by the
        # grid.  Excluding overlays from the card's preferred-size calculation
        # prevents a two-line caption from becoming a window minimum.
        overlay.set_measure_overlay(copy, False)

        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.set_halign(Gtk.Align.END)
        rating.set_valign(Gtk.Align.START)
        rating.set_margin_top(8)
        rating.set_margin_end(8)
        rating.add_css_class("row-rating")
        overlay.add_overlay(rating)
        overlay.set_measure_overlay(rating, False)

        if self._is_record_bookmarked(record):
            saved = Gtk.Image.new_from_icon_name("bookmark-new-symbolic")
            saved.set_halign(Gtk.Align.START)
            saved.set_valign(Gtk.Align.START)
            saved.set_margin_top(8)
            saved.set_margin_start(8)
            saved.add_css_class("explore-saved-badge")
            overlay.add_overlay(saved)
            overlay.set_measure_overlay(saved, False)

        button.set_child(overlay)
        button.connect(
            "clicked",
            lambda _button, record_id=record.id: self._on_explore_card_clicked(
                record_id
            ),
        )
        return button

    def _sync_explore_selection_style(self) -> None:
        for record_id, button in getattr(self, "_explore_card_buttons", {}).items():
            selected = record_id == self.explore_selected_id
            button.update_state(
                [Gtk.AccessibleState.SELECTED],
                [int(selected)],
            )
            if selected:
                button.add_css_class("selected")
            else:
                button.remove_css_class("selected")

    @staticmethod
    def _clear_container(container: Gtk.Widget) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child

    def _sync_results_child(self) -> None:
        if not self.visible_records:
            child: Gtk.Widget = self.empty_page
        elif self.view_mode == "grid":
            child = self.grid_box
        else:
            child = self.list_box

        if self.results_scroller.get_child() is not child:
            self.results_scroller.set_child(child)

    def _create_list_row(self, record):
        return build_library_row(
            record, self._create_poster_overlay(record, 76, 114),
            self._create_record_copy(record, compact=False),
            self._record_context_popover(record),
        )

    @persisted_change
    def _record_context_popover(self, record: TitleRecord) -> Gtk.PopoverMenu:
        menu = Gio.Menu()
        state_section = Gio.Menu()
        watched = self._is_record_completed(record)
        state_section.append(
            _("Mark as unwatched") if watched else _("Mark as watched"),
            "record.watch",
        )
        bookmarked = self._is_record_bookmarked(record)
        state_section.append(
            _("Remove from Watchlist")
            if bookmarked
            else _("Add to Watchlist"),
            "record.watchlist",
        )
        current_rating = self._effective_record_rating(record)
        rating_section = Gio.Menu()
        rating_section.append(
            _("Rate…  ({rating}/10)").format(rating=current_rating)
            if current_rating is not None
            else _("Rate…"),
            "record.rate",
        )
        menu.append_section(None, state_section)
        menu.append_section(None, rating_section)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        actions = Gio.SimpleActionGroup()
        watch_action = Gio.SimpleAction.new("watch", None)
        watch_action.connect(
            "activate",
            lambda *_args: self._activate_context_watched(record.id),
        )
        actions.add_action(watch_action)
        watchlist_action = Gio.SimpleAction.new("watchlist", None)
        watchlist_action.connect(
            "activate",
            lambda *_args: self._activate_context_watchlist(
                record.id,
                not bookmarked,
            ),
        )
        actions.add_action(watchlist_action)
        rating_action = Gio.SimpleAction.new("rate", None)
        rating_action.connect(
            "activate",
            lambda *_args: self._activate_context_rating(record.id),
        )
        actions.add_action(rating_action)
        popover.insert_action_group("record", actions)
        return popover

    def _context_record(self, record_id: str) -> TitleRecord | None:
        return self.records_by_id.get(record_id)

    @persisted_change
    def _activate_context_watched(self, record_id: str) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._activate_record_watched(record)

    @persisted_change
    def _activate_context_watchlist(self, record_id: str, adding: bool) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._set_record_bookmarked(record, adding)

    @persisted_change
    def _activate_context_rating(self, record_id: str) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._show_record_rating_dialog(record)

    def _show_record_rating_dialog(self, record: TitleRecord) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Rate {title}").format(title=record.title),
            body=_("Choose a score from 1 to 10, then save your rating."),
        )
        rating_grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
        rating_grid.set_column_spacing(6)
        rating_grid.set_row_spacing(6)
        selected = {"score": self._effective_record_rating(record)}
        leader: Gtk.ToggleButton | None = None
        for score in range(1, 11):
            button = Gtk.ToggleButton(label=str(score))
            button.set_tooltip_text(_("{score} out of 10").format(score=score))
            if leader is None:
                leader = button
            else:
                button.set_group(leader)
            button.set_active(score == selected["score"])

            def select_score(item: Gtk.ToggleButton, value: int = score) -> None:
                if item.get_active():
                    selected["score"] = value
                    dialog.set_response_enabled("save", True)

            button.connect("toggled", select_score)
            rating_grid.attach(button, (score - 1) % 5, (score - 1) // 5, 1, 1)
        dialog.set_extra_child(rating_grid)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save rating"))
        dialog.set_response_enabled("save", selected["score"] is not None)
        dialog.set_close_response("cancel")
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def save_rating(_dialog: Adw.AlertDialog, response: str) -> None:
            score = selected["score"]
            current = self._context_record(record.id)
            if response == "save" and score is not None and current is not None:
                self._set_record_rating(current, score)

        dialog.connect("response", save_rating)
        dialog.present(self.window)

    def _create_grid_child(self, record: TitleRecord) -> Gtk.FlowBoxChild:
        child = Gtk.FlowBoxChild()
        child.record = record
        child.set_size_request(GRID_CARD_WIDTH + 6, GRID_CARD_HEIGHT + 6)
        child.set_halign(Gtk.Align.CENTER)
        child.set_valign(Gtk.Align.START)

        card = Gtk.Overlay()
        card.set_size_request(GRID_CARD_WIDTH, GRID_CARD_HEIGHT)
        card.set_hexpand(False)
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.START)
        card.set_overflow(Gtk.Overflow.HIDDEN)
        card.add_css_class("poster-grid-card")
        card.set_tooltip_text(record.title)
        poster_record = replace(record, artwork_file=record.poster_file)
        card.set_child(
            PosterWidget(
                poster_record,
                GRID_CARD_WIDTH,
                GRID_CARD_HEIGHT,
                show_text=False,
            )
        )

        caption = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        caption.set_halign(Gtk.Align.FILL)
        caption.set_valign(Gtk.Align.END)
        caption.add_css_class("poster-grid-copy")
        title = Gtk.Label(label=record.title, xalign=0)
        title.set_halign(Gtk.Align.FILL)
        title.set_justify(Gtk.Justification.LEFT)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(20)
        title.set_tooltip_text(record.title)
        title.add_css_class("poster-grid-title")
        caption.append(title)
        card.add_overlay(caption)

        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.set_halign(Gtk.Align.END)
        rating.set_valign(Gtk.Align.START)
        rating.set_margin_top(7)
        rating.set_margin_end(7)
        rating.add_css_class("grid-rating-badge")
        rating.add_css_class("numeric")
        card.add_overlay(rating)
        child.set_child(card)
        return child

    def _create_poster_overlay(
        self,
        record: TitleRecord,
        width: int,
        height: int,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        overlay.set_size_request(width, height)
        overlay.set_hexpand(False)
        overlay.set_halign(Gtk.Align.CENTER)
        overlay.set_valign(Gtk.Align.START)
        poster_record = replace(
            record,
            # A landscape backdrop must never be used in a portrait poster slot.
            artwork_file=record.poster_file,
        )
        overlay.set_child(PosterWidget(poster_record, width, height))

        score = self._effective_record_rating(record)
        if score is not None:
            rating = Gtk.Label(label=str(score))
            rating.set_halign(Gtk.Align.START)
            rating.set_valign(Gtk.Align.START)
            rating.set_margin_top(4)
            rating.set_margin_start(4)
            rating.add_css_class("row-rating")
            rating.add_css_class("numeric")
            overlay.add_overlay(rating)

        if self._is_record_completed(record):
            watched = Gtk.Label(label="✓")
            watched.set_halign(Gtk.Align.END)
            watched.set_valign(Gtk.Align.START)
            watched.set_margin_top(4)
            watched.set_margin_end(4)
            watched.add_css_class("watched-badge")
            overlay.add_overlay(watched)

        return overlay

    def _create_record_copy(
        self,
        record: TitleRecord,
        *,
        compact: bool,
    ) -> Gtk.Box:
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        copy.set_hexpand(True)
        copy.set_valign(Gtk.Align.CENTER)

        top = Gtk.CenterBox()
        date = Gtk.Label(label=record.date, xalign=0)
        date.add_css_class("dim-label")
        date.add_css_class("caption")
        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.add_css_class("numeric")
        rating.add_css_class("caption")
        top.set_start_widget(date)
        top.set_end_widget(rating)

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("title-3")

        description = Gtk.Label(label=record.description, xalign=0)
        description.set_wrap(True)
        description.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        description.set_lines(2)
        description.set_ellipsize(Pango.EllipsizeMode.END)
        description.add_css_class("dim-label")
        description.add_css_class("caption" if compact else "body")

        metadata_values = (str(record.year), record.runtime, *record.genres[:2])
        metadata = Gtk.Label(label="  ·  ".join(metadata_values), xalign=0)
        metadata.set_ellipsize(Pango.EllipsizeMode.END)
        metadata.add_css_class("dim-label")
        metadata.add_css_class("caption")

        copy.append(top)
        copy.append(title)
        copy.append(description)
        copy.append(metadata)
        return copy

    def _build_detail_hero(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_poster_host)
        if record.id in self._tmdb_details_loading:
            placeholder = self._loading_media_placeholder(
                352,
                198,
                "Loading title artwork",
            )
            placeholder.set_hexpand(True)
            self.detail_poster_host.append(placeholder)
            return
        overlay = Gtk.Overlay()
        overlay.set_hexpand(True)
        overlay.set_halign(Gtk.Align.FILL)
        trailer_info = record.videos[0] if record.videos else None
        hero_record = replace(
            record,
            artwork_file=(
                record.backdrop_file
                or (trailer_info.thumbnail_file if trailer_info else None)
                or record.poster_file
                or record.artwork_file
            ),
        )
        artwork_button = Gtk.Button()
        artwork_button.set_hexpand(True)
        artwork_button.set_halign(Gtk.Align.FILL)
        artwork_button.set_child(
            PosterWidget(hero_record, 352, 198, show_text=False, flexible_width=True)
        )
        artwork_button.set_tooltip_text(
            _("Open Images for {title}").format(title=record.title)
        )
        artwork_button.add_css_class("flat")
        artwork_button.add_css_class("media-thumbnail")
        artwork_button.connect(
            "clicked",
            lambda *_args: self._open_record_media(record, "backdrops"),
        )
        overlay.set_child(artwork_button)

        trailer_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        trailer_content.append(
            Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        )
        trailer_content.append(Gtk.Label(label=_("Watch trailer")))
        trailer = Gtk.Button()
        trailer.set_child(trailer_content)
        trailer.set_halign(Gtk.Align.CENTER)
        trailer.set_valign(Gtk.Align.CENTER)
        trailer.add_css_class("pill")
        trailer.add_css_class("detail-hero-button")
        trailer.set_tooltip_text(
            _("Play the Trailer for {title}").format(title=record.title)
        )
        trailer.set_visible(trailer_info is not None)
        if trailer_info is not None and trailer_info.url is not None:
            trailer.connect(
                "clicked",
                lambda _button, video=trailer_info: (
                    self._open_external_uri_with_warning(
                        video.url or "",
                        heading=_("Open the trailer?"),
                        body=(
                            _("Gisheh will open “{title}” on YouTube in your default web browser.").format(title=video.title)
                        ),
                    )
                ),
            )
        overlay.add_overlay(trailer)
        overlay.set_measure_overlay(trailer, False)

        self.detail_poster_host.append(overlay)

    @staticmethod
    def _rating_sources(record: TitleRecord) -> tuple[tuple[str, str], ...]:
        valid_sources: dict[str, str] = {}
        for source, raw_value in record.external_ratings:
            if source not in {"TMDB", "Your rating"} or source in valid_sources:
                continue
            value = raw_value.strip()
            try:
                numeric_value = float(value)
            except ValueError:
                continue
            if (
                not value
                or not math.isfinite(numeric_value)
                or not 0 <= numeric_value <= 10
            ):
                continue
            valid_sources[source] = value
        return tuple(
            (source, valid_sources[source])
            for source in ("TMDB", "Your rating")
            if source in valid_sources
        )

    @staticmethod
    def _tmdb_rating_value(record: TitleRecord) -> str | None:
        for source, value in GishehWindow._rating_sources(record):
            if source == "TMDB":
                return value
        return None

    def _populate_detail_ratings(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_ratings_host)
        rating_sources = self._rating_sources(record)
        if not rating_sources:
            message = Gtk.Label(
                label=(
                    _("Loading ratings…")
                    if record.id in self._tmdb_details_loading
                    else _("No rating information is available.")
                )
            )
            message.set_wrap(True)
            message.set_xalign(0)
            message.add_css_class("caption")
            message.add_css_class("dim-label")
            self.detail_ratings_host.attach(message, 0, 0, 2, 1)
            return
        for index, (source, value) in enumerate(rating_sources):
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            chip.set_hexpand(True)
            chip.add_css_class("detail-metric")
            score = Gtk.Label(label=value)
            score.add_css_class("numeric")
            score.add_css_class("heading")
            source_label = Gtk.Label(
                label=(
                    _("Your rating") if source == "Your rating" else source
                )
            )
            source_label.set_ellipsize(Pango.EllipsizeMode.END)
            source_label.add_css_class("caption")
            source_label.add_css_class("dim-label")
            chip.append(score)
            chip.append(source_label)
            self.detail_ratings_host.attach(chip, index % 2, index // 2, 1, 1)

    @staticmethod
    def _cast_members(record: TitleRecord) -> tuple[CastMember, ...]:
        return record.cast[:12]

    def _populate_cast(self, record: TitleRecord) -> None:
        self._populate_cast_container(self.cast_box, record)

    def _populate_cast_container(
        self,
        container: Gtk.Box,
        record: TitleRecord,
        *,
        empty_message: str | None = None,
    ) -> None:
        if empty_message is None:
            empty_message = _("Cast information is unavailable.")
        self._clear_container(container)
        if record.id in self._tmdb_details_loading:
            for _index in range(4):
                container.append(self._loading_cast_placeholder())
            return

        members = self._cast_members(record)
        if not members:
            empty = Gtk.Label(label=empty_message)
            empty.add_css_class("dim-label")
            empty.add_css_class("caption")
            container.append(empty)
            return
        pending_images = self._tmdb_cast_images_loading.get(record.id, set())
        for index, member in enumerate(members):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.set_valign(Gtk.Align.START)
            card.set_size_request(82, -1)
            card.add_css_class("cast-card")

            avatar = Adw.Avatar(size=58, text=member.name, show_initials=True)
            avatar.set_halign(Gtk.Align.CENTER)
            avatar.set_tooltip_text(
                _("{name}, {role}").format(name=member.name, role=member.role)
            )
            if member.profile_file and Path(member.profile_file).is_file():
                try:
                    avatar.set_custom_image(
                        Gdk.Texture.new_from_filename(member.profile_file)
                    )
                except GLib.Error:
                    pass

            avatar_host = Gtk.Overlay()
            avatar_host.set_child(avatar)
            if index in pending_images:
                pending = Gtk.Box()
                pending.set_size_request(58, 58)
                pending.set_halign(Gtk.Align.CENTER)
                pending.set_valign(Gtk.Align.CENTER)
                pending.set_tooltip_text(
                    _("Loading photo for {name}").format(name=member.name)
                )
                pending.add_css_class("content-skeleton-avatar")
                avatar_host.add_overlay(pending)

            name = Gtk.Label(label=member.name)
            self._configure_bounded_card_label(name, 9)
            name.set_justify(Gtk.Justification.CENTER)
            name.set_xalign(0.5)
            name.set_tooltip_text(member.name)
            name.add_css_class("caption")
            name.add_css_class("cast-name")

            role = Gtk.Label(label=member.role)
            self._configure_bounded_card_label(role, 9, lines=1)
            role.set_xalign(0.5)
            role.set_tooltip_text(member.role)
            role.add_css_class("caption")
            role.add_css_class("dim-label")

            card.append(avatar_host)
            card.append(name)
            card.append(role)
            container.append(card)

    @staticmethod
    def _loading_media_placeholder(width: int, height: int, tooltip: str) -> Gtk.Box:
        placeholder = Gtk.Box()
        placeholder.set_size_request(width, height)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.add_css_class("content-skeleton-surface")
        placeholder.set_tooltip_text(tooltip)
        return placeholder

    @staticmethod
    def _loading_cast_placeholder() -> Gtk.Box:
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        placeholder.set_size_request(82, 104)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.START)
        placeholder.set_tooltip_text(_("Loading cast member"))
        avatar = Gtk.Box()
        avatar.set_size_request(58, 58)
        avatar.set_halign(Gtk.Align.CENTER)
        avatar.add_css_class("content-skeleton-avatar")
        name = Gtk.Box()
        name.set_size_request(66, 8)
        name.set_halign(Gtk.Align.CENTER)
        name.add_css_class("content-skeleton-cast-line")
        role = Gtk.Box()
        role.set_size_request(46, 7)
        role.set_halign(Gtk.Align.CENTER)
        role.add_css_class("content-skeleton-cast-line")
        role.add_css_class("short")
        placeholder.append(avatar)
        placeholder.append(name)
        placeholder.append(role)
        return placeholder

    def _series_seasons(self, record: TitleRecord) -> tuple[SeasonInfo, ...]:
        if record.seasons:
            return record.seasons

        numbers = [int(value) for value in record.runtime.split() if value.isdigit()]
        is_completed = self._is_record_completed(record)
        if "episodes" in record.runtime or _("episodes") in record.runtime:
            episode_count = numbers[0] if numbers else 12
            return (
                SeasonInfo(
                    "s1",
                    1,
                    _("Season 1"),
                    episode_count if is_completed else 0,
                    episode_count,
                ),
            )

        season_count = max(1, numbers[0] if numbers else 1)
        return tuple(
            SeasonInfo(
                f"s{index}",
                index,
                _("Season {number}").format(number=index),
                10 if is_completed else 0,
                10,
            )
            for index in range(1, season_count + 1)
        )

    def _episodes_for_season(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> tuple[EpisodeInfo, ...]:
        seasons = self._series_seasons(record)
        if not seasons:
            return ()
        season_index = max(0, min(season_index, len(seasons) - 1))
        season = seasons[season_index]
        provided = {episode.number: episode for episode in season.episode_items}
        episodes: list[EpisodeInfo] = []
        for number in range(1, season.episodes + 1):
            episode = provided.get(number)
            if episode is None:
                episode = EpisodeInfo(
                    id=f"e{number}",
                    number=number,
                    title=_("Episode {number}").format(number=number),
                    date=str(record.year + season_index),
                    description=record.description,
                    watched=None,
                    image_variant=number + season_index * 2,
                )
            episodes.append(episode)
        return tuple(episodes)

    @staticmethod
    def _season_short_label(season: SeasonInfo) -> str:
        return f"S{season.number}"

    def _episode_key(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> str:
        season = self._series_seasons(record)[season_index]
        return f"{self._canonical_record_id(record)}/{season.id}/{episode.id}"

    def _episode_code(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> str:
        season = self._series_seasons(record)[season_index]
        return f"{self._season_short_label(season)}E{episode.number}"

    def _episode_is_watched(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> bool:
        key = self._episode_key(record, season_index, episode)
        if key in self.episode_status_overrides:
            return self.episode_status_overrides[key]
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        if record.episode_history_loaded:
            return any(
                item.season == season.number and item.episode == episode.number
                for item in record.episode_history
            )
        default = episode.watched
        return episode.number <= season.watched if default is None else default

    def _season_watched_count(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> int:
        return sum(
            self._episode_is_watched(record, season_index, episode)
            for episode in self._episodes_for_season(record, season_index)
        )

    def _series_completion_progress(
        self,
        record: TitleRecord,
    ) -> tuple[int, int]:
        """Return effective watched and total episode counts for progress UI."""
        seasons = self._series_seasons(record)
        progress_indexes = main_progress_season_indexes(seasons)
        total = sum(max(0, seasons[index].episodes) for index in progress_indexes)
        if total == 0:
            return 0, 0
        if self._is_record_completed(record):
            return total, total
        watched = sum(
            self._season_watched_count(record, index) for index in progress_indexes
        )
        return min(max(0, watched), total), total

    def _update_activity_progress(self, record: TitleRecord) -> None:
        """Refresh the title-detail progress card from effective episode state."""
        show_completion = should_show_completion_progress(record.media_type)
        self.activity_progress_card.set_visible(show_completion)
        if not show_completion:
            return

        watched_episodes, total_episodes = self._series_completion_progress(record)
        fraction = watched_episodes / total_episodes if total_episodes > 0 else 0.0
        percentage = round(fraction * 100)
        if total_episodes == 0:
            activity_status = _("Episode data unavailable")
            tooltip = activity_status
        elif watched_episodes == 0:
            activity_status = _("{watched} of {total} episodes watched").format(
                watched=0, total=total_episodes
            )
            tooltip = activity_status
        elif watched_episodes >= total_episodes:
            activity_status = _("All {total} episodes watched").format(
                total=total_episodes
            )
            tooltip = _("{watched} of {total} episodes watched").format(
                watched=total_episodes, total=total_episodes
            )
        else:
            activity_status = _("{watched} of {total} episodes watched").format(
                watched=watched_episodes, total=total_episodes
            )
            tooltip = activity_status
        self.activity_status.set_label(activity_status)
        self.activity_percentage.set_label(f"{percentage}%")
        self.activity_progress.set_fraction(fraction)
        self.activity_progress.set_tooltip_text(tooltip)

    def _episode_progress_items(
        self,
        record: TitleRecord,
    ) -> tuple[
        tuple[int, EpisodeInfo] | None,
        tuple[int, EpisodeInfo] | None,
    ]:
        seasons = self._series_seasons(record)
        next_item: tuple[int, EpisodeInfo] | None = None
        last_item: tuple[int, EpisodeInfo] | None = None
        for season_index in main_progress_season_indexes(seasons):
            for episode in self._episodes_for_season(record, season_index):
                if self._episode_is_watched(record, season_index, episode):
                    last_item = (season_index, episode)
                elif next_item is None:
                    next_item = (season_index, episode)
        return next_item, last_item

    def _episode_artwork(
        self,
        record: TitleRecord,
        episode: EpisodeInfo,
        width: int,
        height: int,
        *,
        flexible_width: bool = False,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        # ActionRow prefixes default to FILL and would stretch a 16:9 still to
        # the row's full height.  Keep both dimensions explicit and centre the
        # thumbnail so the image is never distorted by a taller text block.
        overlay.set_size_request(width, height)
        overlay.set_halign(Gtk.Align.START)
        overlay.set_valign(Gtk.Align.CENTER)
        overlay.add_css_class("episode-artwork")
        artwork_record = replace(
            record,
            artwork_file=episode.artwork_file,
            poster_file=None,
            backdrop_file=episode.artwork_file,
        )
        overlay.set_child(
            PosterWidget(
                artwork_record,
                width,
                height,
                variant_offset=episode.image_variant,
                show_text=False,
                flexible_width=flexible_width,
            )
        )
        overlay.set_tooltip_text(
            _("Episode {number}: {title}").format(
                number=episode.number, title=episode.title
            )
        )
        return overlay

    @staticmethod
    def _episode_watch_button(watched: bool) -> Gtk.Button:
        """Return a real, compact Adwaita control for episode watch state."""
        button = Gtk.Button.new_from_icon_name(
            "object-select-symbolic" if watched else "media-playback-start-symbolic"
        )
        icon = button.get_child()
        if isinstance(icon, Gtk.Image):
            icon.set_pixel_size(14)
            if watched:
                icon.add_css_class("success")
        button.add_css_class("flat")
        button.add_css_class("circular")
        button.add_css_class("episode-watch-button")
        label = (
            _("Mark Episode Unwatched") if watched else _("Mark Episode Watched")
        )
        button.set_tooltip_text(label)
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        return button

    @staticmethod
    def _episode_card(label: str, value: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.set_hexpand(True)
        card.add_css_class("episode-card")
        overline = Gtk.Label(label=label, xalign=0)
        overline.set_wrap(True)
        overline.add_css_class("caption")
        overline.add_css_class("dim-label")
        title = Gtk.Label(label=value, xalign=0)
        title.set_wrap(True)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        detail = Gtk.Label(label=subtitle, xalign=0)
        detail.set_wrap(True)
        detail.set_lines(2)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        detail.add_css_class("caption")
        detail.add_css_class("dim-label")
        card.append(overline)
        card.append(title)
        card.append(detail)
        return card

    def _populate_series(self, record: TitleRecord) -> None:
        episodic = record.media_type != "Movies"
        self.series_section.set_visible(episodic)
        self._update_activity_progress(record)
        if not episodic:
            return

        seasons = self._series_seasons(record)
        self._clear_container(self.episode_cards_box)
        self._clear_container(self.seasons_list)

        next_item, last_item = self._episode_progress_items(record)

        if next_item is None:
            next_episode = _("Up to date")
            next_subtitle = record.availability
        else:
            next_season_index, next_info = next_item
            next_episode = self._episode_code(record, next_season_index, next_info)
            next_subtitle = next_info.title

        if last_item is None:
            last_episode = _("Not started")
            last_subtitle = record.network
        else:
            last_season_index, last_info = last_item
            last_episode = self._episode_code(record, last_season_index, last_info)
            last_subtitle = last_info.title
        self.episode_cards_box.append(
            self._episode_card(_("Next episode"), next_episode, next_subtitle)
        )
        self.episode_cards_box.append(
            self._episode_card(_("Last episode"), last_episode, last_subtitle)
        )

        for season_index, season in enumerate(seasons):
            watched = self._season_watched_count(record, season_index)
            season_complete = is_episode_group_complete(watched, season.episodes)
            row = Adw.ActionRow(
                title=season.title,
                subtitle=_("{watched}/{total} episodes").format(
                    watched=watched, total=season.episodes
                ),
            )
            row.season_index = season_index
            row.set_activatable(True)
            row.set_tooltip_text(
                _("Open {season} of {title}").format(
                    season=season.title, title=record.title
                )
            )
            progress = Gtk.Label(label=f"{watched}/{season.episodes}")
            progress.add_css_class("caption")
            progress.add_css_class("dim-label")
            row.add_suffix(progress)
            icon = Gtk.Image.new_from_icon_name(
                "object-select-symbolic"
                if season_complete
                else "media-playback-start-symbolic"
            )
            icon.set_tooltip_text(
                "Season watched" if season_complete else "Season in progress"
            )
            icon.update_property(
                [Gtk.AccessibleProperty.LABEL],
                ["Season watched" if season_complete else "Season in progress"],
            )
            if season_complete:
                icon.add_css_class("success")
            row.add_suffix(icon)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.seasons_list.append(row)

    def _populate_season_page(
        self,
        record: TitleRecord,
        season_index: int,
        *,
        reset_scroll: bool = True,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons:
            return
        season_index = max(0, min(season_index, len(seasons) - 1))
        season = seasons[season_index]
        episodes = self._episodes_for_season(record, season_index)
        watched = self._season_watched_count(record, season_index)
        details_ready = self._season_episode_details_ready(record, season_index)

        self.detail_record_id = record.id
        self.current_season_index = season_index
        self.season_header_title.set_title(season.title)
        self.season_header_title.set_subtitle(record.title)
        self.season_summary_label.set_label(
            _("{watched} of {total} episodes watched · {network}").format(
                watched=watched, total=len(episodes), network=record.network
            )
        )
        self._set_watched_action_state(
            self.season_watched_button,
            is_episode_group_complete(watched, len(episodes)),
            "season",
        )

        self._clear_container(self.season_episodes_list)
        for episode_index, episode in enumerate(episodes):
            row = Adw.ActionRow(
                title=f"{episode.number}. {episode.title}",
                subtitle=f"{episode.date}\n{episode.description}",
            )
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_activatable(details_ready)
            row.season_index = season_index
            row.episode_index = episode_index
            row.episode_number = episode.number
            row.episode_artwork = self._episode_artwork(record, episode, 112, 63)
            row.add_prefix(row.episode_artwork)

            watched = self._episode_is_watched(record, season_index, episode)
            watched_button = self._episode_watch_button(watched)
            watched_button.connect(
                "clicked",
                self._on_episode_row_watched_clicked,
                record.id,
                season_index,
                episode.number,
            )
            row.watch_button = watched_button
            row.add_suffix(watched_button)
            if details_ready:
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.set_tooltip_text(
                    _("Open Episode {number}: {title}").format(
                        number=episode.number, title=episode.title
                    )
                )
            else:
                row.set_tooltip_text(
                    _("Wait for all episode details to finish loading")
                )
            self.season_episodes_list.append(row)

        if reset_scroll:
            self._scroll_to_top(self.season_details_scroller)

    def _populate_episode_page(
        self,
        record: TitleRecord,
        season_index: int,
        episode_index: int,
        *,
        reset_scroll: bool = True,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons:
            return
        season_index = max(0, min(season_index, len(seasons) - 1))
        episodes = self._episodes_for_season(record, season_index)
        if not episodes:
            return
        episode_index = max(0, min(episode_index, len(episodes) - 1))
        season = seasons[season_index]
        episode = episodes[episode_index]

        self.detail_record_id = record.id
        self.current_season_index = season_index
        self.current_episode_index = episode_index
        self.episode_header_title.set_title(
            _("Episode {number}").format(number=episode.number)
        )
        self.episode_header_title.set_subtitle(season.title)

        self._clear_container(self.episode_hero_host)
        self.episode_hero_host.append(
            self._episode_artwork(record, episode, 352, 198, flexible_width=True)
        )
        self.episode_title_label.set_label(episode.title)
        episode_code = f"S{season.number:02d}E{episode.number:02d}"
        self.episode_date_label.set_label(
            " · ".join(value for value in (episode_code, episode.date) if value)
        )
        self.episode_runtime_label.set_label(
            episode.runtime or _("Runtime unavailable")
        )
        self.episode_series_label.set_label(f"{record.title} · {season.title}")
        self.episode_overview_label.set_label(episode.description)
        self._populate_cast_container(
            self.episode_cast_box,
            replace(record, cast=episode.cast),
            empty_message=_(
                "Guest cast information is unavailable for this episode."
            ),
        )
        self._update_episode_watch_controls(record, season_index, episode)
        if reset_scroll:
            self._scroll_to_top(self.episode_details_scroller)

    def _update_episode_watch_controls(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> None:
        watched = self._episode_is_watched(record, season_index, episode)
        self.episode_status_label.set_visible(watched)
        self.episode_status_label.set_label(_("Watched"))
        self._set_watched_action_state(self.episode_watched_button, watched, "episode")
        watched_at = self.episode_watched_at.get(
            self._episode_key(record, season_index, episode)
        )
        if watched and watched_at:
            status = _("Watched · {date}").format(
                date=format_watched_iso(watched_at)
            )
        elif watched:
            status = _("Watched")
        else:
            status = _("Not watched yet")
        self.episode_watched_at_label.set_label(status)

    @staticmethod
    def _set_watched_action_state(
        button: Gtk.Button,
        watched: bool,
        noun: str,
    ) -> None:
        translated_noun = (
            _("season") if noun == "season" else _("episode") if noun == "episode" else noun
        )
        if watched:
            # Translators: e.g. "Mark season unwatched". "{noun}" is the
            # translated "season"/"episode" word above.
            label = _("Mark {noun} unwatched").format(noun=translated_noun)
        else:
            label = _("Mark {noun} watched").format(noun=translated_noun)
        button.action_label.set_label(label)
        button.action_icon.set_from_icon_name(
            "edit-undo-symbolic" if watched else "object-select-symbolic"
        )
        button.set_tooltip_text(label)
        if watched:
            button.remove_css_class("suggested-action")
        else:
            button.add_css_class("suggested-action")

    @staticmethod
    def _scroll_to_value(scroller: Gtk.ScrolledWindow, value: float) -> None:
        def reset_adjustment() -> bool:
            scroller.get_vadjustment().set_value(value)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(reset_adjustment)

    @staticmethod
    def _scroll_to_top(scroller: Gtk.ScrolledWindow) -> None:
        GishehWindow._scroll_to_value(scroller, 0)

    def _video_card(
        self,
        record: TitleRecord,
        video: VideoInfo,
        variant_offset: int,
    ) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        overlay = Gtk.Overlay()
        video_record = replace(
            record,
            artwork_file=(
                video.thumbnail_file
                or record.backdrop_file
                or record.poster_file
                or record.artwork_file
            ),
        )
        overlay.set_child(
            PosterWidget(video_record, 156, 88, variant_offset=variant_offset)
        )
        play = Gtk.Label(label="▶")
        play.set_halign(Gtk.Align.CENTER)
        play.set_valign(Gtk.Align.CENTER)
        play.add_css_class("rating-badge")
        overlay.add_overlay(play)
        caption = Gtk.Label(label=video.title, xalign=0)
        self._configure_bounded_card_label(caption, 17, lines=1)
        caption.set_tooltip_text(video.title)
        caption.add_css_class("caption")
        content.append(overlay)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("flat")
        button.add_css_class("detail-media-card")
        button.set_tooltip_text(
            _("Play {video} for {title}").format(
                video=video.title, title=record.title
            )
        )
        if video.url is not None:
            button.connect(
                "clicked",
                lambda _button, item=video: self._open_external_uri_with_warning(
                    item.url or "",
                    heading=_("Open the video?"),
                    body=(
                        _("Gisheh will open “{title}” on YouTube in your default web browser.").format(title=item.title)
                    ),
                ),
            )
        return button

    def _populate_videos(self, record: TitleRecord) -> None:
        self._clear_container(self.videos_box)
        if record.id in self._tmdb_details_loading:
            for _index in range(2):
                self.videos_box.append(
                    self._loading_media_placeholder(156, 112, _("Loading video"))
                )
            return
        self.videos_section.set_visible(bool(record.videos))
        for index, video in enumerate(record.videos[:8], start=1):
            self.videos_box.append(self._video_card(record, video, index))

    def _populate_images(self, record: TitleRecord) -> None:
        self._clear_container(self.images_box)
        is_poster = self.image_mode == "posters"
        width, height = (96, 144) if is_poster else (176, 99)
        if record.id in self._tmdb_details_loading:
            for _index in range(3 if is_poster else 2):
                self.images_box.append(
                    self._loading_media_placeholder(
                        width, height, _("Loading image")
                    )
                )
            return
        mode = "posters" if is_poster else "backdrops"
        media_items = self._media_items(record, mode)
        gallery = tuple(path for path, _label in media_items)
        pending_kind = "poster" if is_poster else "backdrop"
        pending_count = self._tmdb_gallery_images_loading.get(record.id, {}).get(
            pending_kind,
            0,
        )
        fallback_count = 0 if pending_count else (3 if is_poster else 2)
        artwork_files = gallery or tuple(None for _index in range(fallback_count))
        for index, artwork_file in enumerate(artwork_files):
            image_record = (
                replace(record, artwork_file=artwork_file)
                if artwork_file is not None
                else record
            )
            button = Gtk.Button()
            button.set_child(
                PosterWidget(image_record, width, height, variant_offset=index + 1)
            )
            button.add_css_class("flat")
            button.add_css_class("detail-media-card")
            button.add_css_class("media-thumbnail")
            button.set_tooltip_text(
                _("Open {kind} {index} for {title}").format(
                    kind=(
                        _("poster")
                        if self.image_mode == "posters"
                        else _("backdrop")
                    ),
                    index=index + 1,
                    title=record.title,
                )
            )
            button.connect(
                "clicked",
                (
                    lambda _button, image_index=index: (
                        self.media_viewer.open(
                            media_items,
                            image_index,
                        )
                        if media_items
                        else self._toast(
                            _("No {mode} available for {title}").format(
                                mode=(
                                    _("posters")
                                    if mode == "posters"
                                    else _("backdrops")
                                    if mode == "backdrops"
                                    else mode
                                ),
                                title=record.title,
                            )
                        )
                    )
                ),
            )
            self.images_box.append(button)
        for _index in range(pending_count):
            self.images_box.append(
                self._loading_media_placeholder(width, height, _("Loading image"))
            )

    def _related_records(self, record: TitleRecord) -> tuple[TitleRecord, ...]:
        related: list[TitleRecord] = []
        for record_id in self._tmdb_recommendations.get(record.id, ()):
            candidate = self.records_by_id.get(record_id)
            if (
                candidate is not None
                and candidate.id != record.id
                and candidate not in related
            ):
                related.append(candidate)
        return tuple(related)

    def _on_recommendation_clicked(self, record_id: str) -> None:
        record = self.records_by_id.get(record_id)
        if record is None:
            return
        self.selected_id = record.id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(record)

    def _populate_recommendations(self, record: TitleRecord) -> None:
        self._clear_container(self.recommendations_box)
        related = self._related_records(record)
        self.recommendations_section.set_visible(bool(related))
        for item in related:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            poster_record = replace(
                item,
                artwork_file=item.poster_file or item.artwork_file,
            )
            content.append(PosterWidget(poster_record, 88, 132))
            title = Gtk.Label(label=item.title, xalign=0)
            self._configure_bounded_card_label(title, 10)
            title.set_tooltip_text(item.title)
            title.add_css_class("caption")
            year = Gtk.Label(label=str(item.year), xalign=0)
            year.add_css_class("caption")
            year.add_css_class("dim-label")
            content.append(title)
            content.append(year)

            button = Gtk.Button()
            button.set_child(content)
            button.add_css_class("flat")
            button.add_css_class("recommendation-card")
            button.set_tooltip_text(_("Open {title}").format(title=item.title))
            button.connect(
                "clicked",
                lambda _button, item_id=item.id: self._on_recommendation_clicked(
                    item_id
                ),
            )
            self.recommendations_box.append(button)

    def _populate_detail_sections(self, record: TitleRecord) -> None:
        self._populate_detail_ratings(record)
        self._populate_cast(record)
        self._populate_series(record)
        self._populate_videos(record)
        self._populate_images(record)
        self._populate_recommendations(record)

    def _reset_detail_navigation(self) -> None:
        if self.detail_navigation.get_visible_page_tag() != "title":
            self.detail_navigation.pop_to_tag("title")

    def _update_details(self) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is None:
            self._reset_detail_navigation()
            self.detail_record_id = None
            self.detail_box.set_visible(False)
            return

        record_changed = self.detail_record_id != record.id
        if record_changed:
            self._reset_detail_navigation()
        self.detail_record_id = record.id
        self.detail_box.set_visible(True)
        self.detail_poster_host.set_visible(True)
        self._build_detail_hero(record)

        is_completed = self._is_record_completed(record)
        self.detail_status_label.set_label(
            localize_collection_status(self._effective_status(record))
        )
        self.detail_overline.set_label(" · ".join(record.genres))
        self.detail_title.set_label(record.title)
        tmdb_rating = self._tmdb_rating_value(record)
        self.community_rating.set_visible(tmdb_rating is not None)
        if tmdb_rating is not None:
            self.community_rating.set_label(f"★ {tmdb_rating}")
        self.watched_button.set_label(
            _("✓  Watched") if is_completed else _("＋  Mark watched")
        )
        self.runtime_label.set_label(
            f"{record.certification} · {record.language} · {record.runtime}"
        )
        self.genres_label.set_label(f"{record.year} · {record.availability}")
        self.overview_label.set_label(record.description)
        self.creator_row.set_title(
            _("Director") if record.media_type == "Movies" else _("Creator")
        )
        self.creator_row.set_subtitle(record.creator)
        self.release_row.set_subtitle(f"{record.year} · {record.availability}")
        self.country_row.set_subtitle(record.country)
        self.activity_row.set_subtitle(record.date)

        self._updating_details = True
        self.bookmark_button.set_visible(True)
        self.bookmark_button.set_active(self._is_record_bookmarked(record))
        score = self._effective_record_rating(record)
        for value, button in self.rating_buttons.items():
            button.set_active(value == score)
        self.rating_value.set_label(
            _("Not rated") if score is None else f"{score}/10"
        )
        self.rating_button.set_icon_name(
            "non-starred-symbolic" if score is None else "starred-symbolic"
        )
        self.rating_button.set_tooltip_text(
            _("Rate this title")
            if score is None
            else _("Your rating: {score}/10").format(score=score)
        )
        self._updating_details = False
        self._populate_detail_sections(record)
        if record_changed:
            self._scroll_to_top(self.details_scroller)

    def _remember_active_collection_state(self) -> None:
        """Store the active collection's selection, scroll, and filters."""
        collection = self.active_collection
        self.collection_selected_ids[collection] = self.selected_id
        self.collection_scroll_positions[collection] = (
            self.results_scroller.get_vadjustment().get_value()
        )
        self.collection_view_states[collection] = {
            "query": self.search_entry.get_text(),
            "genre": self.genre,
            "sortKey": self.sort_key,
            "sortReversed": self.sort_reversed,
        }

    def _restore_active_collection_state(self) -> float:
        """Restore controls for the active collection and return its scroll."""
        state = self.collection_view_states[self.active_collection]
        self.selected_id = self.collection_selected_ids[self.active_collection]
        self.genre = str(state["genre"])
        self.sort_key = str(state["sortKey"])
        self.sort_reversed = bool(state["sortReversed"])
        self._updating = True
        self.search_entry.set_text(str(state["query"]))
        sort_keys = tuple(key for key, _label in SORT_OPTIONS)
        self.sort_dropdown.set_selected(sort_keys.index(self.sort_key))
        self._updating = False
        self._update_genre_model(preserve=True)
        return self.collection_scroll_positions[self.active_collection]

    def _sync_collection_selection(self) -> None:
        was_updating = self._updating
        self._updating = True
        self.destination_list.unselect_all()
        self.collection_list.select_row(self.collection_rows[self.active_collection])
        self._updating = was_updating

    def _update_sort_icon(self) -> None:
        base_reverse = self.sort_key != "title"
        descending = base_reverse ^ self.sort_reversed
        icon_name = (
            "view-sort-descending-symbolic"
            if descending
            else "view-sort-ascending-symbolic"
        )
        self.sort_direction_button.set_icon_name(icon_name)
        self.sort_direction_button.set_tooltip_text(
            "Descending order" if descending else "Ascending order"
        )

    @persisted_change
    def _on_media_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        if self._updating:
            return
        active = group.get_active_name()
        if not active:
            return
        media_type = active.title()
        if media_type not in MEDIA_TYPES:
            return
        self._updating = True
        try:
            other = (
                self.compact_media_switcher
                if group is self.media_switcher
                else self.media_switcher
            )
            other.set_active_name(active)
        finally:
            self._updating = False
        if self.active_destination == "profile":
            return
        self._set_details_open(False)
        self.active_media = media_type
        if self.active_destination == "explore":
            self._update_genre_model()
            self._update_explore_genre_model(preserve=False)
            if self.explore_search_entry.get_text().strip():
                self._queue_tmdb_explore_search()
            else:
                self._refresh_explore()
        else:
            self._updating = True
            self.search_entry.set_text("")
            self._updating = False
            self._update_genre_model()
            self._refresh_results()

    @persisted_change
    def _on_destination_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        if row.key != self.active_destination and self.details_open:
            self._set_details_open(False)
        if row.key == "calendar":
            if self.active_destination == "collection":
                self._remember_active_collection_state()
            elif self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
            self.active_destination = "calendar"
            self._set_media_switcher_available(False)
            self._updating = True
            self.collection_list.unselect_all()
            self._updating = False
            self.browser_stack.set_visible_child_name("calendar")
            self._close_sidebar_overlay()
            self._queue_responsive_layout()
            if self.calendar_snapshot is None:
                self._start_calendar_refresh(False)
            else:
                self._render_calendar()
            return
        if row.key != "explore":
            return
        if self.active_destination == "collection":
            self._remember_active_collection_state()
        self.active_destination = "explore"
        self._set_media_switcher_available(True)
        self._updating = True
        self.collection_list.unselect_all()
        self._updating = False
        self.browser_stack.set_visible_child_name("explore")
        self._update_explore_genre_model()
        self._refresh_explore()
        self._close_sidebar_overlay()
        self._queue_responsive_layout()

    def _on_profile_clicked(self, _button: Gtk.Button) -> None:
        if self._updating:
            return
        if self.active_destination == "profile":
            return
        if self.details_open:
            self._set_details_open(False)
        if self.active_destination == "collection":
            self._remember_active_collection_state()
        elif self.active_destination == "explore":
            self.explore_selected_id = self.selected_id
        self.active_destination = "profile"
        self._set_media_switcher_available(False)
        self._updating = True
        self.destination_list.unselect_all()
        self.collection_list.unselect_all()
        self._updating = False
        self.browser_stack.set_visible_child_name("profile")
        self._refresh_profile()
        self._close_sidebar_overlay()
        self._queue_responsive_layout()

    def _sidebar_is_open(self) -> bool:
        return bool(self.workspace.get_show_sidebar())

    def _sidebar_overlay_open(self) -> bool:
        return bool(
            self.workspace.get_collapsed() and self.workspace.get_show_sidebar()
        )

    def _set_sidebar_open(self, open_sidebar: bool) -> None:
        self.workspace.set_show_sidebar(open_sidebar)
        self._update_sidebar_toggle()

    def _update_sidebar_toggle(self) -> None:
        self._updating_sidebar_toggle = True
        try:
            is_open = self._sidebar_is_open()
            self.sidebar_toggle_button.set_active(is_open)
            self.sidebar_toggle_button.set_tooltip_text(
                _("Hide Sidebar (Ctrl+B)")
                if is_open
                else _("Show Sidebar (Ctrl+B)")
            )
        finally:
            self._updating_sidebar_toggle = False

    def _on_sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_sidebar_toggle:
            return
        self._set_sidebar_open(button.get_active())
        self._queue_responsive_layout()
        if self._sidebar_resize_source_id:
            GLib.source_remove(self._sidebar_resize_source_id)
        self._sidebar_resize_source_id = GLib.timeout_add(
            280,
            self._on_sidebar_transition_complete,
        )

    def _close_sidebar_overlay(self) -> None:
        if self._sidebar_overlay_open():
            self._set_sidebar_open(False)

    def _queue_responsive_layout(self) -> None:
        if self._responsive_layout_source_id:
            GLib.source_remove(self._responsive_layout_source_id)
        self._responsive_layout_source_id = GLib.timeout_add(
            90,
            self._apply_responsive_layout,
        )

    def _responsive_window_width(self) -> int:
        try:
            width = self.window.get_width()
        except (AttributeError, RuntimeError, TypeError):
            width = 0
        if width > 0:
            return width
        try:
            surface = self.window.get_surface()
            if surface is not None and int(surface.get_width()) > 0:
                return int(surface.get_width())
        except (AttributeError, RuntimeError, TypeError):
            surface = None
        return self.explore_pane.get_width() or self.collection_pane.get_width() or 0

    def _apply_responsive_layout(self) -> bool:
        self._responsive_layout_source_id = 0
        if self._applying_responsive:
            return GLib.SOURCE_REMOVE
        self._applying_responsive = True
        try:
            width = self._responsive_window_width()
            if width <= 0:
                return GLib.SOURCE_REMOVE
            current_layout = ResponsiveLayout(
                SIDEBAR_EXPANDED if self._sidebar_docked else SIDEBAR_HIDDEN,
                self.effective_details_mode,
            )
            layout = responsive_layout_for_width(
                width,
                details_open=self.details_open,
                current_layout=current_layout,
            )
            self._apply_media_switcher_layout(width)
            self._apply_sidebar_docked(layout.sidebar_mode == SIDEBAR_EXPANDED)
            if (
                self._details_resize_source_id
                and layout.details_mode != self.effective_details_mode
            ):
                # Let the existing revealer complete before moving either
                # shared details widget to a different parent.
                self._pending_details_mode = layout.details_mode
                return GLib.SOURCE_REMOVE
            self._apply_details_mode(layout.details_mode)
            self._sync_details_presentation()
            self._queue_explore_resize()
            self._update_sidebar_toggle()
        finally:
            self._applying_responsive = False
        return GLib.SOURCE_REMOVE

    def _set_media_switcher_available(self, available: bool) -> None:
        """Show the media selector only where changing media is meaningful."""
        self._media_switcher_available = available
        if hasattr(self, "header_bar"):
            if available:
                self.header_bar.set_title_widget(self.media_switcher)
            else:
                self.header_bar.set_title_widget(Adw.WindowTitle(
                    title=_("Profile") if self.active_destination == "profile" else _("Calendar")
                ))
        if not hasattr(self, "compact_media_switcher"):
            self.media_switcher.set_visible(available)
            return
        self._apply_media_switcher_layout(self._responsive_window_width())

    def _apply_media_switcher_layout(self, width: int) -> None:
        """Move the labeled selector below content before labels are elided."""
        compact = 0 < width < COMPACT_MEDIA_SWITCHER_WIDTH
        available = self._media_switcher_available
        self.media_switcher.set_visible(available and not compact)
        self.compact_media_bar.set_visible(available and compact)

    def _explore_base_width(self, *, details_open: bool | None = None) -> int:
        """Return Explore's current allocation, never a guessed subtraction.

        ``details_open`` remains accepted for callers that previously used
        this helper, but card geometry is intentionally based on GTK's actual
        allocation.  A cached width is only useful before the first allocation.
        """
        del details_open
        allocated = self.explore_pane.get_width() or self.collection_pane.get_width()
        if allocated > 0:
            return allocated
        return max(0, self._last_explore_layout_width)

    def _apply_explore_columns_for_width(self) -> None:
        # Kept as a compatibility entrypoint; all callers now receive the
        # allocation-stable, coalesced implementation above.
        self._queue_explore_resize()

    def _apply_sidebar_docked(self, docked: bool) -> None:
        """Dock the sidebar beside content or collapse it into a drawer.

        Only acts when the docked bucket changes, so an open drawer is never
        closed by an unrelated resize callback.
        """
        if docked == self._sidebar_docked:
            return
        self._sidebar_docked = docked
        self.workspace.set_collapsed(not docked)
        if not docked:
            self.workspace.set_show_sidebar(False)
        self._update_sidebar_toggle()

    def _details_revealer_parent(self) -> Any:
        return self.details_revealer.get_parent()

    def _move_details_to_mobile(self) -> None:
        """Host the shared details surface on the full-page mobile page."""
        if self.details_surface.get_parent() is self.mobile_details_host:
            return
        parent = self.details_surface.get_parent()
        if parent is not None:
            parent.remove(self.details_surface)
        self.mobile_details_host.append(self.details_surface)
        self.details_surface.set_hexpand(True)

    def _move_details_home(self) -> None:
        """Return the shared details surface to the inline/overlay panel."""
        if self.details_surface.get_parent() is self.details_panel_layout:
            return
        parent = self.details_surface.get_parent()
        if parent is not None:
            parent.remove(self.details_surface)
        self.details_panel_layout.append(self.details_surface)
        self.details_surface.set_hexpand(False)

    def _sync_mobile_back_visibility(self) -> None:
        if self.mobile_header_bar is None:
            return
        self.mobile_header_bar.set_visible(
            self.detail_navigation.get_visible_page_tag() == "title"
        )

    def _on_inner_details_page_changed(
        self,
        _navigation: Adw.NavigationView,
        _parameter: Any,
    ) -> None:
        self._sync_mobile_back_visibility()

    def _mobile_details_is_visible(self) -> bool:
        """Return whether the mobile Details page is actually visible."""
        return (
            self.content_navigation is not None
            and self.content_navigation.get_visible_page_tag() == "details"
        )

    def _on_content_navigation_page_changed(
        self,
        _navigation: Adw.NavigationView,
        _parameter: Any,
    ) -> None:
        """Synchronize flags when the outer navigation changes externally.

        Never pushes or pops here; only mirrors the real visible page so a
        Back button or gesture cannot desynchronize the details state.
        Programmatic pops during breakpoint transitions leave navigation
        mode, so they are ignored here and handled by the mode transition.
        """
        if self._mobile_details_is_visible():
            return
        if not self.details_open:
            return
        if self.effective_details_mode != DETAILS_NAVIGATION:
            return
        self.details_open = False
        self._restore_details_return_focus()
        self._schedule_details_reset()

    def _sync_details_presentation(self) -> None:
        """Idempotently place the details UI for the open flag and mode."""
        mode = self.effective_details_mode
        requested = (mode, self.details_open)
        if requested == getattr(self, "_last_applied_details_presentation", None):
            return
        if mode == DETAILS_NAVIGATION:
            self._move_details_to_mobile()
        else:
            self._move_details_home()
        want_mobile = self.details_open and mode == DETAILS_NAVIGATION
        mobile_visible = self._mobile_details_is_visible()
        if want_mobile and not mobile_visible:
            self.content_navigation.push(self.mobile_details_page)
        elif not want_mobile and mobile_visible:
            self.content_navigation.pop_to_tag("browser")
        if mode == DETAILS_OVERLAY:
            if self._details_revealer_parent() is not self.content_overlay:
                self.main_workspace.remove(self.details_revealer)
                self.content_overlay.add_overlay(self.details_revealer)
            self.details_revealer.set_halign(Gtk.Align.END)
            self.details_revealer.set_valign(Gtk.Align.FILL)
            self.details_revealer.set_hexpand(False)
            self.details_revealer.set_vexpand(True)
            panel_width = self._details_panel_preferred_width(
                DETAILS_OVERLAY, self._responsive_window_width()
            )
            self.details_surface.set_size_request(panel_width, -1)
        else:
            if self._details_revealer_parent() is not self.main_workspace:
                self.content_overlay.remove_overlay(self.details_revealer)
                self.main_workspace.append(self.details_revealer)
            self.details_revealer.set_halign(Gtk.Align.FILL)
            self.details_revealer.set_valign(Gtk.Align.FILL)
            self.details_revealer.set_hexpand(False)
            self.details_revealer.set_vexpand(True)
            if mode == DETAILS_INLINE:
                self.details_surface.set_size_request(DETAILS_INLINE_WIDTH, -1)
            else:
                self.details_surface.set_size_request(-1, -1)
        revealed = self.details_open and mode != DETAILS_NAVIGATION
        if revealed != getattr(self, "_details_revealed_state", None):
            self.details_revealer.set_reveal_child(revealed)
            self._details_revealed_state = revealed
        self._last_applied_details_presentation = requested
        self._sync_details_mode_chrome()
        self._sync_mobile_back_visibility()

    def _apply_details_mode(self, mode: str) -> None:
        if mode == self.effective_details_mode:
            return
        self.effective_details_mode = mode
        self._last_applied_details_presentation = None

    def _sync_details_mode_chrome(self) -> None:
        overlay_active = (
            self.details_open and self.effective_details_mode == DETAILS_OVERLAY
        )
        navigation_active = (
            self.details_open and self.effective_details_mode == DETAILS_NAVIGATION
        )
        if self.details_overlay_close is not None:
            self.details_overlay_close.set_visible(overlay_active)
        focus_mode = (
            self.effective_details_mode if overlay_active or navigation_active else None
        )
        if focus_mode is not None and focus_mode != getattr(
            self, "_details_chrome_focus_mode", None
        ):
            self.detail_navigation.grab_focus()
        self._details_chrome_focus_mode = focus_mode

    def _on_sidebar_transition_complete(self) -> bool:
        self._sidebar_resize_source_id = 0
        self._queue_explore_resize()
        return GLib.SOURCE_REMOVE

    @persisted_change
    def _on_collection_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self._activate_collection(row.key)

    @persisted_change
    def _activate_collection(self, collection_name: str) -> None:
        """Open one direct collection destination in the shared view."""
        if collection_name not in COLLECTION_NAMES:
            return
        returning_to_collection = self.active_destination != "collection"
        collection_changed = collection_name != self.active_collection
        if not returning_to_collection and not collection_changed:
            self._sync_collection_selection()
            self._close_sidebar_overlay()
            return
        if self.details_open:
            self._set_details_open(False)
        if not returning_to_collection:
            self._remember_active_collection_state()
        else:
            if self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
        self.active_destination = "collection"
        self.active_collection = collection_name
        self._set_media_switcher_available(True)
        self.browser_stack.set_visible_child_name("collection")
        self._sync_collection_selection()
        scroll_position = self._restore_active_collection_state()
        self._refresh_results()
        self._scroll_to_value(self.results_scroller, scroll_position)
        self._save_user_state(remember_collection=False)
        self._close_sidebar_overlay()
        self._queue_responsive_layout()

    @persisted_change
    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if not self._updating:
            self._refresh_results()

    def _on_explore_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if not self._updating and self.active_destination == "explore":
            self._queue_tmdb_explore_search()

    def _on_find_requested(self, *_args: Any) -> None:
        if self.active_destination == "collection":
            self._close_sidebar_overlay()
            self.search_entry.grab_focus()
        else:
            self._on_search_requested()

    def _on_search_requested(self, *_args: Any) -> None:
        if self.active_destination != "explore":
            self.destination_list.select_row(self.explore_row)
        self._post_ui(self._focus_explore_search)

    def _focus_explore_search(self) -> bool:
        self.explore_search_entry.grab_focus()
        return GLib.SOURCE_REMOVE

    @persisted_change
    def _on_sort_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(SORT_OPTIONS):
            return
        self.sort_key = SORT_OPTIONS[selected][0]
        self.sort_reversed = False
        self._refresh_results()

    @persisted_change
    def _on_genre_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.genre_options):
            return
        self.genre = self.genre_options[selected]
        self._refresh_results()

    @persisted_change
    def _on_reverse_sort(self, _button: Gtk.Button) -> None:
        self.sort_reversed = not self.sort_reversed
        self._refresh_results()

    def _on_explore_sort_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(EXPLORE_SORT_OPTIONS):
            return
        self.explore_sort_key = EXPLORE_SORT_OPTIONS[selected][0]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_explore_period_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(EXPLORE_PERIODS):
            return
        self.explore_period = EXPLORE_PERIODS[selected]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_explore_genre_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.explore_genre_options):
            return
        self.explore_genre = self.explore_genre_options[selected]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_clear_explore_filters(self, _button: Gtk.Button) -> None:
        self._updating = True
        self.explore_sort_dropdown.set_selected(0)
        self.explore_period_dropdown.set_selected(0)
        self.explore_genre_dropdown.set_selected(0)
        self.explore_sort_key = "trending"
        self.explore_period = "This month"
        self.explore_genre = "All genres"
        self._updating = False
        self._refresh_explore()

    def _on_explore_card_clicked(self, record_id: str) -> None:
        if (
            record_id not in self.explore_ids
            and record_id not in self.explore_search_ids
        ):
            return
        self.explore_selected_id = record_id
        self.selected_id = record_id
        self._sync_explore_selection_style()
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[record_id])

    @persisted_change
    def _on_view_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        if self._updating:
            return
        active = group.get_active_name()
        if active not in ("list", "grid"):
            return
        if active == self.view_mode:
            return
        selected_index = next(
            (
                index
                for index, record in enumerate(self.visible_records)
                if record.id == self.selected_id
            ),
            0,
        )
        self.view_mode = active
        self.preferred_view_mode = active
        self._save_view_mode_preference()
        self._refresh_results()
        if active == "grid":
            columns = grid_columns_for_width(self.results_scroller.get_width())
            scroll_position = (selected_index // columns) * GRID_ROW_HEIGHT
        else:
            scroll_position = selected_index * 126
        self._scroll_to_value(self.results_scroller, scroll_position)

    def _on_image_mode_changed(
        self,
        group: Adw.ToggleGroup,
        _parameter: Any,
    ) -> None:
        active = group.get_active_name()
        if active not in ("backdrops", "posters"):
            return
        self.image_mode = active
        record = self.records_by_id.get(self.selected_id or "")
        if record is not None:
            self._populate_images(record)

    def _on_season_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        season_index = getattr(row, "season_index", None)
        if record is None or season_index is None or record.media_type == "Movies":
            return
        self._populate_season_page(record, int(season_index))
        self.detail_navigation.push_by_tag("season")
        self._load_tmdb_season_details_async(record, int(season_index))

    def _on_episode_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        season_index = getattr(row, "season_index", None)
        episode_index = getattr(row, "episode_index", None)
        if record is None or season_index is None or episode_index is None:
            return
        season_index = int(season_index)
        if not self._season_episode_details_ready(record, season_index):
            self._toast(_("Wait for all episode details to finish loading"))
            self._load_tmdb_season_details_async(record, season_index)
            return
        self._populate_episode_page(
            record,
            season_index,
            int(episode_index),
        )
        self.detail_navigation.push_by_tag("episode")
        self._load_tmdb_episode_details_async(
            record,
            season_index,
            int(episode_index),
        )

    @persisted_change
    def _on_episode_row_watched_clicked(
        self,
        _button: Gtk.Button,
        record_id: str,
        season_index: int,
        episode_number: int,
    ) -> None:
        """Toggle one episode without navigating away from the season page."""
        record = self.records_by_id.get(record_id)
        if record is None:
            return
        seasons = self._series_seasons(record)
        if not (0 <= season_index < len(seasons)):
            return
        episode = next(
            (
                item
                for item in self._episodes_for_season(record, season_index)
                if item.number == episode_number
            ),
            None,
        )
        if episode is None:
            return
        if self._episode_is_watched(record, season_index, episode):
            self._unmark_episode_watched(record, season_index, episode)
            return
        season = seasons[season_index]
        self._show_watched_time_dialog(
            title_text=record.title,
            subtitle_text=(
                f"S{season.number:02d}E{episode.number:02d} · {episode.title}"
            ),
            on_confirm=lambda iso: self._mark_episode_watched(
                record,
                season_index,
                episode.number,
                iso,
            ),
        )

    @staticmethod
    def _uses_12_hour_clock() -> bool:
        return bool(datetime.now().astimezone().strftime("%p"))

    def _build_watched_time_dialog(
        self,
        *,
        title_text: str,
        subtitle_text: str | None,
        on_confirm: Any,
    ) -> Adw.AlertDialog:
        """Build the watched-at date/time selector dialog (not presented)."""
        now = datetime.now().astimezone().replace(microsecond=0)
        use_12h = self._uses_12_hour_clock()
        body = title_text if not subtitle_text else f"{title_text}\n{subtitle_text}"
        dialog = Adw.AlertDialog(
            heading=_("When did you watch this?"),
            body=body,
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        picker_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        picker_card.add_css_class("card")
        picker_card.add_css_class("watched-dialog-card")
        date_caption = Gtk.Label(label=_("Date"), xalign=0)
        date_caption.add_css_class("caption")
        date_caption.add_css_class("dim-label")
        picker_card.append(date_caption)
        calendar = Gtk.Calendar()
        calendar.set_hexpand(True)
        calendar.add_css_class("watched-dialog-calendar")
        set_calendar_date(
            calendar, GLib.DateTime.new_local(now.year, now.month, now.day, 0, 0, 0.0)
        )
        picker_card.append(calendar)
        time_caption = Gtk.Label(label=_("Time"), xalign=0)
        time_caption.add_css_class("caption")
        time_caption.add_css_class("dim-label")
        picker_card.append(time_caption)

        time_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        time_row.set_halign(Gtk.Align.CENTER)
        display_hour = int(now.strftime("%I" if use_12h else "%H"))
        hour_spin = Gtk.SpinButton.new_with_range(
            1 if use_12h else 0,
            12 if use_12h else 23,
            1,
        )
        hour_spin.set_value(display_hour)
        hour_spin.set_wrap(True)
        hour_spin.set_tooltip_text(_("Hour"))
        time_row.append(hour_spin)
        separator = Gtk.Label(label=":")
        separator.add_css_class("title-2")
        time_row.append(separator)
        minute_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        minute_spin.set_value(now.minute)
        minute_spin.set_wrap(True)
        minute_spin.set_tooltip_text(_("Minute"))
        time_row.append(minute_spin)
        ampm_dropdown: Gtk.DropDown | None = None
        if use_12h:
            ampm_dropdown = Gtk.DropDown.new_from_strings(("AM", "PM"))
            ampm_dropdown.set_selected(1 if now.hour >= 12 else 0)
            ampm_dropdown.set_tooltip_text(_("AM or PM"))
            time_row.append(ampm_dropdown)

        actions_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        actions_row.set_halign(Gtk.Align.CENTER)
        now_button = Gtk.Button(label=_("Now"))
        now_button.set_tooltip_text(_("Reset to the current date and time"))
        now_button.add_css_class("pill")
        actions_row.append(now_button)
        picker_card.append(time_row)
        picker_card.append(actions_row)
        content.append(picker_card)

        error_label = Gtk.Label(xalign=0.5)
        error_label.set_wrap(True)
        error_label.add_css_class("error")
        error_label.set_visible(False)
        content.append(error_label)
        dialog.set_extra_child(content)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("mark", _("Mark as Watched"))
        dialog.set_close_response("cancel")
        dialog.set_default_response("mark")
        dialog.set_response_appearance("mark", Adw.ResponseAppearance.SUGGESTED)

        def read_selection() -> str:
            selected = calendar.get_date()
            year, month, day = (
                selected.get_year(),
                selected.get_month(),
                selected.get_day_of_month(),
            )
            moment = watched_datetime_from_parts(
                year,
                month,
                day,
                hour_spin.get_value_as_int(),
                minute_spin.get_value_as_int(),
                hour_is_12h=use_12h,
                is_pm=bool(
                    ampm_dropdown is not None and ampm_dropdown.get_selected() == 1
                ),
            )
            return moment.isoformat() if moment is not None else ""

        def refresh_validity(*_args: Any) -> None:
            error = validate_watched_iso(read_selection() or "invalid")
            dialog.set_response_enabled("mark", error is None)
            error_label.set_label(error or "")
            error_label.set_visible(error is not None)

        def reset_to_now(*_args: Any) -> None:
            current = datetime.now().astimezone().replace(microsecond=0)
            set_calendar_date(
                calendar,
                GLib.DateTime.new_local(
                    current.year, current.month, current.day, 0, 0, 0.0
                ),
            )
            hour_spin.set_value(int(current.strftime("%I" if use_12h else "%H")))
            minute_spin.set_value(current.minute)
            if ampm_dropdown is not None:
                ampm_dropdown.set_selected(1 if current.hour >= 12 else 0)
            refresh_validity()

        now_button.connect("clicked", reset_to_now)
        calendar.connect("day-selected", refresh_validity)
        hour_spin.connect("value-changed", refresh_validity)
        minute_spin.connect("value-changed", refresh_validity)
        if ampm_dropdown is not None:
            ampm_dropdown.connect("notify::selected", refresh_validity)

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response != "mark":
                return
            selection = read_selection()
            if validate_watched_iso(selection or "invalid") is not None:
                refresh_validity()
                return
            on_confirm(selection)

        dialog.connect("response", on_response)
        refresh_validity()
        dialog._watched_time_controls = (  # type: ignore[attr-defined]
            calendar,
            hour_spin,
            minute_spin,
            ampm_dropdown,
            error_label,
        )
        return dialog

    def _show_watched_time_dialog(
        self,
        *,
        title_text: str,
        subtitle_text: str | None,
        on_confirm: Any,
    ) -> None:
        dialog = self._build_watched_time_dialog(
            title_text=title_text,
            subtitle_text=subtitle_text,
            on_confirm=on_confirm,
        )
        dialog.present(self.window)

    @persisted_change
    def _on_season_watched_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        episodes = self._episodes_for_season(record, self.current_season_index)
        if not episodes:
            return
        watched = self._season_watched_count(record, self.current_season_index)
        new_status = watched < len(episodes)
        if not new_status:
            self._unmark_season_watched(record, self.current_season_index)
            return
        seasons = self._series_seasons(record)
        season = seasons[self.current_season_index]
        season_index = self.current_season_index
        self._show_watched_time_dialog(
            title_text=record.title,
            subtitle_text=f"{season.title}",
            on_confirm=lambda iso: self._mark_season_watched(record, season_index, iso),
        )

    def _refresh_season_watched_ui(
        self, record: TitleRecord, season_index: int
    ) -> None:
        record = self.records_by_id.get(record.id, record)
        season_scroll = self.season_details_scroller.get_vadjustment().get_value()
        self._populate_series(record)
        self._populate_season_page(record, season_index)
        self._scroll_to_value(self.season_details_scroller, season_scroll)
        episodes = self._episodes_for_season(record, season_index)
        if (
            self.detail_record_id == record.id
            and self.current_season_index == season_index
            and 0 <= self.current_episode_index < len(episodes)
        ):
            self._update_episode_watch_controls(
                record,
                season_index,
                episodes[self.current_episode_index],
            )
        if self.active_destination == "profile":
            self._refresh_profile()
        else:
            self._defer_collection_refresh_for_detail_mutation()

    @persisted_change
    def _defer_collection_refresh_for_detail_mutation(self) -> None:
        """Keep the open title stable, then refresh its filter after closing."""
        if self.active_destination != "collection":
            return
        if getattr(self, "details_open", False):
            self._collection_results_dirty = True
            return
        self._refresh_results()

    @persisted_change
    def _mark_season_watched(
        self,
        record: TitleRecord,
        season_index: int,
        iso_timestamp: str,
    ) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        episodes = self._episodes_for_season(record, season_index)
        newly_watched = [
            episode
            for episode in episodes
            if not self._episode_is_watched(record, season_index, episode)
        ]
        if not newly_watched:
            return

        @self._guard_state_callback
        def apply() -> None:
            if self._local_mode_active():
                self._ensure_local_library_record(record)
            for episode in newly_watched:
                key = self._episode_key(record, season_index, episode)
                self.episode_status_overrides[key] = True
                self.episode_watched_at[key] = iso_timestamp
            self._save_user_state()
            self._refresh_season_watched_ui(record, season_index)

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast(_("Season watched time saved locally (not synced)"))
            else:
                self._toast(_("Connect Simkl to change episode history"))
            return
        outcome_box: dict[str, simkl_client.HistorySyncResult] = {}

        def operation() -> dict[str, Any]:
            result = self._post_simkl_history(
                f"season {season.number} of {record.id} "
                f"({len(newly_watched)} episodes) at {iso_timestamp}",
                lambda: simkl_client.set_episode_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    season.number,
                    [(episode.number, iso_timestamp) for episode in newly_watched],
                ),
            )
            outcome = simkl_client.history_sync_result(result)
            outcome_box["result"] = outcome
            if outcome.not_found:
                raise simkl_client.SimklError("Simkl could not match this title.")
            return result

        def on_done() -> None:
            outcome = outcome_box["result"]
            if outcome.accepted_episodes <= 0:
                self._update_details()
                self._toast(_("Simkl did not add any episodes to watched history."))
                return
            apply()
            self._invalidate_simkl_snapshot_after_mutation()
            self._toast(_("Season marked as watched"))

        self._run_simkl_mutation(
            f"{self._canonical_record_id(record)}:s{season.number}:watched",
            operation,
            on_done,
            "",
        )

    @persisted_change
    def _unmark_season_watched(self, record: TitleRecord, season_index: int) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        episodes = self._episodes_for_season(record, season_index)
        watched_snapshot = tuple(
            (
                episode.number,
                self.episode_watched_at.get(
                    self._episode_key(record, season_index, episode),
                    watched_now_iso(),
                ),
            )
            for episode in episodes
            if self._episode_is_watched(record, season_index, episode)
        )

        def offer_undo() -> None:
            self._toast_with_action(
                _("Season Marked as Unwatched"),
                _("Undo"),
                lambda: self._restore_season_watched(
                    record, season_index, watched_snapshot
                ),
            )

        @self._guard_state_callback
        def apply() -> None:
            for episode in episodes:
                key = self._episode_key(record, season_index, episode)
                self.episode_status_overrides[key] = False
                self.episode_watched_at.pop(key, None)
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            self._refresh_season_watched_ui(record, season_index)

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                offer_undo()
            else:
                self._toast(_("Connect Simkl to change episode history"))
            return
        def completed() -> None:
            apply()
            offer_undo()

        self._run_simkl_mutation(
            f"{record.id}:s{season.number}:unwatched",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.remove_episode_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    season.number,
                    [episode.number for episode in episodes],
                )
            ),
            completed,
            "",
        )

    @persisted_change
    def _restore_season_watched(
        self,
        record: TitleRecord,
        season_index: int,
        watched_snapshot: tuple[tuple[int, str], ...],
    ) -> None:
        """Restore exactly the episode timestamps captured before an unwatch."""
        if not watched_snapshot:
            return
        season = self._series_seasons(record)[season_index]

        @self._guard_state_callback
        def apply() -> None:
            episodes_by_number = {
                episode.number: episode
                for episode in self._episodes_for_season(record, season_index)
            }
            for episode_number, watched_at in watched_snapshot:
                episode = episodes_by_number.get(episode_number)
                if episode is None:
                    continue
                key = self._episode_key(record, season_index, episode)
                self.episode_status_overrides[key] = True
                self.episode_watched_at[key] = watched_at
            self._save_user_state()
            self._refresh_season_watched_ui(record, season_index)

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast(_("Season Restored"))
            return
        self._run_simkl_mutation(
            f"{record.id}:s{season.number}:restore",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.set_episode_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    season.number,
                    list(watched_snapshot),
                )
            ),
            apply,
            _("Season Restored"),
        )

    @persisted_change
    def _on_episode_watched_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        episodes = self._episodes_for_season(record, self.current_season_index)
        if not episodes or self.current_episode_index >= len(episodes):
            return
        episode = episodes[self.current_episode_index]
        new_status = not self._episode_is_watched(
            record,
            self.current_season_index,
            episode,
        )
        if not new_status:
            self._unmark_episode_watched(record, self.current_season_index, episode)
            return
        seasons = self._series_seasons(record)
        season = seasons[self.current_season_index]
        season_index = self.current_season_index
        episode_code = f"S{season.number:02d}E{episode.number:02d}"
        self._show_watched_time_dialog(
            title_text=record.title,
            subtitle_text=f"{episode_code} · {episode.title}",
            on_confirm=lambda iso: self._mark_episode_watched(
                record, season_index, episode.number, iso
            ),
        )

    @persisted_change
    def _mark_episode_watched(
        self,
        record: TitleRecord,
        season_index: int,
        episode_number: int,
        iso_timestamp: str,
    ) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        match = next(
            (
                episode
                for episode in self._episodes_for_season(record, season_index)
                if episode.number == episode_number
            ),
            None,
        )
        if match is None:
            return
        key = self._episode_key(record, season_index, match)

        @self._guard_state_callback
        def apply() -> None:
            current_record = self.records_by_id.get(record.id, record)
            if self._local_mode_active():
                self._ensure_local_library_record(current_record)
            self.episode_status_overrides[key] = True
            self.episode_watched_at[key] = iso_timestamp
            self._save_user_state()
            self._populate_series(current_record)
            season_scroll = self.season_details_scroller.get_vadjustment().get_value()
            self._populate_season_page(
                current_record,
                season_index,
                reset_scroll=False,
            )
            self._scroll_to_value(self.season_details_scroller, season_scroll)
            episodes = self._episodes_for_season(current_record, season_index)
            if 0 <= self.current_episode_index < len(episodes):
                self._update_episode_watch_controls(
                    current_record,
                    season_index,
                    episodes[self.current_episode_index],
                )
            if self.active_destination == "profile":
                self._refresh_profile()
            else:
                self._defer_collection_refresh_for_detail_mutation()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast(_("Episode watched time saved locally (not synced)"))
            else:
                self._toast(_("Connect Simkl to change episode history"))
            return
        outcome_box: dict[str, simkl_client.HistorySyncResult] = {}

        def operation() -> dict[str, Any]:
            result = self._post_simkl_history(
                f"episode {episode_number} of season {season.number} "
                f"({record.id}) at {iso_timestamp}",
                lambda: simkl_client.set_episode_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    season.number,
                    [(episode_number, iso_timestamp)],
                ),
            )
            outcome = simkl_client.history_sync_result(result)
            outcome_box["result"] = outcome
            if outcome.not_found:
                raise simkl_client.SimklError("Simkl could not match this title.")
            return result

        def on_done() -> None:
            if outcome_box["result"].accepted_episodes <= 0:
                self._update_details()
                self._toast(_("Simkl did not add this episode to watched history."))
                return
            apply()
            self._invalidate_simkl_snapshot_after_mutation()
            self._toast(_("Episode marked as watched"))

        self._run_simkl_mutation(
            f"{key}:watched",
            operation,
            on_done,
            "",
        )

    @persisted_change
    def _unmark_episode_watched(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        key = self._episode_key(record, season_index, episode)
        previous_watched_at = self.episode_watched_at.get(key) or watched_now_iso()

        def offer_undo() -> None:
            self._toast_with_action(
                _("Episode Marked as Unwatched"),
                _("Undo"),
                lambda: self._mark_episode_watched(
                    record,
                    season_index,
                    episode.number,
                    previous_watched_at,
                ),
            )

        @self._guard_state_callback
        def apply() -> None:
            current_record = self.records_by_id.get(record.id, record)
            self.episode_status_overrides[key] = False
            self.episode_watched_at.pop(key, None)
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            self._populate_series(current_record)
            season_scroll = self.season_details_scroller.get_vadjustment().get_value()
            self._populate_season_page(
                current_record,
                season_index,
                reset_scroll=False,
            )
            self._scroll_to_value(self.season_details_scroller, season_scroll)
            episodes = self._episodes_for_season(current_record, season_index)
            if 0 <= self.current_episode_index < len(episodes):
                self._update_episode_watch_controls(
                    current_record,
                    season_index,
                    episodes[self.current_episode_index],
                )
            if self.active_destination == "profile":
                self._refresh_profile()
            else:
                self._defer_collection_refresh_for_detail_mutation()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                offer_undo()
            else:
                self._toast(_("Connect Simkl to change episode history"))
            return

        def completed() -> None:
            apply()
            offer_undo()

        self._run_simkl_mutation(
            f"{key}:unwatched",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.remove_episode_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    season.number,
                    [episode.number],
                )
            ),
            completed,
            "",
        )

    def _on_list_selected(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self.selected_id = row.record.id
        self.collection_selected_ids[self.active_collection] = self.selected_id
        self._updating = True
        grid_child = self._grid_children.get(self.selected_id)
        if grid_child is not None:
            self.grid_box.select_child(grid_child)
        self._updating = False
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_list_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        self.selected_id = row.record.id
        self.collection_selected_ids[self.active_collection] = self.selected_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_grid_selected(self, flow_box: Gtk.FlowBox) -> None:
        if self._updating:
            return
        selected = flow_box.get_selected_children()
        if not selected:
            return
        child = selected[0]
        self.selected_id = child.record.id
        self.collection_selected_ids[self.active_collection] = self.selected_id
        self._updating = True
        list_row = self._list_rows.get(self.selected_id)
        if list_row is not None:
            self.list_box.select_row(list_row)
        self._updating = False
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_grid_activated(
        self,
        _flow_box: Gtk.FlowBox,
        child: Gtk.FlowBoxChild,
    ) -> None:
        self.selected_id = child.record.id
        self.collection_selected_ids[self.active_collection] = self.selected_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    @staticmethod
    def _details_panel_preferred_width(mode: str, available_width: int) -> int:
        """Return the details panel width for a presentation mode.

        The width depends only on the mode and the available viewport, never
        on the measured content, so Movies, Shows, and Anime share one width.
        Returns 0 for full-page navigation, which fills its allocation.
        """
        if mode == DETAILS_INLINE:
            return DETAILS_INLINE_WIDTH
        if mode == DETAILS_OVERLAY:
            return min(
                DETAILS_OVERLAY_MAX_WIDTH,
                max(
                    DETAILS_OVERLAY_MIN_WIDTH,
                    max(0, available_width) - DETAILS_NARROW_SAFE_MARGIN,
                ),
            )
        return 0

    def _preshrink_explore_for_inline_details(self) -> None:
        """Compatibility no-op retained for external callers.

        Rebuilding before the revealer receives its final allocation was the
        source of the resize feedback loop.  The transition completion path
        now schedules one allocation-based relayout instead.
        """
        self._queue_explore_resize()

    def _cancel_pending_details_reset(self) -> None:
        if self._details_reset_source_id:
            GLib.source_remove(self._details_reset_source_id)
            self._details_reset_source_id = 0

    def _schedule_details_reset(self) -> None:
        self._cancel_pending_details_reset()
        self._details_reset_source_id = GLib.timeout_add(
            300,
            self._reset_details_if_closed,
        )

    def _reset_details_if_closed(self) -> bool:
        self._details_reset_source_id = 0
        if not self.details_open:
            self._reset_detail_navigation()
        return GLib.SOURCE_REMOVE

    def _remember_details_return_focus(self) -> None:
        try:
            focused = self.window.get_focus()
        except GLib.Error:
            focused = None
        self._details_return_focus = focused

    def _restore_details_return_focus(self) -> None:
        target = self._details_return_focus
        self._details_return_focus = None
        if (
            target is not None
            and target.get_root() is not None
            and target.get_visible()
        ):
            target.grab_focus()

    def _set_details_open(self, open_details: bool) -> None:
        if open_details == self.details_open:
            # Selecting a second title updates its content elsewhere; it must
            # not restart the reveal or add another deferred relayout.
            self._sync_details_presentation()
            return
        if open_details:
            self._cancel_pending_details_reset()
            self._remember_details_return_focus()
            width = self._responsive_window_width()
            current_layout = ResponsiveLayout(
                SIDEBAR_EXPANDED if self._sidebar_docked else SIDEBAR_HIDDEN,
                self.effective_details_mode,
            )
            layout = responsive_layout_for_width(
                max(0, width),
                details_open=True,
                current_layout=current_layout,
            )
            self.details_open = True
            self._apply_sidebar_docked(layout.sidebar_mode == SIDEBAR_EXPANDED)
            self._apply_details_mode(layout.details_mode)
            self._sync_details_presentation()
        else:
            self.details_open = False
            self._sync_details_presentation()
            self._schedule_details_reset()
            self._restore_details_return_focus()
        self._queue_responsive_layout()
        if self._details_resize_source_id:
            GLib.source_remove(self._details_resize_source_id)
        self._details_resize_source_id = GLib.timeout_add(
            self.details_revealer.get_transition_duration() + 60,
            self._on_details_transition_complete,
        )

    @persisted_change
    def _on_details_transition_complete(self) -> bool:
        self._details_resize_source_id = 0
        self._pending_details_mode = None
        if not self.details_open and getattr(self, "_collection_results_dirty", False):
            self._collection_results_dirty = False
            if self.active_destination == "collection":
                self._refresh_results()
        self._queue_explore_resize()
        self._queue_responsive_layout()
        return GLib.SOURCE_REMOVE

    def _on_episode_back(self, *_args: Any) -> None:
        self.detail_navigation.pop_to_tag("season")

    def _on_season_back(self, *_args: Any) -> None:
        self.detail_navigation.pop_to_tag("title")

    def _on_mobile_title_back(self, *_args: Any) -> None:
        self._set_details_open(False)

    def _navigate_back(self) -> bool:
        """Walk back through viewer, drawer, episode, season, then details."""
        if self.media_viewer.get_visible():
            self.media_viewer.close()
            return True
        if self._sidebar_overlay_open():
            self._set_sidebar_open(False)
            return True
        if not self.details_open:
            return False
        action = details_back_action(self.detail_navigation.get_visible_page_tag())
        if action == "pop-season":
            self._on_episode_back()
        elif action == "pop-title":
            self._on_season_back()
        else:
            self._set_details_open(False)
        return True

    @persisted_change
    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        self._save_user_state()
        self._save_window_state()
        self.close_background_jobs()
        return False

    def _on_window_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        # Let dialogs and focused controls handle Escape before page navigation.
        if self.window.get_visible_dialog() is not None:
            return False
        return keyval == Gdk.KEY_Escape and self._navigate_back()

    @persisted_change
    def _on_clear_filters(self, _button: Gtk.Button) -> None:
        self._updating = True
        self.search_entry.set_text("")
        self.genre_dropdown.set_selected(0)
        self.genre = "All genres"
        self._updating = False
        self._refresh_results()

    def _on_empty_explore_clicked(self, _button: Gtk.Button) -> None:
        """Take an empty-library user directly to title discovery."""
        self.destination_list.select_row(self.explore_row)

    def _on_search_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval != Gdk.KEY_Escape:
            return False
        self.search_entry.set_text("")
        self.window.set_focus(None)
        return True

    def _on_explore_search_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval != Gdk.KEY_Escape:
            return False
        self.explore_search_entry.set_text("")
        self.window.set_focus(None)
        return True

    @staticmethod
    def _simkl_group(record: TitleRecord) -> str:
        return (
            "movies"
            if record.media_type == "Movies"
            else "anime"
            if record.media_type == "Anime"
            else "shows"
        )

    def _simkl_ids(self, record: TitleRecord) -> dict[str, int | str]:
        """Prefer the matched Library Simkl ID over an Explore TMDB face."""
        ids: dict[str, int | str] = {}
        canonical = self._canonical_record_id(record)
        library_record = getattr(self, "_library_records_by_canonical", {}).get(
            canonical
        )
        source = library_record or record
        if canonical.startswith("simkl-"):
            try:
                ids["simkl"] = int(canonical.rsplit("-", 1)[1])
            except (TypeError, ValueError):
                pass
        if source.tmdb_id is not None:
            ids["tmdb"] = source.tmdb_id
        if not ids:
            raise simkl_client.SimklError("This title has no Simkl or TMDB identifier.")
        return ids

    def _simkl_writable(self) -> bool:
        mode = getattr(
            self,
            "library_mode",
            LIBRARY_MODE_SIMKL
            if getattr(self, "simkl_connected", False)
            else LIBRARY_MODE_LOCAL,
        )
        return bool(
            mode == LIBRARY_MODE_SIMKL
            and self.simkl_client_id
            and self.simkl_token
            and self.simkl_connected
        )

    def _local_mode_active(self) -> bool:
        return (
            getattr(
                self,
                "library_mode",
                LIBRARY_MODE_SIMKL
                if getattr(self, "simkl_connected", False)
                else LIBRARY_MODE_LOCAL,
            )
            == LIBRARY_MODE_LOCAL
        )

    def _ensure_local_library_record(self, record: TitleRecord) -> str:
        """Keep a complete, restart-safe copy of a locally managed title."""
        canonical = self._canonical_record_id(record)
        local_record = replace(
            record,
            id=canonical,
            status=self.status_overrides.get(canonical, record.status),
            user_rating=self.ratings.get(canonical, record.user_rating),
            discover_period="All releases",
            featured=False,
        )
        if not hasattr(self, "local_library_records"):
            self.local_library_records = {}
        self.local_library_records[canonical] = local_record
        library_records = getattr(self, "_library_records_by_canonical", {})
        if canonical not in library_records:
            self.records = (*getattr(self, "records", ()), local_record)
            if not hasattr(self, "library_ids"):
                self.library_ids = set()
            self.library_ids.add(canonical)
            self.records_by_id[canonical] = local_record
            self._rebuild_record_aliases()
        return canonical

    def _remove_unused_local_library_record(self, canonical: str) -> None:
        if (
            canonical in self.bookmarks
            or canonical in self.completed
            or canonical in self.ratings
            or canonical in self.status_overrides
        ):
            return
        if canonical not in self.local_library_records:
            return
        self.local_library_records.pop(canonical, None)
        self.records = tuple(
            item
            for item in self.records
            if self._canonical_record_id(item) != canonical
        )
        self.library_ids = {record.id for record in self.records}
        self.records_by_id.pop(canonical, None)
        self._rebuild_record_aliases()

    def _post_simkl_history(self, description: str, operation: Any) -> dict[str, Any]:
        """Send one history write while leaving a trace in the app log."""
        self._app_log("Sending to Simkl history: %s.", description)
        result = operation()
        # Server responses do not contain credentials; retain the whole payload
        # so an HTTP-success/no-op can be diagnosed from Application Log.
        self._app_log("Simkl history response: %r.", result)
        return result

    @staticmethod
    def _simkl_status_label(status: str | None) -> str | None:
        return {
            "completed": "Watched",
            "watching": "Watching",
            "plantowatch": "Watchlist",
            "hold": "On Hold",
            "dropped": "Dropped",
        }.get(status or "")

    def _invalidate_simkl_snapshot_after_mutation(self) -> None:
        if getattr(self, "library_mode", LIBRARY_MODE_SIMKL) == LIBRARY_MODE_LOCAL:
            return
        self._simkl_state_generation = getattr(self, "_simkl_state_generation", 0) + 1
        try:
            simkl_client.invalidate_snapshot()
        except simkl_client.SimklError as error:
            self._app_log(
                "Could not invalidate stale Simkl snapshot: %s",
                error,
                level=logging.WARNING,
            )

    @persisted_change
    def _apply_title_history_result(
        self,
        record: TitleRecord,
        outcome: simkl_client.HistorySyncResult,
        watched_at: str,
    ) -> None:
        """Patch only server-confirmed title state across every record alias."""
        canonical = self._canonical_record_id(record)
        status = self._simkl_status_label(outcome.effective_status) or "Watched"
        if status == "Watched":
            self.completed.add(canonical)
            self.bookmarks.discard(canonical)
            self.title_watched_at[canonical] = watched_at
        elif status == "Watchlist":
            self.completed.discard(canonical)
            self.bookmarks.add(canonical)
            self.title_watched_at.pop(canonical, None)
        else:
            self.completed.discard(canonical)
            self.bookmarks.discard(canonical)
            self.title_watched_at.pop(canonical, None)
        base_status = (
            getattr(self, "_library_records_by_canonical", {})
            .get(canonical, record)
            .status
        )
        if status == base_status:
            self.status_overrides.pop(canonical, None)
        else:
            self.status_overrides[canonical] = status
        self._invalidate_simkl_snapshot_after_mutation()
        self._save_user_state()
        if self.active_destination == "profile":
            self._refresh_profile()
        elif self.active_destination == "explore":
            self._refresh_explore(reset_scroll=False)
        else:
            self._update_details()
            self._defer_collection_refresh_for_detail_mutation()

    def _run_simkl_mutation(
        self,
        key: str,
        operation: Any,
        on_success: Any,
        success_message: str,
    ) -> None:
        if not self._simkl_writable():
            self._update_details()
            self._toast(_("Connect Simkl to change ratings or lists"))
            return
        if key in self._simkl_mutations_inflight:
            self._update_details()
            return
        self._simkl_mutations_inflight.add(key)
        self._update_details()

        def worker() -> None:
            try:
                operation()
            except simkl_client.SimklError as error:
                self._post_ui(
                    self._finish_simkl_mutation,
                    key,
                    None,
                    "",
                    str(error),
                )
                return
            self._post_ui(
                self._finish_simkl_mutation,
                key,
                on_success,
                success_message,
                None,
            )

        self._start_worker('gisheh-simkl-write', worker, *())

    @staticmethod
    def _checked_simkl_write(operation: Any) -> dict[str, Any]:
        """Reject a matched HTTP response that contains unresolved IDs."""
        result = operation()
        raw_not_found = result.get("not_found") if isinstance(result, dict) else None
        if isinstance(raw_not_found, dict) and any(
            isinstance(items, list) and items for items in raw_not_found.values()
        ):
            raise simkl_client.SimklError("Simkl could not match this title.")
        return result

    @persisted_change
    def _finish_simkl_mutation(
        self,
        key: str,
        on_success: Any | None,
        success_message: str,
        error_message: str | None,
    ) -> bool:
        self._simkl_mutations_inflight.discard(key)
        if error_message is not None:
            self._app_log(
                "Simkl write failed for %s: %s",
                key,
                error_message,
                level=logging.ERROR,
            )
            self._update_details()
            self._toast(error_message)
            return GLib.SOURCE_REMOVE
        if on_success is not None:
            self._remote_commit = True
            on_success()
        if success_message:
            self._toast(success_message)
        return GLib.SOURCE_REMOVE

    @persisted_change
    def _write_simkl_list_change(
        self,
        record: TitleRecord,
        *,
        adding: bool,
        on_success: Any,
    ) -> None:
        if getattr(self, "library_mode", LIBRARY_MODE_SIMKL) == LIBRARY_MODE_LOCAL:
            self._ensure_local_library_record(record)
            on_success()
            if adding:
                self._toast(_("Saved to your local watchlist"))
            else:
                self._show_watchlist_removed_undo(record)
            return

        if adding:
            operation = lambda: simkl_client.set_list_status(
                self.simkl_client_id or "",
                self.simkl_token or "",
                self._simkl_group(record),
                self._simkl_ids(record),
                "plantowatch",
            )
        else:
            operation = lambda: simkl_client.remove_from_library(
                self.simkl_client_id or "",
                self.simkl_token or "",
                self._simkl_group(record),
                self._simkl_ids(record),
            )

        def checked_operation() -> dict[str, Any]:
            result = operation()
            raw_not_found = (
                result.get("not_found") if isinstance(result, dict) else None
            )
            if isinstance(raw_not_found, dict) and any(
                isinstance(items, list) and items for items in raw_not_found.values()
            ):
                raise simkl_client.SimklError("Simkl could not match this title.")
            return result

        def completed() -> None:
            on_success()
            if not adding:
                self._show_watchlist_removed_undo(record)

        self._run_simkl_mutation(
            f"{self._canonical_record_id(record)}:watchlist",
            checked_operation,
            completed,
            _("Added to Simkl watchlist") if adding else "",
        )

    def _show_watchlist_removed_undo(self, record: TitleRecord) -> None:
        self._toast_with_action(
            _("Removed from Watchlist"),
            _("Undo"),
            lambda: self._set_record_bookmarked(record, True),
        )

    @persisted_change
    def _on_watched_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        self._activate_record_watched(record)

    @persisted_change
    def _activate_record_watched(self, record: TitleRecord) -> None:
        watched = not self._is_record_completed(record)
        if not watched:
            self._show_watched_title_actions(record)
            return
        self._show_watched_time_dialog(
            title_text=record.title,
            subtitle_text=f"{record.media_type} · {record.year}",
            on_confirm=lambda iso: self._mark_title_watched(record, iso),
        )

    def _show_watched_title_actions(self, record: TitleRecord) -> None:
        """Offer date correction and unwatch as separate, explicit operations."""
        dialog = Adw.AlertDialog(
            heading=record.title,
            body=(
                "This title is already watched in your local library."
                if getattr(self, "library_mode", LIBRARY_MODE_LOCAL)
                == LIBRARY_MODE_LOCAL
                else "This title is already watched on Simkl."
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("change-date", _("Change watched date"))
        dialog.add_response("unwatch", _("Mark as unwatched"))
        dialog.set_response_appearance("change-date", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("unwatch", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "change-date":
                self._show_watched_time_dialog(
                    title_text=_("Change watched date — {title}").format(title=record.title),
                    subtitle_text=_(
                        "This replaces the existing watch date; it is not a rewatch."
                    ),
                    on_confirm=lambda iso: self._change_title_watched_date(record, iso),
                )
            elif response == "unwatch":
                self._mark_title_unwatched(record)

        dialog.connect("response", on_response)
        dialog.present(self.window)

    @persisted_change
    def _mark_title_unwatched(self, record: TitleRecord) -> None:
        """Remove watched history and return the title to the active watchlist."""
        canonical = self._canonical_record_id(record)
        previous_watched_at = self.title_watched_at.get(canonical) or watched_now_iso()

        def offer_undo() -> None:
            self._toast_with_action(
                _("Marked as Unwatched"),
                _("Undo"),
                lambda: self._mark_title_watched(record, previous_watched_at),
            )

        @self._guard_state_callback
        def apply() -> None:
            self.completed.discard(canonical)
            self.bookmarks.add(canonical)
            self.title_watched_at.pop(canonical, None)
            base_status = (
                getattr(self, "_library_records_by_canonical", {})
                .get(canonical, record)
                .status
            )
            if base_status == "Watchlist":
                self.status_overrides.pop(canonical, None)
            else:
                self.status_overrides[canonical] = "Watchlist"
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            if self.active_destination == "profile":
                self._refresh_profile()
            elif self.active_destination == "explore":
                self._refresh_explore(reset_scroll=False)
            else:
                self._update_details()
                self._defer_collection_refresh_for_detail_mutation()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                offer_undo()
            else:
                self._toast(_("Connect Simkl to change watch history"))
            return
        def completed() -> None:
            apply()
            offer_undo()

        self._run_simkl_mutation(
            f"{canonical}:unwatched",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.set_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    False,
                )
            ),
            completed,
            "",
        )

    @persisted_change
    def _mark_title_watched(self, record: TitleRecord, iso_timestamp: str) -> None:
        def apply_watched() -> None:
            self._apply_title_history_result(
                record,
                simkl_client.HistorySyncResult(
                    changed=True,
                    counts={"movies": 1, "shows": 1, "anime": 1, "episodes": 0},
                    statuses=("completed",),
                    not_found={},
                    noop=False,
                ),
                iso_timestamp,
            )

        if not self._simkl_writable():
            if self._local_mode_active():
                self._ensure_local_library_record(record)
                apply_watched()
                self._toast(_("Watched time saved locally (not synced)"))
            else:
                self._toast(_("Connect Simkl to change watch history"))
            return
        write_outcome: dict[str, simkl_client.HistorySyncResult] = {}

        def operation() -> dict[str, Any]:
            result = self._post_simkl_history(
                f"{record.id} at {iso_timestamp}",
                lambda: simkl_client.set_watched(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    True,
                    watched_at=iso_timestamp,
                ),
            )
            outcome = simkl_client.history_sync_result(result)
            write_outcome["result"] = outcome
            if outcome.not_found:
                raise simkl_client.SimklError("Simkl could not match this title.")
            return result

        def on_done() -> None:
            outcome = write_outcome["result"]
            if outcome.noop:
                self._update_details()
                self._toast(
                    _(
                        "This title is already marked as watched on Simkl. "
                        "Use Change watched date or unmark it first."
                    )
                )
                return
            if not outcome.changed:
                self._update_details()
                self._toast(_("Simkl did not confirm this watched update."))
                return
            self._apply_title_history_result(record, outcome, iso_timestamp)
            self._toast(_("Marked as watched"))

        self._run_simkl_mutation(
            f"{record.id}:watched",
            operation,
            on_done,
            "",
        )

    @persisted_change
    def _change_title_watched_date(
        self, record: TitleRecord, iso_timestamp: str
    ) -> None:
        canonical = self._canonical_record_id(record)
        previous = self.title_watched_at.get(canonical)
        outcome_box: dict[str, simkl_client.HistorySyncResult] = {}

        if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
            self._ensure_local_library_record(record)
            self.title_watched_at[canonical] = iso_timestamp
            self.completed.add(canonical)
            self.status_overrides[canonical] = "Watched"
            self._save_user_state()
            self._update_details()
            self._defer_collection_refresh_for_detail_mutation()
            self._toast(_("Watch date changed locally"))
            return

        def operation() -> simkl_client.HistorySyncResult:
            self._app_log("Changing Simkl watched date for %s.", canonical)
            outcome = simkl_client.change_watched_date(
                self.simkl_client_id or "",
                self.simkl_token or "",
                self._simkl_group(record),
                self._simkl_ids(record),
                previous_watched_at=previous,
                watched_at=iso_timestamp,
            )
            outcome_box["result"] = outcome
            self._app_log("Simkl watched-date change result: %r.", outcome)
            return outcome

        def on_done() -> None:
            self._apply_title_history_result(
                record, outcome_box["result"], iso_timestamp
            )
            self._toast(_("Watched date changed"))

        self._run_simkl_mutation(
            f"{canonical}:change-watched-date",
            operation,
            on_done,
            "",
        )

    @persisted_change
    def _on_bookmark_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        adding = button.get_active()
        self._set_record_bookmarked(record, adding)

    @persisted_change
    def _set_record_bookmarked(
        self,
        record: TitleRecord,
        adding: bool,
    ) -> None:

        @self._guard_state_callback
        def apply_bookmark() -> None:
            canonical = self._canonical_record_id(record)
            if adding:
                if (
                    getattr(self, "library_mode", LIBRARY_MODE_LOCAL)
                    == LIBRARY_MODE_LOCAL
                ):
                    canonical = self._ensure_local_library_record(record)
                self.bookmarks.add(canonical)
                self.completed.discard(canonical)
                if self._effective_status(record) != "Watchlist":
                    self.status_overrides[canonical] = "Watchlist"
            else:
                self.bookmarks.discard(canonical)
                self.status_overrides.pop(canonical, None)
                self.completed.discard(canonical)
                if (
                    getattr(self, "library_mode", LIBRARY_MODE_LOCAL)
                    == LIBRARY_MODE_LOCAL
                ):
                    self._remove_unused_local_library_record(canonical)
                elif (
                    record.id in self.library_ids and record.id not in self.explore_ids
                ):
                    self.records = tuple(
                        item for item in self.records if item.id != record.id
                    )
                    self.library_ids.discard(record.id)
                    self.records_by_id.pop(record.id, None)
                    self._rebuild_record_aliases()
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            if self.active_destination == "explore":
                self._refresh_explore(reset_scroll=False)
            elif self.active_destination == "profile":
                self._refresh_profile()
            else:
                if self.selected_id in self.records_by_id:
                    self._update_details()
                self._defer_collection_refresh_for_detail_mutation()

        self._write_simkl_list_change(
            record,
            adding=adding,
            on_success=apply_bookmark,
        )

    @persisted_change
    def _on_rating_button_toggled(
        self,
        button: Gtk.ToggleButton,
        score: int,
    ) -> None:
        if (
            self._updating_details
            or self.selected_id is None
            or not button.get_active()
        ):
            return
        self.rating_popover.popdown()
        record = self.records_by_id[self.selected_id]
        self._set_record_rating(record, score)

    @persisted_change
    def _set_record_rating(self, record: TitleRecord, score: int) -> None:

        @self._guard_state_callback
        def apply_rating() -> None:
            if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
                self._ensure_local_library_record(record)
            self.ratings[self._canonical_record_id(record)] = score
            sources = tuple(
                source
                for source in record.external_ratings
                if source[0] != "Your rating"
            ) + (("Your rating", str(score)),)
            self._store_tmdb_record(
                replace(
                    self.records_by_id[record.id],
                    user_rating=score,
                    external_ratings=sources,
                )
            )
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            if self.active_destination == "explore":
                self._refresh_explore(reset_scroll=False)
            elif self.active_destination == "profile":
                self._refresh_profile()
            else:
                self._update_details()
                self._defer_collection_refresh_for_detail_mutation()

        if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
            apply_rating()
            self._toast(_("Your local rating is now {score}/10").format(score=score))
            return

        self._run_simkl_mutation(
            f"{self._canonical_record_id(record)}:rating",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.set_rating(
                    self.simkl_client_id or "",
                    self.simkl_token or "",
                    self._simkl_group(record),
                    self._simkl_ids(record),
                    score,
                )
            ),
            apply_rating,
            _("Your Simkl rating is now {score}/10").format(score=score),
        )

    def _toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        preferences = getattr(self, "settings_dialog", None)
        if preferences is not None and preferences.get_visible():
            preferences.add_toast(toast)
        else:
            self.toast_overlay.add_toast(toast)

    def _toast_with_action(
        self,
        message: str,
        action_label: str,
        action: Any,
    ) -> None:
        """Show an actionable toast, falling back cleanly in headless tests."""
        overlay = getattr(self, "toast_overlay", None)
        if overlay is None:
            self._toast(message)
            return
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        toast.set_button_label(action_label)
        toast.connect("button-clicked", lambda *_args: action())
        overlay.add_toast(toast)

    def _app_log(
        self,
        message: str,
        *args: object,
        level: int = logging.INFO,
    ) -> None:
        application_logger().log(level, message, *args)
        if getattr(self, "_log_text_view", None) is not None:
            self._post_ui(self._refresh_log_view)

    def _refresh_log_view(self) -> bool:
        if self._log_text_view is None:
            return GLib.SOURCE_REMOVE
        buffer = self._log_text_view.get_buffer()
        buffer.set_text(read_application_log())
        end = buffer.get_end_iter()
        self._log_text_view.scroll_to_iter(end, 0.0, False, 0.0, 1.0)
        return GLib.SOURCE_REMOVE

    def show_application_log(self) -> None:
        if self._log_dialog is not None:
            self._log_dialog.present(self.window)
            self._refresh_log_view()
            return

        dialog = Adw.Dialog(
            title=_("Application Log"), content_width=760, content_height=480
        )
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        refresh = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text=_("Refresh")
        )
        refresh.update_property([Gtk.AccessibleProperty.LABEL], [_("Refresh")])
        refresh.connect("clicked", lambda *_args: self._refresh_log_view())
        header.pack_start(refresh)
        copy = Gtk.Button(label=_("Copy Log"))
        copy.connect("clicked", self._on_copy_log_clicked)
        header.pack_end(copy)
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        path_label = Gtk.Label(
            label=str(application_log_file()), ellipsize=Pango.EllipsizeMode.MIDDLE
        )
        path_label.set_tooltip_text(str(application_log_file()))
        path_label.set_selectable(True)
        path_label.add_css_class("dim-label")
        content.append(path_label)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_view = Gtk.TextView(editable=False, cursor_visible=True, monospace=True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Application Log")]
        )
        for side in ("left", "right", "top", "bottom"):
            getattr(text_view, f"set_{side}_margin")(12)
        scroller.set_child(text_view)
        content.append(scroller)
        toolbar.set_content(content)
        self._log_toast_overlay = Adw.ToastOverlay(child=toolbar)
        dialog.set_child(self._log_toast_overlay)
        dialog.set_focus(text_view)
        dialog.connect("closed", self._on_log_dialog_closed)
        self._log_dialog = dialog
        self._log_text_view = text_view
        self._refresh_log_view()
        dialog.present(self.window)

    def _on_copy_log_clicked(self, _button: Gtk.Button) -> None:
        self.window.get_clipboard().set_text(read_application_log())
        self._log_toast_overlay.add_toast(Adw.Toast.new(_("Application log copied")))

    def _on_log_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._log_dialog = None
        self._log_text_view = None
