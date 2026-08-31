#!/usr/bin/env python3
"""CineShelf: a lightweight native GTK4/libadwaita movie library."""

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmdb_client  # noqa: E402
import simkl_client  # noqa: E402


APP_ID = "io.github.cineshelf.CineShelf"
APP_NAME = "CineShelf"
APP_VERSION = "1.3.0"
RESOURCE_DIR = Path(__file__).resolve().parent
UI_FILE = RESOURCE_DIR / "cineshelf.ui"
CSS_FILE = RESOURCE_DIR / "cineshelf.css"
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
STATUSES = ("Watching", "Watched", "On Hold", "Calendar", "Dropped")
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
GRID_CARD_WIDTH = 132
GRID_COLUMN_GAP = 12
GRID_HORIZONTAL_PADDING = 24
GRID_MAX_COLUMNS = 8
GRID_ROW_HEIGHT = 246

STATUS_ICONS = {
    "Watching": "media-playback-start-symbolic",
    "Watchlist": "bookmark-new-symbolic",
    "Watched": "emblem-ok-symbolic",
    "On Hold": "media-playback-pause-symbolic",
    "Calendar": "x-office-calendar-symbolic",
    "Dropped": "user-trash-symbolic",
}

LISTS = (("Watchlist", "bookmark-new-symbolic"),)

LANGUAGE_BY_COUNTRY = {
    "Algeria": "AR",
    "Germany": "DE",
    "Iran": "FA",
    "Japan": "JA",
    "United Kingdom": "EN",
    "United States": "EN",
}

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


def application_log_file() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )
    return base / APP_ID / "cineshelf.log"


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


def user_state_file() -> Path:
    configured = os.environ.get("CINESHELF_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / APP_ID / "state.json"


def runtime_minutes(value: str) -> int:
    """Convert the catalog's compact duration strings to minutes."""
    hours = re.search(r"(\d+)\s*h", value)
    minutes = re.search(r"(\d+)\s*m", value)
    if hours or minutes:
        return (int(hours.group(1)) * 60 if hours else 0) + (
            int(minutes.group(1)) if minutes else 0
        )
    return 0


def parse_watched_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%b %d, %Y at %I:%M %p").date()
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None


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


def grid_columns_for_width(width: int) -> int:
    """Return the FlowBox column count implied by the card's real minimum width."""
    content_width = max(1, width - GRID_HORIZONTAL_PADDING)
    columns = (content_width + GRID_COLUMN_GAP) // (
        GRID_CARD_WIDTH + GRID_COLUMN_GAP
    )
    return max(1, min(GRID_MAX_COLUMNS, columns))


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


@dataclass(frozen=True, slots=True)
class SeasonInfo:
    id: str
    number: int
    title: str
    watched: int
    episodes: int
    episode_items: tuple[EpisodeInfo, ...] = ()


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
    artwork_file: str | None = None
    poster_file: str | None = None
    backdrop_file: str | None = None
    gallery_backdrops: tuple[str, ...] = ()
    gallery_posters: tuple[str, ...] = ()
    video_titles: tuple[str, ...] = ()

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
            certification=str(
                raw.get("certification", "TV-MA" if media_type != "Movies" else "NR")
            ),
            language=str(raw.get("language", LANGUAGE_BY_COUNTRY.get(country, "—"))),
            availability=str(
                raw.get(
                    "availability",
                    "Upcoming"
                    if "discoverPeriod" in raw
                    else "Airing" if media_type != "Movies" else "Released",
                )
            ),
            network=str(raw.get("network", "CineShelf")),
            external_ratings=tuple(
                (str(item["source"]), str(item["value"]))
                for item in raw.get("externalRatings", ())
            ),
            cast=tuple(
                CastMember(str(item["name"]), str(item["role"]))
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
        )


def load_catalog() -> tuple[
    tuple[TitleRecord, ...],
    tuple[TitleRecord, ...],
    dict[str, dict[str, int]],
]:
    with DATA_FILE.open(encoding="utf-8") as source:
        payload = json.load(source)

    records = tuple(TitleRecord.from_mapping(raw) for raw in payload["library"])
    explore_records = tuple(
        TitleRecord.from_mapping(raw) for raw in payload.get("explore", ())
    )
    totals = {
        str(media): {str(status): int(count) for status, count in values.items()}
        for media, values in payload["totals"].items()
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
        certification="NR",
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

    runtime_minutes = int(payload.get("runtime") or 0)
    if not runtime_minutes:
        episode_runtimes = payload.get("episode_run_time") or ()
        runtime_minutes = int(episode_runtimes[0]) if episode_runtimes else 0
    runtime = (
        f"{runtime_minutes // 60}h {runtime_minutes % 60:02d}m"
        if runtime_minutes >= 60
        else f"{runtime_minutes}m" if runtime_minutes else record.runtime
    )

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
            watched_count = int(entry.get("watched_episodes_count") or 0)
            total_count = int(entry.get("total_episodes_count") or 0)
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
                runtime="Loading from TMDB…",
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
                certification="NR",
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
    columns = max(2, columns)
    if columns == 2:
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
    ) -> None:
        super().__init__()
        self.record = record
        self.variant_offset = variant_offset
        self.show_text = show_text
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


class PosterWidget(Gtk.Overlay):
    """Display cached TMDB artwork, falling back to the local poster renderer."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
    ) -> None:
        super().__init__()
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
            self.set_child(picture)
        else:
            generated = GeneratedPosterWidget(
                record,
                width,
                height,
                variant_offset=variant_offset,
                show_text=show_text,
            )
            generated.set_hexpand(True)
            generated.set_vexpand(True)
            self.set_child(generated)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
        count: int | None,
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
        self.count_label = Gtk.Label(label="" if count is None else str(count))
        self.count_label.add_css_class("caption")
        self.count_label.add_css_class("numeric")
        self.count_label.set_visible(count is not None)

        content.append(icon)
        content.append(title)
        content.append(self.count_label)
        self.set_child(content)

    def set_count(self, count: int) -> None:
        self.count_label.set_label(str(count))
        self.count_label.set_visible(True)


class CineShelfWindow:
    """Controller for the Gtk.Builder-defined window."""

    def __init__(self, application: Adw.Application) -> None:
        missing = [path.name for path in (UI_FILE, CSS_FILE, DATA_FILE) if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing application files: {', '.join(missing)}")

        self.records, self.explore_records, self.totals = load_catalog()
        self.simkl_client_id = simkl_client.read_client_id()
        self.simkl_token = simkl_client.read_token()
        self.tmdb_token = tmdb_client.read_token()
        self.simkl_settings: dict[str, Any] = {}
        self.simkl_stats: dict[str, Any] = {}
        self.simkl_connected = False
        self.simkl_snapshot_needs_repair = False
        if self.simkl_client_id and self.simkl_token:
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

        self.active_destination = "library"
        self.active_media = "Movies"
        self.active_status = "Watched"
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

        self.bookmarks = {
            record.id for record in self.records if record.status == "Watchlist"
        }
        self.favorites = (
            set()
            if self.simkl_connected
            else {"oppenheimer", "perfect-days", "frieren"}
        )
        self.completed = {
            record.id for record in self.records if record.status == "Watched"
        }
        self.ratings = {
            record.id: record.user_rating
            for record in self.records
            if record.user_rating is not None
        }
        self.status_overrides: dict[str, str] = {}
        self.episode_status_overrides: dict[str, bool] = {}
        self.episode_watched_at: dict[str, str] = {}
        self.title_watched_at: dict[str, str] = {}
        self._tmdb_details_loading: set[str] = set()
        self._tmdb_details_loaded: set[str] = set()
        self._tmdb_detail_generations: dict[str, int] = {}
        self._tmdb_explore_generation = 0
        self._tmdb_library_generation = 0
        self._tmdb_library_refresh_source_id = 0
        self._log_dialog: Adw.AlertDialog | None = None
        self._log_text_view: Gtk.TextView | None = None
        self._simkl_sync_started_at = 0.0
        self._simkl_mutations_inflight: set[str] = set()
        self.state_file = user_state_file()
        self._load_user_state()
        application_logger().info("CineShelf %s started", APP_VERSION)

        self._updating = False
        self._updating_details = False
        self._updating_season_switcher = False
        self.details_open = False
        self.detail_record_id: str | None = None
        self.current_season_index = 0
        self.current_episode_index = 0
        self.status_rows: dict[str, SidebarRow] = {}

        self.builder = Gtk.Builder.new_from_file(str(UI_FILE))
        self.window: Adw.ApplicationWindow = self._object("window")
        self.window.set_application(application)
        self.window.set_size_request(940, 600)

        self._load_css()
        self._bind_objects()
        self._build_browser_stack()
        self._configure_accessibility()
        self._build_header_controls()
        self._build_sidebar()
        self._build_result_views()
        self._build_explore_view()
        self._build_profile_view()
        self._build_detail_sections()
        self._connect_signals(application)
        self._update_genre_model()
        self._refresh_results()
        if self.tmdb_token:
            self._load_tmdb_explore_async()
        if self.simkl_client_id and self.simkl_token:
            if self.simkl_snapshot_needs_repair:
                self._app_log(
                    "Incomplete Simkl snapshot detected; scheduling state repair.",
                    level=logging.WARNING,
                )
            else:
                self._app_log("Scheduling Simkl user-state refresh.")
            GLib.idle_add(self._start_simkl_sync)

    def _object(self, name: str) -> Any:
        obj = self.builder.get_object(name)
        if obj is None:
            raise RuntimeError(f"The UI is missing required object '{name}'")
        return obj

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
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
            "media_switcher",
            "main_menu_button",
            "search_button",
            "add_sidebar_button",
            "destination_list",
            "status_list",
            "collections_list",
            "storage_button",
            "storage_progress",
            "preferences_button",
            "main_workspace",
            "library_pane",
            "eyebrow_label",
            "section_title",
            "section_count",
            "add_title_button",
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
            "favorite_button",
            "bookmark_button",
            "more_button",
            "runtime_label",
            "genres_label",
            "overview_label",
            "quick_actions_host",
            "creator_row",
            "release_row",
            "country_row",
            "activity_row",
            "activity_status",
            "activity_percentage",
            "activity_progress",
            "rating_value",
            "rating_grid",
            "detail_extra_sections",
            "explore_pane",
            "explore_header",
            "explore_eyebrow_label",
            "explore_count_label",
            "explore_filter_bar",
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
        self.browser_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.browser_stack.set_transition_duration(160)
        self.browser_stack.add_named(self.library_pane, "library")
        self.browser_stack.add_named(self.explore_pane, "explore")
        self.browser_stack.set_visible_child_name("library")
        self.main_workspace.prepend(self.browser_stack)

        self.details_surface.set_child(None)
        details_layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        details_layout.add_css_class("detail-panel-layout")
        details_layout.append(self.detail_navigation)
        self.details_surface.set_child(details_layout)
        self.details_surface.set_visible(True)

        panel_layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        panel_layout.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        panel_layout.append(self.details_surface)

        self.details_revealer = Gtk.Revealer()
        self.details_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_LEFT
        )
        self.details_revealer.set_transition_duration(220)
        self.details_revealer.set_reveal_child(False)
        self.details_revealer.set_child(panel_layout)
        self.main_workspace.append(self.details_revealer)

    def _configure_accessibility(self) -> None:
        self.storage_progress.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Local library storage usage"],
        )
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
            print(f"CineShelf could not read user state: {error}", file=sys.stderr)
            return

        valid_ids = set(self.records_by_id)
        def is_valid_id(value: object) -> bool:
            record_id = str(value)
            return (
                record_id in valid_ids
                or record_id.startswith("tmdb-")
                or (bool(self.simkl_token) and record_id.startswith("simkl-"))
            )
        self.bookmarks = {
            value
            for value in payload.get("bookmarks", self.bookmarks)
            if is_valid_id(value)
        }
        self.favorites = {
            value
            for value in payload.get("favorites", self.favorites)
            if is_valid_id(value)
        }
        self.completed = {
            value
            for value in payload.get("completed", self.completed)
            if is_valid_id(value)
        }
        self.ratings = {
            record_id: int(score)
            for record_id, score in payload.get("ratings", self.ratings).items()
            if is_valid_id(record_id) and isinstance(score, int) and 1 <= score <= 10
        }
        self.status_overrides = {
            record_id: status
            for record_id, status in payload.get("statusOverrides", {}).items()
            if is_valid_id(record_id) and status in LIBRARY_FILTERS
        }
        self.episode_status_overrides = {
            str(key): value
            for key, value in payload.get("episodeStatusOverrides", {}).items()
            if isinstance(value, bool)
            and is_valid_id(str(key).split("/", 1)[0])
        }
        self.episode_watched_at = {
            str(key): str(value)
            for key, value in payload.get("episodeWatchedAt", {}).items()
            if isinstance(value, str)
            and is_valid_id(str(key).split("/", 1)[0])
        }
        self.title_watched_at = {
            str(key): str(value)
            for key, value in payload.get("titleWatchedAt", {}).items()
            if isinstance(value, str) and is_valid_id(str(key))
        }

        for record_id, status in self.status_overrides.items():
            if status == "Watched":
                self.completed.add(record_id)
            else:
                self.completed.discard(record_id)

    def _save_user_state(self) -> None:
        payload = {
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
        temporary = self.state_file.with_name(f".{self.state_file.name}.tmp")
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.state_file)
        except OSError as error:
            print(f"CineShelf could not save user state: {error}", file=sys.stderr)

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
        self.media_switcher.set_active_name("movies")

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
        self.view_switcher.set_active_name("list")

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
        menu.append("Application Log", "app.logs")
        menu.append("About CineShelf", "app.about")
        menu.append("Quit", "app.quit")
        self.main_menu_button.set_menu_model(menu)

    def _build_sidebar(self) -> None:
        self.library_row = SidebarRow(
            "library",
            "Library",
            "folder-symbolic",
            self._library_total(self.active_media),
        )
        self.explore_row = SidebarRow(
            "explore",
            "Explore",
            "find-location-symbolic",
            self._explore_total(self.active_media),
        )
        self.profile_row = SidebarRow(
            "profile",
            "Profile",
            "avatar-default-symbolic",
            None,
        )
        self.destination_list.append(self.library_row)
        self.destination_list.append(self.explore_row)
        self.destination_list.append(self.profile_row)

        for status in STATUSES:
            row = SidebarRow(
                status,
                status,
                STATUS_ICONS[status],
                self._status_total(self.active_media, status),
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
                self._status_total(self.active_media, label),
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
        self.grid_box.set_max_children_per_line(8)
        self.grid_box.set_row_spacing(16)
        self.grid_box.set_column_spacing(12)
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
            description="Try another period or clear the genre filter.",
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

        self._update_explore_genre_model()

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

        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hero.add_css_class("profile-hero")
        profile_user = self.simkl_settings.get("user", {})
        profile_account = self.simkl_settings.get("account", {})
        profile_name = str(profile_user.get("name") or getuser())
        self.profile_avatar = Adw.Avatar(
            size=72,
            text=profile_name,
            show_initials=True,
        )
        self.profile_avatar.add_css_class("profile-avatar")
        cached_avatar = simkl_client.cached_avatar() if self.simkl_connected else None
        if cached_avatar:
            try:
                self.profile_avatar.set_custom_image(
                    Gdk.Texture.new_from_filename(cached_avatar)
                )
            except GLib.Error:
                pass
        else:
            self.profile_avatar.set_custom_image(None)
        hero.append(self.profile_avatar)

        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        identity.set_hexpand(True)
        identity.set_valign(Gtk.Align.CENTER)
        self.profile_name_label = Gtk.Label(label=profile_name, xalign=0)
        self.profile_name_label.add_css_class("title-1")
        identity.append(self.profile_name_label)
        account_type = str(profile_account.get("type") or "").upper()
        subtitle_text = (
            f"Connected to Simkl · {account_type or 'Account'}"
            if self.simkl_connected
            else "Local profile · Connect Simkl to sync your library"
        )
        self.profile_subtitle_label = Gtk.Label(label=subtitle_text, xalign=0)
        self.profile_subtitle_label.add_css_class("dim-label")
        identity.append(self.profile_subtitle_label)
        hero.append(identity)

        hero_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hero_actions.set_valign(Gtk.Align.CENTER)
        self.simkl_button = Gtk.Button(
            label="Sync Simkl" if self.simkl_connected else "Connect Simkl"
        )
        self.simkl_button.set_tooltip_text(
            "Refresh data from Simkl"
            if self.simkl_connected
            else "Sign in to Simkl"
        )
        self.simkl_button.add_css_class("pill")
        if not self.simkl_connected:
            self.simkl_button.add_css_class("suggested-action")
        self.simkl_button.connect("clicked", self._on_simkl_button_clicked)
        hero_actions.append(self.simkl_button)
        self.simkl_disconnect_button = Gtk.Button.new_from_icon_name(
            "system-log-out-symbolic"
        )
        self.simkl_disconnect_button.set_tooltip_text("Disconnect Simkl")
        self.simkl_disconnect_button.add_css_class("flat")
        self.simkl_disconnect_button.add_css_class("circular")
        self.simkl_disconnect_button.set_visible(self.simkl_connected)
        self.simkl_disconnect_button.connect(
            "clicked",
            self._on_simkl_disconnect_clicked,
        )
        hero_actions.append(self.simkl_disconnect_button)

        settings = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        settings.set_tooltip_text("Profile settings")
        settings.add_css_class("flat")
        settings.add_css_class("circular")
        settings.set_valign(Gtk.Align.CENTER)
        settings.connect("clicked", self._on_preferences_clicked)
        hero_actions.append(settings)
        hero.append(hero_actions)
        content.append(hero)

        self.profile_tabs = Adw.ToggleGroup()
        for key, label in (
            ("statistics", "Statistics"),
            ("watched", "Watched"),
        ):
            self.profile_tabs.add(Adw.Toggle(name=key, label=label))
        self.profile_tabs.set_active_name("statistics")
        self.profile_tabs.set_halign(Gtk.Align.START)
        content.append(self.profile_tabs)

        self.profile_stack = Gtk.Stack()
        self.profile_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.profile_stack.set_transition_duration(180)
        self.profile_stack.set_vhomogeneous(False)
        self.profile_statistics_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
        )
        self.profile_watched_host = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        self.profile_stack.add_named(self.profile_statistics_host, "statistics")
        self.profile_stack.add_named(self.profile_watched_host, "watched")
        content.append(self.profile_stack)
        self.profile_tabs.connect("notify::active-name", self._on_profile_tab_changed)

        self.browser_stack.add_named(self.profile_pane, "profile")
        self._refresh_profile()

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
        value_label.add_css_class("title-2")
        card.append(value_label)
        label_widget = Gtk.Label(label=label, xalign=0)
        label_widget.add_css_class("dim-label")
        card.append(label_widget)
        return card

    def _profile_stats(self) -> dict[str, Any]:
        watched_records = tuple(
            record for record in self.records if record.id in self.completed
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
            for season_index, season in enumerate(self._series_seasons(record)):
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
                record = self.records_by_id.get(key.split("/", 1)[0])
                if record is not None:
                    per_episode = runtime_minutes(record.runtime)
                    if per_episode == 0:
                        per_episode = 24 if record.media_type == "Anime" else 45
                    episode_events.append((watched_date, per_episode))
        for record_id, watched_at in self.title_watched_at.items():
            watched_date = parse_watched_date(watched_at)
            if watched_date is not None:
                activity[watched_date] += 1
                record = self.records_by_id.get(record_id)
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
        self._refresh_profile_watched(stats)

    def _refresh_profile_watched(self, stats: dict[str, Any]) -> None:
        self._clear_container(self.profile_watched_host)
        self.profile_watched_host.append(
            self._profile_heading(
                "Watched titles",
                f"{len(stats['watched_records'])} completed",
            )
        )
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_min_children_per_line(2)
        grid.set_max_children_per_line(8)
        grid.set_column_spacing(12)
        grid.set_row_spacing(14)
        for record in stats["watched_records"]:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            content.append(PosterWidget(record, 96, 144))
            label = Gtk.Label(label=record.title)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(14)
            label.add_css_class("caption")
            content.append(label)
            button = Gtk.Button(child=content)
            button.add_css_class("flat")
            button.add_css_class("profile-poster-card")
            button.connect(
                "clicked",
                lambda _button, record_id=record.id: self._on_profile_record_clicked(
                    record_id
                ),
            )
            grid.append(button)
        self.profile_watched_host.append(grid)

    def _on_profile_tab_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        active = group.get_active_name()
        if active in ("statistics", "watched"):
            self.profile_stack.set_visible_child_name(active)

    def _on_profile_record_clicked(self, record_id: str) -> None:
        record = self.records_by_id.get(record_id)
        if record is None:
            return
        self.selected_id = record_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(record)

    def _on_simkl_button_clicked(self, _button: Gtk.Button) -> None:
        if self.simkl_connected and self.simkl_client_id and self.simkl_token:
            self._app_log("Manual Simkl refresh requested.")
            self._start_simkl_sync()
            return
        self._simkl_sync_started_at = 0.0
        self._app_log("Simkl connection flow opened.")
        dialog = Adw.AlertDialog(
            heading="Connect Simkl",
            body=(
                "Create an app in Simkl Developer Settings, then paste its "
                "Client ID here. CineShelf uses the PIN flow and never needs "
                "your Client Secret or password."
            ),
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Simkl Client ID")
        entry.set_text(self.simkl_client_id or "")
        entry.set_activates_default(True)
        content.append(entry)
        developer_link = Gtk.LinkButton(
            uri="https://simkl.com/settings/developer/",
            label="Open Simkl Developer Settings",
        )
        developer_link.set_halign(Gtk.Align.START)
        content.append(developer_link)
        dialog.set_extra_child(content)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("continue", "Continue")
        dialog.set_default_response("continue")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance(
            "continue",
            Adw.ResponseAppearance.SUGGESTED,
        )
        dialog.connect("response", self._on_simkl_client_id_response, entry)
        dialog.present(self.window)

    def _on_simkl_client_id_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
        entry: Gtk.Entry,
    ) -> None:
        if response != "continue":
            return
        client_id = entry.get_text().strip()
        if not client_id:
            self._toast("Enter a Simkl Client ID")
            return
        try:
            simkl_client.store_client_id(client_id)
        except simkl_client.SimklError as error:
            self._app_log(
                "Could not save the Simkl Client ID: %s",
                error,
                level=logging.ERROR,
            )
            self._toast("Could not save the Simkl Client ID")
            return
        self.simkl_client_id = client_id
        self._app_log("Simkl Client ID saved; requesting a PIN.")
        self.simkl_button.set_sensitive(False)
        self.simkl_button.set_label("Requesting PIN…")
        threading.Thread(
            target=self._simkl_pin_worker,
            args=(client_id,),
            name="cineshelf-simkl-pin",
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
                "code below. CineShelf will finish automatically after approval."
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
            name="cineshelf-simkl-poll",
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
        self.simkl_button.set_sensitive(True)
        self.simkl_button.set_label("Connect Simkl")
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
            simkl_client.store_token(access_token)
        except simkl_client.SimklError as error:
            return self._on_simkl_failed(str(error), error.code)
        self.simkl_token = access_token
        self._app_log("Simkl authorization approved; access token stored securely.")
        if getattr(self, "simkl_pin_dialog", None) is not None:
            self.simkl_pin_dialog.close()
        self._toast("Simkl connected — syncing your library…")
        self._start_simkl_sync()
        return GLib.SOURCE_REMOVE

    def _start_simkl_sync(self) -> None:
        if not self.simkl_client_id or not self.simkl_token:
            return
        self._simkl_sync_started_at = time.monotonic()
        self._app_log("Simkl sync started.")
        self.simkl_button.set_sensitive(False)
        self.simkl_button.set_label("Syncing…")
        self.simkl_disconnect_button.set_sensitive(False)
        threading.Thread(
            target=self._simkl_sync_worker,
            args=(self.simkl_client_id, self.simkl_token),
            name="cineshelf-simkl-sync",
            daemon=True,
        ).start()

    def _simkl_sync_worker(self, client_id: str, token: str) -> None:
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
            state_is_valid = (
                cached_library is not None
                and simkl_client.library_has_user_state(cached_library)
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
        )

    def _replace_library(self, records: tuple[TitleRecord, ...]) -> None:
        self.records = records
        self.library_ids = {record.id for record in records}
        self.records_by_id = {
            record.id: record for record in (*records, *self.explore_records)
        }
        default_record = next(
            (record for record in records if record.status == "Watched"),
            records[0] if records else None,
        )
        self.selected_id = default_record.id if default_record is not None else None
        self.library_selected_id = self.selected_id
        self.status_overrides = {
            record_id: status
            for record_id, status in self.status_overrides.items()
            if record_id in self.library_ids
        }

    def _apply_simkl_sync(
        self,
        settings: dict[str, Any],
        stats: dict[str, Any],
        records: tuple[TitleRecord, ...],
    ) -> bool:
        self.simkl_settings = settings
        self.simkl_stats = stats
        self.simkl_connected = True
        self.simkl_snapshot_needs_repair = False
        self._replace_library(records)
        self.completed = {
            record.id for record in records if record.status == "Watched"
        }
        self.bookmarks = {
            record.id for record in records if record.status == "Watchlist"
        }
        self.ratings = {
            record.id: record.user_rating
            for record in records
            if record.user_rating is not None
        }
        self.title_watched_at = {
            record.id: record.date
            for record in records
            if record.status == "Watched"
            and parse_watched_date(record.date) is not None
        }
        self.episode_watched_at = {}
        self.episode_status_overrides = {}
        self.favorites.intersection_update(self.library_ids)
        self._save_user_state()
        self._tmdb_details_loading.clear()
        self._tmdb_details_loaded.clear()
        self._update_profile_identity()
        self.simkl_button.set_sensitive(False)
        self.simkl_disconnect_button.set_sensitive(False)
        self._update_sidebar_counts()
        self._update_genre_model()
        self._refresh_results()
        self._refresh_profile()
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
                name="cineshelf-simkl-avatar",
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
        self.simkl_button.set_label("Finishing…")
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
            self.profile_avatar.set_custom_image(
                Gdk.Texture.new_from_filename(avatar_file)
            )
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
        self.simkl_disconnect_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def _update_profile_identity(self) -> None:
        user = self.simkl_settings.get("user", {})
        account = self.simkl_settings.get("account", {})
        name = str(user.get("name") or getuser()) if isinstance(user, dict) else getuser()
        account_type = (
            str(account.get("type") or "Account").upper()
            if isinstance(account, dict)
            else "Account"
        )
        self.profile_name_label.set_label(name)
        self.profile_avatar.set_text(name)
        cached_avatar = simkl_client.cached_avatar()
        if cached_avatar:
            try:
                self.profile_avatar.set_custom_image(
                    Gdk.Texture.new_from_filename(cached_avatar)
                )
            except GLib.Error:
                pass
        self.profile_subtitle_label.set_label(
            f"Connected to Simkl · {account_type}"
            if self.simkl_connected
            else "Local profile · Connect Simkl to sync your library"
        )
        self.simkl_button.set_label(
            "Sync Simkl" if self.simkl_connected else "Connect Simkl"
        )
        self.simkl_button.set_tooltip_text(
            "Refresh data from Simkl"
            if self.simkl_connected
            else "Sign in to Simkl"
        )
        self.simkl_button.remove_css_class("suggested-action")
        if not self.simkl_connected:
            self.simkl_button.add_css_class("suggested-action")
        self.simkl_disconnect_button.set_visible(self.simkl_connected)
        self.simkl_disconnect_button.set_sensitive(True)
        self.simkl_button.set_sensitive(True)

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
            record.id for record in records if record.status == "Watched"
        }
        self.bookmarks = {
            record.id for record in records if record.status == "Watchlist"
        }
        self.ratings = {
            record.id: record.user_rating
            for record in records
            if record.user_rating is not None
        }
        self.favorites.intersection_update(self.library_ids)
        self.status_overrides = {}
        self.episode_status_overrides = {}
        self.episode_watched_at = {}
        self.title_watched_at = {
            record.id: record.date
            for record in records
            if record.status == "Watched"
            and parse_watched_date(record.date) is not None
        }
        self._save_user_state()
        self._update_profile_identity()
        self._update_sidebar_counts()
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

        self.episode_cards_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
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

        self.season_switcher = Adw.ToggleGroup()
        self.season_switcher_record_id: str | None = None
        self.season_switcher.set_halign(Gtk.Align.START)
        season_switcher_scroller = Gtk.ScrolledWindow()
        season_switcher_scroller.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.NEVER,
        )
        season_switcher_scroller.set_propagate_natural_height(True)
        season_switcher_scroller.set_child(self.season_switcher)

        self.season_summary_label = Gtk.Label(xalign=0)
        self.season_summary_label.add_css_class("dim-label")

        season_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            homogeneous=True,
        )
        self.season_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        self.season_comments_button = self._detail_navigation_action(
            "mail-unread-symbolic",
            "Comments",
        )
        season_actions.append(self.season_watched_button)
        season_actions.append(self.season_comments_button)

        episodes_heading = Gtk.CenterBox()
        episodes_title = Gtk.Label(label="Episodes", xalign=0)
        episodes_title.add_css_class("title-4")
        self.season_episode_count = Gtk.Label()
        self.season_episode_count.add_css_class("caption")
        self.season_episode_count.add_css_class("dim-label")
        episodes_heading.set_start_widget(episodes_title)
        episodes_heading.set_end_widget(self.season_episode_count)

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
        self.season_detail_box.append(season_switcher_scroller)
        self.season_detail_box.append(self.season_summary_label)
        self.season_detail_box.append(season_actions)
        self.season_detail_box.append(Gtk.Separator())
        self.season_detail_box.append(episodes_heading)
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

        self.episode_position_label = Gtk.Label(xalign=0)
        self.episode_position_label.add_css_class("dim-label")
        self.episode_position_dots = Gtk.Label(xalign=1)
        self.episode_position_dots.add_css_class("numeric")
        self.episode_position_dots.add_css_class("dim-label")
        episode_position = Gtk.CenterBox()
        episode_position.set_start_widget(self.episode_position_label)
        episode_position.set_end_widget(self.episode_position_dots)

        self.episode_hero_host = Gtk.Box()
        self.episode_hero_host.set_halign(Gtk.Align.CENTER)
        self.episode_hero_host.set_hexpand(True)
        self.episode_hero_host.set_size_request(-1, 200)

        self.episode_title_label = Gtk.Label(xalign=0)
        self.episode_title_label.set_wrap(True)
        self.episode_title_label.add_css_class("title-1")
        self.episode_date_label = Gtk.Label(xalign=0)
        self.episode_date_label.add_css_class("dim-label")

        episode_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
        self.episode_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        self.episode_comments_button = self._detail_navigation_action(
            "mail-unread-symbolic",
            "Comments",
        )
        self.episode_check_in_button = self._detail_navigation_action(
            "media-playback-start-symbolic",
            "Check in",
        )
        episode_actions.append(self.episode_watched_button)
        episode_actions.append(self.episode_comments_button)
        episode_actions.append(self.episode_check_in_button)

        self.episode_watched_at_label = Gtk.Label(xalign=0.5)
        self.episode_watched_at_label.set_wrap(True)
        self.episode_watched_at_label.add_css_class("caption")
        self.episode_watched_at_label.add_css_class("dim-label")

        overview_title = Gtk.Label(label="Overview", xalign=0)
        overview_title.add_css_class("title-4")
        self.episode_overview_label = Gtk.Label(xalign=0)
        self.episode_overview_label.set_wrap(True)
        self.episode_overview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.episode_overview_label.add_css_class("dim-label")

        cast_heading = Gtk.Label(label="Cast & Crew", xalign=0)
        cast_heading.add_css_class("title-4")
        self.episode_cast_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )

        self.episode_detail_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.episode_detail_box.set_vexpand(True)
        self.episode_detail_box.set_margin_top(14)
        self.episode_detail_box.set_margin_bottom(28)
        self.episode_detail_box.set_margin_start(16)
        self.episode_detail_box.set_margin_end(16)
        self.episode_detail_box.add_css_class("detail-page")
        self.episode_detail_box.add_css_class("detail-subpage-content")
        self.episode_detail_box.append(episode_position)
        self.episode_detail_box.append(self.episode_hero_host)
        self.episode_detail_box.append(self.episode_title_label)
        self.episode_detail_box.append(self.episode_date_label)
        self.episode_detail_box.append(episode_actions)
        self.episode_detail_box.append(self.episode_watched_at_label)
        self.episode_detail_box.append(Gtk.Separator())
        self.episode_detail_box.append(overview_title)
        self.episode_detail_box.append(self.episode_overview_label)
        self.episode_detail_box.append(Gtk.Separator())
        self.episode_detail_box.append(cast_heading)
        self.episode_detail_box.append(
            self._horizontal_scroller(self.episode_cast_box, 116)
        )

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
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        caption = Gtk.Label(label=label)
        caption.set_wrap(True)
        caption.add_css_class("caption")
        content.append(icon)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("flat")
        button.add_css_class("detail-action-button")
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

        heading = Gtk.CenterBox()
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        heading.set_start_widget(label)

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
            heading.set_end_widget(end_box)

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
        scroller.set_propagate_natural_height(True)
        scroller.set_child(child)
        return scroller

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
            lambda *_args: self._toast("Release calendar opened"),
        )
        self.sort_direction_button.connect("clicked", self._on_reverse_sort)
        self.image_switcher.connect("notify::active-name", self._on_image_mode_changed)
        self.season_switcher.connect(
            "notify::active-name",
            self._on_season_switch_changed,
        )

        self.search_button.connect("clicked", self._on_search_requested)
        self.add_sidebar_button.connect(
            "clicked", lambda *_args: self._toast("Add dialog opened")
        )
        self.add_title_button.connect(
            "clicked",
            lambda *_args: self._toast(
                f"Add {self.active_media.lower()} to {self.active_status.lower()}"
            ),
        )
        self.storage_button.connect(
            "clicked", lambda *_args: self._toast("Library storage: 68% used")
        )
        self.preferences_button.connect("clicked", self._on_preferences_clicked)
        self.more_button.connect("clicked", self._on_more_clicked)
        self.watched_button.connect("clicked", self._on_watched_clicked)
        self.favorite_button.connect("toggled", self._on_favorite_toggled)
        self.bookmark_button.connect("toggled", self._on_bookmark_toggled)
        self.season_watched_button.connect(
            "clicked",
            self._on_season_watched_clicked,
        )
        self.season_comments_button.connect(
            "clicked",
            lambda *_args: self._toast("Season comments opened"),
        )
        self.episode_watched_button.connect(
            "clicked",
            self._on_episode_watched_clicked,
        )
        self.episode_comments_button.connect(
            "clicked",
            lambda *_args: self._toast("Episode comments opened"),
        )
        self.episode_check_in_button.connect(
            "clicked",
            lambda *_args: self._toast("Episode check-in recorded"),
        )

        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", self._on_search_requested)
        self.window.add_action(search_action)
        application.set_accels_for_action("win.search", ["<primary>k"])

        sidebar_action = Gio.SimpleAction.new("toggle-sidebar", None)
        sidebar_action.connect(
            "activate",
            lambda *_args: self.sidebar_toggle_button.set_active(
                not self.sidebar_toggle_button.get_active()
            ),
        )
        self.window.add_action(sidebar_action)
        application.set_accels_for_action("win.toggle-sidebar", ["<primary>b"])

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_search_key_pressed)
        self.search_entry.add_controller(key_controller)

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
        self._queue_explore_resize()

    def _on_surface_width_changed(
        self,
        _surface: Gdk.Surface,
        _parameter: Any,
    ) -> None:
        self._queue_explore_resize()

    def _queue_explore_resize(self) -> None:
        if self._explore_resize_source_id:
            GLib.source_remove(self._explore_resize_source_id)
        self._explore_resize_source_id = GLib.timeout_add(
            90,
            self._apply_explore_resize,
        )

    def _apply_explore_resize(self) -> bool:
        self._explore_resize_source_id = 0
        width = self.explore_pane.get_width() or self.library_pane.get_width()
        if width <= 0:
            return GLib.SOURCE_REMOVE
        columns = self._explore_columns_for_width(width)
        columns_changed = columns != self.explore_columns
        width_changed = abs(width - self._last_explore_layout_width) >= 12
        self._last_explore_layout_width = width
        self.explore_columns = columns
        if (
            self.active_destination == "explore"
            and self.explore_visible_records
            and (columns_changed or width_changed)
        ):
            scroll_value = self.explore_scroller.get_vadjustment().get_value()
            self._populate_explore_feed()
            self._scroll_to_value(self.explore_scroller, scroll_value)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _explore_columns_for_width(width: int) -> int:
        return 5 if width >= 760 else 4 if width >= 540 else 3 if width >= 390 else 2

    def _explore_card_height(self, kind: str, span: int) -> int:
        """Size a card from its real grid span instead of its child request."""
        pane_width = (
            self._last_explore_layout_width
            or self.explore_pane.get_width()
            or self.library_pane.get_width()
            or 620
        )
        content_width = max(280, pane_width - 48)
        columns = max(2, self.explore_columns)
        column_width = max(88, (content_width - 10 * (columns - 1)) / columns)
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
            name="cineshelf-tmdb-library",
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
        threading.Thread(
            target=self._load_tmdb_explore_worker,
            args=(token, generation, self.active_media),
            name="cineshelf-tmdb-explore",
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
                    collections.get(media_type, ())[:18],
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
        self.explore_records = records
        self.explore_ids = {record.id for record in records}
        self.records_by_id = {
            record.id: record for record in (*self.records, *self.explore_records)
        }
        self.explore_selected_id = None
        self._update_sidebar_counts()
        self._update_explore_genre_model(preserve=False)
        if self.active_destination == "explore":
            self._refresh_explore()
        self._toast("Live TMDB data loaded")
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
        overlay.set_child(
            PosterWidget(
                artwork_record,
                art_width,
                self._explore_card_height(kind, span),
                variant_offset=1 if kind == "landscape" else 0,
                show_text=False,
            )
        )

    def _on_tmdb_explore_failed(self, generation: int, message: str) -> bool:
        if generation != self._tmdb_explore_generation:
            return GLib.SOURCE_REMOVE
        print(f"CineShelf TMDB: {message}", file=sys.stderr)
        self._toast("TMDB unavailable — showing local sample data")
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
        generation = self._tmdb_detail_generations.get(record.id, 0) + 1
        self._tmdb_detail_generations[record.id] = generation
        threading.Thread(
            target=self._load_tmdb_details_worker,
            args=(record, self.tmdb_token, generation),
            name=f"cineshelf-tmdb-{record.tmdb_id}",
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
                runtime_minutes = int(payload.get("runtime") or 0)
                directors = [
                    str(item.get("name"))
                    for item in payload.get("credits", {}).get("crew", ())
                    if isinstance(item, dict) and item.get("job") == "Director"
                ]
                creator = ", ".join(directors[:2]) or record.creator
                seasons: tuple[SeasonInfo, ...] = ()
            else:
                runtimes = payload.get("episode_run_time") or ()
                runtime_minutes = int(runtimes[0]) if runtimes else 0
                creators = [
                    str(item.get("name"))
                    for item in payload.get("created_by", ())
                    if isinstance(item, dict) and item.get("name")
                ]
                creator = ", ".join(creators[:2]) or record.creator
                total_watched = sum(season.watched for season in record.seasons)
                season_rows = [
                    item
                    for item in payload.get("seasons", ())
                    if isinstance(item, dict)
                ]
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
                    )
                    for position, item in enumerate(season_rows, start=1)
                )
            runtime = (
                f"{runtime_minutes // 60}h {runtime_minutes % 60:02d}m"
                if runtime_minutes >= 60
                else f"{runtime_minutes}m" if runtime_minutes else record.runtime
            )
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
            video_titles = tuple(
                str(item.get("name"))
                for item in payload.get("videos", {}).get("results", ())[:8]
                if isinstance(item, dict) and item.get("name")
            )
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
            )
        except tmdb_client.TmdbError as error:
            GLib.idle_add(
                self._on_tmdb_details_failed,
                record.id,
                generation,
                str(error),
            )
            return
        GLib.idle_add(self._apply_tmdb_details, generation, updated)

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

        profile_work = [
            (index, str(item.get("profile_path") or ""))
            for index, item in enumerate(cast_items)
            if item.get("profile_path") and cast[index].profile_file is None
        ]
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size="w185"): index
                for index, path in profile_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is not None:
                    GLib.idle_add(
                        self._apply_tmdb_cast_artwork,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

        gallery_work = [
            ("backdrop", str(item["file_path"]), "w500")
            for item in backdrop_items
            if tmdb_client.cached_image(str(item["file_path"]), size="w500") is None
        ] + [
            ("poster", str(item["file_path"]), "w342")
            for item in poster_items
            if tmdb_client.cached_image(str(item["file_path"]), size="w342") is None
        ]
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(tmdb_client.cache_image, path, size=size): kind
                for kind, path, size in gallery_work
            }
            for future in as_completed(futures):
                image_file = future.result()
                if image_file is not None:
                    GLib.idle_add(
                        self._apply_tmdb_gallery_artwork,
                        record.id,
                        generation,
                        futures[future],
                        image_file,
                    )

    def _apply_tmdb_details(
        self,
        generation: int,
        updated: TitleRecord,
    ) -> bool:
        if self._tmdb_detail_generations.get(updated.id) != generation:
            return GLib.SOURCE_REMOVE
        self._tmdb_details_loading.discard(updated.id)
        self._tmdb_details_loaded.add(updated.id)
        self._store_tmdb_record(updated)
        return GLib.SOURCE_REMOVE

    def _store_tmdb_record(self, updated: TitleRecord) -> None:
        self.records_by_id[updated.id] = updated
        self.records = tuple(
            updated if record.id == updated.id else record
            for record in self.records
        )
        self.explore_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_records
        )
        self.visible_records = tuple(
            updated if record.id == updated.id else record
            for record in self.visible_records
        )
        self.explore_visible_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_visible_records
        )
        if updated.id in self.explore_ids:
            self._update_explore_card_artwork(updated)
        if self.selected_id == updated.id:
            self._update_details()

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
        image_file: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None or index >= len(record.cast):
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
        image_file: str,
    ) -> bool:
        if self._tmdb_detail_generations.get(record_id) != generation:
            return GLib.SOURCE_REMOVE
        record = self.records_by_id.get(record_id)
        if record is None:
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
        print(f"CineShelf TMDB details: {message}", file=sys.stderr)
        return GLib.SOURCE_REMOVE

    def _on_preferences_clicked(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading="Connect to TMDB",
            body=(
                "Enter a TMDB API Read Access Token to load live titles, "
                "details and artwork. The token is stored only for this user."
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
            print(f"CineShelf TMDB token: {error}", file=sys.stderr)
            self._toast("Could not save the TMDB token")
            return

        self.tmdb_token = token
        self._tmdb_details_loading.clear()
        self._tmdb_details_loaded.clear()
        self._toast("Connecting to TMDB…")
        if self.simkl_connected:
            self._load_tmdb_library_async(self.records)
        self._load_tmdb_explore_async()

    def _effective_status(self, record: TitleRecord) -> str:
        return self.status_overrides.get(record.id, record.status)

    def _status_total(self, media_type: str, status: str) -> int:
        total = sum(
            record.media_type == media_type
            and self._effective_status(record) == status
            for record in self.records
        )
        total += sum(
            record.id in self.bookmarks
            and record.media_type == media_type
            and self._effective_status(record) == status
            for record in self.explore_records
        )
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
        records = []
        for record in self.explore_records:
            if record.media_type != self.active_media:
                continue
            if (
                self.explore_period == "This month"
                and record.discover_period != "This month"
            ):
                continue
            if (
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
        promoted = tuple(
            record for record in self.explore_records if record.id in self.bookmarks
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

        total = self._status_total(self.active_media, self.active_status)
        sample_count = len(self.visible_records)
        has_filters = bool(self.search_entry.get_text().strip()) or self.genre != "All genres"
        if has_filters:
            description = f"{sample_count} matching {'title' if sample_count == 1 else 'titles'}"
        else:
            description = f"Showing {sample_count} recent {'entry' if sample_count == 1 else 'entries'}"

        self.eyebrow_label.set_label(f"My library / {self.active_media}")
        self.section_title.set_label(self.active_status)
        self.section_count.set_label(str(total))
        self.result_count.set_label(f"All ({total})")
        self.result_description.set_label(description)
        self.search_entry.set_placeholder_text(
            f"Search {self.active_media.lower()}…"
        )
        self._update_sort_icon()
        self._update_details()

    def _refresh_explore(self, *, reset_scroll: bool = True) -> None:
        scroll_value = self.explore_scroller.get_vadjustment().get_value()
        self.explore_visible_records = self._filtered_explore_records()
        visible_ids = {record.id for record in self.explore_visible_records}
        if self.explore_selected_id not in visible_ids:
            self.explore_selected_id = (
                self.explore_visible_records[0].id
                if self.explore_visible_records
                else None
            )
        self.selected_id = self.explore_selected_id

        self.explore_eyebrow_label.set_label(
            f"Discover / {self.active_media}"
        )
        self.explore_count_label.set_label(str(len(self.explore_visible_records)))
        self.explore_row.set_count(self._explore_total(self.active_media))
        self._populate_explore_feed()
        self._update_details()
        if reset_scroll:
            self._scroll_to_top(self.explore_scroller)
        else:
            self._scroll_to_value(self.explore_scroller, scroll_value)

    def _populate_explore_feed(self) -> None:
        self._clear_container(self.explore_feed_box)
        self._clear_container(self.explore_grid)
        self._explore_card_buttons: dict[str, Gtk.Button] = {}
        self._explore_card_layouts: dict[str, tuple[str, int]] = {}

        if not self.explore_visible_records:
            self.explore_feed_box.append(self.explore_empty_page)
            return

        records = list(self.explore_visible_records)
        columns = self.explore_columns
        data_signature = sum(
            (position + 1) * sum(record.id.encode("utf-8"))
            for position, record in enumerate(records)
        )
        layout_seed = self._explore_layout_seed ^ data_signature ^ (columns << 24)
        layout = build_explore_layout_plan(len(records), columns, layout_seed)

        record_index = 0
        for row, pattern in enumerate(layout):
            column = 0
            for kind, span in pattern:
                record = records[record_index]
                record_index += 1
                card = self._create_explore_card(record, kind, span)
                self.explore_grid.attach(card, column, row, span, 1)
                self._explore_card_buttons[record.id] = card
                self._explore_card_layouts[record.id] = (kind, span)
                column += span

        self.explore_feed_box.append(self.explore_grid)
        if any(record.tmdb_id is not None for record in self.explore_visible_records):
            attribution = Gtk.Label(label="Data & images provided by TMDB")
            attribution.set_halign(Gtk.Align.START)
            attribution.set_margin_top(2)
            attribution.add_css_class("caption")
            attribution.add_css_class("dim-label")
            self.explore_feed_box.append(attribution)
        elif not self.tmdb_token:
            fallback_notice = Gtk.Label(
                label="Sample artwork · Configure TMDB in Preferences for live data"
            )
            fallback_notice.set_halign(Gtk.Align.START)
            fallback_notice.set_margin_top(2)
            fallback_notice.add_css_class("caption")
            fallback_notice.add_css_class("dim-label")
            self.explore_feed_box.append(fallback_notice)
        self._sync_explore_selection_style()

    def _create_explore_card(
        self,
        record: TitleRecord,
        kind: str,
        span: int,
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_vexpand(False)
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
        overlay.set_size_request(-1, card_height)
        art_width = 480 if kind == "hero" else 320 if kind == "landscape" else 160
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
        )
        artwork.set_hexpand(True)
        artwork.set_vexpand(True)
        artwork.set_size_request(-1, -1)
        overlay.set_child(artwork)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_halign(Gtk.Align.FILL)
        copy.set_valign(Gtk.Align.END)
        copy.set_hexpand(True)
        copy.add_css_class("explore-card-copy")

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
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
            subtitle.add_css_class("caption")
            subtitle.add_css_class("explore-card-subtitle")
            copy.append(subtitle)
        overlay.add_overlay(copy)

        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.set_halign(Gtk.Align.END)
        rating.set_valign(Gtk.Align.START)
        rating.set_margin_top(8)
        rating.set_margin_end(8)
        rating.add_css_class("row-rating")
        overlay.add_overlay(rating)

        if record.id in self.bookmarks:
            saved = Gtk.Image.new_from_icon_name("bookmark-new-symbolic")
            saved.set_halign(Gtk.Align.START)
            saved.set_valign(Gtk.Align.START)
            saved.set_margin_top(8)
            saved.set_margin_start(8)
            saved.add_css_class("explore-saved-badge")
            overlay.add_overlay(saved)

        button.set_child(overlay)
        button.connect(
            "clicked",
            lambda _button, record_id=record.id: self._on_explore_card_clicked(
                record_id
            ),
        )
        return button

    def _sync_explore_selection_style(self) -> None:
        for record_id, button in self._explore_card_buttons.items():
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

        menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
        menu_button.set_tooltip_text(f"More options for {record.title}")
        menu_button.set_valign(Gtk.Align.START)
        menu_button.add_css_class("flat")
        menu_button.add_css_class("circular")
        menu_button.connect(
            "clicked",
            lambda _button, title=record.title: self._toast(f"More options for {title}"),
        )
        content.append(menu_button)
        row.set_child(content)
        return row

    def _create_grid_child(self, record: TitleRecord) -> Gtk.FlowBoxChild:
        child = Gtk.FlowBoxChild()
        child.record = record
        child.set_halign(Gtk.Align.FILL)
        child.set_valign(Gtk.Align.START)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.set_size_request(132, 230)
        card.set_hexpand(False)
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.START)
        card.add_css_class("poster-grid-card")
        card.append(self._create_poster_overlay(record, 120, 180))

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(15)
        title.set_hexpand(False)
        title.set_size_request(120, 38)
        title.set_tooltip_text(record.title)
        title.add_css_class("poster-grid-title")
        card.append(title)
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
            artwork_file=record.poster_file or record.artwork_file,
        )
        overlay.set_child(PosterWidget(poster_record, width, height))

        score = self.ratings.get(record.id)
        if score is not None:
            rating = Gtk.Label(label=str(score))
            rating.set_halign(Gtk.Align.START)
            rating.set_valign(Gtk.Align.START)
            rating.set_margin_top(4)
            rating.set_margin_start(4)
            rating.add_css_class("row-rating")
            rating.add_css_class("numeric")
            overlay.add_overlay(rating)

        if record.id in self.completed:
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
        overlay = Gtk.Overlay()
        hero_record = replace(
            record,
            artwork_file=(
                record.backdrop_file or record.poster_file or record.artwork_file
            ),
        )
        overlay.set_child(PosterWidget(hero_record, 352, 198, show_text=False))

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
        trailer.connect(
            "clicked",
            lambda _button, title=record.title: self._toast(f"Playing trailer for {title}"),
        )
        overlay.add_overlay(trailer)

        self.detail_poster_host.append(overlay)

    def _rating_sources(self, record: TitleRecord) -> tuple[tuple[str, str], ...]:
        if record.external_ratings:
            return record.external_ratings[:4]
        return (
            ("CineShelf", f"{record.rating:.1f}"),
            ("IMDb", f"{min(10.0, record.rating + 0.1):.1f}"),
            ("Meta", str(min(99, round(record.rating * 10)))),
            ("Match", f"{min(99, round(record.rating * 10 + 8))}%"),
        )

    def _populate_detail_ratings(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_ratings_host)
        for source, value in self._rating_sources(record):
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
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
            self.detail_ratings_host.append(chip)

    def _populate_quick_actions(self, record: TitleRecord) -> None:
        self._clear_container(self.quick_actions_host)
        fourth_action = "Check in" if record.media_type == "Movies" else "Drop"
        actions = (
            ("starred-symbolic", "Rate"),
            ("mail-unread-symbolic", "Comments"),
            ("document-edit-symbolic", "Note"),
            ("media-playback-stop-symbolic", fourth_action),
        )
        for icon_name, label in actions:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.append(Gtk.Image.new_from_icon_name(icon_name))
            caption = Gtk.Label(label=label)
            caption.set_wrap(True)
            caption.add_css_class("caption")
            content.append(caption)

            button = Gtk.Button()
            button.set_child(content)
            button.add_css_class("flat")
            button.add_css_class("detail-action-button")
            button.set_tooltip_text(f"{label}: {record.title}")
            button.connect(
                "clicked",
                lambda _button, action=label, title=record.title: self._toast(
                    f"{action} for {title}"
                ),
            )
            self.quick_actions_host.append(button)

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
    ) -> None:
        self._clear_container(container)
        for member in self._cast_members(record):
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

            name = Gtk.Label(label=member.name)
            name.set_wrap(True)
            name.set_lines(2)
            name.set_width_chars(11)
            name.set_max_width_chars(11)
            name.set_justify(Gtk.Justification.CENTER)
            name.set_xalign(0.5)
            name.add_css_class("caption")
            name.add_css_class("cast-name")

            role = Gtk.Label(label=member.role)
            role.set_ellipsize(Pango.EllipsizeMode.END)
            role.set_width_chars(11)
            role.set_max_width_chars(11)
            role.set_xalign(0.5)
            role.add_css_class("caption")
            role.add_css_class("dim-label")

            card.append(avatar)
            card.append(name)
            card.append(role)
            container.append(card)

    def _series_seasons(self, record: TitleRecord) -> tuple[SeasonInfo, ...]:
        if record.seasons:
            return record.seasons

        numbers = [int(value) for value in record.runtime.split() if value.isdigit()]
        is_completed = record.id in self.completed
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

    @staticmethod
    def _watched_timestamp() -> str:
        now = datetime.now().astimezone()
        hour = now.strftime("%I").lstrip("0") or "12"
        return (
            f"{now.strftime('%b')} {now.day}, {now.year} at "
            f"{hour}:{now.strftime('%M %p')}"
        )

    def _episode_key(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> str:
        season = self._series_seasons(record)[season_index]
        return f"{record.id}/{season.id}/{episode.id}"

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

    def _episode_artwork(
        self,
        record: TitleRecord,
        episode: EpisodeInfo,
        width: int,
        height: int,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        overlay.set_child(
            PosterWidget(
                record,
                width,
                height,
                variant_offset=episode.image_variant,
                show_text=False,
            )
        )
        number = Gtk.Label(label=str(episode.number))
        number.set_halign(Gtk.Align.END)
        number.set_valign(Gtk.Align.END)
        number.set_margin_end(5)
        number.set_margin_bottom(5)
        number.add_css_class("episode-number-badge")
        number.add_css_class("numeric")
        overlay.add_overlay(number)
        overlay.set_tooltip_text(f"Episode {episode.number}: {episode.title}")
        return overlay

    @staticmethod
    def _episode_card(label: str, value: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.add_css_class("episode-card")
        overline = Gtk.Label(label=label, xalign=0)
        overline.add_css_class("caption")
        overline.add_css_class("dim-label")
        title = Gtk.Label(label=value, xalign=0)
        title.add_css_class("heading")
        detail = Gtk.Label(label=subtitle, xalign=0)
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
        if not episodic:
            return

        seasons = self._series_seasons(record)
        self._clear_container(self.episode_cards_box)
        self._clear_container(self.seasons_list)

        next_item: tuple[int, EpisodeInfo] | None = None
        last_item: tuple[int, EpisodeInfo] | None = None
        for season_index, _season in enumerate(seasons):
            for episode in self._episodes_for_season(record, season_index):
                if self._episode_is_watched(record, season_index, episode):
                    last_item = (season_index, episode)
                elif next_item is None:
                    next_item = (season_index, episode)

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
                "emblem-ok-symbolic"
                if watched >= season.episodes
                else "media-playback-start-symbolic"
            )
            if watched >= season.episodes:
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

        self.detail_record_id = record.id
        self.current_season_index = season_index
        self.season_header_title.set_title(season.title)
        self.season_header_title.set_subtitle(record.title)
        self.season_summary_label.set_label(
            f"{watched} of {len(episodes)} episodes watched · {record.network}"
        )
        self.season_episode_count.set_label(f"{len(episodes)} episodes")
        self.season_watched_button.action_label.set_label(
            "Mark unwatched" if watched == len(episodes) else "Mark watched"
        )

        self._updating_season_switcher = True
        rebuild_switcher = (
            self.season_switcher_record_id != record.id
            or self.season_switcher.get_n_toggles() != len(seasons)
        )
        if rebuild_switcher:
            self.season_switcher.remove_all()
            for index, item in enumerate(seasons):
                item_watched = self._season_watched_count(record, index)
                self.season_switcher.add(
                    Adw.Toggle(
                        name=f"season-{index}",
                        label=(
                            f"{self._season_short_label(item)}  "
                            f"{item_watched}/{item.episodes}"
                        ),
                    )
                )
            self.season_switcher_record_id = record.id
        else:
            for index, item in enumerate(seasons):
                item_watched = self._season_watched_count(record, index)
                self.season_switcher.get_toggle(index).set_label(
                    f"{self._season_short_label(item)}  "
                    f"{item_watched}/{item.episodes}"
                )
        self.season_switcher.set_active_name(f"season-{season_index}")
        self._updating_season_switcher = False

        self._clear_container(self.season_episodes_list)
        for episode_index, episode in enumerate(episodes):
            row = Adw.ActionRow(
                title=episode.title,
                subtitle=f"{episode.date}\n{episode.description}",
            )
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_activatable(True)
            row.season_index = season_index
            row.episode_index = episode_index
            row.add_prefix(self._episode_artwork(record, episode, 112, 64))

            watched_icon = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic"
                if self._episode_is_watched(record, season_index, episode)
                else "media-playback-start-symbolic"
            )
            if self._episode_is_watched(record, season_index, episode):
                watched_icon.add_css_class("success")
            row.add_suffix(watched_icon)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.set_tooltip_text(f"Open episode {episode.number}: {episode.title}")
            self.season_episodes_list.append(row)

        if reset_scroll:
            self._scroll_to_top(self.season_details_scroller)

    def _populate_episode_page(
        self,
        record: TitleRecord,
        season_index: int,
        episode_index: int,
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
        self.episode_position_label.set_label(
            f"Episode {episode.number} of {len(episodes)}"
        )
        if len(episodes) <= 7:
            dots = "  ".join(
                "●" if index == episode_index else "•"
                for index in range(len(episodes))
            )
        else:
            dots = f"{episode.number}/{len(episodes)}  •••"
        self.episode_position_dots.set_label(dots)

        self._clear_container(self.episode_hero_host)
        self.episode_hero_host.append(
            self._episode_artwork(record, episode, 352, 198)
        )
        self.episode_title_label.set_label(episode.title)
        self.episode_date_label.set_label(episode.date)
        self.episode_overview_label.set_label(episode.description)
        self._populate_cast_container(self.episode_cast_box, record)
        self._update_episode_watch_controls(record, season_index, episode)
        self._scroll_to_top(self.episode_details_scroller)

    def _update_episode_watch_controls(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> None:
        watched = self._episode_is_watched(record, season_index, episode)
        self.episode_watched_button.action_label.set_label(
            "Watched" if watched else "Mark watched"
        )
        watched_at = self.episode_watched_at.get(
            self._episode_key(record, season_index, episode)
        )
        if watched and watched_at:
            status = f"Watched · {watched_at}"
        elif watched:
            status = "Watched"
        else:
            status = "Not watched yet"
        self.episode_watched_at_label.set_label(status)

    @staticmethod
    def _scroll_to_value(scroller: Gtk.ScrolledWindow, value: float) -> None:
        def reset_adjustment() -> bool:
            scroller.get_vadjustment().set_value(value)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(reset_adjustment)

    @staticmethod
    def _scroll_to_top(scroller: Gtk.ScrolledWindow) -> None:
        CineShelfWindow._scroll_to_value(scroller, 0)

    def _video_card(
        self,
        record: TitleRecord,
        title: str,
        variant_offset: int,
    ) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        overlay = Gtk.Overlay()
        video_record = replace(
            record,
            artwork_file=(
                record.backdrop_file or record.poster_file or record.artwork_file
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
        caption = Gtk.Label(label=title, xalign=0)
        caption.set_ellipsize(Pango.EllipsizeMode.END)
        caption.add_css_class("caption")
        content.append(overlay)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("flat")
        button.add_css_class("detail-media-card")
        button.set_tooltip_text(f"Play {title} for {record.title}")
        button.connect(
            "clicked",
            lambda _button, video_title=title: self._toast(f"Playing {video_title}"),
        )
        return button

    def _populate_videos(self, record: TitleRecord) -> None:
        self._clear_container(self.videos_box)
        titles = record.video_titles or ("New trailer", "Official trailer")
        for index, title in enumerate(titles[:8], start=1):
            self.videos_box.append(self._video_card(record, title, index))

    def _populate_images(self, record: TitleRecord) -> None:
        self._clear_container(self.images_box)
        is_poster = self.image_mode == "posters"
        width, height = (96, 144) if is_poster else (176, 99)
        gallery = record.gallery_posters if is_poster else record.gallery_backdrops
        fallback_count = 3 if is_poster else 2
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
            button.set_tooltip_text(
                f"Open {self.image_mode[:-1]} {index + 1} for {record.title}"
            )
            button.connect(
                "clicked",
                lambda _button, image_number=index + 1: self._toast(
                    f"Opened image {image_number}"
                ),
            )
            self.images_box.append(button)

    def _related_records(self, record: TitleRecord) -> tuple[TitleRecord, ...]:
        related: list[TitleRecord] = []
        for record_id in record.recommendations:
            candidate = self.records_by_id.get(record_id)
            if candidate is not None and candidate.id != record.id and candidate not in related:
                related.append(candidate)

        if len(related) < 8:
            for candidate in self.records:
                if candidate.id == record.id or candidate in related:
                    continue
                shares_genre = bool(set(candidate.genres).intersection(record.genres))
                if candidate.media_type == record.media_type or shares_genre:
                    related.append(candidate)
                if len(related) == 8:
                    break
        return tuple(related[:8])

    def _populate_recommendations(self, record: TitleRecord) -> None:
        self._clear_container(self.recommendations_box)
        for related in self._related_records(record):
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.append(PosterWidget(related, 88, 132))
            title = Gtk.Label(label=related.title, xalign=0)
            title.set_wrap(True)
            title.set_lines(2)
            title.set_max_width_chars(13)
            title.add_css_class("caption")
            year = Gtk.Label(label=str(related.year), xalign=0)
            year.add_css_class("caption")
            year.add_css_class("dim-label")
            content.append(title)
            content.append(year)

            button = Gtk.Button()
            button.set_child(content)
            button.add_css_class("flat")
            button.add_css_class("recommendation-card")
            button.set_tooltip_text(f"Open {related.title}")
            button.connect(
                "clicked",
                lambda _button, title_name=related.title: self._toast(
                    f"Open {title_name}"
                ),
            )
            self.recommendations_box.append(button)

    def _populate_detail_sections(self, record: TitleRecord) -> None:
        self._populate_detail_ratings(record)
        self._populate_quick_actions(record)
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
        self._reset_detail_navigation()
        self.detail_record_id = record.id
        self.detail_box.set_visible(True)
        self.detail_poster_host.set_visible(True)
        self._build_detail_hero(record)

        is_completed = record.id in self.completed
        is_explore_view = (
            self.active_destination == "explore" and record.id in self.explore_ids
        )
        self.detail_status_label.set_label(
            (
                "In watchlist"
                if record.id in self.bookmarks
                else record.availability
            )
            if is_explore_view
            else self._effective_status(record)
        )
        self.detail_overline.set_label(" · ".join(record.genres))
        self.detail_title.set_label(record.title)
        self.community_rating.set_label(f"★ {record.rating:.1f}")
        if is_explore_view:
            self.watched_button.set_label(
                "✓  In watchlist"
                if record.id in self.bookmarks
                else "＋  Add to watchlist"
            )
        else:
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
        self.activity_status.set_label("Completed" if is_completed else "Not watched yet")
        self.activity_percentage.set_label("100%" if is_completed else "0%")
        self.activity_progress.set_fraction(1.0 if is_completed else 0.0)

        self._updating_details = True
        self.favorite_button.set_active(record.id in self.favorites)
        self.bookmark_button.set_visible(not is_explore_view)
        self.bookmark_button.set_active(record.id in self.bookmarks)
        score = self.ratings.get(record.id)
        for value, button in self.rating_buttons.items():
            button.set_active(value == score)
        self.rating_value.set_label("Not rated" if score is None else f"{score}/10")
        self._updating_details = False
        self._populate_detail_sections(record)
        if record_changed:
            self._scroll_to_top(self.details_scroller)

    def _update_sidebar_counts(self) -> None:
        for status, row in self.status_rows.items():
            row.set_count(self._status_total(self.active_media, status))
        for list_name, row in self.list_rows.items():
            row.set_count(self._status_total(self.active_media, list_name))
        self.library_row.set_count(self._library_total(self.active_media))
        self.explore_row.set_count(self._explore_total(self.active_media))

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
        self._update_sidebar_counts()
        if self.active_destination == "explore":
            self._update_genre_model()
            self._update_explore_genre_model(preserve=False)
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
            return
        if row.key == "profile":
            if self.active_destination == "library":
                self.library_selected_id = self.selected_id
            elif self.active_destination == "explore":
                self.explore_selected_id = self.selected_id
            self.active_destination = "profile"
            self.media_switcher.set_visible(False)
            self._updating = True
            self.status_list.unselect_all()
            self.collections_list.unselect_all()
            self._updating = False
            self.browser_stack.set_visible_child_name("profile")
            self._refresh_profile()
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
        self._queue_explore_resize()

    def _on_sidebar_toggled(self, button: Gtk.ToggleButton) -> None:
        sidebar_visible = button.get_active()
        if not sidebar_visible:
            self.workspace.set_show_content(True)
        self.workspace.set_collapsed(not sidebar_visible)
        button.set_tooltip_text(
            "Hide sidebar (Ctrl+B)" if sidebar_visible else "Show sidebar (Ctrl+B)"
        )
        self._queue_explore_resize()
        if self._sidebar_resize_source_id:
            GLib.source_remove(self._sidebar_resize_source_id)
        self._sidebar_resize_source_id = GLib.timeout_add(
            280,
            self._on_sidebar_transition_complete,
        )

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
        self._set_details_open(False)
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

    def _on_search_requested(self, *_args: Any) -> None:
        if self.active_destination != "library":
            if self.active_status == "Watchlist":
                self.collections_list.select_row(self.watchlist_row)
            else:
                self.status_list.select_row(self.status_rows[self.active_status])
        self.search_entry.grab_focus()

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
        if record_id not in self.explore_ids:
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

    def _on_season_switch_changed(
        self,
        group: Adw.ToggleGroup,
        _parameter: Any,
    ) -> None:
        if self._updating_season_switcher:
            return
        active = group.get_active_name()
        if not active or not active.startswith("season-"):
            return
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        try:
            season_index = int(active.removeprefix("season-"))
        except ValueError:
            return
        self._populate_season_page(record, season_index)

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
        self._populate_episode_page(
            record,
            int(season_index),
            int(episode_index),
        )
        self.detail_navigation.push_by_tag("episode")

    def _on_season_watched_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        episodes = self._episodes_for_season(record, self.current_season_index)
        if not episodes:
            return
        watched = self._season_watched_count(record, self.current_season_index)
        new_status = watched < len(episodes)
        timestamp = self._watched_timestamp() if new_status else None
        for episode in episodes:
            key = self._episode_key(record, self.current_season_index, episode)
            self.episode_status_overrides[key] = new_status
            if timestamp is None:
                self.episode_watched_at.pop(key, None)
            else:
                self.episode_watched_at[key] = timestamp
        self._save_user_state()
        self._populate_series(record)
        self._populate_season_page(record, self.current_season_index)
        if self.active_destination == "profile":
            self._refresh_profile()
        self._toast(
            "Season marked as watched"
            if new_status
            else "Season marked as unwatched"
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
        key = self._episode_key(record, self.current_season_index, episode)
        self.episode_status_overrides[key] = new_status
        if new_status:
            self.episode_watched_at[key] = self._watched_timestamp()
        else:
            self.episode_watched_at.pop(key, None)
        self._save_user_state()
        self._populate_series(record)
        season_scroll = self.season_details_scroller.get_vadjustment().get_value()
        self._populate_season_page(
            record,
            self.current_season_index,
            reset_scroll=False,
        )
        self._scroll_to_value(self.season_details_scroller, season_scroll)
        self._update_episode_watch_controls(
            record,
            self.current_season_index,
            episode,
        )
        if self.active_destination == "profile":
            self._refresh_profile()
        self._toast(
            "Episode marked as watched"
            if new_status
            else "Episode marked as unwatched"
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

    def _set_details_open(self, open_details: bool) -> None:
        if self.details_open == open_details:
            return
        if (
            open_details
            and self.active_destination == "explore"
            and self.explore_visible_records
        ):
            panel_width = max(388, self.details_surface.get_width())
            target_width = max(280, self.explore_pane.get_width() - panel_width)
            target_columns = min(4, self._explore_columns_for_width(target_width))
            if target_columns != self.explore_columns:
                self.explore_columns = target_columns
                self._last_explore_layout_width = target_width
                self._populate_explore_feed()
        self.details_open = open_details
        self.details_revealer.set_reveal_child(open_details)
        if not open_details:
            self._reset_detail_navigation()
        self._queue_explore_resize()
        if self._details_resize_source_id:
            GLib.source_remove(self._details_resize_source_id)
        self._details_resize_source_id = GLib.timeout_add(
            self.details_revealer.get_transition_duration() + 60,
            self._on_details_transition_complete,
        )

    def _on_details_transition_complete(self) -> bool:
        self._details_resize_source_id = 0
        self._queue_explore_resize()
        return GLib.SOURCE_REMOVE

    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        if not self.details_open:
            return False
        self._set_details_open(False)
        self.window.set_focus(None)
        return True

    def _on_window_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if (
            keyval == Gdk.KEY_Escape
            and self.details_open
            and self.detail_navigation.get_visible_page_tag() == "title"
        ):
            self._set_details_open(False)
            self.window.set_focus(None)
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

    @staticmethod
    def _simkl_group(record: TitleRecord) -> str:
        return (
            "movies"
            if record.media_type == "Movies"
            else "anime" if record.media_type == "Anime" else "shows"
        )

    @staticmethod
    def _simkl_ids(record: TitleRecord) -> dict[str, int | str]:
        ids: dict[str, int | str] = {}
        if record.id.startswith("simkl-"):
            try:
                ids["simkl"] = int(record.id.rsplit("-", 1)[1])
            except (TypeError, ValueError):
                pass
        if record.tmdb_id is not None:
            ids["tmdb"] = record.tmdb_id
        if not ids:
            raise simkl_client.SimklError(
                "This title has no Simkl or TMDB identifier."
            )
        return ids

    def _run_simkl_mutation(
        self,
        key: str,
        operation: Any,
        on_success: Any,
        success_message: str,
    ) -> None:
        if not self.simkl_client_id or not self.simkl_token or not self.simkl_connected:
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
            name="cineshelf-simkl-write",
            daemon=True,
        ).start()

    def _finish_simkl_mutation(
        self,
        key: str,
        on_success: Any | None,
        success_message: str,
        error_message: str | None,
    ) -> bool:
        self._simkl_mutations_inflight.discard(key)
        if error_message is not None:
            self._update_details()
            self._toast(error_message)
            return GLib.SOURCE_REMOVE
        if on_success is not None:
            on_success()
        self._toast(success_message)
        return GLib.SOURCE_REMOVE

    def _write_simkl_list_change(
        self,
        record: TitleRecord,
        *,
        adding: bool,
        on_success: Any,
    ) -> None:
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
        self._run_simkl_mutation(
            f"{record.id}:watchlist",
            operation,
            on_success,
            "Added to Simkl watchlist" if adding else "Removed from Simkl watchlist",
        )

    def _on_watched_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        if self.active_destination == "explore" and record.id in self.explore_ids:
            adding = record.id not in self.bookmarks

            def apply_explore_watchlist() -> None:
                if adding:
                    self.bookmarks.add(record.id)
                    if record.status != "Watchlist":
                        self.status_overrides[record.id] = "Watchlist"
                else:
                    self.bookmarks.discard(record.id)
                    self.status_overrides.pop(record.id, None)
                    self.completed.discard(record.id)
                self._save_user_state()
                self._update_sidebar_counts()
                self._refresh_explore(reset_scroll=False)

            self._write_simkl_list_change(
                record,
                adding=adding,
                on_success=apply_explore_watchlist,
            )
            return
        watched = record.id not in self.completed

        def apply_watched() -> None:
            if watched:
                self.completed.add(record.id)
                self.status_overrides[record.id] = "Watched"
                self.title_watched_at[record.id] = self._watched_timestamp()
            else:
                self.completed.discard(record.id)
                self.status_overrides[record.id] = "Watchlist"
                self.title_watched_at.pop(record.id, None)
            if self.status_overrides[record.id] == record.status:
                self.status_overrides.pop(record.id)
            self._save_user_state()
            self._update_sidebar_counts()
            if self.active_destination == "profile":
                self._refresh_profile()
            else:
                self._refresh_results()

        self._run_simkl_mutation(
            f"{record.id}:watched",
            lambda: simkl_client.set_watched(
                self.simkl_client_id or "",
                self.simkl_token or "",
                self._simkl_group(record),
                self._simkl_ids(record),
                watched,
            ),
            apply_watched,
            "Marked as watched" if watched else "Marked as unwatched",
        )

    def _on_favorite_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        if button.get_active():
            self.favorites.add(self.selected_id)
            message = "Added to favorites"
        else:
            self.favorites.discard(self.selected_id)
            message = "Removed from favorites"
        self._save_user_state()
        self._toast(message)

    def _on_bookmark_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        adding = button.get_active()

        def apply_bookmark() -> None:
            if adding:
                self.bookmarks.add(record.id)
                if record.status != "Watchlist":
                    self.status_overrides[record.id] = "Watchlist"
            else:
                self.bookmarks.discard(record.id)
                self.status_overrides.pop(record.id, None)
                self.completed.discard(record.id)
                if record.id in self.library_ids and record.id not in self.explore_ids:
                    self.records = tuple(
                        item for item in self.records if item.id != record.id
                    )
                    self.library_ids.discard(record.id)
                    self.records_by_id.pop(record.id, None)
            self._save_user_state()
            self._update_sidebar_counts()
            if self.active_destination == "explore":
                self._refresh_explore(reset_scroll=False)
            else:
                self._refresh_results()

        self._write_simkl_list_change(
            record,
            adding=adding,
            on_success=apply_bookmark,
        )

    def _on_more_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is not None:
            self._toast(f"More options for {record.title}")

    def _on_rating_button_toggled(
        self,
        button: Gtk.ToggleButton,
        score: int,
    ) -> None:
        if self._updating_details or self.selected_id is None or not button.get_active():
            return
        record = self.records_by_id[self.selected_id]

        def apply_rating() -> None:
            self.ratings[record.id] = score
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
            self._save_user_state()
            if self.active_destination == "explore":
                self._refresh_explore(reset_scroll=False)
            elif self.active_destination == "profile":
                self._refresh_profile()
            else:
                self._refresh_results()

        self._run_simkl_mutation(
            f"{record.id}:rating",
            lambda: simkl_client.set_rating(
                self.simkl_client_id or "",
                self.simkl_token or "",
                self._simkl_group(record),
                self._simkl_ids(record),
                score,
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


class CineShelfApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.controller: CineShelfWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_args: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about_dialog)
        self.add_action(about_action)

        logs_action = Gio.SimpleAction.new("logs", None)
        logs_action.connect("activate", self._show_logs)
        self.add_action(logs_action)

    def do_activate(self) -> None:
        if self.props.active_window is None:
            try:
                self.controller = CineShelfWindow(self)
            except Exception as error:
                print(f"CineShelf failed to start: {error}", file=sys.stderr)
                window = Adw.ApplicationWindow(application=self, title=APP_NAME)
                window.set_default_size(720, 480)
                window.set_content(
                    Adw.StatusPage(
                        icon_name="dialog-error-symbolic",
                        title="Unable to start CineShelf",
                        description=str(error),
                    )
                )
        window = self.props.active_window
        if window is not None:
            window.present()

    def do_shutdown(self) -> None:
        simkl_client.close_image_http_client()
        Adw.Application.do_shutdown(self)

    def _show_about_dialog(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        window = self.props.active_window
        if window is None:
            return
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="CineShelf",
            version=APP_VERSION,
            comments="A lightweight native GTK4 movie library built with Gtk.Builder XML.",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(window)

    def _show_logs(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self.controller is not None:
            self.controller.show_application_log()


def main() -> int:
    application = CineShelfApplication()
    return application.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
