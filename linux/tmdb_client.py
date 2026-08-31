#!/usr/bin/env python3
"""Small dependency-free TMDB client used by the native CineShelf app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


APP_ID = "io.github.cineshelf.CineShelf"
API_ROOT = "https://api.themoviedb.org/3"
IMAGE_ROOT = "https://image.tmdb.org/t/p"
USER_AGENT = "CineShelf/1.3.0"


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
        return None
    return stored_token or None


def store_token(token: str) -> Path:
    normalized = token.strip()
    if not normalized:
        raise TmdbError("The TMDB read token cannot be empty.")

    destination = token_file()
    temporary = destination.with_name(f".{destination.name}.tmp")
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


def cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / APP_ID / "tmdb-images"


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
        if error.code == 401:
            raise TmdbError("TMDB rejected the read token (HTTP 401).") from None
        raise TmdbError(f"TMDB request failed with HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise TmdbError(f"Could not reach TMDB: {reason}") from None


def fetch_explore(token: str, *, language: str = "en-US") -> dict[str, list[dict[str, Any]]]:
    common = {"language": language, "page": 1}
    movies = request_json(
        "/trending/movie/week",
        token=token,
        params=common,
    ).get("results", [])
    shows = request_json(
        "/trending/tv/week",
        token=token,
        params=common,
    ).get("results", [])
    anime = request_json(
        "/discover/tv",
        token=token,
        params={
            **common,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "with_genres": 16,
            "with_origin_country": "JP",
        },
    ).get("results", [])
    return {
        "Movies": [item for item in movies if isinstance(item, dict)],
        "Shows": [item for item in shows if isinstance(item, dict)],
        "Anime": [item for item in anime if isinstance(item, dict)],
    }


def fetch_details(
    token: str,
    media_type: str,
    tmdb_id: int,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    return request_json(
        f"/{namespace}/{tmdb_id}",
        token=token,
        params={
            "language": language,
            "append_to_response": "credits,videos,images,recommendations",
            "include_image_language": "en,null",
        },
    )


def cache_image(image_path: str | None, *, size: str = "w780") -> str | None:
    if not image_path:
        return None
    safe_name = Path(image_path).name
    if not safe_name:
        return None
    destination = cache_dir() / f"{size}-{safe_name}"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)

    request = Request(
        f"{IMAGE_ROOT}/{size}/{image_path.lstrip('/')}",
        headers={"User-Agent": USER_AGENT},
    )
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=15) as response:
            payload = response.read(8 * 1024 * 1024 + 1)
        if not payload or len(payload) > 8 * 1024 * 1024:
            return None
        temporary.write_bytes(payload)
        temporary.replace(destination)
        return str(destination)
    except (HTTPError, URLError, TimeoutError, OSError):
        try:
            temporary.unlink()
        except OSError:
            pass
        return None
