#!/usr/bin/env python3
"""Small dependency-free TMDB client used by the native Gisheh app."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..version import APP_VERSION
from . import image_http

try:
    from .._build_config import BUNDLED_TMDB_READ_TOKEN
except ImportError:
    BUNDLED_TMDB_READ_TOKEN = ""


APP_ID = "io.github.arashe023.Gisheh"
API_ROOT = "https://api.themoviedb.org/3"
IMAGE_ROOT = "https://image.tmdb.org/t/p"
USER_AGENT = f"Gisheh/{APP_VERSION}"


class TmdbError(RuntimeError):
    """A safe, user-facing TMDB request error that never includes credentials."""


def token_file() -> Path:
    configured = os.environ.get("TMDB_TOKEN_FILE")
    if configured:
        return Path(configured).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / APP_ID / "tmdb-read-token"


def read_token() -> str | None:
    environment_token = os.environ.get("TMDB_READ_TOKEN", "").strip()
    if environment_token:
        return environment_token
    try:
        stored_token = token_file().read_text(encoding="utf-8").strip()
    except OSError:
        stored_token = ""
    return stored_token or BUNDLED_TMDB_READ_TOKEN.strip() or None


def token_source() -> str | None:
    """Describe the active credential without exposing its value."""
    if os.environ.get("TMDB_READ_TOKEN", "").strip():
        return "environment"
    try:
        if token_file().read_text(encoding="utf-8").strip():
            return "user"
    except OSError:
        pass
    return "bundled" if BUNDLED_TMDB_READ_TOKEN.strip() else None


def store_token(token: str) -> Path:
    normalized = token.strip()
    if not normalized:
        raise TmdbError("The TMDB read token cannot be empty.")

    destination = token_file()
    temporary = destination.with_name(
        f".{destination.name}.{threading.get_ident()}.tmp"
    )
    try:
        parent_was_missing = not destination.parent.exists()
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent_was_missing:
            os.chmod(destination.parent, 0o700)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(f"{normalized}\n")
        temporary.replace(destination)
        os.chmod(destination, 0o600)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise TmdbError(f"Could not save the TMDB token: {error}") from None
    return destination


def clear_token() -> None:
    """Remove the user-stored TMDB token without touching environment config."""
    try:
        token_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise TmdbError(f"Could not remove the TMDB token: {error}") from None


def cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / APP_ID / "tmdb-images"


def metadata_cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / APP_ID / "tmdb-metadata"


def clear_cache() -> None:
    """Remove reproducible TMDB image and metadata caches."""
    for destination in (cache_dir(), metadata_cache_dir()):
        try:
            shutil.rmtree(destination)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise TmdbError(f"Could not clear the TMDB cache: {error}") from None


def _summary_file(media_type: str, tmdb_id: int) -> Path:
    namespace = "movie" if media_type == "movie" else "tv"
    return metadata_cache_dir() / f"{namespace}-{tmdb_id}.json"


def load_summary(
    media_type: str,
    tmdb_id: int,
    *,
    max_age_seconds: float | None = None,
) -> dict[str, Any] | None:
    destination = _summary_file(media_type, tmdb_id)
    try:
        cached = json.loads(destination.read_text(encoding="utf-8"))
        payload = cached["payload"]
        fetched_at = float(cached["fetched_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not isinstance(payload, dict):
        return None
    if max_age_seconds is not None and time.time() - fetched_at > max_age_seconds:
        return None
    return payload


def store_summary(
    media_type: str,
    tmdb_id: int,
    payload: dict[str, Any],
) -> Path:
    destination = _summary_file(media_type, tmdb_id)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                {"fetched_at": time.time(), "payload": payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise TmdbError(f"Could not cache TMDB metadata: {error}") from None
    return destination


def request_json(
    path: str,
    *,
    token: str,
    params: dict[str, str | int | bool] | None = None,
    timeout: float = 15,
) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{API_ROOT}{path}{query}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        code = error.code
        error.close()
        if code == 401:
            raise TmdbError("TMDB rejected the read token (HTTP 401).") from None
        raise TmdbError(f"TMDB request failed with HTTP {code}.") from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise TmdbError(f"Could not reach TMDB: {reason}") from None


def fetch_explore_page(
    token: str,
    media_type: str,
    page: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    """Fetch one pageable Explore feed while keeping anime distinct from TV."""
    page = max(1, page)
    common: dict[str, str | int | bool] = {
        "language": language,
        "page": page,
    }
    if media_type == "Movies":
        path = "/trending/movie/week"
        params = common
    elif media_type == "Shows":
        path = "/trending/tv/week"
        params = common
    elif media_type == "Anime":
        path = "/discover/tv"
        params = {
            **common,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "with_genres": 16,
            "with_origin_country": "JP",
        }
    else:
        raise ValueError(f"Unsupported Explore media type: {media_type}")
    payload = request_json(path, token=token, params=params)
    results = payload.get("results", [])
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or page),
        "results": [item for item in results if isinstance(item, dict)],
    }


def fetch_explore(token: str, *, language: str = "en-US") -> dict[str, list[dict[str, Any]]]:
    movies = fetch_explore_page(token, "Movies", 1, language=language)["results"]
    shows = fetch_explore_page(token, "Shows", 1, language=language)["results"]
    anime = fetch_explore_page(token, "Anime", 1, language=language)["results"]
    return {
        "Movies": movies,
        "Shows": shows,
        "Anime": anime,
    }


def search_titles_page(
    token: str,
    media_type: str,
    query: str,
    page: int = 1,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    """Search TMDB directly for the active Explore media type."""
    normalized_query = query.strip()
    if not normalized_query:
        return {"page": 1, "total_pages": 0, "results": []}
    page = max(1, page)
    if media_type == "Movies":
        path = "/search/movie"
    elif media_type in ("Shows", "Anime"):
        path = "/search/tv"
    else:
        raise ValueError(f"Unsupported Explore media type: {media_type}")
    payload = request_json(
        path,
        token=token,
        params={
            "query": normalized_query,
            "include_adult": "false",
            "language": language,
            "page": page,
        },
    )
    results = [
        item
        for item in payload.get("results", ())
        if isinstance(item, dict)
    ]
    if media_type == "Anime":
        results = [
            item
            for item in results
            if 16 in item.get("genre_ids", ())
        ]
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or page),
        "results": results,
    }


def fetch_details(
    token: str,
    media_type: str,
    tmdb_id: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    rating_resource = (
        "release_dates" if namespace == "movie" else "content_ratings"
    )
    return request_json(
        f"/{namespace}/{tmdb_id}",
        token=token,
        params={
            "language": language,
            "append_to_response": (
                f"credits,videos,images,recommendations,{rating_resource}"
            ),
            "include_image_language": "en,null",
        },
    )


def fetch_episode_details(
    token: str,
    series_id: int,
    season_number: int,
    episode_number: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    """Fetch metadata belonging to one TV episode, including its still image."""
    return request_json(
        f"/tv/{series_id}/season/{season_number}/episode/{episode_number}",
        token=token,
        params={"language": language},
    )


def fetch_season_details(
    token: str,
    series_id: int,
    season_number: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    """Fetch every episode of one TV season with a single TMDB request."""
    return request_json(
        f"/tv/{series_id}/season/{season_number}",
        token=token,
        params={"language": language},
    )


def fetch_summary(
    token: str,
    media_type: str,
    tmdb_id: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    payload = request_json(
        f"/{namespace}/{tmdb_id}",
        token=token,
        params={"language": language},
    )
    store_summary(namespace, tmdb_id, payload)
    return payload


def cache_image(image_path: str | None, *, size: str = "w780") -> str | None:
    if not image_path:
        return None
    safe_name = Path(image_path).name
    if not safe_name:
        return None
    destination = cache_dir() / f"{size}-{safe_name}"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    downloaded = image_http.download(
        f"{IMAGE_ROOT}/{size}/{image_path.lstrip('/')}",
        destination,
        max_bytes=8 * 1024 * 1024,
    )
    return str(destination) if downloaded else None


def cached_image(image_path: str | None, *, size: str = "w780") -> str | None:
    if not image_path:
        return None
    safe_name = Path(image_path).name
    if not safe_name:
        return None
    destination = cache_dir() / f"{size}-{safe_name}"
    return (
        str(destination)
        if destination.is_file() and destination.stat().st_size > 0
        else None
    )


def _youtube_thumbnail_destination(video_key: str) -> Path | None:
    """Return a cache destination only for a safe YouTube video key."""
    normalized = video_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", normalized):
        return None
    return cache_dir() / f"youtube-{normalized}.jpg"


def cached_youtube_thumbnail(video_key: str) -> str | None:
    destination = _youtube_thumbnail_destination(video_key)
    if destination is None:
        return None
    return (
        str(destination)
        if destination.is_file() and destination.stat().st_size > 0
        else None
    )


def cache_youtube_thumbnail(video_key: str) -> str | None:
    """Download the preview image for a TMDB-provided YouTube video."""
    destination = _youtube_thumbnail_destination(video_key)
    if destination is None:
        return None
    cached = cached_youtube_thumbnail(video_key)
    if cached is not None:
        return cached
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    downloaded = image_http.download(
        f"https://i.ytimg.com/vi/{video_key.strip()}/hqdefault.jpg",
        destination,
        max_bytes=4 * 1024 * 1024,
    )
    return str(destination) if downloaded else None
