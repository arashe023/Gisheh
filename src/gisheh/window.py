#!/usr/bin/env python3
"""گیشه: a lightweight native GTK4/libadwaita movie library."""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from getpass import getuser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from .services import simkl_client, tmdb_client  # noqa: E402
from .state_store import (  # noqa: E402
    LIBRARY_MODE_LOCAL,
    LIBRARY_MODE_SIMKL,
    LIBRARY_MODES,
    clear_state,
    read_state,
    save_library_mode,
    user_state_file as persistent_user_state_file,
    write_state,
)


APP_ID = "io.github.gisheh.Gisheh"
APP_NAME = "گیشه"
APP_VERSION = "1.3.0"
RESOURCE_DIR = Path(__file__).resolve().parent
RESOURCE_PREFIX = "/io/github/gisheh/Gisheh"
UI_RESOURCE = f"{RESOURCE_PREFIX}/ui/window.ui"
CSS_RESOURCE = f"{RESOURCE_PREFIX}/style.css"
LIBRARY_RESOURCE = f"{RESOURCE_PREFIX}/library.json"
UI_FILE = RESOURCE_DIR / "ui" / "window.ui"
CSS_FILE = RESOURCE_DIR / "style.css"
DATA_FILE = RESOURCE_DIR / "library.json"
_APP_LOGGER: logging.Logger | None = None


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating log whose active file always remains private to the user."""

    def _open(self) -> Any:
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
        return stream

MEDIA_TYPES = ("Movies", "Shows", "Anime")
STATUSES = ("Watching", "Watched", "On Hold", "Dropped")
LIBRARY_FILTERS = (*STATUSES, "Watchlist")
SORT_OPTIONS = (
    ("recent", "Last watched"),
    ("title", "Title"),
    ("rating", "Highest rated"),
    ("year", "Release year"),
)
EXPLORE_SORT_OPTIONS = (
    ("trending", "Trending"),
    ("popular", "Popular"),
    ("rating", "Top rated"),
    ("upcoming", "Coming soon"),
)
EXPLORE_PERIODS = ("This month", "This year", "All releases")
GRID_CARD_WIDTH = 140
GRID_CARD_HEIGHT = 210
GRID_COLUMN_GAP = 10
GRID_HORIZONTAL_PADDING = 24
GRID_MAX_COLUMNS = 6
GRID_ROW_HEIGHT = 226
CALENDAR_TIMELINE_PAGE_SIZE = 120

STATUS_ICONS = {
    "Watching": "media-playback-start-symbolic",
    "Watchlist": "bookmark-new-symbolic",
    "Watched": "emblem-ok-symbolic",
    "On Hold": "media-playback-pause-symbolic",
    "Dropped": "user-trash-symbolic",
}

LISTS = (("Watchlist", "bookmark-new-symbolic"),)
COLOR_SCHEMES = ("system", "light", "dark")
COLOR_SCHEME_LABELS = ("Follow system", "Light", "Dark")


def should_show_completion_progress(media_type: str) -> bool:
    """Return whether episodic completion progress belongs in title details."""
    return media_type != "Movies"


def is_episode_group_complete(watched: int, total: int) -> bool:
    """Treat a season as complete only when it has episodes and all are watched."""
    return total > 0 and watched >= total

TMDB_GENRES = {
    12: "Adventure",
    14: "Fantasy",
    16: "Animation",
    18: "Drama",
    27: "Horror",
    28: "Action",
    35: "Comedy",
    36: "History",
    37: "Western",
    53: "Thriller",
    80: "Crime",
    99: "Documentary",
    878: "Science Fiction",
    9648: "Mystery",
    10402: "Music",
    10749: "Romance",
    10751: "Family",
    10752: "War",
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
}


def certification_from_tmdb(payload: dict[str, Any], media_type: str) -> str:
    """Return the best available regional certification from TMDB details."""
    namespace = "movie" if media_type == "movie" else "tv"
    resource = "release_dates" if namespace == "movie" else "content_ratings"
    result_items = payload.get(resource, {}).get("results", ())
    results = [item for item in result_items if isinstance(item, dict)]

    origin_codes = [
        str(code).upper()
        for code in payload.get("origin_country", ())
        if code
    ]
    origin_codes.extend(
        str(item.get("iso_3166_1") or "").upper()
        for item in payload.get("production_countries", ())
        if isinstance(item, dict) and item.get("iso_3166_1")
    )
    preferred_regions = tuple(
        dict.fromkeys(("US", *origin_codes, "GB", "CA", "AU"))
    )

    def value_for(item: dict[str, Any]) -> str:
        if namespace == "tv":
            return str(item.get("rating") or "").strip()
        release_items = [
            release
            for release in item.get("release_dates", ())
            if isinstance(release, dict)
            and str(release.get("certification") or "").strip()
        ]
        release_priority = {3: 0, 2: 1, 4: 2, 5: 3, 6: 4, 1: 5}
        release_items.sort(
            key=lambda release: release_priority.get(
                int(release.get("type") or 0),
                9,
            )
        )
        return (
            str(release_items[0].get("certification") or "").strip()
            if release_items
            else ""
        )

    by_region = {
        str(item.get("iso_3166_1") or "").upper(): item
        for item in results
        if item.get("iso_3166_1")
    }
    for region in preferred_regions:
        certification = value_for(by_region.get(region, {}))
        if certification:
            return certification
    for item in results:
        certification = value_for(item)
        if certification:
            return certification
    return "Unrated"


def application_log_file() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )
    return base / APP_ID / "gisheh.log"


def application_logger() -> logging.Logger:
    global _APP_LOGGER
    if _APP_LOGGER is not None:
        return _APP_LOGGER

    logger = logging.getLogger(APP_ID)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    try:
        destination = application_log_file()
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        file_handler = PrivateRotatingFileHandler(
            destination,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:
        logger.warning("File logging is unavailable: %s", error)
    _APP_LOGGER = logger
    return logger


def read_application_log(max_bytes: int = 250_000) -> str:
    path = application_log_file()
    try:
        with path.open("rb") as source:
            source.seek(0, os.SEEK_END)
            size = source.tell()
            source.seek(max(0, size - max_bytes))
            content = source.read()
    except FileNotFoundError:
        return "No log entries yet."
    except OSError as error:
        return f"Could not read the application log: {error}"
    text = content.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    return text or "No log entries yet."


def clear_application_logs() -> None:
    """Close active file handlers and remove the log plus rotated copies."""
    global _APP_LOGGER
    if _APP_LOGGER is not None:
        for handler in tuple(_APP_LOGGER.handlers):
            _APP_LOGGER.removeHandler(handler)
            handler.close()
        _APP_LOGGER = None
    destination = application_log_file()
    for path in destination.parent.glob(f"{destination.name}*"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def clear_desktop_preferences() -> None:
    """Reset any GSettings values left by this or an earlier گیشه build."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(APP_ID, True) if source is not None else None
    if schema is None:
        return
    settings = Gio.Settings.new_full(schema, None, None)
    for key in schema.list_keys():
        settings.reset(key)
    Gio.Settings.sync()


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


def runtime_minutes(value: str) -> int:
    """Convert the catalog's compact duration strings to minutes."""
    hours = re.search(r"(\d+)\s*h", value)
    minutes = re.search(r"(\d+)\s*m", value)
    if hours or minutes:
        return (int(hours.group(1)) * 60 if hours else 0) + (
            int(minutes.group(1)) if minutes else 0
        )
    return 0


def parse_watched_datetime(value: str) -> datetime | None:
    """Parse canonical ISO 8601 or legacy watched timestamps."""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%b %d, %Y at %I:%M %p")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=datetime.now().astimezone().tzinfo
        )
    return parsed


def parse_watched_date(value: str) -> date | None:
    parsed = parse_watched_datetime(value)
    return parsed.date() if parsed is not None else None


def watched_now_iso() -> str:
    """Return the current local time as a canonical ISO 8601 timestamp."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def watched_datetime_from_parts(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    *,
    hour_is_12h: bool = False,
    is_pm: bool = False,
) -> datetime | None:
    """Build a timezone-aware local datetime from dialog controls."""
    try:
        year, month, day, hour, minute = (
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
        )
    except (TypeError, ValueError):
        return None
    if hour_is_12h:
        if not 1 <= hour <= 12:
            return None
        hour = (hour % 12) + (12 if is_pm else 0)
    elif not 0 <= hour <= 23:
        return None
    if not 0 <= minute <= 59:
        return None
    try:
        moment = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    return moment.replace(tzinfo=datetime.now().astimezone().tzinfo)


def validate_watched_iso(
    value: str,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return an error message for an invalid watched timestamp, else None."""
    parsed = parse_watched_datetime(value)
    if parsed is None:
        return "The selected date and time are not valid."
    reference = now if now is not None else datetime.now().astimezone()
    if reference.tzinfo is None:
        reference = reference.replace(
            tzinfo=datetime.now().astimezone().tzinfo
        )
    if parsed > reference:
        return "The watched time cannot be in the future."
    return None


def format_watched_iso(value: str) -> str:
    """Format a canonical or legacy watched timestamp for display."""
    parsed = parse_watched_datetime(value)
    if parsed is None:
        return value
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return (
        f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at "
        f"{hour}:{parsed.strftime('%M %p')}"
    )


def simkl_history_changed(result: object) -> bool:
    """Return whether a /sync/history response recorded anything new.

    Simkl ignores a history write for an already-completed item (all
    ``added`` counts stay zero). Callers use this to tell "saved" apart
    from "already had it, nothing changed".
    """
    return simkl_client.history_sync_result(result).changed


def format_watch_time(minutes: int) -> str:
    days, remainder = divmod(max(0, minutes), 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def merge_tmdb_season_episodes(
    episodes: tuple[EpisodeInfo, ...],
    tmdb_episodes: Any,
    *,
    cached_image_lookup: Any = None,
) -> tuple[EpisodeInfo, ...]:
    """Merge one TMDB season response into existing episodes by episode number.

    Matching uses ``episode_number`` (not list position) so specials and
    unusual orders stay correct. Empty TMDB values never replace useful
    existing values. Malformed items are skipped without affecting valid ones.
    """
    if not isinstance(tmdb_episodes, (list, tuple)):
        return episodes
    by_number: dict[int, dict[str, Any]] = {}
    for item in tmdb_episodes:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("episode_number"))
        except (TypeError, ValueError):
            continue
        if number not in by_number:
            by_number[number] = item

    def resolve_artwork(still_path: str) -> str | None:
        if cached_image_lookup is not None:
            try:
                return cached_image_lookup(still_path)
            except Exception:
                return None
        try:
            return tmdb_client.cached_image(still_path, size="w780")
        except Exception:
            return None

    merged: list[EpisodeInfo] = []
    for episode in episodes:
        payload = by_number.get(episode.number)
        if payload is None:
            merged.append(episode)
            continue
        try:
            title_value = str(payload.get("name") or "").strip()
            title = title_value if title_value else episode.title
            date_value = str(payload.get("air_date") or "").strip()
            date = date_value if date_value else episode.date
            description_value = str(payload.get("overview") or "").strip()
            description = (
                description_value if description_value else episode.description
            )
            try:
                runtime_value = int(payload.get("runtime") or 0)
            except (TypeError, ValueError):
                runtime_value = 0
            runtime = (
                format_watch_time(runtime_value)
                if runtime_value > 0
                else episode.runtime
            )
            guest_stars = payload.get("guest_stars")
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
                    except Exception:
                        profile_file = None
                    cast_items.append(
                        CastMember(
                            name=str(member.get("name") or "Unknown"),
                            role=str(member.get("character") or "Guest star"),
                            profile_file=profile_file,
                        )
                    )
                cast: tuple[CastMember, ...] = (
                    tuple(cast_items) if cast_items else episode.cast
                )
            else:
                cast = episode.cast
            still_path = str(payload.get("still_path") or "").strip()
            if still_path:
                artwork_file = resolve_artwork(still_path) or episode.artwork_file
            else:
                artwork_file = episode.artwork_file
            merged.append(
                replace(
                    episode,
                    title=title,
                    date=date,
                    description=description,
                    runtime=runtime,
                    cast=cast,
                    artwork_file=artwork_file,
                )
            )
        except Exception:
            merged.append(episode)
    return tuple(merged)


def grid_columns_for_width(width: int) -> int:
    """Return the FlowBox column count implied by the card's real minimum width."""
    content_width = max(1, width - GRID_HORIZONTAL_PADDING)
    columns = (content_width + GRID_COLUMN_GAP) // (
        GRID_CARD_WIDTH + GRID_COLUMN_GAP
    )
    return max(1, min(GRID_MAX_COLUMNS, columns))


SIDEBAR_EXPANDED = "expanded"
SIDEBAR_HIDDEN = "hidden"

DETAILS_INLINE = "inline"
DETAILS_OVERLAY = "overlay"
DETAILS_NAVIGATION = "navigation"

# Explore must keep enough room for a useful card grid.  This is deliberately
# part of the responsive contract rather than an accidental consequence of a
# card's natural size request.
EXPLORE_SAFE_CONTENT_WIDTH = 480
RESPONSIVE_LAYOUT_GAPS = 24

# The enter/exit pairs provide a small stable band around each transition.
# They are intentionally named separately: a layout entered at the upper
# threshold is not immediately abandoned when allocation changes by a few
# pixels during a revealer animation.
RESPONSIVE_WIDE_ENTER_WIDTH = 1200
RESPONSIVE_WIDE_EXIT_WIDTH = 1160
RESPONSIVE_INLINE_ENTER_WIDTH = 980
RESPONSIVE_INLINE_EXIT_WIDTH = 940
RESPONSIVE_NARROW_ENTER_WIDTH = 720
RESPONSIVE_NARROW_EXIT_WIDTH = 760

# Compatibility names used by callers and older tests.  New decisions use the
# explicit enter/exit values above.
RESPONSIVE_WIDE_WIDTH = RESPONSIVE_WIDE_ENTER_WIDTH
RESPONSIVE_MEDIUM_WIDTH = RESPONSIVE_INLINE_ENTER_WIDTH
RESPONSIVE_NARROW_WIDTH = RESPONSIVE_NARROW_ENTER_WIDTH

SIDEBAR_EXPANDED_MIN_WIDTH = 248
SIDEBAR_EXPANDED_MAX_WIDTH = 300

DETAILS_INLINE_WIDTH = 384
DETAILS_OVERLAY_MAX_WIDTH = 388
DETAILS_OVERLAY_MIN_WIDTH = 280
DETAILS_NARROW_SAFE_MARGIN = 48
EXPLORE_COLUMN_HYSTERESIS = 20


@dataclass(frozen=True, slots=True)
class ResponsiveLayout:
    sidebar_mode: str
    details_mode: str


def responsive_layout_for_width(
    width: int,
    *,
    details_open: bool = False,
    current_layout: ResponsiveLayout | None = None,
) -> ResponsiveLayout:
    """Map allocated window width to an explicit responsive layout decision.

    The result depends only on its inputs so layout states stay deterministic
    and unit-testable without GTK widgets.
    """
    normalized = max(0, int(width))
    previous_sidebar = (
        current_layout.sidebar_mode if current_layout is not None else None
    )
    previous_details = (
        current_layout.details_mode if current_layout is not None else None
    )

    # A docked sidebar is allowed only when its own minimum, the fixed details
    # panel, gaps and a useful Explore allocation can coexist.  When details
    # are closed, the panel has no allocation and the normal wide breakpoint
    # may keep the sidebar docked.
    required_inline_with_sidebar = (
        SIDEBAR_EXPANDED_MIN_WIDTH
        + DETAILS_INLINE_WIDTH
        + EXPLORE_SAFE_CONTENT_WIDTH
        + RESPONSIVE_LAYOUT_GAPS
    )
    wide_enter = max(RESPONSIVE_WIDE_ENTER_WIDTH, required_inline_with_sidebar)
    wide_exit = max(RESPONSIVE_WIDE_EXIT_WIDTH, required_inline_with_sidebar)
    keep_wide = previous_sidebar == SIDEBAR_EXPANDED and normalized >= wide_exit
    can_dock = normalized >= wide_enter or keep_wide
    if details_open and normalized < required_inline_with_sidebar:
        can_dock = False
    sidebar_mode = SIDEBAR_EXPANDED if can_dock else SIDEBAR_HIDDEN

    if not details_open:
        # The inactive surface stays in its desktop home.  This prevents an
        # unnecessary mobile reparent before a title has been selected.
        return ResponsiveLayout(sidebar_mode, DETAILS_INLINE)

    keep_navigation = (
        previous_details == DETAILS_NAVIGATION
        and normalized < RESPONSIVE_NARROW_EXIT_WIDTH
    )
    if normalized < RESPONSIVE_NARROW_ENTER_WIDTH or keep_navigation:
        return ResponsiveLayout(SIDEBAR_HIDDEN, DETAILS_NAVIGATION)

    required_inline = (
        (SIDEBAR_EXPANDED_MIN_WIDTH if sidebar_mode == SIDEBAR_EXPANDED else 0)
        + DETAILS_INLINE_WIDTH
        + EXPLORE_SAFE_CONTENT_WIDTH
        + RESPONSIVE_LAYOUT_GAPS
    )
    inline_enter = max(RESPONSIVE_INLINE_ENTER_WIDTH, required_inline)
    inline_exit = max(RESPONSIVE_INLINE_EXIT_WIDTH, required_inline)
    keep_inline = (
        previous_details == DETAILS_INLINE and normalized >= inline_exit
    )
    if normalized >= inline_enter or keep_inline:
        return ResponsiveLayout(sidebar_mode, DETAILS_INLINE)
    return ResponsiveLayout(SIDEBAR_HIDDEN, DETAILS_OVERLAY)


def details_back_action(inner_tag: str) -> str:
    """Map the visible inner details page to its Back behavior.

    Returns ``"pop-season"`` (episode → season), ``"pop-title"``
    (season → title), or ``"close"`` (title → content).
    """
    if inner_tag == "episode":
        return "pop-season"
    if inner_tag == "season":
        return "pop-title"
    return "close"


@dataclass(frozen=True, slots=True)
class CastMember:
    name: str
    role: str
    profile_file: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeInfo:
    id: str
    number: int
    title: str
    date: str
    description: str
    watched: bool | None
    image_variant: int
    artwork_file: str | None = None
    runtime: str = ""
    cast: tuple[CastMember, ...] = ()


@dataclass(frozen=True, slots=True)
class EpisodeWatch:
    season: int
    episode: int
    watched_at: str = ""


@dataclass(frozen=True, slots=True)
class SeasonInfo:
    id: str
    number: int
    title: str
    watched: int
    episodes: int
    episode_items: tuple[EpisodeInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class VideoInfo:
    title: str
    key: str
    site: str = "YouTube"
    thumbnail_file: str | None = None

    @property
    def url(self) -> str | None:
        if self.site.casefold() == "youtube" and self.key:
            return f"https://www.youtube.com/watch?v={self.key}"
        return None


def main_progress_season_indexes(seasons: tuple[SeasonInfo, ...]) -> tuple[int, ...]:
    """Use regular seasons for progress, falling back to Specials-only catalogs."""
    regular_indexes = tuple(
        index for index, season in enumerate(seasons) if season.number > 0
    )
    return regular_indexes or tuple(range(len(seasons)))


@dataclass(frozen=True, slots=True)
class TitleRecord:
    id: str
    title: str
    media_type: str
    status: str
    date: str
    year: int
    runtime: str
    rating: float
    user_rating: int | None
    genres: tuple[str, ...]
    country: str
    creator: str
    description: str
    poster_palette: tuple[str, str, str]
    poster_variant: int
    order: int
    certification: str
    language: str
    availability: str
    network: str
    external_ratings: tuple[tuple[str, str], ...]
    cast: tuple[CastMember, ...]
    seasons: tuple[SeasonInfo, ...]
    recommendations: tuple[str, ...]
    discover_period: str
    featured: bool
    popularity: int
    release_rank: int
    discover_layout: str
    tmdb_id: int | None = None
    tmdb_media_type: str | None = None
    simkl_id: int | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    mal_id: int | None = None
    artwork_file: str | None = None
    poster_file: str | None = None
    backdrop_file: str | None = None
    gallery_backdrops: tuple[str, ...] = ()
    gallery_posters: tuple[str, ...] = ()
    video_titles: tuple[str, ...] = ()
    videos: tuple[VideoInfo, ...] = ()
    episode_history: tuple[EpisodeWatch, ...] = ()
    episode_history_loaded: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "TitleRecord":
        media_type = str(raw["type"])
        country = str(raw["country"])
        discover_period = str(raw.get("discoverPeriod", "All releases"))
        period_rank = {
            "This month": 0,
            "This year": 1,
            "All releases": 2,
        }.get(discover_period, 3)
        order = int(raw["order"])

        def parse_season(item: dict[str, Any], position: int) -> SeasonInfo:
            title = str(item["title"])
            default_number = 0 if title.casefold() == "specials" else position
            number = int(item.get("number", default_number))
            season_id = str(
                item.get("id", "specials" if number == 0 else f"s{number}")
            )
            return SeasonInfo(
                id=season_id,
                number=number,
                title=title,
                watched=int(item.get("watched", 0)),
                episodes=int(item["episodes"]),
                episode_items=tuple(
                    EpisodeInfo(
                        id=str(episode.get("id", f"e{episode_position}")),
                        number=int(episode.get("number", episode_position)),
                        title=str(
                            episode.get("title", f"Episode {episode_position}")
                        ),
                        date=str(episode.get("date", str(raw["year"]))),
                        description=str(
                            episode.get("description", raw["description"])
                        ),
                        watched=(
                            bool(episode["watched"])
                            if "watched" in episode
                            else None
                        ),
                        image_variant=int(
                            episode.get("imageVariant", episode_position)
                        ),
                        artwork_file=(
                            str(episode["artworkFile"])
                            if episode.get("artworkFile") is not None
                            else None
                        ),
                        runtime=str(episode.get("runtime", "")),
                        cast=tuple(
                            CastMember(
                                str(member["name"]),
                                str(member["role"]),
                                str(member.get("profileFile") or "") or None,
                            )
                            for member in episode.get("cast", ())
                            if isinstance(member, dict)
                        ),
                    )
                    for episode_position, episode in enumerate(
                        item.get("episodeItems", ()), start=1
                    )
                ),
            )

        return cls(
            id=str(raw["id"]),
            title=str(raw["title"]),
            media_type=media_type,
            status=str(raw["status"]),
            date=str(raw["date"]),
            year=int(raw["year"]),
            runtime=str(raw["runtime"]),
            rating=float(raw["rating"]),
            user_rating=(
                int(raw["userRating"])
                if raw.get("userRating") is not None
                else None
            ),
            genres=tuple(str(value) for value in raw["genres"]),
            country=country,
            creator=str(raw["creator"]),
            description=str(raw["description"]),
            poster_palette=tuple(str(value) for value in raw["posterPalette"]),
            poster_variant=int(raw["posterVariant"]),
            order=order,
            certification=str(raw.get("certification", "Unrated")),
            language=str(raw.get("language", "—")),
            availability=str(
                raw.get(
                    "availability",
                    "Upcoming"
                    if "discoverPeriod" in raw
                    else "Airing" if media_type != "Movies" else "Released",
                )
            ),
            network=str(raw.get("network", "گیشه")),
            external_ratings=tuple(
                (str(item["source"]), str(item["value"]))
                for item in raw.get("externalRatings", ())
            ),
            cast=tuple(
                CastMember(
                    str(item["name"]),
                    str(item["role"]),
                    str(item.get("profileFile") or "") or None,
                )
                for item in raw.get("cast", ())
            ),
            seasons=tuple(
                parse_season(item, position)
                for position, item in enumerate(raw.get("seasons", ()), start=1)
            ),
            recommendations=tuple(str(value) for value in raw.get("recommendations", ())),
            discover_period=discover_period,
            featured=bool(raw.get("featured", False)),
            popularity=int(raw.get("popularity", order)),
            release_rank=int(raw.get("releaseRank", period_rank * 1000 - order)),
            discover_layout=str(raw.get("layout", "poster")),
            tmdb_id=(int(raw["tmdbId"]) if raw.get("tmdbId") is not None else None),
            tmdb_media_type=(
                str(raw["tmdbMediaType"])
                if raw.get("tmdbMediaType") is not None
                else None
            ),
            simkl_id=(
                int(raw["simklId"])
                if raw.get("simklId") is not None
                else None
            ),
            imdb_id=str(raw.get("imdbId") or "").strip() or None,
            tvdb_id=(
                int(raw["tvdbId"])
                if raw.get("tvdbId") is not None
                else None
            ),
            mal_id=(
                int(raw["malId"])
                if raw.get("malId") is not None
                else None
            ),
            artwork_file=(
                str(raw["artworkFile"])
                if raw.get("artworkFile") is not None
                else None
            ),
            poster_file=(
                str(raw["posterFile"])
                if raw.get("posterFile") is not None
                else None
            ),
            backdrop_file=(
                str(raw["backdropFile"])
                if raw.get("backdropFile") is not None
                else None
            ),
            gallery_backdrops=tuple(
                str(value) for value in raw.get("galleryBackdrops", ())
            ),
            gallery_posters=tuple(
                str(value) for value in raw.get("galleryPosters", ())
            ),
            video_titles=tuple(
                str(value) for value in raw.get("videoTitles", ())
            ),
            videos=tuple(
                VideoInfo(
                    title=str(item.get("title") or "Trailer"),
                    key=str(item.get("key") or ""),
                    site=str(item.get("site") or "YouTube"),
                    thumbnail_file=(
                        str(item["thumbnailFile"])
                        if item.get("thumbnailFile") is not None
                        else None
                    ),
                )
                for item in raw.get("videos", ())
                if isinstance(item, dict) and item.get("key")
            ),
            episode_history=tuple(
                EpisodeWatch(
                    season=int(item["season"]),
                    episode=int(item["episode"]),
                    watched_at=str(item.get("watchedAt", "")),
                )
                for item in raw.get("episodeHistory", ())
                if isinstance(item, dict)
                and item.get("season") is not None
                and item.get("episode") is not None
            ),
            episode_history_loaded=bool(raw.get("episodeHistoryLoaded", False)),
        )


def title_record_to_mapping(record: TitleRecord) -> dict[str, Any]:
    """Serialize one locally owned library record without losing rich metadata."""
    return {
        "id": record.id,
        "title": record.title,
        "type": record.media_type,
        "status": record.status,
        "date": record.date,
        "year": record.year,
        "runtime": record.runtime,
        "rating": record.rating,
        "userRating": record.user_rating,
        "genres": list(record.genres),
        "country": record.country,
        "creator": record.creator,
        "description": record.description,
        "posterPalette": list(record.poster_palette),
        "posterVariant": record.poster_variant,
        "order": record.order,
        "certification": record.certification,
        "language": record.language,
        "availability": record.availability,
        "network": record.network,
        "externalRatings": [
            {"source": source, "value": value}
            for source, value in record.external_ratings
        ],
        "cast": [
            {
                "name": member.name,
                "role": member.role,
                "profileFile": member.profile_file,
            }
            for member in record.cast
        ],
        "seasons": [
            {
                "id": season.id,
                "number": season.number,
                "title": season.title,
                "watched": season.watched,
                "episodes": season.episodes,
                "episodeItems": [
                    {
                        "id": episode.id,
                        "number": episode.number,
                        "title": episode.title,
                        "date": episode.date,
                        "description": episode.description,
                        "watched": episode.watched,
                        "imageVariant": episode.image_variant,
                        "artworkFile": episode.artwork_file,
                        "runtime": episode.runtime,
                        "cast": [
                            {
                                "name": member.name,
                                "role": member.role,
                                "profileFile": member.profile_file,
                            }
                            for member in episode.cast
                        ],
                    }
                    for episode in season.episode_items
                ],
            }
            for season in record.seasons
        ],
        "recommendations": list(record.recommendations),
        "discoverPeriod": record.discover_period,
        "featured": record.featured,
        "popularity": record.popularity,
        "releaseRank": record.release_rank,
        "layout": record.discover_layout,
        "tmdbId": record.tmdb_id,
        "tmdbMediaType": record.tmdb_media_type,
        "simklId": record.simkl_id,
        "imdbId": record.imdb_id,
        "tvdbId": record.tvdb_id,
        "malId": record.mal_id,
        "artworkFile": record.artwork_file,
        "posterFile": record.poster_file,
        "backdropFile": record.backdrop_file,
        "galleryBackdrops": list(record.gallery_backdrops),
        "galleryPosters": list(record.gallery_posters),
        "videoTitles": list(record.video_titles),
        "videos": [
            {
                "title": item.title,
                "key": item.key,
                "site": item.site,
                "thumbnailFile": item.thumbnail_file,
            }
            for item in record.videos
        ],
        "episodeHistory": [
            {
                "season": item.season,
                "episode": item.episode,
                "watchedAt": item.watched_at,
            }
            for item in record.episode_history
        ],
        "episodeHistoryLoaded": record.episode_history_loaded,
    }


def load_catalog(
    *,
    include_sample_data: bool = False,
) -> tuple[
    tuple[TitleRecord, ...],
    tuple[TitleRecord, ...],
    dict[str, dict[str, int]],
]:
    try:
        resource = Gio.resources_lookup_data(
            LIBRARY_RESOURCE,
            Gio.ResourceLookupFlags.NONE,
        )
        payload = json.loads(resource.get_data().decode("utf-8"))
    except GLib.Error:
        with DATA_FILE.open(encoding="utf-8") as source:
            payload = json.load(source)

    # Bundled records are retained solely as deterministic test fixtures.
    # Production callers use the default, so both the personal library and
    # Explore start empty and are populated only by user actions or live APIs.
    records = (
        tuple(TitleRecord.from_mapping(raw) for raw in payload["library"])
        if include_sample_data
        else ()
    )
    explore_records = (
        tuple(TitleRecord.from_mapping(raw) for raw in payload.get("explore", ()))
        if include_sample_data
        else ()
    )
    totals = {
        media_type: {status: 0 for status in LIBRARY_FILTERS}
        for media_type in MEDIA_TYPES
    }
    return records, explore_records, totals


def _tmdb_palette(tmdb_id: int) -> tuple[str, str, str]:
    red = 36 + tmdb_id * 37 % 92
    green = 42 + tmdb_id * 53 % 90
    blue = 54 + tmdb_id * 71 % 110
    return (
        f"#{red // 2:02x}{green // 2:02x}{blue // 2:02x}",
        f"#{red:02x}{green:02x}{blue:02x}",
        f"#{min(255, red + 74):02x}{min(255, green + 74):02x}{min(255, blue + 74):02x}",
    )


def title_record_from_tmdb(
    raw: dict[str, Any],
    media_type: str,
    position: int,
    poster_file: str | None,
    backdrop_file: str | None,
) -> TitleRecord:
    tmdb_id = int(raw["id"])
    tmdb_namespace = "movie" if media_type == "Movies" else "tv"
    title = str(raw.get("title") or raw.get("name") or "Untitled")
    release_date = str(raw.get("release_date") or raw.get("first_air_date") or "")
    year = int(release_date[:4]) if release_date[:4].isdigit() else datetime.now().year
    genres = tuple(
        TMDB_GENRES[genre_id]
        for genre_id in raw.get("genre_ids", ())
        if genre_id in TMDB_GENRES
    ) or ("Uncategorized",)
    origin = raw.get("origin_country") or ()
    country = str(origin[0]) if origin else "—"
    rating = round(float(raw.get("vote_average") or 0), 1)
    return TitleRecord(
        id=f"tmdb-{tmdb_namespace}-{tmdb_id}",
        title=title,
        media_type=media_type,
        status="Watchlist",
        date=release_date or "Release date unavailable",
        year=year,
        runtime="Runtime unavailable",
        rating=rating,
        user_rating=None,
        genres=genres,
        country=country,
        creator="TMDB",
        description=str(raw.get("overview") or "No overview is available yet."),
        poster_palette=_tmdb_palette(tmdb_id),
        poster_variant=tmdb_id % 6 + 1,
        order=max(1, 1000 - position),
        certification="Loading…",
        language=str(raw.get("original_language") or "—").upper(),
        availability="Released" if media_type == "Movies" else "Airing",
        network="TMDB",
        external_ratings=(("TMDB", f"{rating:.1f}"),),
        cast=(),
        seasons=(),
        recommendations=(),
        discover_period="This month",
        featured=position == 1,
        popularity=round(float(raw.get("popularity") or 0)),
        release_rank=position,
        discover_layout="poster",
        tmdb_id=tmdb_id,
        tmdb_media_type=tmdb_namespace,
        artwork_file=poster_file or backdrop_file,
        poster_file=poster_file,
        backdrop_file=backdrop_file,
    )


def recommendation_records_from_tmdb(
    items: Any,
    parent: TitleRecord,
    *,
    start_position: int = 1,
) -> tuple[TitleRecord, ...]:
    """Normalize TMDB recommendation results into openable title records.

    Matches the shared ``title_record_from_tmdb()`` path used by Explore and
    search results. Skips the parent title and duplicate TMDB IDs, preserves
    TMDB order, and caps the result at 12 entries.
    """
    if not isinstance(items, (list, tuple)):
        return ()
    parent_ids = {parent.tmdb_id} if parent.tmdb_id is not None else set()
    seen: set[int] = set(parent_ids)
    records: list[TitleRecord] = []
    position = max(1, start_position)
    for item in items:
        if len(records) >= 12:
            break
        if not isinstance(item, dict):
            continue
        try:
            tmdb_id = int(item["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if tmdb_id in seen:
            continue
        seen.add(tmdb_id)
        kind = str(item.get("media_type") or "").lower()
        if kind == "movie":
            media_type = "Movies"
        elif kind == "tv":
            media_type = (
                parent.media_type
                if parent.media_type in ("Shows", "Anime")
                else "Shows"
            )
        elif parent.media_type in ("Movies", "Shows", "Anime"):
            media_type = parent.media_type
        elif (parent.tmdb_media_type or "movie") == "movie":
            media_type = "Movies"
        else:
            media_type = "Shows"
        try:
            poster_file = tmdb_client.cached_image(
                str(item.get("poster_path") or ""),
                size="w342",
            )
            backdrop_file = tmdb_client.cached_image(
                str(item.get("backdrop_path") or ""),
                size="w780",
            )
        except Exception:
            poster_file, backdrop_file = None, None
        try:
            record = title_record_from_tmdb(
                item,
                media_type,
                position,
                poster_file,
                backdrop_file,
            )
        except (TypeError, ValueError, KeyError):
            continue
        if record.id == parent.id:
            continue
        records.append(record)
        position += 1
    return tuple(records)


def video_infos_from_tmdb(items: Any) -> tuple[VideoInfo, ...]:
    """Normalize playable YouTube videos and attach any cached thumbnails."""
    if not isinstance(items, (list, tuple)):
        return ()
    videos: list[VideoInfo] = []
    seen: set[str] = set()
    for item in items:
        if len(videos) >= 8:
            break
        if not isinstance(item, dict):
            continue
        site = str(item.get("site") or "")
        key = str(item.get("key") or "").strip()
        if site.casefold() != "youtube" or not key or key in seen:
            continue
        seen.add(key)
        videos.append(
            VideoInfo(
                title=str(item.get("name") or "Trailer"),
                key=key,
                site=site,
                thumbnail_file=tmdb_client.cached_youtube_thumbnail(key),
            )
        )
    return tuple(videos)


def runtime_from_tmdb(payload: dict[str, Any], fallback: str) -> str:
    """Read a useful duration even when TMDB omits episode_run_time."""
    candidates: list[Any] = [payload.get("runtime")]
    episode_runtimes = payload.get("episode_run_time")
    if isinstance(episode_runtimes, (list, tuple)):
        candidates.extend(episode_runtimes)
    if fallback in {"", "Loading from TMDB…", "Runtime unavailable"}:
        for episode_key in ("last_episode_to_air", "next_episode_to_air"):
            episode = payload.get(episode_key)
            if isinstance(episode, dict):
                candidates.append(episode.get("runtime"))
    for candidate in candidates:
        try:
            minutes = int(candidate or 0)
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            return format_watch_time(minutes)
    return fallback


def enrich_record_from_tmdb(
    record: TitleRecord,
    payload: dict[str, Any],
    *,
    poster_file: str | None = None,
    backdrop_file: str | None = None,
) -> TitleRecord:
    """Apply TMDB-owned catalog metadata while preserving Simkl user state."""
    title = str(payload.get("title") or payload.get("name") or record.title)
    release_date = str(
        payload.get("release_date") or payload.get("first_air_date") or ""
    )
    year = int(release_date[:4]) if release_date[:4].isdigit() else record.year
    genre_items = payload.get("genres", ())
    genres = tuple(
        str(item["name"])
        for item in genre_items
        if isinstance(item, dict) and item.get("name")
    )
    if not genres:
        genres = tuple(
            TMDB_GENRES[genre_id]
            for genre_id in payload.get("genre_ids", ())
            if genre_id in TMDB_GENRES
        ) or record.genres

    runtime = runtime_from_tmdb(payload, record.runtime)

    countries = [
        str(item.get("name") or item.get("iso_3166_1"))
        for item in payload.get("production_countries", ())
        if isinstance(item, dict) and (item.get("name") or item.get("iso_3166_1"))
    ]
    if not countries:
        countries = [str(value) for value in payload.get("origin_country", ()) if value]
    creators = [
        str(item.get("name"))
        for item in payload.get("created_by", ())
        if isinstance(item, dict) and item.get("name")
    ]
    if not creators:
        creators = [
            str(item.get("name"))
            for item in payload.get("production_companies", ())[:2]
            if isinstance(item, dict) and item.get("name")
        ]
    networks = [
        str(item.get("name"))
        for item in payload.get("networks", ())
        if isinstance(item, dict) and item.get("name")
    ]
    tmdb_rating = round(float(payload.get("vote_average") or 0), 1)
    external_ratings = (("TMDB", f"{tmdb_rating:.1f}"),)
    if record.user_rating is not None:
        external_ratings += (("Your rating", str(record.user_rating)),)

    poster_path = str(payload.get("poster_path") or "")
    backdrop_path = str(payload.get("backdrop_path") or "")
    poster_file = poster_file or tmdb_client.cached_image(poster_path, size="w500")
    backdrop_file = backdrop_file or tmdb_client.cached_image(
        backdrop_path,
        size="w780",
    )
    return replace(
        record,
        title=title,
        year=year,
        runtime=runtime,
        rating=tmdb_rating,
        genres=genres,
        country=", ".join(countries[:2]) or record.country,
        creator=", ".join(creators[:2]) or "TMDB",
        description=str(payload.get("overview") or record.description),
        certification=certification_from_tmdb(
            payload,
            record.tmdb_media_type or "movie",
        ),
        language=str(payload.get("original_language") or record.language).upper(),
        availability=str(payload.get("status") or record.availability),
        network=", ".join(networks[:2]) or "TMDB",
        external_ratings=external_ratings,
        popularity=round(float(payload.get("popularity") or record.popularity)),
        artwork_file=poster_file or backdrop_file or record.artwork_file,
        poster_file=poster_file or record.poster_file,
        backdrop_file=backdrop_file or record.backdrop_file,
    )


def enrich_records_from_tmdb_cache(
    records: tuple[TitleRecord, ...],
) -> tuple[TitleRecord, ...]:
    enriched: list[TitleRecord] = []
    for record in records:
        if record.tmdb_id is None or record.tmdb_media_type is None:
            enriched.append(record)
            continue
        summary = tmdb_client.load_summary(
            record.tmdb_media_type,
            record.tmdb_id,
        )
        enriched.append(
            enrich_record_from_tmdb(record, summary)
            if summary is not None
            else record
        )
    return tuple(enriched)


def title_records_from_simkl(payload: dict[str, Any]) -> tuple[TitleRecord, ...]:
    status_map = {
        "plantowatch": "Watchlist",
        "watching": "Watching",
        "hold": "On Hold",
        "completed": "Watched",
        "dropped": "Dropped",
    }
    media_map = {
        "movies": ("Movies", "movie", "movie"),
        "shows": ("Shows", "show", "tv"),
        "anime": ("Anime", "show", "tv"),
    }
    sortable: list[tuple[str, TitleRecord]] = []
    for group, (media_type, object_key, tmdb_namespace) in media_map.items():
        items = payload.get(group, ())
        if not isinstance(items, list):
            continue
        for position, entry in enumerate(items, start=1):
            if not isinstance(entry, dict):
                continue
            media = entry.get(object_key)
            if not isinstance(media, dict):
                continue
            ids = media.get("ids") if isinstance(media.get("ids"), dict) else {}
            simkl_id = ids.get("simkl")
            try:
                numeric_simkl_id = int(simkl_id)
            except (TypeError, ValueError):
                continue
            user_rating = entry.get("user_rating")
            raw_status = str(entry.get("status") or "")
            if raw_status not in status_map:
                continue
            status = status_map[raw_status]
            try:
                watched_count = int(entry.get("watched_episodes_count") or 0)
                total_count = int(entry.get("total_episodes_count") or 0)
            except (TypeError, ValueError):
                continue
            try:
                simkl_runtime_minutes = int(media.get("runtime") or 0)
            except (TypeError, ValueError):
                simkl_runtime_minutes = 0
            simkl_runtime = (
                format_watch_time(simkl_runtime_minutes)
                if simkl_runtime_minutes > 0
                else "Runtime unavailable"
            )
            raw_seasons = entry.get("seasons")
            episode_history: list[EpisodeWatch] = []
            if isinstance(raw_seasons, list):
                for raw_season in raw_seasons:
                    if not isinstance(raw_season, dict):
                        continue
                    try:
                        season_number = int(raw_season.get("number") or 0)
                    except (TypeError, ValueError):
                        continue
                    raw_episodes = raw_season.get("episodes")
                    if not isinstance(raw_episodes, list):
                        continue
                    for raw_episode in raw_episodes:
                        if not isinstance(raw_episode, dict):
                            continue
                        mapping = raw_episode.get("tvdb")
                        mapped_season = season_number
                        mapped_episode = raw_episode.get("number")
                        if isinstance(mapping, dict):
                            mapped_season = mapping.get("season", mapped_season)
                            mapped_episode = mapping.get("episode", mapped_episode)
                        try:
                            mapped_season = int(mapped_season)
                            mapped_episode = int(mapped_episode)
                        except (TypeError, ValueError):
                            continue
                        watched_value = raw_episode.get("watched")
                        if mapped_episode <= 0 or (
                            watched_value is not None and not bool(watched_value)
                        ):
                            continue
                        episode_history.append(
                            EpisodeWatch(
                                season=mapped_season,
                                episode=mapped_episode,
                                watched_at=str(raw_episode.get("watched_at") or ""),
                            )
                        )
            last_activity = str(
                entry.get("last_watched_at")
                or entry.get("added_to_watchlist_at")
                or ""
            )
            tmdb_value = ids.get("tmdb")
            try:
                tmdb_id = int(tmdb_value) if tmdb_value is not None else None
            except (TypeError, ValueError):
                tmdb_id = None
            record = TitleRecord(
                id=f"simkl-{group}-{simkl_id}",
                title="Loading from TMDB…",
                media_type=media_type,
                status=status,
                date=last_activity or "Synced from Simkl",
                year=0,
                runtime=simkl_runtime,
                rating=0.0,
                user_rating=(
                    int(user_rating)
                    if isinstance(user_rating, int) and 1 <= user_rating <= 10
                    else None
                ),
                genres=("Loading from TMDB",),
                country="—",
                creator="TMDB",
                description="Catalog metadata is loading from TMDB.",
                poster_palette=_tmdb_palette(numeric_simkl_id),
                poster_variant=numeric_simkl_id % 6 + 1,
                order=max(1, 100000 - position),
                certification="Loading…",
                language="—",
                availability=str(entry.get("status") or "Synced")
                .replace("plantowatch", "Plan to watch")
                .title(),
                network="TMDB",
                external_ratings=(
                    (("Your rating", str(user_rating)),)
                    if isinstance(user_rating, int) and 1 <= user_rating <= 10
                    else ()
                ),
                cast=(),
                seasons=(
                    (
                        SeasonInfo(
                            id="s1",
                            number=1,
                            title="Progress",
                            watched=watched_count,
                            episodes=total_count,
                        ),
                    )
                    if media_type != "Movies" and total_count
                    else ()
                ),
                recommendations=(),
                discover_period="All releases",
                featured=False,
                popularity=0,
                release_rank=position,
                discover_layout="poster",
                tmdb_id=tmdb_id,
                tmdb_media_type=tmdb_namespace if tmdb_id is not None else None,
                simkl_id=numeric_simkl_id,
                imdb_id=str(ids.get("imdb") or "").strip() or None,
                tvdb_id=(
                    int(ids["tvdb"])
                    if str(ids.get("tvdb") or "").isdigit()
                    else None
                ),
                mal_id=(
                    int(ids["mal"])
                    if str(ids.get("mal") or "").isdigit()
                    else None
                ),
                episode_history=tuple(episode_history),
                episode_history_loaded=isinstance(raw_seasons, list),
            )
            sortable.append((last_activity, record))
    sortable.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    return tuple(
        replace(record, order=max(1, len(sortable) - position))
        for position, (_activity, record) in enumerate(sortable)
    )


def should_refresh_simkl_stats(
    *,
    has_incremental_state: bool,
    repairing_metadata: bool,
    cached_stats: dict[str, Any],
    activities: dict[str, Any],
    last_sync: str,
) -> bool:
    """Avoid the expensive statistics request when account activity is unchanged."""
    if not cached_stats:
        return True
    if repairing_metadata:
        return False
    return not has_incremental_state or activities.get("all") != last_sync


def build_explore_layout_plan(
    count: int,
    columns: int,
    seed: int,
) -> tuple[tuple[tuple[str, int], ...], ...]:
    """Build varied rows without ever assigning one card the complete width."""
    columns = max(1, columns)
    if columns == 1:
        patterns = (
            (("poster", 1),),
        )
    elif columns == 2:
        patterns = (
            (("poster", 1), ("poster", 1)),
        )
    elif columns == 3:
        patterns = (
            (("poster", 1), ("poster", 1), ("poster", 1)),
        )
    elif columns == 4:
        patterns = (
            (("poster", 1), ("poster", 1), ("poster", 1), ("poster", 1)),
            (("landscape", 2), ("landscape", 2)),
            (("landscape", 2), ("poster", 1), ("poster", 1)),
            (("poster", 1), ("poster", 1), ("landscape", 2)),
        )
    else:
        patterns = (
            tuple(("poster", 1) for _ in range(columns)),
            (("hero", 3), ("landscape", 2), *(
                ("poster", 1) for _ in range(columns - 5)
            )),
            (("landscape", 2), ("hero", 3), *(
                ("poster", 1) for _ in range(columns - 5)
            )),
            (("hero", 3), *(
                ("poster", 1) for _ in range(columns - 3)
            )),
            (("landscape", 2), ("landscape", 2), *(
                ("poster", 1) for _ in range(columns - 4)
            )),
            (("landscape", 2), *(
                ("poster", 1) for _ in range(columns - 2)
            )),
        )

    rng = random.Random(seed)
    rows: list[tuple[tuple[str, int], ...]] = []
    remaining = max(0, count)
    previous_signature: tuple[str, ...] | None = None
    while remaining:
        candidates = [pattern for pattern in patterns if len(pattern) <= remaining]
        if not candidates:
            rows.append(tuple(("poster", 1) for _ in range(remaining)))
            break
        alternatives = [
            pattern
            for pattern in candidates
            if tuple(kind for kind, _span in pattern) != previous_signature
        ]
        pattern = rng.choice(alternatives or candidates)
        rows.append(pattern)
        previous_signature = tuple(kind for kind, _span in pattern)
        remaining -= len(pattern)
    return tuple(rows)


def preserve_explore_page_prefix(
    existing: tuple[TitleRecord, ...],
    filtered: tuple[TitleRecord, ...],
) -> tuple[TitleRecord, ...]:
    """Keep rendered pagination results stable and append newly visible rows."""
    filtered_by_id = {record.id: record for record in filtered}
    existing_ids = tuple(
        record.id for record in existing if record.id in filtered_by_id
    )
    existing_id_set = set(existing_ids)
    return (
        *(filtered_by_id[record_id] for record_id in existing_ids),
        *(record for record in filtered if record.id not in existing_id_set),
    )


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _rounded_rectangle(
    context: cairo.Context,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    context.close_path()


class GeneratedPosterWidget(Gtk.DrawingArea):
    """Tiny native poster renderer; no image decoder or browser is required."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
        fixed_size: bool = True,
    ) -> None:
        super().__init__()
        self.record = record
        self.variant_offset = variant_offset
        self.show_text = show_text
        if fixed_size:
            self.set_content_width(width)
            self.set_content_height(height)
            self.set_size_request(width, height)
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Poster artwork for {record.title}"],
        )
        self.set_draw_func(self._draw)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        context: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        first, second, third = (_hex_to_rgb(color) for color in self.record.poster_palette)
        radius = min(11.0, width * 0.12)

        context.save()
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.clip()

        gradient = cairo.LinearGradient(0, 0, width, height)
        gradient.add_color_stop_rgb(0, *first)
        gradient.add_color_stop_rgb(0.58, *second)
        gradient.add_color_stop_rgb(1, *third)
        context.set_source(gradient)
        context.paint()

        self._draw_art(context, width, height, third)

        if not self.show_text:
            fade = cairo.LinearGradient(0, height * 0.54, 0, height)
            fade.add_color_stop_rgba(0, 0, 0, 0, 0)
            fade.add_color_stop_rgba(1, 0, 0, 0, 0.48)
            context.set_source(fade)
            context.rectangle(0, height * 0.54, width, height * 0.46)
            context.fill()
            context.restore()
            context.set_line_width(1)
            context.set_source_rgba(1, 1, 1, 0.16)
            _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
            context.stroke()
            return

        context.set_source_rgba(0, 0, 0, 0.58)
        context.rectangle(0, height * 0.73, width, height * 0.27)
        context.fill()

        context.set_source_rgb(1, 1, 1)
        title = self.record.title.upper()
        context.move_to(width * 0.08, height * 0.87)
        title_layout = PangoCairo.create_layout(context)
        title_layout.set_text(title, -1)
        title_layout.set_width(int(width * 0.84 * Pango.SCALE))
        title_layout.set_ellipsize(Pango.EllipsizeMode.END)
        title_layout.set_single_paragraph_mode(True)
        title_font = Pango.FontDescription("Sans Bold")
        title_font.set_absolute_size(int(max(7.0, width * 0.085) * Pango.SCALE))
        title_layout.set_font_description(title_font)
        PangoCairo.show_layout(context, title_layout)

        context.set_source_rgba(1, 1, 1, 0.78)
        context.move_to(width * 0.08, height * 0.95)
        year_layout = PangoCairo.create_layout(context)
        year_layout.set_text(str(self.record.year), -1)
        year_font = Pango.FontDescription("Sans")
        year_font.set_absolute_size(int(max(6.0, width * 0.07) * Pango.SCALE))
        year_layout.set_font_description(year_font)
        PangoCairo.show_layout(context, year_layout)

        context.restore()

        context.set_line_width(1)
        context.set_source_rgba(1, 1, 1, 0.16)
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.stroke()

    def _draw_art(
        self,
        context: cairo.Context,
        width: int,
        height: int,
        accent: tuple[float, float, float],
    ) -> None:
        variant = ((self.record.poster_variant - 1 + self.variant_offset) % 6) + 1
        context.set_line_width(max(1.0, width * 0.018))

        if variant == 1:
            context.set_source_rgba(*accent, 0.9)
            context.arc(width * 0.68, height * 0.23, width * 0.2, 0, math.tau)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.75, height * 0.18, width * 0.18, 0, math.tau)
            context.fill()
            context.arc(width * 0.5, height * 0.5, width * 0.1, 0, math.tau)
            context.fill()
            context.rectangle(width * 0.4, height * 0.57, width * 0.2, height * 0.26)
            context.fill()
        elif variant == 2:
            context.set_source_rgba(0, 0, 0, 0.56)
            for center_x in (0.36, 0.64):
                context.arc(width * center_x, height * 0.48, width * 0.14, 0, math.tau)
                context.fill()
                context.rectangle(
                    width * (center_x - 0.13),
                    height * 0.56,
                    width * 0.26,
                    height * 0.27,
                )
                context.fill()
        elif variant == 3:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.55, height * 0.4, width * 0.27, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 0.78, 0.25, 0.72)
            for index in range(12):
                angle = math.tau * index / 12
                context.move_to(
                    width * 0.55 + math.cos(angle) * width * 0.31,
                    height * 0.4 + math.sin(angle) * width * 0.31,
                )
                context.line_to(
                    width * 0.55 + math.cos(angle) * width * 0.44,
                    height * 0.4 + math.sin(angle) * width * 0.44,
                )
            context.stroke()
        elif variant == 4:
            context.set_source_rgba(1, 1, 1, 0.78)
            context.rectangle(width * 0.08, height * 0.1, width * 0.38, height * 0.6)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.7)
            context.rectangle(width * 0.14, height * 0.18, width * 0.2, height * 0.22)
            context.fill()
            context.set_source_rgba(*accent, 0.86)
            context.rectangle(width * 0.5, height * 0.28, width * 0.42, height * 0.25)
            context.fill()
        elif variant == 5:
            context.set_source_rgba(*accent, 0.74)
            for index in range(5):
                angle = -math.pi / 2 + index * math.tau / 5
                next_angle = angle + math.tau * 2 / 5
                context.move_to(
                    width * 0.5 + math.cos(angle) * width * 0.33,
                    height * 0.42 + math.sin(angle) * width * 0.33,
                )
                context.line_to(
                    width * 0.5 + math.cos(next_angle) * width * 0.33,
                    height * 0.42 + math.sin(next_angle) * width * 0.33,
                )
            context.stroke()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.5, height * 0.43, width * 0.16, 0, math.tau)
            context.fill()
        else:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.62, height * 0.29, width * 0.25, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 1, 1, 0.38)
            context.move_to(width * 0.08, height * 0.67)
            context.curve_to(
                width * 0.32,
                height * 0.48,
                width * 0.6,
                height * 0.8,
                width * 0.94,
                height * 0.56,
            )
            context.line_to(width * 0.94, height * 0.78)
            context.line_to(width * 0.08, height * 0.78)
            context.close_path()
            context.fill()


class PosterWidget(Gtk.Widget):
    """Display cached TMDB artwork, falling back to the local poster renderer."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
        flexible_width: bool = False,
    ) -> None:
        super().__init__()
        self.fixed_width = width
        self.fixed_height = height
        self.flexible_width = flexible_width
        if flexible_width:
            self.set_size_request(-1, height)
        else:
            self.set_size_request(width, height)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.add_css_class("rounded-media")
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Artwork for {record.title}"],
        )

        artwork_path = Path(record.artwork_file) if record.artwork_file else None
        if artwork_path is not None and artwork_path.is_file():
            picture = Gtk.Picture.new_for_filename(str(artwork_path))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_can_shrink(True)
            picture.set_hexpand(True)
            picture.set_vexpand(True)
            self._media_child: Gtk.Widget = picture
        else:
            pending = Gtk.Box()
            pending.set_hexpand(True)
            pending.set_vexpand(True)
            pending.add_css_class("content-skeleton-surface")
            pending.set_tooltip_text(f"Loading artwork for {record.title}")
            self._media_child = pending
        self._media_child.set_parent(self)

    def do_measure(
        self,
        orientation: Gtk.Orientation,
        _for_size: int,
    ) -> tuple[int, int, int, int]:
        """Keep cached images from imposing their intrinsic size on card layouts."""
        if orientation == Gtk.Orientation.HORIZONTAL:
            if self.flexible_width:
                # The parent grid assigns this width.  A natural artwork width
                # would otherwise be propagated through GtkGrid and make the
                # outer window request room for a card span.
                return 0, 0, -1, -1
            return self.fixed_width, self.fixed_width, -1, -1
        return self.fixed_height, self.fixed_height, -1, -1

    def do_size_allocate(
        self,
        width: int,
        height: int,
        baseline: int,
    ) -> None:
        self._media_child.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        self.snapshot_child(self._media_child, snapshot)

    def do_dispose(self) -> None:
        if self._media_child is not None:
            self._media_child.unparent()
            self._media_child = None
        super().do_dispose()


class MediaViewer(Gtk.Overlay):
    """A Tuba-inspired, in-window viewer for a collection of local images."""

    def __init__(self, window: Adw.ApplicationWindow) -> None:
        super().__init__()
        self.window = window
        self.items: tuple[tuple[str, str], ...] = ()
        self.position = 0
        self.zoom_level = 1.0
        self.texture: Gdk.Texture | None = None
        self._fullscreen_from_viewer = False

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_focusable(True)
        self.set_visible(False)
        self.set_can_target(False)
        self.add_css_class("media-viewer")

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.add_css_class("media-viewer-header")

        close_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        close_button.set_tooltip_text("Back to گیشه")
        close_button.connect("clicked", lambda *_args: self.close())
        header.pack_start(close_button)

        self.window_title = Adw.WindowTitle(
            title="Media Viewer",
            subtitle="",
        )
        header.set_title_widget(self.window_title)

        copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_button.set_tooltip_text("Copy image")
        copy_button.connect("clicked", self._copy_image)
        header.pack_end(copy_button)

        self.fullscreen_button = Gtk.Button.new_from_icon_name(
            "view-fullscreen-symbolic"
        )
        self.fullscreen_button.set_tooltip_text("Toggle fullscreen")
        self.fullscreen_button.connect("clicked", self._toggle_fullscreen)
        header.pack_end(self.fullscreen_button)
        toolbar.add_top_bar(header)

        stage = Gtk.Overlay()
        stage.set_hexpand(True)
        stage.set_vexpand(True)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.scroller.add_css_class("media-viewer-stage")

        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_halign(Gtk.Align.CENTER)
        self.picture.set_valign(Gtk.Align.CENTER)
        self.picture.add_css_class("media-viewer-picture")
        self.scroller.set_child(self.picture)
        stage.set_child(self.scroller)

        page_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        page_controls.set_halign(Gtk.Align.START)
        page_controls.set_valign(Gtk.Align.END)
        page_controls.set_margin_start(18)
        page_controls.set_margin_bottom(18)
        page_controls.add_css_class("media-viewer-osd-box")
        self.previous_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.previous_button.set_tooltip_text("Previous image (Left)")
        self.previous_button.add_css_class("flat")
        self.previous_button.connect("clicked", lambda *_args: self.previous())
        page_controls.append(self.previous_button)
        self.page_label = Gtk.Label(label="1 / 1")
        self.page_label.add_css_class("numeric")
        self.page_label.add_css_class("caption")
        page_controls.append(self.page_label)
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.set_tooltip_text("Next image (Right)")
        self.next_button.add_css_class("flat")
        self.next_button.connect("clicked", lambda *_args: self.next())
        page_controls.append(self.next_button)
        stage.add_overlay(page_controls)

        zoom_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        zoom_controls.set_halign(Gtk.Align.END)
        zoom_controls.set_valign(Gtk.Align.END)
        zoom_controls.set_margin_end(18)
        zoom_controls.set_margin_bottom(18)
        zoom_controls.add_css_class("media-viewer-osd-box")
        zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out.set_tooltip_text("Zoom out (Ctrl+-)")
        zoom_out.add_css_class("flat")
        zoom_out.connect("clicked", lambda *_args: self.zoom_out())
        zoom_controls.append(zoom_out)
        self.zoom_label = Gtk.Label(label="Fit")
        self.zoom_label.set_width_chars(6)
        self.zoom_label.add_css_class("numeric")
        self.zoom_label.add_css_class("caption")
        zoom_controls.append(self.zoom_label)
        zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in.set_tooltip_text("Zoom in (Ctrl++)")
        zoom_in.add_css_class("flat")
        zoom_in.connect("clicked", lambda *_args: self.zoom_in())
        zoom_controls.append(zoom_in)
        stage.add_overlay(zoom_controls)

        toolbar.set_content(stage)
        self.set_child(toolbar)

        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        double_click = Gtk.GestureClick()
        double_click.set_button(Gdk.BUTTON_PRIMARY)
        double_click.connect("pressed", self._on_picture_pressed)
        self.picture.add_controller(double_click)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        scroll.connect("scroll", self._on_scroll)
        self.picture.add_controller(scroll)

    def open(
        self,
        items: tuple[tuple[str, str], ...],
        position: int = 0,
    ) -> None:
        valid_items = tuple(
            (path, label)
            for path, label in items
            if path and Path(path).is_file()
        )
        if not valid_items:
            return
        self.items = valid_items
        self.position = max(0, min(position, len(valid_items) - 1))
        self.set_visible(True)
        self.set_can_target(True)
        self._show_current()
        GLib.idle_add(self._focus_viewer)

    def _focus_viewer(self) -> bool:
        self.grab_focus()
        return GLib.SOURCE_REMOVE

    def close(self) -> None:
        if not self.get_visible():
            return
        if self._fullscreen_from_viewer and self.window.is_fullscreen():
            self.window.unfullscreen()
        self._fullscreen_from_viewer = False
        self.fullscreen_button.set_icon_name("view-fullscreen-symbolic")
        self.picture.set_paintable(None)
        self.texture = None
        self.items = ()
        self.set_can_target(False)
        self.set_visible(False)

    def _show_current(self) -> None:
        if not self.items:
            return
        path, label = self.items[self.position]
        try:
            self.texture = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            self.texture = None
        self.picture.set_paintable(self.texture)
        self.picture.set_alternative_text(label)
        self.window_title.set_title(label)
        self.window_title.set_subtitle(
            f"Image {self.position + 1} of {len(self.items)}"
        )
        self.page_label.set_label(f"{self.position + 1} / {len(self.items)}")
        self.previous_button.set_sensitive(self.position > 0)
        self.next_button.set_sensitive(self.position < len(self.items) - 1)
        self.zoom_level = 1.0
        self._apply_zoom()

    def previous(self) -> None:
        if self.position <= 0:
            return
        self.position -= 1
        self._show_current()

    def next(self) -> None:
        if self.position >= len(self.items) - 1:
            return
        self.position += 1
        self._show_current()

    def zoom_in(self) -> None:
        self.zoom_level = min(4.0, self.zoom_level + 0.5)
        self._apply_zoom()

    def zoom_out(self) -> None:
        self.zoom_level = max(1.0, self.zoom_level - 0.5)
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        if self.texture is None or self.zoom_level <= 1.0:
            self.picture.set_size_request(-1, -1)
            self.picture.set_hexpand(True)
            self.picture.set_vexpand(True)
            self.zoom_label.set_label("Fit")
            return
        self.picture.set_hexpand(False)
        self.picture.set_vexpand(False)
        self.picture.set_size_request(
            round(self.texture.get_width() * self.zoom_level),
            round(self.texture.get_height() * self.zoom_level),
        )
        self.zoom_label.set_label(f"{round(self.zoom_level * 100)}%")

    def _on_picture_pressed(
        self,
        _gesture: Gtk.GestureClick,
        press_count: int,
        _x: float,
        _y: float,
    ) -> None:
        if press_count != 2:
            return
        self.zoom_level = 1.0 if self.zoom_level > 1.0 else 2.0
        self._apply_zoom()

    def _on_scroll(
        self,
        controller: Gtk.EventControllerScroll,
        _dx: float,
        dy: float,
    ) -> bool:
        state = controller.get_current_event_state()
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if dy < 0:
            self.zoom_in()
        else:
            self.zoom_out()
        return True

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.previous()
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.next()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.zoom_in()
                return True
            if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.zoom_out()
                return True
        return False

    def _toggle_fullscreen(self, _button: Gtk.Button) -> None:
        if self.window.is_fullscreen():
            self.window.unfullscreen()
            self._fullscreen_from_viewer = False
            self.fullscreen_button.set_icon_name("view-fullscreen-symbolic")
        else:
            self.window.fullscreen()
            self._fullscreen_from_viewer = True
            self.fullscreen_button.set_icon_name("view-restore-symbolic")

    def _copy_image(self, _button: Gtk.Button) -> None:
        if self.texture is not None:
            self.window.get_clipboard().set_texture(self.texture)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
    ) -> None:
        super().__init__()
        self.key = key

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        content.set_margin_start(8)
        content.set_margin_end(8)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        title = Gtk.Label(label=label, xalign=0)
        title.set_hexpand(True)

        content.append(icon)
        content.append(title)
        self.set_child(content)


class GishehWindow:
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

        self.active_destination = "library"
        self.active_media = "Movies"
        self.active_status = "Watched"
        today = date.today()
        self.calendar_month = today.replace(day=1)
        self.calendar_selected_date = today
        self.calendar_scope = "my"
        self.calendar_media_filter = "all"
        self.calendar_include_watched = False
        self.calendar_include_dropped = False
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
        self.library_selected_id: str | None = self.selected_id
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
            for record in self.records if record.status == "Watchlist"
        }
        self.favorites: set[str] = set()
        self.completed = {
            self._canonical_record_id(record)
            for record in self.records if record.status == "Watched"
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
        self._log_dialog: Adw.AlertDialog | None = None
        self._log_text_view: Gtk.TextView | None = None
        self._simkl_sync_started_at = 0.0
        self._simkl_mutations_inflight: set[str] = set()
        self._simkl_state_generation = 0
        self.color_scheme = "system"
        self.auto_sync = True
        self.auto_calendar_refresh = True
        self.default_media = "Movies"
        self.preferred_view_mode = "list"
        self.state_file = user_state_file()
        self._load_user_state()
        self._apply_color_scheme()
        application_logger().info("گیشه %s started", APP_VERSION)

        self._updating = False
        self._updating_details = False
        self._updating_sidebar_toggle = False
        self._applying_responsive = False
        self.details_open = False
        self._library_results_dirty = False
        self.detail_record_id: str | None = None
        self.current_season_index = 0
        self.current_episode_index = 0
        self.status_rows: dict[str, SidebarRow] = {}
        self._sidebar_docked = True
        self.effective_details_mode = DETAILS_INLINE
        self._responsive_layout_source_id = 0
        self._details_reset_source_id = 0
        self._details_return_focus: Gtk.Widget | None = None
        self._details_revealed_state: bool | None = None
        self._last_applied_details_presentation: tuple[str, bool] | None = None
        self._pending_details_mode: str | None = None
        self._details_chrome_focus_mode: str | None = None
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
        self.window.set_default_size(1100, 700)

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
        self._refresh_results()
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
            GLib.idle_add(self._start_simkl_sync)
        if (
            self.library_mode == LIBRARY_MODE_SIMKL
            and self.auto_calendar_refresh
            and self.simkl_client_id
        ):
            GLib.idle_add(self._start_calendar_refresh, False)

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
            "header_data_status_icon",
            "header_data_status_label",
            "media_switcher",
            "main_menu_button",
            "search_button",
            "destination_list",
            "status_list",
            "collections_list",
            "profile_button",
            "sidebar_profile_avatar",
            "main_workspace",
            "library_pane",
            "eyebrow_label",
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
            "explore_eyebrow_label",
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
        self.main_workspace.remove(self.library_pane)
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
        self.browser_stack.add_named(self.library_pane, "library")
        self.browser_stack.add_named(self.explore_pane, "explore")
        self.browser_stack.set_visible_child_name("library")

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
        self.details_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_LEFT
        )
        self.details_revealer.set_transition_duration(220)
        self.details_revealer.set_reveal_child(False)
        self.details_revealer.set_child(panel_layout)
        self.main_workspace.append(self.details_revealer)

        self.details_overlay_close = Gtk.Button.new_from_icon_name(
            "window-close-symbolic"
        )
        self.details_overlay_close.set_tooltip_text("Close details (Escape)")
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
        mobile_back_button = Gtk.Button.new_from_icon_name(
            "go-previous-symbolic"
        )
        mobile_back_button.set_tooltip_text("Back to content")
        mobile_back_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Back to content"],
        )
        mobile_back_button.connect(
            "clicked", self._on_mobile_title_back
        )
        self.mobile_header_bar.pack_start(mobile_back_button)
        mobile_title = Adw.WindowTitle(title="Details", subtitle="")
        self.mobile_header_bar.set_title_widget(mobile_title)

        mobile_toolbar = Adw.ToolbarView()
        mobile_toolbar.add_top_bar(self.mobile_header_bar)
        mobile_toolbar.set_content(self.mobile_details_host)

        self.mobile_details_page = Adw.NavigationPage.new(
            mobile_toolbar, "Details"
        )
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
            kind = "Poster"
        else:
            candidates = (record.backdrop_file, *record.gallery_backdrops)
            kind = "Backdrop"
        paths = tuple(
            dict.fromkeys(
                path
                for path in candidates
                if path is not None and Path(path).is_file()
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
            self._toast(f"No {mode} available for {record.title}")
            return
        self.media_viewer.open(items, position)

    def _configure_accessibility(self) -> None:
        self.activity_progress.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Watch progress"],
        )

    def _load_user_state(self) -> None:
        try:
            with self.state_file.open(encoding="utf-8") as source:
                payload = json.load(source)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as error:
            print(f"گیشه could not read user state: {error}", file=sys.stderr)
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
            return self._canonical_record_id(record) if record is not None else record_id

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
            for record_id, score in personal_state.get(
                "ratings", self.ratings
            ).items()
            if is_valid_id(record_id) and isinstance(score, int) and 1 <= score <= 10
        }
        self.status_overrides = {
            canonical_saved_id(record_id): status
            for record_id, status in personal_state.get(
                "statusOverrides", {}
            ).items()
            if is_valid_id(record_id) and status in LIBRARY_FILTERS
        }
        if not self.simkl_connected:
            self.episode_status_overrides = {
                str(key): value
                for key, value in personal_state.get(
                    "episodeStatusOverrides", {}
                ).items()
                if isinstance(value, bool)
                and is_valid_id(str(key).split("/", 1)[0])
            }
            self.episode_watched_at = {
                str(key): str(value)
                for key, value in personal_state.get(
                    "episodeWatchedAt", {}
                ).items()
                if isinstance(value, str)
                and is_valid_id(str(key).split("/", 1)[0])
            }
        self.title_watched_at = {
            canonical_saved_id(key): str(value)
            for key, value in personal_state.get("titleWatchedAt", {}).items()
            if isinstance(value, str) and is_valid_id(str(key))
        }
        if isinstance(preferences, dict):
            color_scheme = preferences.get("colorScheme")
            if color_scheme in COLOR_SCHEMES:
                self.color_scheme = str(color_scheme)
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

    def _save_user_state(self) -> None:
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
            payload["localProfile"] = personal_state
        payload["localLibrary"] = [
            title_record_to_mapping(record)
            for _record_id, record in sorted(
                getattr(self, "local_library_records", {}).items()
            )
        ]
        payload["preferences"] = {
            "colorScheme": self.color_scheme,
            "autoSync": self.auto_sync,
            "autoCalendarRefresh": getattr(self, "auto_calendar_refresh", True),
            "defaultMedia": self.default_media,
            "libraryView": self.preferred_view_mode,
            "libraryMode": getattr(self, "library_mode", LIBRARY_MODE_LOCAL),
        }
        try:
            write_state(payload, self.state_file)
        except OSError as error:
            print(f"گیشه could not save user state: {error}", file=sys.stderr)

    def _build_header_controls(self) -> None:
        self.sidebar_toggle_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic"
        )
        self.sidebar_toggle_button.set_active(True)
        self.sidebar_toggle_button.set_tooltip_text("Hide sidebar (Ctrl+B)")
        self.sidebar_toggle_button.add_css_class("flat")
        self.sidebar_toggle_button.add_css_class("circular")
        self.sidebar_toggle_button.connect(
            "toggled",
            self._on_sidebar_toggled,
        )
        self.header_bar.pack_start(self.sidebar_toggle_button)

        for media_type in MEDIA_TYPES:
            self.media_switcher.add(
                Adw.Toggle(name=media_type.lower(), label=media_type)
            )
        self.media_switcher.set_active_name(self.active_media.lower())

        self.view_switcher.add(
            Adw.Toggle(
                name="list",
                icon_name="view-list-symbolic",
                tooltip="List view",
            )
        )
        self.view_switcher.add(
            Adw.Toggle(
                name="grid",
                icon_name="view-grid-symbolic",
                tooltip="Grid view",
            )
        )
        self.view_switcher.set_active_name(self.view_mode)

        self.rating_buttons: dict[int, Gtk.ToggleButton] = {}
        rating_leader: Gtk.ToggleButton | None = None
        for score in range(1, 11):
            button = Gtk.ToggleButton(label=str(score))
            button.set_tooltip_text(f"{score} out of 10")
            if rating_leader is None:
                rating_leader = button
            else:
                button.set_group(rating_leader)
            button.connect("toggled", self._on_rating_button_toggled, score)
            self.rating_grid.attach(button, (score - 1) % 5, (score - 1) // 5, 1, 1)
            self.rating_buttons[score] = button

        sort_labels = [label for _key, label in SORT_OPTIONS]
        self.sort_dropdown.set_model(Gtk.StringList.new(sort_labels))
        self.sort_dropdown.set_selected(0)

        explore_sort_labels = [label for _key, label in EXPLORE_SORT_OPTIONS]
        self.explore_sort_dropdown.set_model(Gtk.StringList.new(explore_sort_labels))
        self.explore_sort_dropdown.set_selected(0)
        self.explore_period_dropdown.set_model(
            Gtk.StringList.new(list(EXPLORE_PERIODS))
        )
        self.explore_period_dropdown.set_selected(0)

        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("Application Log", "app.logs")
        menu.append("Credits & Data Sources", "app.credits")
        menu.append("About گیشه", "app.about")
        menu.append("Quit", "app.quit")
        self.main_menu_button.set_menu_model(menu)

    def _build_sidebar(self) -> None:
        self.library_row = SidebarRow(
            "library",
            "Library",
            "folder-symbolic",
        )
        self.explore_row = SidebarRow(
            "explore",
            "Explore",
            "find-location-symbolic",
        )
        self.calendar_row = SidebarRow(
            "calendar",
            "Calendar",
            "x-office-calendar-symbolic",
        )
        self.destination_list.append(self.library_row)
        self.destination_list.append(self.explore_row)
        self.destination_list.append(self.calendar_row)

        for status in STATUSES:
            row = SidebarRow(
                status,
                status,
                STATUS_ICONS[status],
            )
            self.status_rows[status] = row
            self.status_list.append(row)

        self._updating = True
        self.destination_list.select_row(self.library_row)
        self.status_list.select_row(self.status_rows[self.active_status])
        self._updating = False

        self.list_rows: dict[str, SidebarRow] = {}
        for label, icon_name in LISTS:
            row = SidebarRow(
                label,
                label,
                icon_name,
            )
            self.list_rows[label] = row
            self.collections_list.append(row)
        self.watchlist_row = self.list_rows["Watchlist"]

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
            title="No titles found",
            description="Try a different search term or clear the genre filter.",
        )
        self.empty_page.add_css_class("empty-status")
        clear_button = Gtk.Button(label="Clear filters")
        clear_button.set_halign(Gtk.Align.CENTER)
        clear_button.add_css_class("pill")
        clear_button.connect("clicked", self._on_clear_filters)
        self.empty_page.set_child(clear_button)

    def _build_explore_view(self) -> None:
        self.explore_empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="Nothing new here yet",
            description="Try another search, period, or genre.",
        )
        self.explore_empty_page.add_css_class("empty-status")
        reset_button = Gtk.Button(label="Reset Explore filters")
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
        loading_label = Gtk.Label(label="Loading more from TMDB…")
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
        spinner.set_tooltip_text("Loading recommendations from TMDB")
        status.append(spinner)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Loading recommendations", xalign=0)
        title.add_css_class("heading")
        subtitle = Gtk.Label(
            label="Finding films and series you might enjoy…", xalign=0
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
        eyebrow = Gtk.Label(label="Browse / Simkl", xalign=0)
        eyebrow.add_css_class("caption")
        eyebrow.add_css_class("dim-label")
        header.append(eyebrow)
        title = Gtk.Label(label="Calendar", xalign=0)
        title.add_css_class("title-1")
        header.append(title)

        controls = Adw.WrapBox(child_spacing=6, line_spacing=6)
        controls.set_hexpand(True)
        self.calendar_scope_switcher = Adw.ToggleGroup()
        self.calendar_scope_switcher.add(Adw.Toggle(name="my", label="My Calendar"))
        self.calendar_scope_switcher.add(Adw.Toggle(name="all", label="All Releases"))
        self.calendar_scope_switcher.set_active_name(self.calendar_scope)
        self.calendar_scope_switcher.set_tooltip_text("Calendar source")
        controls.append(self.calendar_scope_switcher)

        self.calendar_media_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(["All", "Movies", "Shows", "Anime"])
        )
        self.calendar_media_dropdown.set_tooltip_text("Filter releases by media type")
        controls.append(self.calendar_media_dropdown)

        self.calendar_filter_button = Gtk.MenuButton(
            icon_name="view-more-symbolic",
            tooltip_text="Calendar status filters",
        )
        filter_popover = Gtk.Popover()
        filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        filter_box.set_margin_top(12)
        filter_box.set_margin_bottom(12)
        filter_box.set_margin_start(12)
        filter_box.set_margin_end(12)
        self.calendar_watched_check = Gtk.CheckButton(label="Show watched")
        self.calendar_dropped_check = Gtk.CheckButton(label="Show dropped")
        filter_box.append(self.calendar_watched_check)
        filter_box.append(self.calendar_dropped_check)
        filter_popover.set_child(filter_box)
        self.calendar_filter_button.set_popover(filter_popover)
        controls.append(self.calendar_filter_button)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls.append(spacer)
        self.calendar_previous_button = Gtk.Button(
            icon_name="go-previous-symbolic", tooltip_text="Previous month"
        )
        self.calendar_today_button = Gtk.Button(label="Today", tooltip_text="Go to today")
        self.calendar_next_button = Gtk.Button(
            icon_name="go-next-symbolic", tooltip_text="Next month"
        )
        self.calendar_refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Refresh Calendar"
        )
        for button in (
            self.calendar_previous_button, self.calendar_today_button,
            self.calendar_next_button, self.calendar_refresh_button,
        ):
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
        self.calendar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.calendar_scroller.set_vexpand(True)
        self.calendar_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.calendar_content.set_margin_top(16)
        self.calendar_content.set_margin_bottom(24)
        self.calendar_content.set_margin_start(24)
        self.calendar_content.set_margin_end(24)
        self.calendar_scroller.set_child(self.calendar_content)
        self.calendar_pane.append(self.calendar_scroller)

        self.calendar_scope_switcher.connect(
            "notify::active-name", self._on_calendar_scope_changed
        )
        self.calendar_media_dropdown.connect(
            "notify::selected", self._on_calendar_media_changed
        )
        self.calendar_watched_check.connect("toggled", self._on_calendar_filter_changed)
        self.calendar_dropped_check.connect("toggled", self._on_calendar_filter_changed)
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

    def _start_calendar_refresh(self, force: bool = False) -> bool:
        if self._calendar_refresh_inflight:
            return GLib.SOURCE_REMOVE
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
                snapshots: list[simkl_client.CalendarSnapshot] = []
                errors: list[str] = []
                for media in ("movies", "shows", "anime"):
                    try:
                        snapshots.append(simkl_client.fetch_calendar(
                            media,
                            client_id=client_id or "",
                            year=year,
                            month=month,
                            display_timezone=display_timezone,
                            force=force,
                        ))
                    except simkl_client.SimklError as error:
                        errors.append(str(error))
                if not snapshots:
                    raise simkl_client.SimklError(
                        errors[0] if errors else "Calendar is unavailable."
                    )
                result = simkl_client.merge_calendar_snapshots(snapshots)
                warning = errors[0] if errors else None
                GLib.idle_add(
                    self._finish_calendar_refresh, generation, result, warning
                )
            except simkl_client.SimklError as error:
                GLib.idle_add(
                    self._finish_calendar_refresh, generation, None, str(error)
                )

        threading.Thread(target=worker, name="simkl-calendar", daemon=True).start()
        return GLib.SOURCE_REMOVE

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
            self.settings_calendar_cache_row.set_subtitle(self._calendar_cache_subtitle())
        if error:
            self._app_log("Calendar refresh failed: %s", error, level=logging.WARNING)
            if self.calendar_snapshot is not None:
                self._toast("Calendar refresh failed; showing cached schedule")
        self._render_calendar(error=error)
        return GLib.SOURCE_REMOVE

    def _reset_calendar_timeline(self) -> None:
        self.calendar_timeline_limit = CALENDAR_TIMELINE_PAGE_SIZE

    def _on_calendar_scope_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        self.calendar_scope = group.get_active_name() or "my"
        self.calendar_filter_button.set_visible(self.calendar_scope == "my")
        self._reset_calendar_timeline()
        self._render_calendar()

    def _on_calendar_media_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        self.calendar_media_filter = ("all", "movies", "shows", "anime")[
            dropdown.get_selected()
        ]
        self._reset_calendar_timeline()
        self._render_calendar()

    def _on_calendar_filter_changed(self, _button: Gtk.CheckButton) -> None:
        self.calendar_include_watched = self.calendar_watched_check.get_active()
        self.calendar_include_dropped = self.calendar_dropped_check.get_active()
        self._reset_calendar_timeline()
        self._render_calendar()

    @staticmethod
    def _shift_month(month: date, offset: int) -> date:
        index = month.year * 12 + month.month - 1 + offset
        return date(index // 12, index % 12 + 1, 1)

    def _on_calendar_previous(self, _button: Gtk.Button) -> None:
        self.calendar_month = self._shift_month(self.calendar_month, -1)
        self.calendar_selected_date = self.calendar_month
        self._reset_calendar_timeline()
        self.calendar_snapshot = None
        self._start_calendar_refresh(False)

    def _on_calendar_next(self, _button: Gtk.Button) -> None:
        self.calendar_month = self._shift_month(self.calendar_month, 1)
        self.calendar_selected_date = self.calendar_month
        self._reset_calendar_timeline()
        self.calendar_snapshot = None
        self._start_calendar_refresh(False)

    def _on_calendar_today(self, _button: Gtk.Button) -> None:
        today = date.today()
        month_changed = self.calendar_month != today.replace(day=1)
        self.calendar_month = today.replace(day=1)
        self.calendar_selected_date = today
        self._reset_calendar_timeline()
        if month_changed:
            self.calendar_snapshot = None
            self._start_calendar_refresh(False)
        else:
            self._render_calendar()

    def _calendar_record(
        self, event: simkl_client.CalendarEvent
    ) -> TitleRecord | None:
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
                    item for item in (*self.records, *self.explore_records)
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
                    item for item in candidates
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
                item for item in candidates
                if " ".join(item.title.casefold().split()) == normalized_title
                and (
                    (group == "movies" and item.media_type == "Movies")
                    or (group == "shows" and item.media_type == "Shows")
                    or (group == "anime" and item.media_type == "Anime")
                )
            ),
            None,
        )

    def _calendar_events(self) -> tuple[simkl_client.CalendarEvent, ...]:
        if self.calendar_snapshot is None:
            return ()
        visible: list[simkl_client.CalendarEvent] = []
        for event in self.calendar_snapshot.events:
            moment = event.local_datetime
            if moment is None or (
                moment.year != self.calendar_month.year
                or moment.month != self.calendar_month.month
            ):
                continue
            if self.calendar_media_filter != "all" and event.media_type != self.calendar_media_filter:
                continue
            if self.calendar_scope == "my":
                record = self._calendar_record(event)
                if record is None or not self._calendar_record_is_in_library(record):
                    continue
                status = self._effective_status(record)
                if status == "Watched" and not self.calendar_include_watched:
                    continue
                if status == "Dropped" and not self.calendar_include_dropped:
                    continue
                if status not in {"Watching", "Watchlist", "On Hold", "Watched", "Dropped"}:
                    continue
            visible.append(event)
        return tuple(visible)

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
            if self.calendar_media_filter != "all" and {
                "Movies": "movies", "Shows": "shows", "Anime": "anime"
            }.get(record.media_type) != self.calendar_media_filter:
                continue
            status = self._effective_status(record)
            if status == "Watched" and not self.calendar_include_watched:
                continue
            if status == "Dropped" and not self.calendar_include_dropped:
                continue
            if status in {"Watching", "Watchlist", "On Hold", "Watched", "Dropped"}:
                seen.add(self._canonical_record_id(record))
        return len(seen)

    @staticmethod
    def _calendar_events_by_day(
        events: tuple[simkl_client.CalendarEvent, ...],
    ) -> tuple[tuple[date, tuple[simkl_client.CalendarEvent, ...]], ...]:
        """Return local Calendar events in chronological, day-sized groups."""
        ordered = sorted(
            (event for event in events if event.local_datetime is not None),
            key=lambda event: (
                event.local_datetime,
                event.title.title.casefold(),
                event.simkl_id,
            ),
        )
        grouped: list[tuple[date, tuple[simkl_client.CalendarEvent, ...]]] = []
        for event in ordered:
            event_day = event.local_datetime.date()
            if grouped and grouped[-1][0] == event_day:
                grouped[-1] = (event_day, (*grouped[-1][1], event))
            else:
                grouped.append((event_day, (event,)))
        return tuple(grouped)

    @staticmethod
    def _calendar_day_heading(day: date, *, today: date | None = None) -> str:
        reference = today or date.today()
        relative = {
            -1: "Yesterday",
            0: "Today",
            1: "Tomorrow",
        }.get((day - reference).days)
        absolute = day.strftime("%B %-d, %Y")
        week = day.isocalendar().week
        parts = [absolute, f"Week {week}", day.strftime("%A")]
        if relative:
            parts.insert(0, relative)
        return " • ".join(parts)

    @staticmethod
    def _calendar_day_summary(
        events: tuple[simkl_client.CalendarEvent, ...],
    ) -> str:
        count = len(events)
        minutes = sum(
            runtime_minutes(event.title.runtime or "") for event in events
        )
        releases = f"{count} release{'s' if count != 1 else ''}"
        if not minutes:
            return releases
        hours, remainder = divmod(minutes, 60)
        duration = (
            f"{hours}h {remainder:02d}m" if hours and remainder
            else f"{hours}h" if hours
            else f"{remainder}m"
        )
        return f"{releases} • {duration}"

    @staticmethod
    def _calendar_timeline_page(
        groups: tuple[
            tuple[date, tuple[simkl_client.CalendarEvent, ...]], ...
        ],
        limit: int,
    ) -> tuple[
        tuple[tuple[date, tuple[simkl_client.CalendarEvent, ...]], ...],
        int,
    ]:
        """Select complete day groups up to a progressive event limit."""
        visible: list[tuple[date, tuple[simkl_client.CalendarEvent, ...]]] = []
        shown = 0
        for group in groups:
            if shown >= limit:
                break
            visible.append(group)
            shown += len(group[1])
        return tuple(visible), shown

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
        self, icon: str, title: str, description: str,
        action: str | None = None, callback: Any = None,
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
            clock = Gtk.Image.new_from_icon_name("appointment-soon-symbolic")
            clock.add_css_class("dim-label")
            header.append(clock)
            heading = Gtk.Label(
                label=self._calendar_day_heading(day),
                xalign=0,
            )
            heading.set_hexpand(True)
            heading.set_wrap(True)
            heading.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            heading.add_css_class("heading")
            if day == date.today():
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
            load_more = Gtk.Button(
                label=f"Load more releases ({remaining} remaining)"
            )
            load_more.set_halign(Gtk.Align.CENTER)
            load_more.add_css_class("pill")
            load_more.connect("clicked", self._on_calendar_load_more)
            timeline.append(load_more)
        self.calendar_timeline_visible_count = shown
        return timeline

    def _on_calendar_load_more(self, _button: Gtk.Button) -> None:
        self.calendar_timeline_limit = (
            getattr(self, "calendar_timeline_limit", CALENDAR_TIMELINE_PAGE_SIZE)
            + CALENDAR_TIMELINE_PAGE_SIZE
        )
        self._render_calendar()

    def _calendar_event_row(
        self, event: simkl_client.CalendarEvent
    ) -> Gtk.Box:
        record = self._calendar_record(event)
        library_record = (
            record
            if record is not None and self._calendar_record_is_in_library(record)
            else None
        )
        row = Gtk.Box(spacing=12)
        row.add_css_class("movie-row-content")
        if record is not None:
            row.append(self._create_poster_overlay(record, 76, 114))
        else:
            row.append(self._calendar_poster_overlay(event.title, 76, 114))

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)

        top = Gtk.CenterBox()
        media_label = {
            "movies": "Movie",
            "shows": "Show",
            "anime": "Anime",
        }[event.media_type]
        schedule = media_label
        if event.local_datetime:
            schedule = f"{media_label} · {event.local_datetime.strftime('%H:%M')}"
        schedule_label = Gtk.Label(label=schedule, xalign=0)
        schedule_label.add_css_class("caption")
        schedule_label.add_css_class("dim-label")
        top.set_start_widget(schedule_label)
        score = (
            record.rating
            if record is not None
            else event.title.rating
        )
        if score is not None:
            rating = Gtk.Label(label=f"★ {score:.1f}")
            rating.add_css_class("caption")
            rating.add_css_class("numeric")
            top.set_end_widget(rating)
        text.append(top)

        title_label = Gtk.Label(label=event.title.title, xalign=0)
        self._configure_bounded_card_label(title_label, 22, lines=2)
        title_label.add_css_class("title-3")
        title_label.set_tooltip_text(event.title.title)
        text.append(title_label)

        episode_details: list[str] = []
        if event.episode is not None:
            if event.season is not None:
                episode_details.append(
                    f"S{event.season:02d}E{event.episode_number:02d}"
                )
            else:
                episode_details.append(f"E{event.episode_number:02d}")
            if event.episode_title:
                episode_details.append(event.episode_title)
        elif event.title.dvd_date:
            episode_details.append(f"Home release {event.title.dvd_date}")
        subtitle = Gtk.Label(label=" · ".join(episode_details), xalign=0)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_lines(2)
        subtitle.set_wrap(True)
        subtitle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("body")
        if episode_details:
            text.append(subtitle)

        original_title = event.title.original_title
        if original_title and original_title.casefold() == event.title.title.casefold():
            original_title = None
        metadata_values = [
            value
            for value in (
                str(record.year) if record is not None else None,
                event.title.network,
                event.title.runtime,
                original_title,
            )
            if value
        ]
        if metadata_values:
            metadata = Gtk.Label(label="  ·  ".join(metadata_values), xalign=0)
            metadata.set_ellipsize(Pango.EllipsizeMode.END)
            metadata.add_css_class("caption")
            metadata.add_css_class("dim-label")
            text.append(metadata)

        badges = Adw.WrapBox(child_spacing=5, line_spacing=5)
        badge_values: list[str] = []
        if event.season == 1 and event.episode_number == 1:
            badge_values.append("Premiere")
        if event.finale_label:
            badge_values.append(event.finale_label)
        if library_record is not None:
            badge_values.append(self._effective_status(library_record))
        for value in badge_values:
            badge = Gtk.Label(label=value)
            badge.add_css_class("status-pill")
            badges.append(badge)
        if badge_values:
            text.append(badges)
        row.append(text)
        if library_record is None and self._simkl_writable():
            add = Gtk.Button(icon_name="bookmark-new-symbolic", tooltip_text="Add to Watchlist")
            add.set_valign(Gtk.Align.START)
            add.add_css_class("flat")
            add.add_css_class("circular")
            add.connect("clicked", lambda button: self._add_calendar_watchlist(button, event))
            row.append(add)
        return row

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
            [Gtk.AccessibleProperty.LABEL], [f"Poster artwork for {title.title}"]
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
            GLib.idle_add(finish, path)

        def finish(path: str | None) -> bool:
            self._calendar_posters_loading.discard(title.simkl_id)
            if path and picture.get_root() is not None:
                picture.set_filename(path)
            return GLib.SOURCE_REMOVE

        threading.Thread(
            target=worker,
            name=f"calendar-poster-{title.simkl_id}",
            daemon=True,
        ).start()
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
            self._app_log("Could not open Calendar link: %s", error, level=logging.WARNING)
            self._toast("Could not open this Simkl page")

    @staticmethod
    def _title_external_url(record: TitleRecord) -> str | None:
        if record.tmdb_id is None:
            return None
        namespace = (
            "movie"
            if record.tmdb_media_type == "movie" or record.media_type == "Movies"
            else "tv"
        )
        return f"https://www.themoviedb.org/{namespace}/{record.tmdb_id}"

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
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("open", "Open in Browser")
        dialog.set_close_response("cancel")
        dialog.set_default_response("open")
        dialog.set_response_appearance(
            "open", Adw.ResponseAppearance.SUGGESTED
        )

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
                self._toast("Could not open the link in your browser")

        dialog.connect("response", respond)
        dialog.present(self.window)

    def _on_detail_title_released(
        self,
        _gesture: Gtk.GestureClick,
        _press_count: int,
        _x: float,
        _y: float,
    ) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is None:
            return
        uri = self._title_external_url(record)
        if uri is None:
            self._toast("No external page is available for this title")
            return
        self._open_external_uri_with_warning(
            uri,
            heading="Open an external link?",
            body=(
                f"گیشه will open the TMDB page for “{record.title}” "
                "in your default web browser."
            ),
        )

    def _add_calendar_watchlist(
        self, button: Gtk.Button, event: simkl_client.CalendarEvent
    ) -> None:
        if not self._simkl_writable():
            self._toast("Connect Simkl to add this title")
            return
        button.set_sensitive(False)
        group = {"movies": "movies", "shows": "shows", "anime": "anime"}[event.media_type]
        self._run_simkl_mutation(
            f"calendar-{group}-{event.simkl_id}:watchlist",
            lambda: self._checked_simkl_write(
                lambda: simkl_client.set_list_status(
                    self.simkl_client_id or "", self.simkl_token or "",
                    group, {"simkl": event.simkl_id}, "plantowatch",
                )
            ),
            lambda: self._start_simkl_sync(),
            "Added to Simkl watchlist",
        )

    def _render_calendar(self, *, loading: bool = False, error: str | None = None) -> None:
        if not hasattr(self, "calendar_content"):
            return
        self._clear_container(self.calendar_content)
        self.calendar_month_label.set_label(self.calendar_month.strftime("%B %Y"))
        snapshot = self.calendar_snapshot
        if snapshot is not None:
            updated = snapshot.fetched_at.astimezone().strftime("Updated %b %-d, %H:%M")
            if snapshot.stale:
                updated = f"Showing cached schedule · {updated}"
            self.calendar_updated_label.set_label(updated)
            self.calendar_updated_label.set_tooltip_text(self._calendar_cache_subtitle())
        else:
            self.calendar_updated_label.set_label("")
        if self.library_mode == LIBRARY_MODE_LOCAL:
            action = "Use Simkl" if self.simkl_client_id else None
            callback = (
                (lambda *_args: self.set_library_mode(LIBRARY_MODE_SIMKL))
                if self.simkl_client_id
                else None
            )
            self.calendar_content.append(self._calendar_status(
                "drive-harddisk-symbolic", "Local-first mode is active",
                "Calendar downloads use Simkl. Your local library remains fully "
                "available without connecting an account.",
                action, callback,
            ))
            return
        if not self.simkl_client_id:
            self.calendar_content.append(self._calendar_status(
                "dialog-error-symbolic", "Simkl integration is unavailable",
                "This build does not include گیشه's public Simkl application ID.",
            ))
            return
        if loading and snapshot is None:
            self.calendar_content.append(self._calendar_skeleton())
            return
        if snapshot is None:
            self.calendar_content.append(self._calendar_status(
                "network-offline-symbolic", "Calendar is unavailable",
                error or "No cached schedule is available. Check your connection and try again.",
                "Retry", lambda *_args: self._start_calendar_refresh(True),
            ))
            return
        if snapshot.unavailable:
            self.calendar_content.append(self._calendar_status(
                "x-office-calendar-symbolic", "Schedule not published",
                "Simkl has not published this month yet.",
            ))
            return
        events = self._calendar_events()
        if self.calendar_scope == "my" and not events:
            eligible_count = self._calendar_eligible_library_count()
            self.calendar_content.append(self._calendar_status(
                "bookmark-new-symbolic", "Nothing scheduled in My Calendar",
                (
                    f"Simkl has no published events this month for the {eligible_count} "
                    "matching Library title"
                    f"{'s' if eligible_count != 1 else ''}. Watching, Watchlist, "
                    "and On Hold titles appear as soon as Simkl schedules them."
                ),
                "Open Explore", self._open_explore_from_calendar,
            ))
            return
        if not events:
            self.calendar_content.append(self._calendar_status(
                "x-office-calendar-symbolic", "Nothing scheduled",
                "No releases match the selected month and filters.",
            ))
            return
        self.calendar_timeline_view = self._calendar_timeline(events)
        self.calendar_content.append(self.calendar_timeline_view)

    def _build_profile_view(self) -> None:
        self.profile_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.profile_pane.add_css_class("main-content-pane")

        self.profile_scroller = Gtk.ScrolledWindow()
        self.profile_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.profile_scroller.set_vexpand(True)
        self.profile_pane.append(self.profile_scroller)

        clamp = Adw.Clamp(maximum_size=1040, tightening_threshold=760)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(40)
        clamp.set_margin_start(24)
        clamp.set_margin_end(24)
        self.profile_scroller.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(content)

        self.profile_statistics_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
        )
        content.append(self.profile_statistics_host)
        self._update_profile_identity()

        self.browser_stack.add_named(self.profile_pane, "profile")
        self._refresh_profile()

    def _build_settings_dialog(self) -> None:
        """Build a native searchable GNOME preferences dialog."""
        self.settings_dialog = Adw.PreferencesDialog(title="Preferences")
        self.settings_dialog.set_search_enabled(True)

        general_page = Adw.PreferencesPage(
            title="General",
            icon_name="applications-system-symbolic",
        )
        services_page = Adw.PreferencesPage(
            title="Services",
            icon_name="network-workgroup-symbolic",
        )

        ownership = Adw.PreferencesGroup(
            title="Data ownership",
            description="Choose where گیشه keeps your personal library state.",
        )
        self.settings_library_mode_row = Adw.ActionRow(title="Library mode")
        self.settings_library_mode_button = Gtk.Button(label="Change…")
        self.settings_library_mode_button.set_valign(Gtk.Align.CENTER)
        self.settings_library_mode_button.connect(
            "clicked", self._on_change_library_mode_clicked
        )
        self.settings_library_mode_row.add_suffix(
            self.settings_library_mode_button
        )
        ownership.add(self.settings_library_mode_row)
        general_page.add(ownership)

        appearance = Adw.PreferencesGroup(
            title="Appearance",
            description="Choose how گیشه looks on this device.",
        )
        self.settings_color_scheme_row = Adw.ComboRow(
            title="Color scheme",
            subtitle="Use the system style or override it for گیشه.",
        )
        self.settings_color_scheme_row.set_model(
            Gtk.StringList.new(list(COLOR_SCHEME_LABELS))
        )
        self.settings_color_scheme_row.set_selected(
            COLOR_SCHEMES.index(self.color_scheme)
        )
        self.settings_color_scheme_row.connect(
            "notify::selected", self._on_settings_color_scheme_changed
        )
        appearance.add(self.settings_color_scheme_row)

        general_page.add(appearance)

        library = Adw.PreferencesGroup(
            title="Library",
            description="Set the view گیشه uses when it starts.",
        )
        self.settings_media_row = Adw.ComboRow(
            title="Default media type",
            subtitle="Open this catalog first on the next launch.",
        )
        self.settings_media_row.set_model(Gtk.StringList.new(list(MEDIA_TYPES)))
        self.settings_media_row.set_selected(MEDIA_TYPES.index(self.default_media))
        self.settings_media_row.connect(
            "notify::selected", self._on_settings_default_media_changed
        )
        library.add(self.settings_media_row)

        self.settings_view_row = Adw.ComboRow(
            title="Library layout",
            subtitle="Choose between the compact list and poster grid.",
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
            title="Accounts &amp; Sync",
            description="گیشه uses Simkl for your library and TMDB for metadata.",
        )
        self.settings_auto_sync_row = Adw.SwitchRow(
            title="Sync Simkl on startup",
            subtitle="Refresh cloud library state whenever گیشه starts.",
        )
        self.settings_auto_sync_row.set_active(self.auto_sync)
        self.settings_auto_sync_row.connect(
            "notify::active", self._on_settings_auto_sync_changed
        )
        accounts.add(self.settings_auto_sync_row)

        self.settings_auto_calendar_row = Adw.SwitchRow(
            title="Refresh Calendar automatically",
            subtitle="Use a fresh local schedule cache and update it when needed.",
        )
        self.settings_auto_calendar_row.set_active(
            getattr(self, "auto_calendar_refresh", True)
        )
        self.settings_auto_calendar_row.connect(
            "notify::active", self._on_settings_auto_calendar_changed
        )
        accounts.add(self.settings_auto_calendar_row)

        self.settings_simkl_row = Adw.ActionRow(title="Simkl")
        self.settings_simkl_button = Gtk.Button()
        self.settings_simkl_button.set_valign(Gtk.Align.CENTER)
        self.settings_simkl_button.connect("clicked", self._on_simkl_button_clicked)
        self.settings_simkl_disconnect_button = Gtk.Button.new_from_icon_name(
            "system-log-out-symbolic"
        )
        self.settings_simkl_disconnect_button.set_valign(Gtk.Align.CENTER)
        self.settings_simkl_disconnect_button.set_tooltip_text("Disconnect Simkl")
        self.settings_simkl_disconnect_button.add_css_class("flat")
        self.settings_simkl_disconnect_button.add_css_class("circular")
        self.settings_simkl_disconnect_button.connect(
            "clicked", self._on_simkl_disconnect_clicked
        )
        self.settings_simkl_row.add_suffix(self.settings_simkl_button)
        self.settings_simkl_row.add_suffix(self.settings_simkl_disconnect_button)
        accounts.add(self.settings_simkl_row)

        self.settings_tmdb_row = Adw.ActionRow(title="TMDB")
        self.settings_tmdb_button = Gtk.Button()
        self.settings_tmdb_button.set_valign(Gtk.Align.CENTER)
        self.settings_tmdb_button.connect(
            "clicked", self._on_tmdb_settings_clicked
        )
        self.settings_tmdb_disconnect_button = Gtk.Button.new_from_icon_name(
            "edit-delete-symbolic"
        )
        self.settings_tmdb_disconnect_button.set_valign(Gtk.Align.CENTER)
        self.settings_tmdb_disconnect_button.set_tooltip_text("Remove TMDB token")
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
            title="Data &amp; Diagnostics",
            description="Manage reproducible downloads and troubleshooting information.",
        )
        self.settings_cache_row = Adw.ActionRow(
            title="Downloaded TMDB data",
            subtitle="Posters, backdrops, cast photos and metadata cache.",
        )
        clear_cache = Gtk.Button(label="Clear Cache")
        clear_cache.set_valign(Gtk.Align.CENTER)
        clear_cache.connect("clicked", self._on_clear_cache_clicked)
        self.settings_cache_row.add_suffix(clear_cache)
        self.settings_cache_row.set_activatable_widget(clear_cache)
        data.add(self.settings_cache_row)

        self.settings_calendar_cache_row = Adw.ActionRow(
            title="Calendar cache",
            subtitle=self._calendar_cache_subtitle(),
        )
        clear_calendar_cache = Gtk.Button(label="Clear Cache")
        clear_calendar_cache.set_valign(Gtk.Align.CENTER)
        clear_calendar_cache.connect(
            "clicked", self._on_clear_calendar_cache_clicked
        )
        self.settings_calendar_cache_row.add_suffix(clear_calendar_cache)
        self.settings_calendar_cache_row.set_activatable_widget(clear_calendar_cache)
        data.add(self.settings_calendar_cache_row)

        log_row = Adw.ActionRow(
            title="Application Log",
            subtitle="Review sync, loading and recoverable error messages.",
        )
        log_button = Gtk.Button(label="Open Log")
        log_button.set_valign(Gtk.Align.CENTER)
        log_button.connect("clicked", lambda *_args: self.show_application_log())
        log_row.add_suffix(log_button)
        log_row.set_activatable_widget(log_button)
        data.add(log_row)
        services_page.add(data)

        reset_group = Adw.PreferencesGroup(
            title="Reset",
            description="Erase local گیشه data and return to first-run setup.",
        )
        self.settings_factory_reset_row = Adw.ActionRow(
            title="Reset گیشه",
            subtitle="Delete your library, preferences, accounts, caches and logs.",
        )
        self.settings_factory_reset_button = Gtk.Button(label="Reset…")
        self.settings_factory_reset_button.set_valign(Gtk.Align.CENTER)
        self.settings_factory_reset_button.add_css_class("destructive-action")
        self.settings_factory_reset_button.connect(
            "clicked", self._on_factory_reset_clicked
        )
        self.settings_factory_reset_row.add_suffix(
            self.settings_factory_reset_button
        )
        self.settings_factory_reset_row.set_activatable_widget(
            self.settings_factory_reset_button
        )
        reset_group.add(self.settings_factory_reset_row)
        services_page.add(reset_group)

        self._update_settings_account_rows()
        self.settings_dialog.add(general_page)
        self.settings_dialog.add(services_page)

    def _apply_color_scheme(self) -> None:
        schemes = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        Adw.StyleManager.get_default().set_color_scheme(
            schemes.get(self.color_scheme, Adw.ColorScheme.DEFAULT)
        )

    def _update_settings_account_rows(self, *, syncing: bool = False) -> None:
        if not hasattr(self, "settings_simkl_row"):
            return
        local_mode = (
            getattr(self, "library_mode", LIBRARY_MODE_LOCAL)
            == LIBRARY_MODE_LOCAL
        )
        if hasattr(self, "settings_library_mode_row"):
            self.settings_library_mode_row.set_subtitle(
                "Local-first · Personal data stays on this device"
                if local_mode
                else "Simkl sync · Simkl manages lists, ratings and watch history"
            )
        if local_mode:
            simkl_subtitle = "Not active · Local-first mode is managing this library"
        elif self.simkl_connected:
            simkl_subtitle = "Connected · Library and watch state sync enabled"
        elif getattr(self, "simkl_client_id", None):
            simkl_subtitle = "Ready to connect · Sign in with a Simkl PIN"
        else:
            simkl_subtitle = "Unavailable · This build has no Simkl application ID"
        self.settings_simkl_row.set_subtitle(simkl_subtitle)
        self.settings_simkl_button.set_label(
            "Syncing…"
            if syncing
            else (
                "Use Simkl"
                if local_mode and getattr(self, "simkl_client_id", None)
                else "Unavailable"
                if local_mode
                else "Sync Now"
                if self.simkl_connected
                else (
                    "Connect"
                    if getattr(self, "simkl_client_id", None)
                    else "Unavailable"
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
            tmdb_subtitle = "Connected · Credential provided by this build"
        elif tmdb_source == "environment":
            tmdb_subtitle = "Connected · Developer environment override"
        elif tmdb_source == "user":
            tmdb_subtitle = "Connected · Developer token stored for this user"
        else:
            tmdb_subtitle = "Unavailable · This build has no TMDB credential"
        self.settings_tmdb_row.set_subtitle(tmdb_subtitle)
        self.settings_tmdb_button.set_label(
            "Data Source"
            if tmdb_source in {"bundled", "environment"}
            else ("Change Token" if tmdb_source == "user" else "Developer Setup")
        )
        self.settings_tmdb_disconnect_button.set_visible(tmdb_source == "user")

    def _on_settings_color_scheme_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        self.color_scheme = COLOR_SCHEMES[row.get_selected()]
        self._apply_color_scheme()
        self._save_user_state()

    def _on_change_library_mode_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Choose how your library is managed",
            body=(
                "Local-first keeps lists, ratings and watch history on this device. "
                "Simkl sync uses your Simkl account as the shared library source. "
                "Changing mode does not delete the saved local copy."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("local", "Use Local-first")
        if self.simkl_client_id:
            dialog.add_response("simkl", "Use Simkl")
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

    def _on_settings_default_media_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        self.default_media = MEDIA_TYPES[row.get_selected()]
        self._save_user_state()

    def _on_settings_view_changed(
        self, row: Adw.ComboRow, _parameter: Any
    ) -> None:
        self.preferred_view_mode = ("list", "grid")[row.get_selected()]
        self.view_mode = self.preferred_view_mode
        self._updating = True
        self.view_switcher.set_active_name(self.view_mode)
        self._updating = False
        self._refresh_results()
        self._save_user_state()

    def _on_settings_auto_sync_changed(
        self, row: Adw.SwitchRow, _parameter: Any
    ) -> None:
        self.auto_sync = row.get_active()
        self._save_user_state()

    def _on_settings_auto_calendar_changed(
        self, row: Adw.SwitchRow, _parameter: Any
    ) -> None:
        self.auto_calendar_refresh = row.get_active()
        self._save_user_state()

    def _calendar_cache_subtitle(self) -> str:
        snapshot = getattr(self, "calendar_snapshot", None)
        if snapshot is None:
            return "No schedule has been cached yet."
        local = snapshot.fetched_at.astimezone()
        return f"Last refreshed {local.strftime('%b %-d, %Y at %H:%M')}"

    def _on_clear_calendar_cache_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Clear Calendar cache?",
            body=(
                "Downloaded Simkl schedules will be removed. گیشه can "
                "download them again when Calendar is opened."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear Cache")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_calendar_cache_response)
        dialog.present(self.window)

    def _on_clear_calendar_cache_response(
        self, _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "clear":
            return
        try:
            simkl_client.clear_calendar_cache()
        except simkl_client.SimklError as error:
            self._app_log("Could not clear Calendar cache: %s", error, level=logging.ERROR)
            self._toast("Could not clear the Calendar cache")
            return
        self.calendar_snapshot = None
        self.settings_calendar_cache_row.set_subtitle(self._calendar_cache_subtitle())
        if self.active_destination == "calendar":
            self._render_calendar()
        self._toast("Calendar cache cleared")

    def _on_clear_cache_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Clear downloaded TMDB data?",
            body=(
                "Downloaded posters, backdrops, cast photos and metadata will "
                "be removed. گیشه can download them again when needed."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear Cache")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_clear_cache_response)
        dialog.present(self.window)

    def _on_clear_cache_response(
        self, _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "clear":
            return
        try:
            tmdb_client.clear_cache()
        except tmdb_client.TmdbError as error:
            self._app_log("Could not clear TMDB cache: %s", error, level=logging.ERROR)
            self._toast("Could not clear the TMDB cache")
            return
        self._tmdb_details_loaded.clear()
        self._tmdb_episode_details_loaded.clear()
        self._tmdb_season_details_loaded.clear()
        self._app_log("Downloaded TMDB image and metadata cache cleared.")
        self._toast("TMDB cache cleared")

    def _on_factory_reset_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Reset گیشه completely?",
            body=(
                "Your local library, watch history, ratings, preferences, "
                "connected accounts, downloaded artwork, metadata, Calendar "
                "cache and application logs will be permanently deleted. "
                "گیشه will restart at the Welcome screen."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Delete Everything & Restart")
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
                heading="گیشه could not be fully reset",
                body=str(error),
            )
            failure.add_response("close", "Close")
            failure.present(self.settings_dialog)
            return
        try:
            self._restart_application()
        except OSError as error:
            self.settings_factory_reset_button.set_sensitive(True)
            failure = Adw.AlertDialog(
                heading="گیشه was reset but could not restart",
                body=f"Close and open گیشه again.\n\n{error}",
            )
            failure.add_response("close", "Close")
            failure.present(self.settings_dialog)

    @staticmethod
    def _restart_application() -> None:
        """Replace this process with a clean first-run گیشه process."""
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

    @staticmethod
    def _profile_card() -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("profile-card")
        return card

    @staticmethod
    def _profile_heading(title: str, subtitle: str | None = None) -> Gtk.Box:
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("title-3")
        heading.append(title_label)
        if subtitle:
            subtitle_label = Gtk.Label(label=subtitle, xalign=0)
            subtitle_label.add_css_class("dim-label")
            subtitle_label.add_css_class("caption")
            heading.append(subtitle_label)
        return heading

    @staticmethod
    def _profile_metric(icon: str, value: str, label: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        card.add_css_class("profile-metric-card")
        icon_widget = Gtk.Image.new_from_icon_name(icon)
        icon_widget.set_halign(Gtk.Align.START)
        icon_widget.add_css_class("accent")
        card.append(icon_widget)
        value_label = Gtk.Label(label=value, xalign=0)
        value_label.set_wrap(True)
        value_label.add_css_class("title-2")
        card.append(value_label)
        label_widget = Gtk.Label(label=label, xalign=0)
        label_widget.set_wrap(True)
        label_widget.add_css_class("dim-label")
        card.append(label_widget)
        return card

    def _profile_stats(self) -> dict[str, Any]:
        watched_records = tuple(
            record for record in self.records if self._is_record_completed(record)
        )
        watched_movies = tuple(
            record for record in watched_records if record.media_type == "Movies"
        )
        movie_minutes = sum(runtime_minutes(record.runtime) for record in watched_movies)

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

        today = date.today()
        current_streak = 0
        cursor = today
        while activity.get(cursor, 0):
            current_streak += 1
            cursor -= timedelta(days=1)
        longest_streak = 0
        running = 0
        previous: date | None = None
        for active_day in sorted(activity):
            running = running + 1 if previous == active_day - timedelta(days=1) else 1
            longest_streak = max(longest_streak, running)
            previous = active_day

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
            1 for watched_date, _minutes in episode_events if in_current_month(watched_date)
        )
        month_movie_count = sum(
            1 for watched_date, _minutes in movie_events if in_current_month(watched_date)
        )
        year_episode_count = sum(
            1 for watched_date, _minutes in episode_events if in_current_year(watched_date)
        )
        year_movie_count = sum(
            1 for watched_date, _minutes in movie_events if in_current_year(watched_date)
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
            if genre != "Synced"
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
            television_minutes = sum(
                int(group.get("total_mins") or 0)
                for group in (tv_stats, anime_stats)
                if isinstance(group, dict)
            ) or television_minutes
            episode_count = watched_episodes(tv_stats) + watched_episodes(anime_stats)
            total_minutes = int(
                self.simkl_stats.get("total_mins")
                or movie_minutes + television_minutes
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
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "active_days_year": sum(
                1 for active_day in activity if active_day.year == today.year
            ),
        }

    @staticmethod
    def _review_metric(value: str, label: str) -> Gtk.Box:
        metric = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        metric.set_hexpand(True)
        value_label = Gtk.Label(label=value, xalign=0)
        value_label.add_css_class("title-2")
        metric.append(value_label)
        caption = Gtk.Label(label=label, xalign=0)
        caption.add_css_class("caption")
        caption.add_css_class("dim-label")
        metric.append(caption)
        return metric

    def _build_review_summary(
        self,
        period: str,
        minutes: int,
        episodes: int,
        movies: int,
        active_days: int,
    ) -> Gtk.Box:
        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        summary.add_css_class("profile-review-summary")
        period_label = Gtk.Label(label=period, xalign=0)
        period_label.add_css_class("heading")
        summary.append(period_label)
        watch_time = Gtk.Label(label=format_watch_time(minutes), xalign=0)
        watch_time.add_css_class("review-watch-time")
        summary.append(watch_time)
        watch_caption = Gtk.Label(label="Watch time", xalign=0)
        watch_caption.add_css_class("dim-label")
        summary.append(watch_caption)

        metrics = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        metrics.append(self._review_metric(str(episodes), "Episodes"))
        metrics.append(self._review_metric(str(movies), "Movies"))
        metrics.append(self._review_metric(str(active_days), "Active days"))
        summary.append(metrics)
        return summary

    def _build_monthly_review(self, stats: dict[str, Any]) -> Gtk.Box:
        today = date.today()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.append(
            self._build_review_summary(
                today.strftime("%B %Y"),
                stats["month_minutes"],
                stats["month_episode_count"],
                stats["month_movie_count"],
                len(stats["month_activity"]),
            )
        )

        content.append(self._profile_heading("Daily activity"))

        grid = Gtk.Grid(column_spacing=7, row_spacing=7)
        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        for column, weekday in enumerate(weekdays):
            label = Gtk.Label(label=weekday)
            label.add_css_class("caption")
            label.add_css_class("dim-label")
            grid.attach(label, column, 0, 1, 1)

        first = date(today.year, today.month, 1)
        next_month = (
            date(today.year + 1, 1, 1)
            if today.month == 12
            else date(today.year, today.month + 1, 1)
        )
        days_in_month = (next_month - first).days
        maximum = max(stats["month_activity"].values(), default=1)
        for day_number in range(1, days_in_month + 1):
            current = date(today.year, today.month, day_number)
            position = first.weekday() + day_number - 1
            count = stats["month_activity"].get(current, 0)
            level = 0 if count == 0 else max(1, math.ceil(count / maximum * 4))
            cell = Gtk.Box()
            cell.set_size_request(30, 30)
            cell.add_css_class("activity-cell")
            cell.add_css_class(f"activity-level-{level}")
            if current == today:
                cell.add_css_class("today")
            cell.set_tooltip_text(f"{current.strftime('%B %d')}: {count} watched")
            grid.attach(cell, position % 7, position // 7 + 1, 1, 1)
        content.append(grid)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        for value, label in (
            (stats["current_streak"], "Current streak"),
            (stats["longest_streak"], "Longest streak"),
            (len(stats["month_activity"]), "Active this month"),
        ):
            item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            value_label = Gtk.Label(label=str(value))
            value_label.add_css_class("title-3")
            value_label.add_css_class("accent")
            item.append(value_label)
            caption = Gtk.Label(label=label)
            caption.add_css_class("caption")
            caption.add_css_class("dim-label")
            item.append(caption)
            footer.append(item)
        content.append(footer)
        return content

    def _build_yearly_review(self, stats: dict[str, Any]) -> Gtk.Box:
        today = date.today()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.append(
            self._build_review_summary(
                str(today.year),
                stats["year_minutes"],
                stats["year_episode_count"],
                stats["year_movie_count"],
                stats["active_days_year"],
            )
        )
        content.append(self._profile_heading("Activity through the year"))

        chart = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
        maximum = max(stats["year_month_activity"].values(), default=1)
        for month in range(1, 13):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            column.set_valign(Gtk.Align.END)
            bar_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            bar_host.set_vexpand(True)
            bar_host.set_valign(Gtk.Align.END)
            count = stats["year_month_activity"].get(month, 0)
            bar = Gtk.Box()
            bar.set_size_request(-1, max(4, round(count / maximum * 112)))
            bar.add_css_class("review-month-bar")
            if month == today.month:
                bar.add_css_class("current")
            bar.set_tooltip_text(f"{date(today.year, month, 1).strftime('%B')}: {count} watched")
            bar_host.append(bar)
            column.append(bar_host)
            label = Gtk.Label(label=date(today.year, month, 1).strftime("%b")[0])
            label.add_css_class("caption")
            label.add_css_class("dim-label")
            column.append(label)
            chart.append(column)
        content.append(chart)
        return content

    def _build_review_card(self, stats: dict[str, Any]) -> Gtk.Box:
        card = self._profile_card()
        card.add_css_class("profile-review-shell")

        heading = Gtk.CenterBox()
        heading.set_start_widget(
            self._profile_heading("Review", "Your activity over time")
        )
        self.profile_review_switcher = Adw.ToggleGroup()
        self.profile_review_switcher.add(Adw.Toggle(name="month", label="Month"))
        self.profile_review_switcher.add(Adw.Toggle(name="year", label="Year"))
        active = getattr(self, "profile_review_mode", "month")
        self.profile_review_switcher.set_active_name(active)
        self.profile_review_switcher.connect(
            "notify::active-name",
            self._on_profile_review_changed,
        )
        heading.set_end_widget(self.profile_review_switcher)
        card.append(heading)

        self.profile_review_stack = Gtk.Stack()
        self.profile_review_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.profile_review_stack.set_transition_duration(180)
        self.profile_review_stack.set_vhomogeneous(False)
        self.profile_review_stack.add_named(
            self._build_monthly_review(stats),
            "month",
        )
        self.profile_review_stack.add_named(
            self._build_yearly_review(stats),
            "year",
        )
        self.profile_review_stack.set_visible_child_name(active)
        card.append(self.profile_review_stack)
        return card

    def _on_profile_review_changed(
        self,
        group: Adw.ToggleGroup,
        _parameter: Any,
    ) -> None:
        active = group.get_active_name()
        if active not in ("month", "year"):
            return
        self.profile_review_mode = active
        self.profile_review_stack.set_visible_child_name(active)

    def _build_habits_card(self, stats: dict[str, Any]) -> Gtk.Box:
        card = self._profile_card()
        card.append(self._profile_heading("Watching habits", "All-time library totals"))
        for label, value in (
            ("All time", format_watch_time(stats["total_minutes"])),
            ("Movie time", format_watch_time(stats["movie_minutes"])),
            ("TV & anime time", format_watch_time(stats["television_minutes"])),
            ("Movies", str(stats["movie_count"])),
            ("Episodes", f"{stats['episode_count']:,}"),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            name = Gtk.Label(label=label, xalign=0)
            name.set_hexpand(True)
            name.add_css_class("dim-label")
            row.append(name)
            result = Gtk.Label(label=value)
            result.add_css_class("heading")
            row.append(result)
            card.append(row)
        return card

    def _build_ratings_card(self, stats: dict[str, Any]) -> Gtk.Box:
        card = self._profile_card()
        card.append(
            self._profile_heading(
                "Ratings",
                f"{stats['rating_count']} ratings across your library",
            )
        )
        chart = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        maximum = max(stats["rating_histogram"].values(), default=1)
        for score in range(1, 11):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            column.set_valign(Gtk.Align.END)
            bar_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            bar_host.set_vexpand(True)
            bar_host.set_valign(Gtk.Align.END)
            bar = Gtk.Box()
            count = stats["rating_histogram"].get(score, 0)
            bar.set_size_request(-1, max(4, round(count / maximum * 96)))
            bar.add_css_class("profile-rating-bar")
            bar.set_tooltip_text(f"{score}/10: {count} ratings")
            bar_host.append(bar)
            column.append(bar_host)
            label = Gtk.Label(label=str(score))
            label.add_css_class("caption")
            column.append(label)
            chart.append(column)
        card.append(chart)
        return card

    def _build_genres_card(self, stats: dict[str, Any]) -> Gtk.Box:
        card = self._profile_card()
        card.append(self._profile_heading("Favorite genres", "Based on watched titles"))
        top_genres = stats["genres"].most_common(6)
        maximum = top_genres[0][1] if top_genres else 1
        for genre, count in top_genres:
            labels = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            title = Gtk.Label(label=genre, xalign=0)
            title.set_hexpand(True)
            labels.append(title)
            value = Gtk.Label(label=str(count))
            value.add_css_class("dim-label")
            labels.append(value)
            card.append(labels)
            progress = Gtk.ProgressBar(fraction=count / maximum)
            progress.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [f"{genre}: {count} watched titles"],
            )
            card.append(progress)
        return card

    def _refresh_profile(self) -> None:
        stats = self._profile_stats()
        self._clear_container(self.profile_statistics_host)
        self.profile_statistics_host.append(self._build_review_card(stats))

        metrics = Gtk.FlowBox()
        metrics.set_selection_mode(Gtk.SelectionMode.NONE)
        metrics.set_min_children_per_line(2)
        metrics.set_max_children_per_line(4)
        metrics.set_column_spacing(12)
        metrics.set_row_spacing(12)
        for metric in (
            self._profile_metric(
                "document-open-recent-symbolic",
                format_watch_time(stats["total_minutes"]),
                "Total watch time",
            ),
            self._profile_metric(
                "emblem-ok-symbolic",
                str(len(stats["watched_records"])),
                "Completed titles",
            ),
            self._profile_metric(
                "media-playback-start-symbolic",
                f"{stats['episode_count']:,}",
                "Episodes watched",
            ),
            self._profile_metric(
                "starred-symbolic",
                str(stats["rating_count"]),
                "Ratings given",
            ),
        ):
            metrics.append(metric)
        self.profile_statistics_host.append(metrics)

        paired = Gtk.FlowBox()
        paired.set_selection_mode(Gtk.SelectionMode.NONE)
        paired.set_min_children_per_line(1)
        paired.set_max_children_per_line(2)
        paired.set_column_spacing(14)
        paired.set_row_spacing(14)
        paired.append(self._build_habits_card(stats))
        paired.append(self._build_genres_card(stats))
        self.profile_statistics_host.append(paired)
        self.profile_statistics_host.append(self._build_ratings_card(stats))

    def begin_simkl_connection(self) -> bool:
        """Enter Simkl mode and start its PIN or refresh flow."""
        self.library_mode = LIBRARY_MODE_SIMKL
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

    def set_library_mode(self, mode: str) -> None:
        """Apply an explicit data-ownership choice without deleting either copy."""
        if mode not in LIBRARY_MODES:
            raise ValueError(f"Unsupported library mode: {mode}")
        if mode == self.library_mode:
            if mode == LIBRARY_MODE_SIMKL and not self.simkl_connected:
                self.begin_simkl_connection()
            return

        if mode == LIBRARY_MODE_LOCAL:
            stored_state = read_state(self.state_file)
            self.library_mode = mode
            save_library_mode(mode, self.state_file)
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
                self._load_user_state()
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
            self._toast("Local-first mode enabled")
            return

        self._save_user_state()
        self.library_mode = mode
        save_library_mode(mode, self.state_file)
        self._update_settings_account_rows()
        self._update_profile_identity()
        self.begin_simkl_connection()

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
                heading="Simkl is unavailable in this build",
                body=(
                    "The distributor must register گیشه with Simkl and include "
                    "the public Client ID when building the application. You never "
                    "need to create a developer app or enter a Client Secret."
                ),
            )
            dialog.add_response("close", "Close")
            dialog.set_close_response("close")
            dialog.present(self.window)
            return
        self._simkl_sync_started_at = 0.0
        client_id = self.simkl_client_id
        self._app_log("Simkl sign-in started; requesting a PIN.")
        self._update_settings_account_rows(syncing=True)
        threading.Thread(
            target=self._simkl_pin_worker,
            args=(client_id,),
            name="gisheh-simkl-pin",
            daemon=True,
        ).start()

    def _simkl_pin_worker(self, client_id: str) -> None:
        started_at = time.monotonic()
        try:
            payload = simkl_client.request_pin(client_id)
        except simkl_client.SimklError as error:
            GLib.idle_add(self._on_simkl_failed, str(error), error.code)
            return
        self._app_log(
            "Simkl PIN received in %.1fs.",
            time.monotonic() - started_at,
        )
        GLib.idle_add(self._present_simkl_pin, client_id, payload)

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
            heading="Enter this code on Simkl",
            body=(
                "The browser has been opened. Sign in to Simkl and enter the "
                "code below. گیشه will finish automatically after approval."
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
        waiting.append(Gtk.Label(label="Waiting for approval…"))
        content.append(waiting)
        dialog.set_extra_child(content)
        dialog.add_response("cancel", "Cancel")
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
        threading.Thread(
            target=self._simkl_poll_worker,
            args=(client_id, user_code, interval, expires_in),
            name="gisheh-simkl-poll",
            daemon=True,
        ).start()
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
                GLib.idle_add(self._on_simkl_failed, str(error), error.code)
                return
            if self._simkl_poll_cancelled:
                return
            access_token = str(payload.get("access_token") or "")
            if payload.get("result") == "OK" and access_token:
                GLib.idle_add(self._on_simkl_authorized, access_token)
                return
            if payload.get("device_code"):
                GLib.idle_add(
                    self._on_simkl_failed,
                    "The Simkl PIN expired. Request a new code.",
                    None,
                )
                return
        if not self._simkl_poll_cancelled:
            GLib.idle_add(
                self._on_simkl_failed,
                "The Simkl PIN expired. Request a new code.",
                None,
            )

    def _on_simkl_authorized(self, access_token: str) -> bool:
        self._simkl_poll_cancelled = True
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
        self._app_log("Simkl authorization approved; access token stored in %s.", location)
        if getattr(self, "simkl_pin_dialog", None) is not None:
            self.simkl_pin_dialog.close()
        self._toast("Simkl connected — syncing your library…")
        self._start_simkl_sync()
        return GLib.SOURCE_REMOVE

    def _start_simkl_sync(self) -> None:
        if (
            self.library_mode != LIBRARY_MODE_SIMKL
            or not self.simkl_client_id
            or not self.simkl_token
        ):
            return
        self._simkl_sync_started_at = time.monotonic()
        self._app_log("Simkl sync started.")
        self._update_settings_account_rows(syncing=True)
        generation = self._simkl_state_generation
        threading.Thread(
            target=self._simkl_sync_worker,
            args=(self.simkl_client_id, self.simkl_token, generation),
            name="gisheh-simkl-sync",
            daemon=True,
        ).start()

    def _simkl_sync_worker(
        self, client_id: str, token: str, generation: int
    ) -> None:
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
                cached_library is not None
                and bool(last_sync)
                and not state_is_valid
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
                    self._app_log(
                        "State repair: account settings loaded from cache."
                    )
                else:
                    self._app_log(
                        "State repair: fetching missing account settings."
                    )
                    settings = simkl_client.fetch_settings(client_id, token)
            else:
                activities = {}
                self._app_log("Initial sync: fetching Simkl account settings.")
                settings = simkl_client.fetch_settings(client_id, token)
            account = settings.get("account", {})
            try:
                user_id = (
                    int(account.get("id") or 0)
                    if isinstance(account, dict)
                    else 0
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
            if not has_incremental_state:
                phase_started = time.monotonic()
                if repairing_metadata:
                    self._app_log(
                        "Repairing Simkl user state and external IDs."
                    )
                else:
                    self._app_log(
                        "Initial sync: downloading Simkl user state and IDs."
                    )
                library = simkl_client.fetch_library(client_id, token)
                if not repairing_metadata:
                    activities = simkl_client.fetch_activities(client_id, token)
                self._app_log(
                    "%s library download finished in %.1fs.",
                    "State repair" if repairing_metadata else "Initial",
                    time.monotonic() - phase_started,
                )
            elif activities.get("all") == last_sync:
                library = cached_library
                self._app_log("No Simkl library changes; using the local snapshot.")
            else:
                phase_started = time.monotonic()
                self._app_log("Changes found; downloading the incremental library delta.")
                delta = simkl_client.fetch_library_delta(
                    client_id,
                    token,
                    last_sync,
                )
                valid_ids = None
                if simkl_client.removals_changed(cached_activities, activities):
                    self._app_log(
                        "Removed items detected; reconciling the compact ID list."
                    )
                    id_snapshot = simkl_client.fetch_library_ids(client_id, token)
                    valid_ids = simkl_client.library_ids(id_snapshot)
                library = simkl_client.merge_library(
                    cached_library,
                    delta,
                    valid_ids,
                )
                self._app_log(
                    "Incremental library merge finished in %.1fs.",
                    time.monotonic() - phase_started,
                )
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
            records = enrich_records_from_tmdb_cache(
                title_records_from_simkl(library)
            )
        except simkl_client.SimklError as error:
            GLib.idle_add(self._on_simkl_failed, str(error), error.code)
            return
        except Exception as error:
            self._app_log(
                "Unexpected Simkl sync failure: %s",
                type(error).__name__,
                level=logging.ERROR,
            )
            GLib.idle_add(
                self._on_simkl_failed,
                "Unexpected Simkl sync error. Open Application Log for details.",
                None,
            )
            return
        GLib.idle_add(
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
        self.library_selected_id = self.selected_id
        valid_canonical_ids = set(self._library_records_by_canonical)
        self.status_overrides = {
            record_id: status
            for record_id, status in self.status_overrides.items()
            if record_id in valid_canonical_ids
        }

    def _apply_simkl_sync(
        self,
        settings: dict[str, Any],
        stats: dict[str, Any],
        records: tuple[TitleRecord, ...],
        generation: int | None = None,
    ) -> bool:
        if self.library_mode != LIBRARY_MODE_SIMKL:
            self._app_log("Ignoring Simkl sync result while Local-first mode is active.")
            return GLib.SOURCE_REMOVE
        if generation is not None and generation != self._simkl_state_generation:
            self._app_log(
                "Discarding a Simkl snapshot that predates a local mutation."
            )
            return GLib.SOURCE_REMOVE
        self.simkl_settings = settings
        self.simkl_stats = stats
        self.simkl_connected = True
        self.simkl_snapshot_needs_repair = False
        self._replace_library(records)
        self.completed = {
            self._canonical_record_id(record)
            for record in records if record.status == "Watched"
        }
        self.bookmarks = {
            self._canonical_record_id(record)
            for record in records if record.status == "Watchlist"
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
            str(user.get("avatar") or "") or None
            if isinstance(user, dict)
            else None
        )
        if avatar_url and simkl_client.cached_avatar() is None:
            threading.Thread(
                target=self._cache_simkl_avatar,
                args=(avatar_url,),
                name="gisheh-simkl-avatar",
                daemon=True,
            ).start()
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
                f"Synced {len(records)} Simkl states — loading catalog from TMDB"
            )
            self._load_tmdb_library_async(records)
        else:
            self._toast(
                "Simkl state synced — connect TMDB to load titles and artwork"
            )
        self._finish_simkl_sync(len(records))
        return GLib.SOURCE_REMOVE

    def _cache_simkl_avatar(self, avatar_url: str) -> None:
        avatar_file = simkl_client.cache_avatar(avatar_url)
        if avatar_file is not None:
            GLib.idle_add(self._apply_simkl_avatar, avatar_file)

    def _apply_simkl_avatar(self, avatar_file: str) -> bool:
        if not self.simkl_connected:
            return GLib.SOURCE_REMOVE
        try:
            texture = Gdk.Texture.new_from_filename(avatar_file)
            self.sidebar_profile_avatar.set_custom_image(texture)
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
        self._update_profile_identity()
        self._update_settings_account_rows()
        return GLib.SOURCE_REMOVE

    def _update_profile_identity(self) -> None:
        user = self.simkl_settings.get("user", {})
        name = str(user.get("name") or getuser()) if isinstance(user, dict) else getuser()
        self.sidebar_profile_avatar.set_text(name)
        cached_avatar = simkl_client.cached_avatar()
        if cached_avatar:
            try:
                texture = Gdk.Texture.new_from_filename(cached_avatar)
                self.sidebar_profile_avatar.set_custom_image(texture)
            except GLib.Error:
                pass
        else:
            self.sidebar_profile_avatar.set_custom_image(None)
        self._update_header_data_status()
        self._update_settings_account_rows()

    def _update_header_data_status(self) -> None:
        if not hasattr(self, "header_data_status_label"):
            return
        if self.library_mode == LIBRARY_MODE_LOCAL:
            self.header_data_status_icon.set_from_icon_name(
                "drive-harddisk-symbolic"
            )
            self.header_data_status_icon.remove_css_class("success")
            self.header_data_status_icon.add_css_class("accent")
            self.header_data_status_label.set_label("Local")
            self.header_data_status_label.set_tooltip_text(
                "Local-first · Personal library data stays on this device"
            )
        elif self.simkl_connected:
            self.header_data_status_icon.set_from_icon_name(
                "emblem-ok-symbolic"
            )
            self.header_data_status_icon.remove_css_class("accent")
            self.header_data_status_icon.add_css_class("success")
            self.header_data_status_label.set_label("Synced")
            self.header_data_status_label.set_tooltip_text(
                "Your library is connected to Simkl"
            )
        else:
            self.header_data_status_icon.set_from_icon_name(
                "network-offline-symbolic"
            )
            self.header_data_status_icon.remove_css_class("success")
            self.header_data_status_icon.remove_css_class("accent")
            self.header_data_status_label.set_label("Not synced")
            self.header_data_status_label.set_tooltip_text(
                "Simkl mode is selected but no account is connected"
            )

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
            heading="Disconnect Simkl?",
            body=(
                "The local access token will be removed. Your Simkl account "
                "and cloud library will not be changed."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("disconnect", "Disconnect")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "disconnect",
            Adw.ResponseAppearance.DESTRUCTIVE,
        )
        dialog.connect("response", self._on_simkl_disconnect_response)
        dialog.present(self.window)

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
        self.simkl_token = None
        self.simkl_connected = False
        self.simkl_settings = {}
        self.simkl_stats = {}
        records, _explore, _totals = load_catalog()
        self._replace_library(records)
        self.completed = {
            self._canonical_record_id(record)
            for record in records if record.status == "Watched"
        }
        self.bookmarks = {
            self._canonical_record_id(record)
            for record in records if record.status == "Watchlist"
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
        self._app_log("Simkl disconnected; local credentials and account cache removed.")
        self._toast("Simkl disconnected")

    def _build_detail_sections(self) -> None:
        self.image_mode = "backdrops"

        self.cast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cast_scroller = self._horizontal_scroller(self.cast_box, 116)
        self.cast_section = self._detail_section(
            "Cast & Crew",
            self.cast_scroller,
            action_label="See all",
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
        self.series_section = self._detail_section("Episodes & Seasons", series_content)

        self.videos_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.videos_scroller = self._horizontal_scroller(self.videos_box, 126)
        self.videos_section = self._detail_section(
            "Videos",
            self.videos_scroller,
        )

        self.images_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.image_switcher = Adw.ToggleGroup()
        self.image_switcher.add(Adw.Toggle(name="backdrops", label="Backdrops"))
        self.image_switcher.add(Adw.Toggle(name="posters", label="Posters"))
        self.image_switcher.set_active_name("backdrops")
        self.images_scroller = self._horizontal_scroller(self.images_box, 154)
        self.images_section = self._detail_section(
            "Images",
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
            "More like this",
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
        self.season_header_title = Adw.WindowTitle(title="Season", subtitle="")
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

        episodes_title = Gtk.Label(label="Episodes", xalign=0)
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

        self.episode_header_title = Adw.WindowTitle(title="Episode", subtitle="")
        episode_header = Adw.HeaderBar()
        episode_header.set_show_start_title_buttons(False)
        episode_header.set_show_end_title_buttons(False)
        episode_header.set_show_back_button(True)
        episode_header.set_title_widget(self.episode_header_title)

        self.episode_hero_host = Gtk.Box()
        self.episode_hero_host.set_halign(Gtk.Align.CENTER)
        self.episode_hero_host.set_hexpand(True)
        self.episode_hero_host.set_size_request(-1, 198)

        self.episode_status_label = Gtk.Label(label="Watched")
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

        overview_title = Gtk.Label(label="Overview", xalign=0)
        overview_title.add_css_class("heading")
        self.episode_overview_label = Gtk.Label(xalign=0)
        self.episode_overview_label.set_wrap(True)
        self.episode_overview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.episode_overview_label.set_max_width_chars(42)
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
            "Cast & Crew",
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
        action_label: str | None = None,
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
        if action_label is not None:
            action = Gtk.Button(label=action_label)
            action.add_css_class("flat")
            action.add_css_class("caption")
            action.connect(
                "clicked",
                lambda _button, section_title=title: self._toast(
                    f"Open all {section_title.lower()}"
                ),
            )
            end_box.append(action)
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
        previous.set_tooltip_text(f"Previous {title.lower()}")
        previous.add_css_class("flat")
        previous.connect(
            "clicked",
            lambda _button: self._scroll_carousel_page(scroller, -1),
        )

        following = Gtk.Button.new_from_icon_name("go-next-symbolic")
        following.set_tooltip_text(f"Next {title.lower()}")
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
        GLib.idle_add(lambda: (update_visibility(), GLib.SOURCE_REMOVE)[1])
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
        self.view_switcher.connect("notify::active-name", self._on_view_changed)
        self.destination_list.connect(
            "row-selected",
            self._on_destination_selected,
        )
        self.status_list.connect("row-selected", self._on_status_selected)
        self.collections_list.connect(
            "row-selected",
            self._on_library_list_selected,
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
        self.watched_button.connect("clicked", self._on_watched_clicked)
        self.bookmark_button.connect("toggled", self._on_bookmark_toggled)
        title_click = Gtk.GestureClick()
        title_click.connect("released", self._on_detail_title_released)
        self.detail_title.add_controller(title_click)
        self.detail_title.set_cursor_from_name("pointer")
        self.detail_title.set_tooltip_text("Open this title on TMDB")
        self.detail_title.add_css_class("detail-title-link")
        self.season_watched_button.connect(
            "clicked",
            self._on_season_watched_clicked,
        )
        self.episode_watched_button.connect(
            "clicked",
            self._on_episode_watched_clicked,
        )

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
        window_key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        window_key_controller.connect("key-pressed", self._on_window_key_pressed)
        self.window.add_controller(window_key_controller)

        self.window.connect("close-request", self._on_window_close_request)
        self.window.connect("realize", self._on_window_realized)

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
        self._explore_resize_source_id = GLib.idle_add(
            self._apply_explore_resize,
        )

    def _apply_explore_resize(self) -> bool:
        self._explore_resize_source_id = 0
        # During a sidebar/revealer transition the allocation is deliberately
        # intermediate.  The completion callback queues exactly one fresh
        # pass, so cards are never measured against a guessed future pane.
        if self._details_resize_source_id or self._sidebar_resize_source_id:
            return GLib.SOURCE_REMOVE
        width = self.explore_pane.get_width() or self.library_pane.get_width()
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
            or self.library_pane.get_width()
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
        self.genre_dropdown.set_model(Gtk.StringList.new(list(self.genre_options)))
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
            Gtk.StringList.new(list(self.explore_genre_options))
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
        threading.Thread(
            target=self._load_tmdb_library_worker,
            args=(ordered, token, generation),
            name="gisheh-tmdb-library",
            daemon=True,
        ).start()

    def _load_tmdb_library_worker(
        self,
        records: tuple[TitleRecord, ...],
        token: str,
        generation: int,
    ) -> None:
        started_at = time.monotonic()
        completed = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
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
        GLib.idle_add(
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
        GLib.idle_add(
            self._apply_tmdb_library_summary,
            generation,
            record.id,
            summary,
        )
        poster_path = str(summary.get("poster_path") or "")
        if poster_path:
            poster_file = tmdb_client.cache_image(poster_path, size="w500")
            if poster_file is not None:
                GLib.idle_add(
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
        record = self.records_by_id.get(record_id)
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
        if self.active_destination == "library":
            scroll_position = self.results_scroller.get_vadjustment().get_value()
            self._refresh_results()
            self._scroll_to_value(self.results_scroller, scroll_position)
        elif self.active_destination == "profile":
            self._refresh_profile()
        return GLib.SOURCE_REMOVE

    def _finish_tmdb_library_enrichment(
        self,
        generation: int,
        completed: int,
        total: int,
    ) -> bool:
        if generation != self._tmdb_library_generation:
            return GLib.SOURCE_REMOVE
        self._update_genre_model(preserve=True)
        if self.active_destination == "library":
            self._refresh_results()
        self._toast(f"TMDB catalog ready for {completed}/{total} titles")
        return GLib.SOURCE_REMOVE

    def _load_tmdb_explore_async(self) -> None:
        token = self.tmdb_token
        if not token:
            return
        self._tmdb_explore_generation += 1
        generation = self._tmdb_explore_generation
        self._tmdb_explore_pages_loading.update(MEDIA_TYPES)
        self._sync_explore_loading_indicator()
        threading.Thread(
            target=self._load_tmdb_explore_worker,
            args=(token, generation, self.active_media),
            name="gisheh-tmdb-explore",
            daemon=True,
        ).start()

    def _load_tmdb_explore_worker(
        self,
        token: str,
        generation: int,
        active_media: str,
    ) -> None:
        try:
            collections = tmdb_client.fetch_explore(token)
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
        except tmdb_client.TmdbError as error:
            GLib.idle_add(
                self._on_tmdb_explore_failed,
                generation,
                str(error),
            )
            return
        GLib.idle_add(self._apply_tmdb_explore, generation, tuple(records))

        image_work.sort(key=lambda item: (item[0], item[1]))
        with ThreadPoolExecutor(max_workers=8) as executor:
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
                GLib.idle_add(
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
            media_type: any(
                record.media_type == media_type for record in records
            )
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
        self._toast("Live TMDB data loaded")
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
        threading.Thread(
            target=self._load_next_tmdb_explore_page_worker,
            args=(self.tmdb_token, generation, media_type, page),
            name=f"gisheh-tmdb-explore-{media_type.lower()}-{page}",
            daemon=True,
        ).start()

    def _load_next_tmdb_explore_page_worker(
        self,
        token: str,
        generation: int,
        media_type: str,
        page: int,
    ) -> None:
        try:
            payload = tmdb_client.fetch_explore_page(token, media_type, page)
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
            GLib.idle_add(
                self._on_next_tmdb_explore_page_failed,
                generation,
                media_type,
                str(error),
            )
            return

        GLib.idle_add(
            self._apply_next_tmdb_explore_page,
            generation,
            media_type,
            page,
            total_pages,
            tuple(records),
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
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
                GLib.idle_add(
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
        self._toast("Could not load more titles from TMDB")
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
                record.id: record
                for record in (*self.records, *self.explore_records)
            }
            self._refresh_explore()
            self._sync_explore_loading_indicator()
            return
        self._set_details_open(False)
        self._refresh_explore()
        self._sync_explore_loading_indicator()
        if not self.tmdb_token:
            self._toast("Connect TMDB to search its catalog")
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
        threading.Thread(
            target=self._load_tmdb_search_page_worker,
            args=(self.tmdb_token, generation, media_type, query, 1),
            name=f"gisheh-tmdb-search-{media_type.lower()}",
            daemon=True,
        ).start()
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
        threading.Thread(
            target=self._load_tmdb_search_page_worker,
            args=(
                self.tmdb_token,
                self._tmdb_search_generation,
                self.active_media,
                self._tmdb_search_query,
                page,
            ),
            name=f"gisheh-tmdb-search-{self.active_media.lower()}-{page}",
            daemon=True,
        ).start()

    def _load_tmdb_search_page_worker(
        self,
        token: str,
        generation: int,
        media_type: str,
        query: str,
        page: int,
    ) -> None:
        try:
            payload = tmdb_client.search_titles_page(
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
            GLib.idle_add(
                self._on_tmdb_search_failed,
                generation,
                media_type,
                query,
                str(error),
            )
            return

        GLib.idle_add(
            self._apply_tmdb_search_page,
            generation,
            media_type,
            query,
            page,
            total_pages,
            tuple(records),
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
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
                GLib.idle_add(
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
            additions
            if page == 1
            else (*self.explore_search_records, *additions)
        )
        self.explore_search_ids = {
            record.id for record in self.explore_search_records
        }
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
            backdrop_file=(
                image_file if kind == "backdrop" else record.backdrop_file
            ),
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
        self._toast("Could not search TMDB")
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
            backdrop_file=(
                image_file if kind == "backdrop" else record.backdrop_file
            ),
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
        print(f"گیشه TMDB: {message}", file=sys.stderr)
        self._toast("TMDB is unavailable — Explore could not be loaded")
        return GLib.SOURCE_REMOVE

    def _load_tmdb_details_async(self, record: TitleRecord) -> None:
        if (
            not self.tmdb_token
            or record.tmdb_id is None
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
        threading.Thread(
            target=self._load_tmdb_details_worker,
            args=(record, self.tmdb_token, generation),
            name=f"gisheh-tmdb-{record.tmdb_id}",
            daemon=True,
        ).start()

    def _load_tmdb_details_worker(
        self,
        record: TitleRecord,
        token: str,
        generation: int,
    ) -> None:
        try:
            payload = tmdb_client.fetch_details(
                token,
                record.tmdb_media_type or "movie",
                record.tmdb_id or 0,
            )
            poster_path = str(payload.get("poster_path") or "")
            backdrop_path = str(payload.get("backdrop_path") or "")
            poster_file = tmdb_client.cached_image(poster_path, size="w500")
            backdrop_file = tmdb_client.cached_image(backdrop_path, size="w780")
            genres = tuple(
                str(item["name"])
                for item in payload.get("genres", ())
                if isinstance(item, dict) and item.get("name")
            ) or record.genres
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
                    str(item.get("character", "Cast")),
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
                        title=str(item.get("name") or f"Season {position}"),
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
                raw_videos.get("results", ())
                if isinstance(raw_videos, dict)
                else ()
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
                country=", ".join(countries[:2]) or record.country,
                creator=creator,
                description=str(payload.get("overview") or record.description),
                availability=str(payload.get("status") or record.availability),
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
        except tmdb_client.TmdbError as error:
            GLib.idle_add(
                self._on_tmdb_details_failed,
                record.id,
                generation,
                str(error),
            )
            return
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
        GLib.idle_add(
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
        recommendations = recommendation_records_from_tmdb(
            raw_recommendations, updated
        )
        GLib.idle_add(
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
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    tmdb_client.cache_image, path, size="w342"
                ): item_id
                for item_id, path in recommendation_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file:
                    GLib.idle_add(
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
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): kind
                for job in main_images
                if job is not None
                for kind, path, size in (job,)
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is not None:
                    GLib.idle_add(
                        self._apply_tmdb_detail_artwork,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size="w185"): index
                for index, path in profile_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                GLib.idle_add(
                    self._apply_tmdb_cast_artwork,
                    record.id,
                    generation,
                    futures[future],
                    image_file,
                )

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): kind
                for kind, path, size in gallery_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                GLib.idle_add(
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
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    tmdb_client.cache_youtube_thumbnail, key
                ): index
                for index, key in video_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file:
                    GLib.idle_add(
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
            replace(item, thumbnail_file=image_file)
            if position == index
            else item
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
            updated if record.id == updated.id else record
            for record in self.records
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
        threading.Thread(
            target=self._load_tmdb_season_details_worker,
            args=(
                record.id,
                token,
                record.tmdb_id,
                season.number,
                season_key,
            ),
            name=f"gisheh-tmdb-season-{record.tmdb_id}-{season.number}",
            daemon=True,
        ).start()

    def _load_tmdb_season_details_worker(
        self,
        record_id: str,
        token: str,
        tmdb_id: int,
        season_number: int,
        season_key: str,
    ) -> None:
        try:
            payload = tmdb_client.fetch_season_details(
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
                        format_watch_time(runtime_value)
                        if runtime_value > 0
                        else ""
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
                                    tmdb_client.cached_image(
                                        profile_path, size="w185"
                                    )
                                    if profile_path
                                    else None
                                )
                            except Exception:
                                profile_file = None
                            cast_items.append(
                                CastMember(
                                    name=str(member.get("name") or "Unknown"),
                                    role=str(
                                        member.get("character") or "Guest star"
                                    ),
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
                        except Exception:
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
                except Exception:
                    continue
            downloaded_stills: dict[int, str] = {}
            for episode_number, still_path in pending_stills:
                try:
                    image_file = tmdb_client.cache_image(still_path, size="w780")
                except Exception as error:
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
            GLib.idle_add(
                self._apply_tmdb_season_details,
                record_id,
                season_number,
                season_key,
                complete_updates,
            )
        except Exception as error:
            GLib.idle_add(
                self._on_tmdb_season_details_failed, season_key, str(error)
            )

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
        episode_index = max(
            0, min(self.current_episode_index, len(episodes) - 1)
        )
        self._populate_episode_page(
            record, season_index, episode_index, reset_scroll=False
        )

    def _on_tmdb_season_details_failed(self, season_key: str, message: str) -> bool:
        self._tmdb_season_details_loading.discard(season_key)
        self._app_log(
            "TMDB season details failed: %s", message, level=logging.WARNING
        )
        self._toast("Season details could not be loaded from TMDB")
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
        threading.Thread(
            target=self._load_tmdb_episode_details_worker,
            args=(
                record.id,
                token,
                record.tmdb_id,
                season.number,
                episode.number,
                key,
            ),
            name=f"gisheh-tmdb-episode-{record.tmdb_id}-{season.number}-{episode.number}",
            daemon=True,
        ).start()

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
            payload = tmdb_client.fetch_episode_details(
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
                    name=str(item.get("name") or "Unknown"),
                    role=str(item.get("character") or "Guest star"),
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
            GLib.idle_add(
                self._apply_tmdb_episode_details,
                record_id,
                season_number,
                episode_number,
                key,
                str(payload.get("name") or f"Episode {episode_number}"),
                str(payload.get("air_date") or "Air date unavailable"),
                str(payload.get("overview") or "No episode overview is available."),
                runtime,
                cast,
                cached_still,
            )
            if still_path and cached_still is None:
                image_file = tmdb_client.cache_image(still_path, size="w780")
                if image_file:
                    GLib.idle_add(
                        self._apply_tmdb_episode_artwork,
                        record_id,
                        season_number,
                        episode_number,
                        image_file,
                    )
        except (tmdb_client.TmdbError, TypeError, ValueError) as error:
            GLib.idle_add(self._on_tmdb_episode_details_failed, key, str(error))

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
        self._toast("Episode details could not be loaded from TMDB")
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
        print(f"گیشه TMDB details: {message}", file=sys.stderr)
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
                "Change TMDB developer override"
                if tmdb_client.token_source() == "user"
                else "Configure this development build"
            ),
            body=(
                "Public releases should include گیشه's approved TMDB credential. "
                "For local development only, you can enter your own API Read Access "
                "Token; it will be stored only for this user."
            ),
        )
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_tooltip_text("TMDB API Read Access Token")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save and connect")
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_tmdb_token_response, entry)
        dialog.present(self.window)

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
            self._toast("Enter a TMDB Read Access Token")
            return
        try:
            tmdb_client.store_token(token)
        except tmdb_client.TmdbError as error:
            print(f"گیشه TMDB token: {error}", file=sys.stderr)
            self._toast("Could not save the TMDB token")
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
        self._toast("Connecting to TMDB…")
        if self.simkl_connected:
            self._load_tmdb_library_async(self.records)
        self._load_tmdb_explore_async()

    def _on_tmdb_disconnect_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Remove the TMDB connection?",
            body=(
                "The locally stored read token will be removed. Downloaded "
                "artwork remains available until you clear the cache."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove Token")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_tmdb_disconnect_response)
        dialog.present(self.window)

    def _on_tmdb_disconnect_response(
        self, _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "remove":
            return
        try:
            tmdb_client.clear_token()
        except tmdb_client.TmdbError as error:
            self._app_log("Could not remove TMDB token: %s", error, level=logging.ERROR)
            self._toast("Could not remove the TMDB token")
            return
        self.tmdb_token = tmdb_client.read_token()
        self._update_settings_account_rows()
        if self.tmdb_token:
            self._toast("The TMDB token is provided by the environment")
            return
        self._app_log("Locally stored TMDB read token removed.")
        self._toast("TMDB disconnected")

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
        library_record = getattr(self, "_library_records_by_canonical", {}).get(canonical)
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
        return sum(
            record.media_type == media_type for record in self.explore_records
        )

    def _library_total(self, media_type: str) -> int:
        return sum(
            self._status_total(media_type, status)
            for status in LIBRARY_FILTERS
        )

    def _filtered_explore_records(self) -> tuple[TitleRecord, ...]:
        query = self.explore_search_entry.get_text().strip()
        source_records = (
            self.explore_search_records
            if query
            else self.explore_records
        )
        records = []
        for record in source_records:
            if record.media_type != self.active_media:
                continue
            if (
                not query
                and
                self.explore_period == "This month"
                and record.discover_period != "This month"
            ):
                continue
            if (
                not query
                and
                self.explore_period == "This year"
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
            if (
                self._is_record_bookmarked(record)
                or self._is_record_completed(record)
            )
            and self._canonical_record_id(record) not in present
        )
        return (*self.records, *promoted)

    def _filtered_records(self) -> tuple[TitleRecord, ...]:
        query = self.search_entry.get_text().strip().casefold()
        records = []
        for record in self._library_records():
            haystack = " ".join(
                (record.title, record.description, record.creator, *record.genres)
            ).casefold()
            if record.media_type != self.active_media:
                continue
            if self._effective_status(record) != self.active_status:
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
        self.visible_records = self._filtered_records()
        visible_ids = {record.id for record in self.visible_records}
        if self.selected_id not in visible_ids:
            self.selected_id = self.visible_records[0].id if self.visible_records else None
        self.library_selected_id = self.selected_id

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
        has_filters = bool(self.search_entry.get_text().strip()) or self.genre != "All genres"
        if has_filters:
            description = f"{sample_count} matching {'title' if sample_count == 1 else 'titles'}"
        else:
            description = f"Showing {sample_count} recent {'entry' if sample_count == 1 else 'entries'}"

        self.eyebrow_label.set_label(f"My library / {self.active_media}")
        self.section_title.set_label(self.active_status)
        self.result_count.set_label("All")
        self.result_description.set_label(description)
        self.search_entry.set_placeholder_text(
            f"Search {self.active_media.lower()}…"
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

        self.explore_eyebrow_label.set_label(
            f"{'TMDB Search' if query else 'Discover'} / {self.active_media}"
        )
        if query:
            self.explore_empty_page.set_icon_name("system-search-symbolic")
            self.explore_empty_page.set_title(
                "Searching TMDB…" if self._tmdb_search_loading else "No TMDB matches"
            )
            self.explore_empty_page.set_description(
                f'Searching the complete TMDB catalog for “{query}”.'
                if self._tmdb_search_loading
                else f'No {self.active_media.lower()} matched “{query}” on TMDB.'
            )
        else:
            self.explore_empty_page.set_icon_name("system-search-symbolic")
            self.explore_empty_page.set_title("Nothing new here yet")
            self.explore_empty_page.set_description(
                "Try another search, period, or genre."
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
        rendered_signatures = getattr(
            self, "_explore_rendered_signatures", ()
        )
        rendered_columns = getattr(self, "_explore_rendered_columns", 0)
        is_extension = (
            not force_relayout
            and bool(rendered_ids)
            and self.explore_columns == rendered_columns
            and len(record_ids) >= len(rendered_ids)
            and record_ids[: len(rendered_ids)] == rendered_ids
            and visual_signatures[: len(rendered_signatures)]
            == rendered_signatures
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
            attribution = Gtk.Label(label="Data & images provided by TMDB")
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
        layout_seed = (
            self._explore_layout_seed
            ^ (columns << 24)
            ^ (row << 8)
        )
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
            adjustment.get_upper()
            - adjustment.get_page_size()
            - adjustment.get_value()
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
        button.set_tooltip_text(f"Open {record.title}")
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

    def _create_list_row(self, record: TitleRecord) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.record = record

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content.add_css_class("movie-row-content")
        content.append(self._create_poster_overlay(record, 76, 114))
        content.append(self._create_record_copy(record, compact=False))

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("view-more-symbolic")
        menu_button.set_tooltip_text(f"More options for {record.title}")
        menu_button.set_valign(Gtk.Align.START)
        menu_button.add_css_class("flat")
        menu_button.add_css_class("circular")
        menu_button.set_popover(self._record_context_popover(record))
        content.append(menu_button)
        row.set_child(content)
        return row

    def _record_context_popover(self, record: TitleRecord) -> Gtk.PopoverMenu:
        menu = Gio.Menu()
        state_section = Gio.Menu()
        watched = self._is_record_completed(record)
        state_section.append(
            "Mark as unwatched" if watched else "Mark as watched",
            "record.watch",
        )
        bookmarked = self._is_record_bookmarked(record)
        state_section.append(
            "Remove from Watchlist" if bookmarked else "Add to Watchlist",
            "record.watchlist",
        )
        current_rating = self._effective_record_rating(record)
        rating_section = Gio.Menu()
        rating_section.append(
            f"Rate…  ({current_rating}/10)" if current_rating is not None else "Rate…",
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

    def _activate_context_watched(self, record_id: str) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._activate_record_watched(record)

    def _activate_context_watchlist(self, record_id: str, adding: bool) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._set_record_bookmarked(record, adding)

    def _activate_context_rating(self, record_id: str) -> None:
        record = self._context_record(record_id)
        if record is not None:
            self._show_record_rating_dialog(record)

    def _show_record_rating_dialog(self, record: TitleRecord) -> None:
        dialog = Adw.AlertDialog(
            heading=f"Rate {record.title}",
            body="Choose a score from 1 to 10, then save your rating.",
        )
        rating_grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True)
        rating_grid.set_column_spacing(6)
        rating_grid.set_row_spacing(6)
        selected = {"score": self._effective_record_rating(record)}
        leader: Gtk.ToggleButton | None = None
        for score in range(1, 11):
            button = Gtk.ToggleButton(label=str(score))
            button.set_tooltip_text(f"{score} out of 10")
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
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save rating")
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
        artwork_button.set_tooltip_text(f"Open images for {record.title}")
        artwork_button.add_css_class("flat")
        artwork_button.add_css_class("media-thumbnail")
        artwork_button.connect(
            "clicked",
            lambda *_args: self._open_record_media(record, "backdrops"),
        )
        overlay.set_child(artwork_button)

        trailer_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        trailer_content.append(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
        trailer_content.append(Gtk.Label(label="Watch trailer"))
        trailer = Gtk.Button()
        trailer.set_child(trailer_content)
        trailer.set_halign(Gtk.Align.CENTER)
        trailer.set_valign(Gtk.Align.CENTER)
        trailer.add_css_class("pill")
        trailer.add_css_class("detail-hero-button")
        trailer.set_tooltip_text(f"Play the trailer for {record.title}")
        trailer.set_visible(trailer_info is not None)
        if trailer_info is not None and trailer_info.url is not None:
            trailer.connect(
                "clicked",
                lambda _button, video=trailer_info: (
                    self._open_external_uri_with_warning(
                        video.url or "",
                        heading="Open the trailer?",
                        body=(
                            f"گیشه will open “{video.title}” on YouTube "
                            "in your default web browser."
                        ),
                    )
                ),
            )
        overlay.add_overlay(trailer)
        overlay.set_measure_overlay(trailer, False)

        self.detail_poster_host.append(overlay)

    def _rating_sources(self, record: TitleRecord) -> tuple[tuple[str, str], ...]:
        if record.external_ratings:
            return record.external_ratings[:4]
        return (
            ("گیشه", f"{record.rating:.1f}"),
            ("IMDb", f"{min(10.0, record.rating + 0.1):.1f}"),
            ("Meta", str(min(99, round(record.rating * 10)))),
            ("Match", f"{min(99, round(record.rating * 10 + 8))}%"),
        )

    def _populate_detail_ratings(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_ratings_host)
        for index, (source, value) in enumerate(self._rating_sources(record)):
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            chip.set_hexpand(True)
            chip.add_css_class("detail-metric")
            score = Gtk.Label(label=value)
            score.add_css_class("numeric")
            score.add_css_class("heading")
            source_label = Gtk.Label(label=source)
            source_label.set_ellipsize(Pango.EllipsizeMode.END)
            source_label.add_css_class("caption")
            source_label.add_css_class("dim-label")
            chip.append(score)
            chip.append(source_label)
            self.detail_ratings_host.attach(chip, index % 2, index // 2, 1, 1)

    @staticmethod
    def _cast_members(record: TitleRecord) -> tuple[CastMember, ...]:
        if record.cast:
            return record.cast[:12]
        return (
            CastMember(record.creator, "Director / Creator"),
            CastMember("Lead Ensemble", "Cast"),
            CastMember("Supporting Ensemble", "Cast"),
            CastMember("Guest Artist", "Cast"),
        )

    def _populate_cast(self, record: TitleRecord) -> None:
        self._populate_cast_container(self.cast_box, record)

    def _populate_cast_container(
        self,
        container: Gtk.Box,
        record: TitleRecord,
        *,
        allow_fallback: bool = True,
    ) -> None:
        self._clear_container(container)
        if record.id in self._tmdb_details_loading:
            for _index in range(4):
                container.append(self._loading_cast_placeholder())
            return

        members = self._cast_members(record) if allow_fallback else record.cast[:12]
        if not members:
            empty = Gtk.Label(label="No guest cast information is available.")
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
            avatar.set_tooltip_text(f"{member.name}, {member.role}")
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
                pending.set_tooltip_text(f"Loading photo for {member.name}")
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
    def _loading_media_placeholder(
        width: int, height: int, tooltip: str
    ) -> Gtk.Box:
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
        placeholder.set_tooltip_text("Loading cast member")
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
        if "episodes" in record.runtime:
            episode_count = numbers[0] if numbers else 12
            return (
                SeasonInfo(
                    "s1",
                    1,
                    "Season 1",
                    episode_count if is_completed else 0,
                    episode_count,
                ),
            )

        season_count = max(1, numbers[0] if numbers else 1)
        return tuple(
            SeasonInfo(
                f"s{index}",
                index,
                f"Season {index}",
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
                    title=f"Episode {number}",
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
            self._season_watched_count(record, index)
            for index in progress_indexes
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
            activity_status = "Episode data unavailable"
            tooltip = activity_status
        elif watched_episodes == 0:
            activity_status = f"0 of {total_episodes} episodes watched"
            tooltip = activity_status
        elif watched_episodes >= total_episodes:
            activity_status = f"All {total_episodes} episodes watched"
            tooltip = f"{total_episodes} of {total_episodes} episodes watched"
        else:
            activity_status = f"{watched_episodes} of {total_episodes} episodes watched"
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
        overlay.set_tooltip_text(f"Episode {episode.number}: {episode.title}")
        return overlay

    @staticmethod
    def _episode_watch_button(watched: bool) -> Gtk.Button:
        """Return a real, compact Adwaita control for episode watch state."""
        button = Gtk.Button.new_from_icon_name(
            "object-select-symbolic"
            if watched
            else "media-playback-start-symbolic"
        )
        icon = button.get_child()
        if isinstance(icon, Gtk.Image):
            icon.set_pixel_size(14)
            if watched:
                icon.add_css_class("success")
        button.add_css_class("flat")
        button.add_css_class("circular")
        button.add_css_class("episode-watch-button")
        label = "Mark episode unwatched" if watched else "Mark episode watched"
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
            next_episode = "Up to date"
            next_subtitle = record.availability
        else:
            next_season_index, next_info = next_item
            next_episode = self._episode_code(record, next_season_index, next_info)
            next_subtitle = next_info.title

        if last_item is None:
            last_episode = "Not started"
            last_subtitle = record.network
        else:
            last_season_index, last_info = last_item
            last_episode = self._episode_code(record, last_season_index, last_info)
            last_subtitle = last_info.title
        self.episode_cards_box.append(
            self._episode_card("Next episode", next_episode, next_subtitle)
        )
        self.episode_cards_box.append(
            self._episode_card("Last episode", last_episode, last_subtitle)
        )

        for season_index, season in enumerate(seasons):
            watched = self._season_watched_count(record, season_index)
            season_complete = is_episode_group_complete(watched, season.episodes)
            row = Adw.ActionRow(
                title=season.title,
                subtitle=f"{watched}/{season.episodes} episodes",
            )
            row.season_index = season_index
            row.set_activatable(True)
            row.set_tooltip_text(f"Open {season.title} of {record.title}")
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
            f"{watched} of {len(episodes)} episodes watched · {record.network}"
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
                    f"Open episode {episode.number}: {episode.title}"
                )
            else:
                row.set_tooltip_text(
                    "Wait for all episode details to finish loading"
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
        self.episode_header_title.set_title(f"Episode {episode.number}")
        self.episode_header_title.set_subtitle(season.title)

        self._clear_container(self.episode_hero_host)
        self.episode_hero_host.append(
            self._episode_artwork(
                record, episode, 352, 198, flexible_width=True
            )
        )
        self.episode_title_label.set_label(episode.title)
        episode_code = f"S{season.number:02d}E{episode.number:02d}"
        self.episode_date_label.set_label(
            " · ".join(value for value in (episode_code, episode.date) if value)
        )
        self.episode_runtime_label.set_label(
            episode.runtime or "Runtime unavailable"
        )
        self.episode_series_label.set_label(f"{record.title} · {season.title}")
        self.episode_overview_label.set_label(episode.description)
        self._populate_cast_container(
            self.episode_cast_box,
            replace(record, cast=episode.cast),
            allow_fallback=False,
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
        self.episode_status_label.set_label("Watched")
        self._set_watched_action_state(
            self.episode_watched_button, watched, "episode"
        )
        watched_at = self.episode_watched_at.get(
            self._episode_key(record, season_index, episode)
        )
        if watched and watched_at:
            status = f"Watched · {format_watched_iso(watched_at)}"
        elif watched:
            status = "Watched"
        else:
            status = "Not watched yet"
        self.episode_watched_at_label.set_label(status)

    @staticmethod
    def _set_watched_action_state(
        button: Gtk.Button,
        watched: bool,
        noun: str,
    ) -> None:
        label = f"Mark {noun} unwatched" if watched else f"Mark {noun} watched"
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
        button.set_tooltip_text(f"Play {video.title} for {record.title}")
        if video.url is not None:
            button.connect(
                "clicked",
                lambda _button, item=video: self._open_external_uri_with_warning(
                    item.url or "",
                    heading="Open the video?",
                    body=(
                        f"گیشه will open “{item.title}” on YouTube "
                        "in your default web browser."
                    ),
                ),
            )
        return button

    def _populate_videos(self, record: TitleRecord) -> None:
        self._clear_container(self.videos_box)
        if record.id in self._tmdb_details_loading:
            for _index in range(2):
                self.videos_box.append(
                    self._loading_media_placeholder(156, 112, "Loading video")
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
                    self._loading_media_placeholder(width, height, "Loading image")
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
                f"Open {self.image_mode[:-1]} {index + 1} for {record.title}"
            )
            button.connect(
                "clicked",
                (
                    lambda _button, image_index=index: self.media_viewer.open(
                        media_items,
                        image_index,
                    )
                    if media_items
                    else self._toast(f"No {mode} available for {record.title}")
                ),
            )
            self.images_box.append(button)
        for _index in range(pending_count):
            self.images_box.append(
                self._loading_media_placeholder(width, height, "Loading image")
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
            button.set_tooltip_text(f"Open {item.title}")
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
        self.detail_status_label.set_label(self._effective_status(record))
        self.detail_overline.set_label(" · ".join(record.genres))
        self.detail_title.set_label(record.title)
        self.community_rating.set_label(f"★ {record.rating:.1f}")
        self.watched_button.set_label(
            "✓  Watched" if is_completed else "＋  Mark watched"
        )
        self.runtime_label.set_label(
            f"{record.certification} · {record.language} · {record.runtime}"
        )
        self.genres_label.set_label(f"{record.year} · {record.availability}")
        self.overview_label.set_label(record.description)
        self.creator_row.set_title(
            "Director" if record.media_type == "Movies" else "Creator"
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
        self.rating_value.set_label("Not rated" if score is None else f"{score}/10")
        self.rating_button.set_icon_name(
            "non-starred-symbolic" if score is None else "starred-symbolic"
        )
        self.rating_button.set_tooltip_text(
            "Rate this title" if score is None else f"Your rating: {score}/10"
        )
        self._updating_details = False
        self._populate_detail_sections(record)
        if record_changed:
            self._scroll_to_top(self.details_scroller)

    def _sync_library_filter_selection(self) -> None:
        was_updating = self._updating
        self._updating = True
        if self.active_status == "Watchlist":
            self.status_list.unselect_all()
            self.collections_list.select_row(self.watchlist_row)
        else:
            self.collections_list.unselect_all()
            self.status_list.select_row(self.status_rows[self.active_status])
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

    def _on_media_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        if self._updating:
            return
        active = group.get_active_name()
        if not active:
            return
        media_type = active.title()
        if media_type not in MEDIA_TYPES:
            return
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

    def _on_destination_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        if row.key != self.active_destination and self.details_open:
            self._set_details_open(False)
        if row.key == "library":
            if self.active_destination == "library":
                return
            if self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
            self.active_destination = "library"
            self.media_switcher.set_visible(True)
            self.browser_stack.set_visible_child_name("library")
            self.selected_id = self.library_selected_id
            self._sync_library_filter_selection()
            self._refresh_results()
            self._close_sidebar_overlay()
            self._queue_responsive_layout()
            return
        if row.key == "calendar":
            if self.active_destination == "library":
                self.library_selected_id = self.selected_id
            elif self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
            self.active_destination = "calendar"
            self.media_switcher.set_visible(False)
            self._updating = True
            self.status_list.unselect_all()
            self.collections_list.unselect_all()
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
        if self.active_destination == "library":
            self.library_selected_id = self.selected_id
        self.active_destination = "explore"
        self.media_switcher.set_visible(True)
        self._updating = True
        self.status_list.unselect_all()
        self.collections_list.unselect_all()
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
        if self.active_destination == "library":
            self.library_selected_id = self.selected_id
        elif self.active_destination == "explore":
            self.explore_selected_id = self.selected_id
        self.active_destination = "profile"
        self.media_switcher.set_visible(False)
        self._updating = True
        self.destination_list.unselect_all()
        self.status_list.unselect_all()
        self.collections_list.unselect_all()
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
                "Hide sidebar (Ctrl+B)" if is_open else "Show sidebar (Ctrl+B)"
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
        except Exception:
            width = 0
        if width > 0:
            return width
        try:
            surface = self.window.get_surface()
            if surface is not None and int(surface.get_width()) > 0:
                return int(surface.get_width())
        except Exception:
            pass
        return self.explore_pane.get_width() or self.library_pane.get_width() or 0

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

    def _explore_base_width(self, *, details_open: bool | None = None) -> int:
        """Return Explore's current allocation, never a guessed subtraction.

        ``details_open`` remains accepted for callers that previously used
        this helper, but card geometry is intentionally based on GTK's actual
        allocation.  A cached width is only useful before the first allocation.
        """
        del details_open
        allocated = self.explore_pane.get_width() or self.library_pane.get_width()
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
                self.details_surface.set_size_request(
                    DETAILS_INLINE_WIDTH, -1
                )
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
            self.details_open
            and self.effective_details_mode == DETAILS_NAVIGATION
        )
        if self.details_overlay_close is not None:
            self.details_overlay_close.set_visible(overlay_active)
        focus_mode = (
            self.effective_details_mode
            if overlay_active or navigation_active
            else None
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

    def _on_status_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self._updating = True
        self.collections_list.unselect_all()
        self._updating = False
        self._activate_library_filter(row.key)

    def _activate_library_filter(self, filter_name: str) -> None:
        returning_to_library = self.active_destination != "library"
        previous_status = self.active_status
        if returning_to_library:
            if self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
            self.active_destination = "library"
            self.media_switcher.set_visible(True)
            self._updating = True
            self.destination_list.select_row(self.library_row)
            self._updating = False
            self.browser_stack.set_visible_child_name("library")
            self.selected_id = self.library_selected_id
        self.active_status = filter_name
        if not returning_to_library or filter_name != previous_status:
            self._updating = True
            self.search_entry.set_text("")
            self.genre_dropdown.set_selected(0)
            self.genre = "All genres"
            self._updating = False
        self._refresh_results()
        self._close_sidebar_overlay()
        self._queue_responsive_layout()

    def _on_library_list_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self._updating = True
        self.status_list.unselect_all()
        self._updating = False
        self._activate_library_filter(row.key)

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if not self._updating:
            self._refresh_results()

    def _on_explore_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if not self._updating and self.active_destination == "explore":
            self._queue_tmdb_explore_search()

    def _on_search_requested(self, *_args: Any) -> None:
        if self.active_destination != "explore":
            self.destination_list.select_row(self.explore_row)
        GLib.idle_add(self._focus_explore_search)

    def _focus_explore_search(self) -> bool:
        self.explore_search_entry.grab_focus()
        return GLib.SOURCE_REMOVE

    def _on_sort_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(SORT_OPTIONS):
            return
        self.sort_key = SORT_OPTIONS[selected][0]
        self.sort_reversed = False
        self._refresh_results()

    def _on_genre_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.genre_options):
            return
        self.genre = self.genre_options[selected]
        self._refresh_results()

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
        if record_id not in self.explore_ids and record_id not in self.explore_search_ids:
            return
        self.explore_selected_id = record_id
        self.selected_id = record_id
        self._sync_explore_selection_style()
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[record_id])

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
            self._toast("Wait for all episode details to finish loading")
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
        return bool(datetime.now().strftime("%p"))

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
            heading="When did you watch this?",
            body=body,
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        picker_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        picker_card.add_css_class("card")
        picker_card.add_css_class("watched-dialog-card")
        date_caption = Gtk.Label(label="Date", xalign=0)
        date_caption.add_css_class("caption")
        date_caption.add_css_class("dim-label")
        picker_card.append(date_caption)
        calendar = Gtk.Calendar()
        calendar.set_hexpand(True)
        calendar.add_css_class("watched-dialog-calendar")
        calendar.select_day(
            GLib.DateTime.new_local(now.year, now.month, now.day, 0, 0, 0.0)
        )
        picker_card.append(calendar)
        time_caption = Gtk.Label(label="Time", xalign=0)
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
        hour_spin.set_tooltip_text("Hour")
        time_row.append(hour_spin)
        separator = Gtk.Label(label=":")
        separator.add_css_class("title-2")
        time_row.append(separator)
        minute_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        minute_spin.set_value(now.minute)
        minute_spin.set_wrap(True)
        minute_spin.set_tooltip_text("Minute")
        time_row.append(minute_spin)
        ampm_dropdown: Gtk.DropDown | None = None
        if use_12h:
            ampm_dropdown = Gtk.DropDown.new_from_strings(("AM", "PM"))
            ampm_dropdown.set_selected(1 if now.hour >= 12 else 0)
            ampm_dropdown.set_tooltip_text("AM or PM")
            time_row.append(ampm_dropdown)

        actions_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        actions_row.set_halign(Gtk.Align.CENTER)
        now_button = Gtk.Button(label="Now")
        now_button.set_tooltip_text("Reset to the current date and time")
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

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("mark", "Mark as Watched")
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
                    ampm_dropdown is not None
                    and ampm_dropdown.get_selected() == 1
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
            calendar.select_day(
                GLib.DateTime.new_local(
                    current.year, current.month, current.day, 0, 0, 0.0
                )
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
            on_confirm=lambda iso: self._mark_season_watched(
                record, season_index, iso
            ),
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
            self._defer_library_refresh_for_detail_mutation()

    def _defer_library_refresh_for_detail_mutation(self) -> None:
        """Keep the open title stable, then refresh its filter after closing."""
        if self.active_destination != "library":
            return
        if getattr(self, "details_open", False):
            self._library_results_dirty = True
            return
        self._refresh_results()

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
                self._toast("Season watched time saved locally (not synced)")
            else:
                self._toast("Connect Simkl to change episode history")
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
                self._toast("Simkl did not add any episodes to watched history.")
                return
            apply()
            self._invalidate_simkl_snapshot_after_mutation()
            self._toast("Season marked as watched")

        self._run_simkl_mutation(
            f"{self._canonical_record_id(record)}:s{season.number}:watched",
            operation,
            on_done,
            "",
        )

    def _unmark_season_watched(
        self, record: TitleRecord, season_index: int
    ) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        episodes = self._episodes_for_season(record, season_index)

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
                self._toast("Season marked as unwatched locally (not synced)")
            else:
                self._toast("Connect Simkl to change episode history")
            return
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
            apply,
            "Season marked as unwatched",
        )

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
            self._unmark_episode_watched(
                record, self.current_season_index, episode
            )
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

        def apply() -> None:
            current_record = self.records_by_id.get(record.id, record)
            if self._local_mode_active():
                self._ensure_local_library_record(current_record)
            self.episode_status_overrides[key] = True
            self.episode_watched_at[key] = iso_timestamp
            self._save_user_state()
            self._populate_series(current_record)
            season_scroll = (
                self.season_details_scroller.get_vadjustment().get_value()
            )
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
                self._defer_library_refresh_for_detail_mutation()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast("Episode watched time saved locally (not synced)")
            else:
                self._toast("Connect Simkl to change episode history")
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
                self._toast("Simkl did not add this episode to watched history.")
                return
            apply()
            self._invalidate_simkl_snapshot_after_mutation()
            self._toast("Episode marked as watched")

        self._run_simkl_mutation(
            f"{key}:watched",
            operation,
            on_done,
            "",
        )

    def _unmark_episode_watched(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> None:
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        key = self._episode_key(record, season_index, episode)

        def apply() -> None:
            current_record = self.records_by_id.get(record.id, record)
            self.episode_status_overrides[key] = False
            self.episode_watched_at.pop(key, None)
            self._invalidate_simkl_snapshot_after_mutation()
            self._save_user_state()
            self._populate_series(current_record)
            season_scroll = (
                self.season_details_scroller.get_vadjustment().get_value()
            )
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
                self._defer_library_refresh_for_detail_mutation()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast("Episode marked as unwatched locally (not synced)")
            else:
                self._toast("Connect Simkl to change episode history")
            return
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
            apply,
            "Episode marked as unwatched",
        )

    def _on_list_selected(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self.selected_id = row.record.id
        self.library_selected_id = self.selected_id
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
        self.library_selected_id = self.selected_id
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
        self.library_selected_id = self.selected_id
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
        self.library_selected_id = self.selected_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    @staticmethod
    def _details_panel_preferred_width(
        mode: str, available_width: int
    ) -> int:
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
            self._apply_sidebar_docked(
                layout.sidebar_mode == SIDEBAR_EXPANDED
            )
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

    def _on_details_transition_complete(self) -> bool:
        self._details_resize_source_id = 0
        self._pending_details_mode = None
        if not self.details_open and getattr(self, "_library_results_dirty", False):
            self._library_results_dirty = False
            if self.active_destination == "library":
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
        action = details_back_action(
            self.detail_navigation.get_visible_page_tag()
        )
        if action == "pop-season":
            self._on_episode_back()
        elif action == "pop-title":
            self._on_season_back()
        else:
            self._set_details_open(False)
        return True

    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        if not self.details_open:
            return False
        self._set_details_open(False)
        return True

    def _on_window_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape and self._navigate_back():
            return True
        return False

    def _on_clear_filters(self, _button: Gtk.Button) -> None:
        self._updating = True
        self.search_entry.set_text("")
        self.genre_dropdown.set_selected(0)
        self.genre = "All genres"
        self._updating = False
        self._refresh_results()

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
            else "anime" if record.media_type == "Anime" else "shows"
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
            raise simkl_client.SimklError(
                "This title has no Simkl or TMDB identifier."
            )
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

    def _post_simkl_history(
        self, description: str, operation: Any
    ) -> dict[str, Any]:
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
            self._app_log("Could not invalidate stale Simkl snapshot: %s", error,
                          level=logging.WARNING)

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
        base_status = getattr(self, "_library_records_by_canonical", {}).get(
            canonical, record
        ).status
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
            self._refresh_results()

    def _run_simkl_mutation(
        self,
        key: str,
        operation: Any,
        on_success: Any,
        success_message: str,
    ) -> None:
        if not self._simkl_writable():
            self._update_details()
            self._toast("Connect Simkl to change ratings or lists")
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
                GLib.idle_add(
                    self._finish_simkl_mutation,
                    key,
                    None,
                    "",
                    str(error),
                )
                return
            GLib.idle_add(
                self._finish_simkl_mutation,
                key,
                on_success,
                success_message,
                None,
            )

        threading.Thread(
            target=worker,
            name="gisheh-simkl-write",
            daemon=True,
        ).start()

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
            on_success()
        if success_message:
            self._toast(success_message)
        return GLib.SOURCE_REMOVE

    def _write_simkl_list_change(
        self,
        record: TitleRecord,
        *,
        adding: bool,
        on_success: Any,
    ) -> None:
        if (
            getattr(self, "library_mode", LIBRARY_MODE_SIMKL)
            == LIBRARY_MODE_LOCAL
        ):
            self._ensure_local_library_record(record)
            on_success()
            self._toast(
                "Saved to your local watchlist"
                if adding
                else "Removed from your local watchlist"
            )
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
            raw_not_found = result.get("not_found") if isinstance(result, dict) else None
            if isinstance(raw_not_found, dict) and any(
                isinstance(items, list) and items for items in raw_not_found.values()
            ):
                raise simkl_client.SimklError("Simkl could not match this title.")
            return result

        self._run_simkl_mutation(
            f"{self._canonical_record_id(record)}:watchlist",
            checked_operation,
            on_success,
            "Added to Simkl watchlist" if adding else "Removed from Simkl watchlist",
        )

    def _on_watched_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        self._activate_record_watched(record)

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
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("change-date", "Change watched date")
        dialog.add_response("unwatch", "Mark as unwatched")
        dialog.set_response_appearance(
            "change-date", Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_response_appearance(
            "unwatch", Adw.ResponseAppearance.DESTRUCTIVE
        )
        dialog.set_close_response("cancel")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "change-date":
                self._show_watched_time_dialog(
                    title_text=f"Change watched date — {record.title}",
                    subtitle_text=(
                        "This replaces the existing watch date; it is not a rewatch."
                    ),
                    on_confirm=lambda iso: self._change_title_watched_date(record, iso),
                )
            elif response == "unwatch":
                self._mark_title_unwatched(record)

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _mark_title_unwatched(self, record: TitleRecord) -> None:
        """Remove watched history and return the title to the active watchlist."""
        canonical = self._canonical_record_id(record)

        def apply() -> None:
            self.completed.discard(canonical)
            self.bookmarks.add(canonical)
            self.title_watched_at.pop(canonical, None)
            base_status = getattr(self, "_library_records_by_canonical", {}).get(
                canonical, record
            ).status
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
                self._refresh_results()

        if not self._simkl_writable():
            if self._local_mode_active():
                apply()
                self._toast("Marked as unwatched locally (not synced)")
            else:
                self._toast("Connect Simkl to change watch history")
            return
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
            apply,
            "Marked as unwatched",
        )

    def _mark_title_watched(
        self, record: TitleRecord, iso_timestamp: str
    ) -> None:
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
                self._toast("Watched time saved locally (not synced)")
            else:
                self._toast("Connect Simkl to change watch history")
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
                    "This title is already marked as watched on Simkl. "
                    "Use Change watched date or unmark it first."
                )
                return
            if not outcome.changed:
                self._update_details()
                self._toast("Simkl did not confirm this watched update.")
                return
            self._apply_title_history_result(record, outcome, iso_timestamp)
            self._toast("Marked as watched")

        self._run_simkl_mutation(
            f"{record.id}:watched",
            operation,
            on_done,
            "",
        )

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
            self._refresh_results()
            self._toast("Watch date changed locally")
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
            self._apply_title_history_result(record, outcome_box["result"], iso_timestamp)
            self._toast("Watched date changed")

        self._run_simkl_mutation(
            f"{canonical}:change-watched-date",
            operation,
            on_done,
            "",
        )

    def _on_bookmark_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        adding = button.get_active()
        self._set_record_bookmarked(record, adding)

    def _set_record_bookmarked(
        self,
        record: TitleRecord,
        adding: bool,
    ) -> None:

        def apply_bookmark() -> None:
            canonical = self._canonical_record_id(record)
            if adding:
                if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
                    canonical = self._ensure_local_library_record(record)
                self.bookmarks.add(canonical)
                self.completed.discard(canonical)
                if self._effective_status(record) != "Watchlist":
                    self.status_overrides[canonical] = "Watchlist"
            else:
                self.bookmarks.discard(canonical)
                self.status_overrides.pop(canonical, None)
                self.completed.discard(canonical)
                if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
                    self._remove_unused_local_library_record(canonical)
                elif record.id in self.library_ids and record.id not in self.explore_ids:
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
            else:
                self._refresh_results()

        self._write_simkl_list_change(
            record,
            adding=adding,
            on_success=apply_bookmark,
        )

    def _on_rating_button_toggled(
        self,
        button: Gtk.ToggleButton,
        score: int,
    ) -> None:
        if self._updating_details or self.selected_id is None or not button.get_active():
            return
        self.rating_popover.popdown()
        record = self.records_by_id[self.selected_id]
        self._set_record_rating(record, score)

    def _set_record_rating(self, record: TitleRecord, score: int) -> None:

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
                self._refresh_results()

        if getattr(self, "library_mode", LIBRARY_MODE_LOCAL) == LIBRARY_MODE_LOCAL:
            apply_rating()
            self._toast(f"Your local rating is now {score}/10")
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
            f"Your Simkl rating is now {score}/10",
        )

    def _toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _app_log(
        self,
        message: str,
        *args: object,
        level: int = logging.INFO,
    ) -> None:
        application_logger().log(level, message, *args)
        if self._log_text_view is not None:
            GLib.idle_add(self._refresh_log_view)

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

        dialog = Adw.AlertDialog(
            heading="Application Log",
            body=str(application_log_file()),
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_size_request(700, 360)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add_css_class("card")
        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        text_view.set_left_margin(10)
        text_view.set_right_margin(10)
        text_view.set_top_margin(10)
        text_view.set_bottom_margin(10)
        scroller.set_child(text_view)
        content.append(scroller)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_args: self._refresh_log_view())
        actions.append(refresh)
        copy = Gtk.Button(label="Copy Log")
        copy.connect("clicked", self._on_copy_log_clicked)
        actions.append(copy)
        content.append(actions)

        dialog.set_extra_child(content)
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.connect("response", self._on_log_dialog_response)
        self._log_dialog = dialog
        self._log_text_view = text_view
        self._refresh_log_view()
        dialog.present(self.window)

    def _on_copy_log_clicked(self, _button: Gtk.Button) -> None:
        self.window.get_clipboard().set_text(read_application_log())
        self._toast("Application log copied")

    def _on_log_dialog_response(
        self,
        _dialog: Adw.AlertDialog,
        _response: str,
    ) -> None:
        self._log_dialog = None
        self._log_text_view = None
