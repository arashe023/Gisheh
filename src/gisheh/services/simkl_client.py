#!/usr/bin/env python3
"""Simkl authentication and user-state sync client."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gi
from gi.repository import GLib

from . import image_http

try:
    from .._build_config import BUNDLED_SIMKL_CLIENT_ID
except ImportError:
    BUNDLED_SIMKL_CLIENT_ID = ""


APP_ID = "io.github.gisheh.Gisheh"
APP_NAME = "gisheh"
APP_VERSION = "1.3.0"
API_ROOT = "https://api.simkl.com"
CALENDAR_ROOT = "https://data.simkl.in/calendar/v2"
USER_AGENT = f"Gisheh/{APP_VERSION}"
CALENDAR_SCHEMA_VERSION = 1
CALENDAR_CACHE_MAX_AGE = timedelta(hours=5)
CALENDAR_MEDIA_FILES = {
    "shows": "tv.json",
    "tv": "tv.json",
    "anime": "anime.json",
    "movies": "movie_release.json",
    "movie": "movie_release.json",
}
LOGGER = logging.getLogger(__name__)
LIBRARY_GROUPS = {
    "movies": "movie",
    "shows": "show",
    "anime": "show",
}

EPISODE_SYNC_PARAMS = {
    "extended": "full_anime_seasons",
    "include_all_episodes": "yes",
    "episode_watched_at": "yes",
}


def normalize_watched_at(
    value: str | None,
    *,
    default_timezone: tzinfo | None = None,
) -> str | None:
    """Return a UTC Zulu timestamp for the Simkl wire.

    Simkl documents ``watched_at`` with ISO-8601 ``Z``-suffixed examples, so
    local offsets (``+03:30``) are converted to ``...Z`` before sending.
    Naive input is refused unless its source timezone was supplied explicitly;
    silently treating it as UTC shifts dates selected in a local UI.
    """
    if not value:
        return value
    text = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise SimklError("The watched timestamp is not a valid ISO-8601 date.")
    if moment.tzinfo is None:
        if default_timezone is None:
            raise SimklError(
                "The watched timestamp needs an explicit timezone offset."
            )
        moment = moment.replace(tzinfo=default_timezone)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimklError(RuntimeError):
    """Safe error that never contains an access token."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CalendarEpisode:
    season: int | None
    episode: int
    title: str | None
    url: str | None


@dataclass(frozen=True, slots=True)
class CalendarTitle:
    title: str
    original_title: str | None
    simkl_id: int
    tmdb_id: int | None
    imdb_id: str | None
    tvdb_id: int | None
    mal_id: int | None
    poster: str | None
    fanart: str | None
    url: str | None
    network: str | None
    genres: tuple[str, ...]
    runtime: str | None
    status: str | None
    total_episodes: int | None
    rating: float | None
    rank: int | None
    anime_type: str | None
    dvd_date: str | None

    @property
    def poster_url(self) -> str:
        if not self.poster:
            return "https://simkl.in/poster_no_pic.png"
        return (
            "https://wsrv.nl/?url=https://simkl.in/posters/"
            f"{self.poster}_m.webp&q=90"
        )


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    simkl_id: int
    media_type: str
    date: str | None
    utc_datetime: datetime | None
    local_datetime: datetime | None
    finale_type: int | None
    season: int | None
    episode: int | None
    episode_title: str | None
    episode_url: str | None
    title: CalendarTitle

    @property
    def episode_data(self) -> CalendarEpisode | None:
        if self.episode is None:
            return None
        return CalendarEpisode(
            self.season, self.episode, self.episode_title, self.episode_url
        )

    @property
    def episode_number(self) -> int | None:
        return self.episode

    @property
    def finale_label(self) -> str | None:
        return {
            1: "Mid-season finale",
            2: "Season finale",
            3: "Series finale",
        }.get(self.finale_type)


@dataclass(frozen=True, slots=True)
class CalendarSnapshot:
    events: tuple[CalendarEvent, ...]
    titles: tuple[CalendarTitle, ...]
    source_url: str
    fetched_at: datetime
    last_modified: str | None = None
    from_cache: bool = False
    stale: bool = False
    unavailable: bool = False


@dataclass(frozen=True, slots=True)
class CalendarFilter:
    media_types: tuple[str, ...] = ("movies", "shows", "anime")
    include_watched: bool = False
    include_dropped: bool = False


def calendar_cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / APP_ID / "simkl-calendar"


def _calendar_media_type(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"tv", "show", "shows"}:
        return "shows"
    if normalized in {"movie", "movies", "movie_release"}:
        return "movies"
    if normalized == "anime":
        return "anime"
    raise SimklError("The requested Calendar media type is not valid.")


def calendar_url(
    media_type: str,
    year: int | None = None,
    month: int | None = None,
    *,
    client_id: str | None = None,
) -> str:
    """Build a rolling or monthly v2 CDN URL with required app parameters."""
    media = _calendar_media_type(media_type)
    if (year is None) != (month is None):
        raise SimklError("Calendar year and month must be provided together.")
    if year is not None:
        try:
            normalized_year, normalized_month = int(year), int(month or 0)
        except (TypeError, ValueError):
            raise SimklError("The Calendar month is not valid.") from None
        if not 1 <= normalized_month <= 12:
            raise SimklError("The Calendar month is not valid.")
        path = (
            f"{CALENDAR_ROOT}/{normalized_year:04d}/{normalized_month}/"
            f"{CALENDAR_MEDIA_FILES[media]}"
        )
    else:
        path = f"{CALENDAR_ROOT}/{CALENDAR_MEDIA_FILES[media]}"
    query = urlencode(
        {
            "client_id": (client_id or read_client_id() or "").strip(),
            "app-name": APP_NAME,
            "app-version": APP_VERSION,
        }
    )
    return f"{path}?{query}"


def resolve_calendar_timezone(value: str | tzinfo | None) -> tzinfo:
    if isinstance(value, tzinfo):
        return value
    if value:
        try:
            return ZoneInfo(str(value))
        except (ZoneInfoNotFoundError, ValueError):
            LOGGER.warning("Ignoring invalid Simkl account timezone %r", value)
    return datetime.now().astimezone().tzinfo or timezone.utc


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _calendar_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _calendar_title(raw: dict[str, Any], simkl_id: int) -> CalendarTitle:
    ids = raw.get("ids") if isinstance(raw.get("ids"), dict) else {}
    ratings = raw.get("ratings") if isinstance(raw.get("ratings"), dict) else {}
    simkl_rating = (
        ratings.get("simkl") if isinstance(ratings.get("simkl"), dict) else {}
    )
    raw_url = str(raw.get("url") or "").strip() or None
    if raw_url and raw_url.startswith("/"):
        raw_url = f"https://simkl.com{raw_url}"
    original = str(raw.get("title_romaji") or "").strip() or None
    if original is None and isinstance(raw.get("alt_titles"), list):
        for item in raw["alt_titles"]:
            if isinstance(item, dict) and item.get("type") == "original":
                original = str(item.get("name") or "").strip() or None
                if original:
                    break
    return CalendarTitle(
        title=str(raw.get("title") or "Untitled"),
        original_title=original,
        simkl_id=simkl_id,
        tmdb_id=_optional_int(ids.get("tmdb")),
        imdb_id=str(ids.get("imdb") or "").strip() or None,
        tvdb_id=_optional_int(ids.get("tvdb")),
        mal_id=_optional_int(ids.get("mal")),
        poster=str(raw.get("poster") or "").strip() or None,
        fanart=str(raw.get("fanart") or "").strip() or None,
        url=raw_url,
        network=str(raw.get("network") or "").strip() or None,
        genres=tuple(
            str(item) for item in raw.get("genres", ())
            if isinstance(item, str) and item.strip()
        ) if isinstance(raw.get("genres", ()), (list, tuple)) else (),
        runtime=str(raw.get("runtime") or "").strip() or None,
        status=str(raw.get("status") or "").strip() or None,
        total_episodes=_optional_int(raw.get("total_episodes")),
        rating=_optional_float(simkl_rating.get("rating")),
        rank=_optional_int(raw.get("rank")),
        anime_type=str(raw.get("anime_type") or "").strip() or None,
        dvd_date=str(raw.get("dvd_date") or "").strip() or None,
    )


def parse_calendar_payload(
    payload: object,
    media_type: str,
    *,
    display_timezone: str | tzinfo | None = None,
    source_url: str = "",
    fetched_at: datetime | None = None,
    last_modified: str | None = None,
    from_cache: bool = False,
    stale: bool = False,
) -> CalendarSnapshot:
    """Defensively join v2 events to metadata and localize UTC timestamps."""
    media = _calendar_media_type(media_type)
    raw = payload if isinstance(payload, dict) else {}
    raw_events = raw.get("calendar") if isinstance(raw.get("calendar"), list) else []
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    local_zone = resolve_calendar_timezone(display_timezone)
    titles: dict[int, CalendarTitle] = {}
    events: list[CalendarEvent] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        simkl_id = _optional_int(item.get("simkl_id"))
        if simkl_id is None:
            LOGGER.warning("Skipping Calendar event without a valid simkl_id")
            continue
        title_raw = metadata.get(str(simkl_id))
        if not isinstance(title_raw, dict):
            LOGGER.warning("Skipping Calendar event %s without metadata", simkl_id)
            continue
        title = titles.setdefault(simkl_id, _calendar_title(title_raw, simkl_id))
        utc_moment = _calendar_datetime(item.get("date"))
        episode_raw = item.get("episode")
        episode_data = None
        if isinstance(episode_raw, dict):
            number = _optional_int(episode_raw.get("episode"))
            if number is not None:
                episode_data = CalendarEpisode(
                    season=_optional_int(episode_raw.get("season")),
                    episode=number,
                    title=str(episode_raw.get("title") or "").strip() or None,
                    url=str(episode_raw.get("url") or "").strip() or None,
                )
        finale = _optional_int(item.get("finale_type"))
        events.append(
            CalendarEvent(
                simkl_id=simkl_id,
                media_type=media,
                date=str(item.get("date") or "").strip() or None,
                utc_datetime=utc_moment,
                local_datetime=(utc_moment.astimezone(local_zone) if utc_moment else None),
                finale_type=finale if finale in {1, 2, 3} else None,
                season=episode_data.season if episode_data else None,
                episode=episode_data.episode if episode_data else None,
                episode_title=episode_data.title if episode_data else None,
                episode_url=episode_data.url if episode_data else None,
                title=title,
            )
        )
    events.sort(
        key=lambda event: (
            event.utc_datetime is None,
            event.utc_datetime or datetime.max.replace(tzinfo=timezone.utc),
            event.simkl_id,
            event.episode_number or 0,
        )
    )
    moment = fetched_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return CalendarSnapshot(
        events=tuple(events),
        titles=tuple(titles.values()),
        source_url=source_url,
        fetched_at=moment.astimezone(timezone.utc),
        last_modified=last_modified,
        from_cache=from_cache,
        stale=stale,
    )


def merge_calendar_snapshots(
    snapshots: tuple[CalendarSnapshot, ...] | list[CalendarSnapshot],
) -> CalendarSnapshot:
    if not snapshots:
        return CalendarSnapshot((), (), "", datetime.now(timezone.utc))
    titles: dict[tuple[str, int], CalendarTitle] = {}
    events: dict[tuple[object, ...], CalendarEvent] = {}
    for snapshot in snapshots:
        for event in snapshot.events:
            titles[(event.media_type, event.simkl_id)] = event.title
            key = (
                event.media_type, event.simkl_id, event.date,
                event.season, event.episode_number,
            )
            events[key] = event
    ordered = tuple(sorted(events.values(), key=lambda event: (
        event.utc_datetime is None,
        event.utc_datetime or datetime.max.replace(tzinfo=timezone.utc),
        event.media_type, event.simkl_id, event.episode_number or 0,
    )))
    return CalendarSnapshot(
        events=ordered,
        titles=tuple(titles.values()),
        source_url=", ".join(snapshot.source_url for snapshot in snapshots),
        fetched_at=max(snapshot.fetched_at for snapshot in snapshots),
        last_modified=max(
            (snapshot.last_modified for snapshot in snapshots if snapshot.last_modified),
            default=None,
        ),
        from_cache=all(snapshot.from_cache for snapshot in snapshots),
        stale=any(snapshot.stale for snapshot in snapshots),
        unavailable=all(snapshot.unavailable for snapshot in snapshots),
    )


def _calendar_cache_file(media_type: str, year: int | None, month: int | None) -> Path:
    media = _calendar_media_type(media_type)
    period = f"{int(year):04d}-{int(month):02d}" if year is not None else "rolling"
    return calendar_cache_dir() / f"{media}-{period}.json"


def store_calendar_cache(
    media_type: str,
    payload: dict[str, Any],
    *,
    source_url: str,
    fetched_at: datetime | None = None,
    last_modified: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> Path:
    target = _calendar_cache_file(media_type, year, month)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    moment = fetched_at or datetime.now(timezone.utc)
    envelope = {
        "schema_version": CALENDAR_SCHEMA_VERSION,
        "url": source_url,
        "fetched_at": moment.astimezone(timezone.utc).isoformat(),
        "last_modified": last_modified,
        "payload": payload,
    }
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(envelope, stream, separators=(",", ":"), ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise SimklError(f"Could not cache the Simkl Calendar: {error}") from None
    return target


def load_calendar_cache(
    media_type: str,
    *,
    year: int | None = None,
    month: int | None = None,
    display_timezone: str | tzinfo | None = None,
) -> tuple[CalendarSnapshot, dict[str, Any]] | None:
    path = _calendar_cache_file(media_type, year, month)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or envelope.get("schema_version") != CALENDAR_SCHEMA_VERSION:
            raise ValueError("unsupported schema")
        payload = envelope.get("payload")
        fetched_at = _calendar_datetime(envelope.get("fetched_at"))
        if not isinstance(payload, dict) or fetched_at is None:
            raise ValueError("invalid cache")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Ignoring corrupt Calendar cache %s", path)
        try:
            path.unlink()
        except OSError:
            pass
        return None
    age = datetime.now(timezone.utc) - fetched_at
    snapshot = parse_calendar_payload(
        payload,
        media_type,
        display_timezone=display_timezone,
        source_url=str(envelope.get("url") or ""),
        fetched_at=fetched_at,
        last_modified=str(envelope.get("last_modified") or "") or None,
        from_cache=True,
        stale=age > CALENDAR_CACHE_MAX_AGE,
    )
    return snapshot, envelope


def clear_calendar_cache() -> None:
    target = calendar_cache_dir()
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
    except OSError as error:
        raise SimklError(f"Could not clear the Simkl Calendar cache: {error}") from None


def calendar_poster_file(title: CalendarTitle) -> Path:
    return calendar_cache_dir() / "images" / f"{title.simkl_id}.webp"


def cached_calendar_poster(title: CalendarTitle) -> str | None:
    path = calendar_poster_file(title)
    return str(path) if path.is_file() and path.stat().st_size else None


def fetch_calendar_poster(title: CalendarTitle) -> str | None:
    cached = cached_calendar_poster(title)
    if cached:
        return cached
    destination = calendar_poster_file(title)
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return (
        str(destination)
        if image_http.download(
            title.poster_url, destination, max_bytes=8 * 1024 * 1024
        )
        else None
    )


def fetch_calendar(
    media_type: str,
    *,
    client_id: str,
    year: int | None = None,
    month: int | None = None,
    display_timezone: str | tzinfo | None = None,
    force: bool = False,
    timeout: float = 20,
) -> CalendarSnapshot:
    """Fetch one public v2 calendar, conditionally reusing its isolated cache."""
    if not client_id.strip():
        raise SimklError("A Simkl Client ID is required for Calendar requests.", code=412)
    media = _calendar_media_type(media_type)
    cached = load_calendar_cache(
        media, year=year, month=month, display_timezone=display_timezone
    )
    if cached and not cached[0].stale and not force:
        return cached[0]
    url = calendar_url(media, year, month, client_id=client_id)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if cached and cached[0].last_modified:
        headers["If-Modified-Since"] = cached[0].last_modified
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
            last_modified = response.headers.get("Last-Modified")
    except HTTPError as error:
        code = error.code
        error.close()
        if code == 304 and cached:
            snapshot, envelope = cached
            store_calendar_cache(
                media,
                envelope["payload"],
                source_url=url,
                last_modified=snapshot.last_modified,
                year=year,
                month=month,
            )
            refreshed = load_calendar_cache(
                media, year=year, month=month, display_timezone=display_timezone
            )
            return refreshed[0] if refreshed else snapshot
        if code == 412:
            raise SimklError("The Simkl Client ID is missing or invalid.", code=412) from None
        if code == 404 and year is not None and not cached:
            return CalendarSnapshot(
                (), (), url, datetime.now(timezone.utc), unavailable=True
            )
        if cached:
            return CalendarSnapshot(
                cached[0].events, cached[0].titles, cached[0].source_url,
                cached[0].fetched_at, cached[0].last_modified,
                from_cache=True, stale=True,
            )
        message = (
            "The Simkl Client ID is missing or invalid."
            if code == 412 else f"Simkl Calendar request failed with HTTP {code}."
        )
        raise SimklError(message, code=code) from None
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        if cached:
            return CalendarSnapshot(
                cached[0].events, cached[0].titles, cached[0].source_url,
                cached[0].fetched_at, cached[0].last_modified,
                from_cache=True, stale=True,
            )
        reason = getattr(error, "reason", error)
        raise SimklError(f"Could not reach the Simkl Calendar: {reason}") from None
    if not isinstance(payload, dict):
        raise SimklError("Simkl returned an unexpected Calendar response.")
    fetched_at = datetime.now(timezone.utc)
    store_calendar_cache(
        media, payload, source_url=url, fetched_at=fetched_at,
        last_modified=last_modified, year=year, month=month,
    )
    return parse_calendar_payload(
        payload, media, display_timezone=display_timezone, source_url=url,
        fetched_at=fetched_at, last_modified=last_modified,
    )


@dataclass(frozen=True, slots=True)
class HistorySyncResult:
    """The server-authoritative outcome of a ``POST /sync/history`` call."""

    changed: bool
    counts: dict[str, int]
    statuses: tuple[str, ...]
    not_found: dict[str, tuple[object, ...]]
    noop: bool

    @property
    def effective_status(self) -> str | None:
        return self.statuses[-1] if self.statuses else None

    @property
    def accepted_episodes(self) -> int:
        return self.counts.get("episodes", 0)


def history_sync_result(payload: object) -> HistorySyncResult:
    """Parse Simkl's variable history response without assuming HTTP=success.

    In particular, an all-zero ``added`` response is a valid HTTP response but
    means history did not change.  ``statuses[].response.status`` is retained
    because Simkl can downgrade a requested completed show to watching.
    """
    raw = payload if isinstance(payload, dict) else {}
    added = raw.get("added") if isinstance(raw.get("added"), dict) else {}
    counts: dict[str, int] = {}
    for group in ("movies", "shows", "anime", "episodes"):
        try:
            counts[group] = max(0, int(added.get(group) or 0))
        except (TypeError, ValueError):
            counts[group] = 0
    statuses: list[str] = []
    raw_statuses = added.get("statuses")
    if isinstance(raw_statuses, list):
        for item in raw_statuses:
            response = item.get("response") if isinstance(item, dict) else None
            status = response.get("status") if isinstance(response, dict) else None
            if isinstance(status, str) and status.strip():
                statuses.append(status.strip().lower())
    raw_not_found = raw.get("not_found")
    not_found = (
        {
            str(group): tuple(items)
            for group, items in raw_not_found.items()
            if isinstance(items, list) and items
        }
        if isinstance(raw_not_found, dict)
        else {}
    )
    changed = any(counts.values()) and not not_found
    return HistorySyncResult(
        changed=changed,
        counts=counts,
        statuses=tuple(statuses),
        not_found=not_found,
        noop=not changed and not not_found,
    )


def config_dir() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".config"
    return base / APP_ID


def cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / APP_ID / "simkl"


def client_id_file() -> Path:
    return config_dir() / "simkl-client-id"


def token_file() -> Path:
    return config_dir() / "simkl-access-token"


def snapshot_file() -> Path:
    return cache_dir() / "snapshot.json"


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def read_client_id() -> str | None:
    return (
        os.environ.get("SIMKL_CLIENT_ID", "").strip()
        or BUNDLED_SIMKL_CLIENT_ID.strip()
        or _read_text(client_id_file())
    )


def client_id_source() -> str | None:
    """Describe where the public OAuth Client ID came from."""
    if os.environ.get("SIMKL_CLIENT_ID", "").strip():
        return "environment"
    if BUNDLED_SIMKL_CLIENT_ID.strip():
        return "bundled"
    return "legacy-file" if _read_text(client_id_file()) else None


def _secret_schema() -> tuple[Any, Any]:
    """Load libsecret lazily so non-GNOME systems retain the file fallback."""
    gi.require_version("Secret", "1")
    from gi.repository import Secret

    schema = Secret.Schema.new(
        f"{APP_ID}.SimklToken",
        Secret.SchemaFlags.NONE,
        {
            "application": Secret.SchemaAttributeType.STRING,
            "account": Secret.SchemaAttributeType.STRING,
            "profile": Secret.SchemaAttributeType.STRING,
        },
    )
    return Secret, schema


def _secret_attributes() -> dict[str, str]:
    return {
        "application": APP_ID,
        "account": "simkl",
        "profile": str(config_dir()),
    }


def _lookup_keyring_token() -> str | None:
    try:
        secret, schema = _secret_schema()
        value = secret.password_lookup_sync(schema, _secret_attributes(), None)
    except (ImportError, ValueError, RuntimeError, GLib.Error) as error:
        LOGGER.debug("Secret Service lookup is unavailable: %s", error)
        return None
    return str(value).strip() if value else None


def _store_keyring_token(token: str) -> bool:
    try:
        secret, schema = _secret_schema()
        return bool(
            secret.password_store_sync(
                schema,
                _secret_attributes(),
                secret.COLLECTION_DEFAULT,
                "Gisheh Simkl access token",
                token,
                None,
            )
        )
    except (ImportError, ValueError, RuntimeError, GLib.Error) as error:
        LOGGER.warning("Secret Service storage is unavailable: %s", error)
        return False


def _clear_keyring_token() -> bool:
    try:
        secret, schema = _secret_schema()
        secret.password_clear_sync(schema, _secret_attributes(), None)
        return True
    except (ImportError, ValueError, RuntimeError, GLib.Error) as error:
        LOGGER.warning("Secret Service removal is unavailable: %s", error)
        return False


def read_token() -> str | None:
    return (
        os.environ.get("SIMKL_ACCESS_TOKEN", "").strip()
        or _lookup_keyring_token()
        or _read_text(token_file())
    )


def _store_private_text(path: Path, value: str) -> Path:
    normalized = value.strip()
    if not normalized:
        raise SimklError("The value cannot be empty.")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(f"{normalized}\n")
        temporary.replace(path)
        os.chmod(path, 0o600)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise SimklError(f"Could not save Simkl credentials: {error}") from None
    return path


def store_client_id(client_id: str) -> Path:
    return _store_private_text(client_id_file(), client_id)


def store_token(token: str) -> str:
    normalized = token.strip()
    if not normalized:
        raise SimklError("The value cannot be empty.")
    if _store_keyring_token(normalized):
        try:
            token_file().unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            LOGGER.warning("Could not remove the legacy Simkl token file: %s", error)
        return "keyring"
    _store_private_text(token_file(), normalized)
    return "private-file"


def clear_token() -> bool:
    keyring_cleared = _clear_keyring_token()
    try:
        token_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SimklError(f"Could not remove the Simkl token: {error}") from None
    if not keyring_cleared:
        LOGGER.warning(
            "The local token file was removed, but Secret Service could not be reached."
        )
    return keyring_cleared


def clear_account_cache() -> None:
    for path in (snapshot_file(), cache_dir() / "images" / "avatar.jpg"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise SimklError(f"Could not remove cached Simkl data: {error}") from None


def clear_all_user_data() -> None:
    """Remove Simkl credentials, snapshots, artwork and Calendar downloads."""
    failures: list[str] = []
    if not clear_token():
        failures.append("the Secret Service token could not be removed")
    try:
        client_id_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        failures.append(f"the legacy Client ID could not be removed: {error}")
    for destination in (cache_dir(), calendar_cache_dir()):
        try:
            shutil.rmtree(destination)
        except FileNotFoundError:
            pass
        except OSError as error:
            failures.append(f"cache could not be cleared: {error}")
    if failures:
        raise SimklError("; ".join(failures))


def _request_json(
    path: str,
    *,
    client_id: str,
    token: str | None = None,
    method: str = "GET",
    params: dict[str, str | int] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    query = {
        "client_id": client_id,
        "app-name": APP_NAME,
        "app-version": APP_VERSION,
        **(params or {}),
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = b"{}"
    request = Request(
        f"{API_ROOT}{path}?{urlencode(query)}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        code = error.code
        error.close()
        messages = {
            401: "Simkl authorization was revoked. Connect the account again.",
            403: "This Simkl profile is private.",
            412: "The Simkl Client ID is not valid.",
            429: "Simkl rate limit reached. Try again later.",
        }
        raise SimklError(
            messages.get(code, f"Simkl request failed with HTTP {code}."),
            code=code,
        ) from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise SimklError(f"Could not reach Simkl: {reason}") from None
    if not isinstance(payload, dict):
        raise SimklError("Simkl returned an unexpected response.")
    return payload


def _write_sync_json(
    path: str,
    *,
    client_id: str,
    token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    query = urlencode(
        {
            "client_id": client_id,
            "app-name": APP_NAME,
            "app-version": APP_VERSION,
        }
    )
    request = Request(
        f"{API_ROOT}{path}?{query}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "simkl-api-key": client_id,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        code = error.code
        error.close()
        messages = {
            400: "Simkl rejected the tracking update.",
            401: "Simkl authorization was revoked. Connect the account again.",
            412: "The Simkl Client ID is not valid.",
            429: "Simkl rate limit reached. Try again later.",
        }
        raise SimklError(
            messages.get(code, f"Simkl update failed with HTTP {code}."),
            code=code,
        ) from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise SimklError(f"Could not update Simkl: {reason}") from None
    if not isinstance(result, dict):
        raise SimklError("Simkl returned an unexpected update response.")
    return result


def set_rating(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    rating: int,
) -> dict[str, Any]:
    if group not in LIBRARY_GROUPS or not 1 <= rating <= 10:
        raise SimklError("The Simkl rating must be between 1 and 10.")
    return _write_sync_json(
        "/sync/ratings",
        client_id=client_id,
        token=token,
        payload={group: [{"rating": rating, "ids": ids}]},
    )


def set_list_status(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    status: str,
) -> dict[str, Any]:
    if group not in LIBRARY_GROUPS or status not in {
        "watching",
        "plantowatch",
        "hold",
        "dropped",
        "completed",
    }:
        raise SimklError("The requested Simkl list status is not valid.")
    return _write_sync_json(
        "/sync/add-to-list",
        client_id=client_id,
        token=token,
        payload={group: [{"to": status, "ids": ids}]},
    )


def remove_from_library(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
) -> dict[str, Any]:
    if group not in LIBRARY_GROUPS:
        raise SimklError("The requested Simkl media type is not valid.")
    return _write_sync_json(
        "/sync/history/remove",
        client_id=client_id,
        token=token,
        payload={group: [{"ids": ids}]},
    )


def set_watched(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    watched: bool,
    *,
    watched_at: str | None = None,
) -> dict[str, Any]:
    if group not in LIBRARY_GROUPS:
        raise SimklError("The requested Simkl media type is not valid.")
    if watched:
        entry: dict[str, Any] = {"status": "completed", "ids": ids}
        normalized = normalize_watched_at(watched_at)
        if normalized:
            entry["watched_at"] = normalized
        return _write_sync_json(
            "/sync/history",
            client_id=client_id,
            token=token,
            payload={group: [entry]},
        )
    remove_from_library(client_id, token, group, ids)
    try:
        return set_list_status(
            client_id,
            token,
            group,
            ids,
            "plantowatch",
        )
    except SimklError:
        try:
            _write_sync_json(
                "/sync/history",
                client_id=client_id,
                token=token,
                payload={group: [{"status": "completed", "ids": ids}]},
            )
        except SimklError:
            pass
        raise


def change_watched_date(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    *,
    previous_watched_at: str | None,
    watched_at: str,
) -> HistorySyncResult:
    """Replace history's canonical watch date without creating a rewatch.

    Simkl does not expose an in-place edit for the canonical history timestamp.
    This deliberately uses remove then add (never ``allow_rewatch=yes``).  A
    failed add triggers a best-effort restore of the original state and reports
    a partial failure rather than pretending the operation was atomic.
    """
    normalized_new = normalize_watched_at(watched_at)
    normalized_previous = (
        normalize_watched_at(previous_watched_at)
        if previous_watched_at
        else None
    )
    remove_from_library(client_id, token, group, ids)
    try:
        result = set_watched(
            client_id,
            token,
            group,
            ids,
            True,
            watched_at=normalized_new,
        )
    except SimklError as error:
        try:
            set_watched(
                client_id,
                token,
                group,
                ids,
                True,
                watched_at=normalized_previous,
            )
        except SimklError:
            raise SimklError(
                "Changing the watched date partially failed: history was removed "
                "and could not be restored. Check Simkl before retrying."
            ) from None
        raise SimklError(
            "Changing the watched date failed; the previous Simkl history was restored."
        ) from error
    outcome = history_sync_result(result)
    if outcome.not_found or not outcome.changed:
        try:
            set_watched(
                client_id,
                token,
                group,
                ids,
                True,
                watched_at=normalized_previous,
            )
        except SimklError:
            raise SimklError(
                "Changing the watched date partially failed: history was removed "
                "and could not be restored. Check Simkl before retrying."
            ) from None
        raise SimklError(
            "Changing the watched date was not accepted; the previous Simkl history was restored."
        )
    return outcome


def set_episode_watched(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    season_number: int,
    episodes: list[tuple[int, str]],
) -> dict[str, Any]:
    """Record episode-level watch history without completing the show."""
    if group not in LIBRARY_GROUPS:
        raise SimklError("The requested Simkl media type is not valid.")
    try:
        season = int(season_number)
        watched_episodes = [
            {
                "number": int(number),
                "watched_at": normalize_watched_at(watched_at),
            }
            for number, watched_at in episodes
        ]
    except (TypeError, ValueError):
        raise SimklError("The Simkl episode history is not valid.")
    if not watched_episodes:
        raise SimklError("The Simkl episode history is not valid.")
    return _write_sync_json(
        "/sync/history",
        client_id=client_id,
        token=token,
        payload={
            group: [
                {
                    "ids": ids,
                    "seasons": [
                        {"number": season, "episodes": watched_episodes}
                    ],
                }
            ]
        },
    )


def remove_episode_watched(
    client_id: str,
    token: str,
    group: str,
    ids: dict[str, int | str],
    season_number: int,
    episodes: list[int],
) -> dict[str, Any]:
    """Remove episode-level watch history without touching the show."""
    if group not in LIBRARY_GROUPS:
        raise SimklError("The requested Simkl media type is not valid.")
    try:
        season = int(season_number)
        removed_episodes = [{"number": int(number)} for number in episodes]
    except (TypeError, ValueError):
        raise SimklError("The Simkl episode history is not valid.")
    if not removed_episodes:
        raise SimklError("The Simkl episode history is not valid.")
    return _write_sync_json(
        "/sync/history/remove",
        client_id=client_id,
        token=token,
        payload={
            group: [
                {
                    "ids": ids,
                    "seasons": [
                        {"number": season, "episodes": removed_episodes}
                    ],
                }
            ]
        },
    )


def request_pin(client_id: str) -> dict[str, Any]:
    payload = _request_json("/oauth/pin", client_id=client_id)
    if payload.get("result") != "OK" or not payload.get("user_code"):
        raise SimklError(str(payload.get("message") or "Could not create a Simkl PIN."))
    return payload


def poll_pin(client_id: str, user_code: str) -> dict[str, Any]:
    return _request_json(f"/oauth/pin/{user_code}", client_id=client_id)


def fetch_settings(client_id: str, token: str) -> dict[str, Any]:
    return _request_json(
        "/users/settings",
        client_id=client_id,
        token=token,
        method="POST",
    )


def fetch_stats(client_id: str, token: str, user_id: int) -> dict[str, Any]:
    return _request_json(
        f"/users/{user_id}/stats",
        client_id=client_id,
        token=token,
        method="POST",
        timeout=60,
    )


def fetch_activities(client_id: str, token: str) -> dict[str, Any]:
    return _request_json(
        "/sync/activities",
        client_id=client_id,
        token=token,
    )


def fetch_library(client_id: str, token: str) -> dict[str, Any]:
    payload = _request_json(
        "/sync/all-items",
        client_id=client_id,
        token=token,
        params=EPISODE_SYNC_PARAMS,
        timeout=60,
    )
    return {
        group: payload.get(group, [])
        if isinstance(payload.get(group), list)
        else []
        for group in LIBRARY_GROUPS
    }


def fetch_library_delta(
    client_id: str,
    token: str,
    date_from: str,
) -> dict[str, Any]:
    return _request_json(
        "/sync/all-items",
        client_id=client_id,
        token=token,
        params={**EPISODE_SYNC_PARAMS, "date_from": date_from},
        timeout=60,
    )


def fetch_library_ids(client_id: str, token: str) -> dict[str, Any]:
    return _request_json(
        "/sync/all-items",
        client_id=client_id,
        token=token,
        params={"extended": "simkl_ids_only"},
        timeout=60,
    )


def _item_id(group: str, entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    media = entry.get(LIBRARY_GROUPS[group])
    if not isinstance(media, dict):
        return None
    ids = media.get("ids")
    if not isinstance(ids, dict) or ids.get("simkl") is None:
        return None
    return str(ids["simkl"])


def merge_library(
    current: dict[str, Any],
    delta: dict[str, Any],
    valid_ids: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for group in LIBRARY_GROUPS:
        items_by_id: dict[str, dict[str, Any]] = {}
        for entry in current.get(group, ()):
            item_id = _item_id(group, entry)
            if item_id is not None and isinstance(entry, dict):
                items_by_id[item_id] = entry
        for entry in delta.get(group, ()):
            item_id = _item_id(group, entry)
            if item_id is not None and isinstance(entry, dict):
                items_by_id[item_id] = entry
        if valid_ids is not None:
            allowed = valid_ids.get(group, set())
            items_by_id = {
                item_id: entry
                for item_id, entry in items_by_id.items()
                if item_id in allowed
            }
        merged[group] = list(items_by_id.values())
    return merged


def library_ids(payload: dict[str, Any]) -> dict[str, set[str]]:
    return {
        group: {
            item_id
            for entry in payload.get(group, ())
            if (item_id := _item_id(group, entry)) is not None
        }
        for group in LIBRARY_GROUPS
    }


def library_has_user_state(payload: dict[str, Any]) -> bool:
    """Accept snapshots containing only Simkl-owned state and identifiers."""
    for group, object_key in LIBRARY_GROUPS.items():
        items = payload.get(group)
        if not isinstance(items, list):
            return False
        for entry in items:
            if not isinstance(entry, dict):
                return False
            media = entry.get(object_key)
            ids = media.get("ids") if isinstance(media, dict) else None
            if not isinstance(ids, dict) or ids.get("simkl") is None:
                return False
            if not str(entry.get("status") or "").strip():
                return False
    return True


def library_has_episode_history(payload: dict[str, Any]) -> bool:
    """Return whether the payload is structurally usable for episode sync.

    Individual titles may legitimately arrive without an expanded
    ``seasons`` array (e.g. a show the API did not expand), so a single gap
    must not invalidate the whole library response and block syncing. The
    record builder already tolerates missing seasons per title.
    """
    for group, object_key in (("shows", "show"), ("anime", "show")):
        items = payload.get(group)
        if not isinstance(items, list):
            return False
        for entry in items:
            if not isinstance(entry, dict):
                return False
            media = entry.get(object_key)
            if not isinstance(media, dict):
                return False
    return True


def removals_changed(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    for group in ("movies", "tv_shows", "anime"):
        previous_group = previous.get(group, {})
        current_group = current.get(group, {})
        if not isinstance(previous_group, dict) or not isinstance(current_group, dict):
            continue
        before = previous_group.get("removed_from_list")
        after = current_group.get("removed_from_list")
        if after and after != before:
            return True
    return False


def load_snapshot() -> dict[str, Any] | None:
    try:
        payload = json.loads(snapshot_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def store_snapshot(
    settings: dict[str, Any],
    stats: dict[str, Any],
    library: dict[str, Any],
    activities: dict[str, Any] | None = None,
) -> Path:
    destination = snapshot_file()
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = {
        "settings": settings,
        "stats": stats,
        "library": library,
        "activities": activities or {},
    }
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
        temporary.replace(destination)
        os.chmod(destination, 0o600)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise SimklError(f"Could not cache Simkl data: {error}") from None
    return destination


def close_image_http_client() -> None:
    image_http.close_client()


def _download_image(url: str, destination: Path) -> bool:
    return image_http.download(url, destination)


def cache_avatar(url: str | None) -> str | None:
    if not url:
        return None
    destination = cache_dir() / "images" / "avatar.jpg"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return str(destination) if _download_image(url, destination) else None


def cached_avatar() -> str | None:
    destination = cache_dir() / "images" / "avatar.jpg"
    return str(destination) if destination.is_file() else None


def invalidate_snapshot() -> None:
    """Discard only state data that could predate a successful mutation."""
    try:
        snapshot_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SimklError(f"Could not invalidate Simkl cache: {error}") from None
