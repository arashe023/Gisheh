"""TMDB client used by the native Gisheh app."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import httpx

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
DEFAULT_LANGUAGE = "en-US"
PERSIAN_LANGUAGE = "fa-IR"

# --- Central TMDB content-language management ---------------------------
# All language decisions for TMDB content live here so the rest of the
# project never computes system/selected/fallback languages on its own.
CONTENT_LANGUAGE_SYSTEM = "system"
SUPPORTED_CONTENT_LANGUAGES = (DEFAULT_LANGUAGE, PERSIAN_LANGUAGE)
# Manual override values accepted from settings/tests. "system" means follow
# the operating system language. Only fa/en are real TMDB locales here;
# anything unsupported resolves to en-US.
_CONTENT_LANGUAGE_OVERRIDE: str = CONTENT_LANGUAGE_SYSTEM


def normalize_content_language(value: str | None) -> str:
    """Normalize a content-language setting to a TMDB locale or "system"."""
    if value is None:
        return CONTENT_LANGUAGE_SYSTEM
    normalized = value.strip().replace("_", "-").casefold()
    if not normalized or normalized == "system":
        return CONTENT_LANGUAGE_SYSTEM
    if normalized.startswith("fa"):
        return PERSIAN_LANGUAGE
    return DEFAULT_LANGUAGE


def set_content_language(value: str | None) -> str:
    """Set the manual TMDB content-language override ("system"/en-US/fa-IR)."""
    global _CONTENT_LANGUAGE_OVERRIDE
    _CONTENT_LANGUAGE_OVERRIDE = normalize_content_language(value)
    return _CONTENT_LANGUAGE_OVERRIDE


def get_content_language_setting() -> str:
    """Return the manual override ("system" when the user picked nothing)."""
    configured = os.environ.get("GISHEH_TMDB_LANGUAGE", "").strip()
    if configured:
        return normalize_content_language(configured)
    return _CONTENT_LANGUAGE_OVERRIDE


def system_language() -> str:
    """Return the OS language as a TMDB locale (unsupported -> en-US)."""
    candidates = (
        os.environ.get("LANGUAGE", "").split(":", 1)[0],
        os.environ.get("LC_ALL", ""),
        os.environ.get("LC_MESSAGES", ""),
        os.environ.get("LANG", ""),
    )
    selected = next((value for value in candidates if value.strip()), "")
    normalized = selected.split(".", 1)[0].replace("_", "-").casefold()
    return PERSIAN_LANGUAGE if normalized.startswith("fa") else DEFAULT_LANGUAGE


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


def active_language() -> str:
    """Return the effective TMDB content locale.

    Priority: manual content-language setting > temporary application
    language (GISHEH_LANGUAGE, kept for backward compatibility) > OS
    language. Unsupported locales resolve to en-US.
    """
    manual = get_content_language_setting()
    if manual != CONTENT_LANGUAGE_SYSTEM:
        return manual
    # Temporary UI language override behaves like a manual content choice
    # when the content setting itself is "system".
    configured = os.environ.get("GISHEH_LANGUAGE", "").strip()
    if configured:
        normalized = configured.split(".", 1)[0].replace("_", "-").casefold()
        if normalized.startswith("fa"):
            return PERSIAN_LANGUAGE
        if normalized:
            return DEFAULT_LANGUAGE
    return system_language()


def _effective_language(language: str | None) -> str:
    if language is None:
        return active_language()
    if isinstance(language, str) and language.strip().casefold() == "system":
        return active_language()
    normalized = language.strip().replace("_", "-").casefold()
    return PERSIAN_LANGUAGE if normalized.startswith("fa") else DEFAULT_LANGUAGE


def is_missing_translation(value: Any) -> bool:
    """Treat null/empty/whitespace-only/empty-array as untranslated."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _localized_value(primary: Any, fallback: Any) -> Any:
    """Fill missing localized fields without replacing available data.

    Per-field fallback: a present primary value (including person names and
    original titles) is always kept; only null/empty/whitespace/empty-array
    primaries are completed from the English fallback.
    """
    if is_missing_translation(primary):
        return fallback
    if isinstance(primary, dict) and isinstance(fallback, dict):
        return {
            key: _localized_value(primary.get(key), fallback.get(key))
            if key in primary
            else fallback.get(key)
            for key in dict.fromkeys((*primary, *fallback))
        }
    if isinstance(primary, list) and isinstance(fallback, list):
        if not primary:
            return fallback
        if not all(isinstance(item, dict) for item in primary):
            return primary
        identity_keys = (
            "id",
            "file_path",
            "season_number",
            "episode_number",
            "iso_3166_1",
        )
        identity_key = next(
            (
                key
                for key in identity_keys
                if all(key in item for item in primary)
                and any(key in item for item in fallback if isinstance(item, dict))
            ),
            None,
        )
        if identity_key is None:
            return primary
        fallback_by_id = {
            item.get(identity_key): item
            for item in fallback
            if isinstance(item, dict) and identity_key in item
        }
        return [
            _localized_value(item, fallback_by_id.get(item.get(identity_key), {}))
            for item in primary
        ]
    return primary


def merge_localized_payloads(
    primary: dict[str, Any], fallback: dict[str, Any]
) -> dict[str, Any]:
    """Merge English into empty localized fields while preserving primary values."""
    merged = _localized_value(primary, fallback)
    return merged if isinstance(merged, dict) else dict(primary)


# Language-dependent keys whose emptiness justifies one English fallback
# request. Image paths/poster data are excluded: they are handled through
# include_image_language ordering instead of a second request.
_LOCALIZABLE_KEYS = frozenset(
    {
        "title",
        "name",
        "original_title",
        "original_name",
        "overview",
        "biography",
        "tagline",
        "character",
        "description",
        "content",
        "text",
        "headline",
        "genres",
        "keywords",
        "results",
        "cast",
        "crew",
        "credits",
        "videos",
        "recommendations",
        "similar",
        "collection",
        "belongs_to_collection",
        "created_by",
        "networks",
        "companies",
        "production_companies",
    }
)


def _payload_needs_fallback(payload: Any, _depth: int = 0) -> bool:
    """Return True when any localizable field is missing/empty."""
    if _depth > 6 or payload is None:
        return False
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _LOCALIZABLE_KEYS and is_missing_translation(value):
                # Empty placeholders such as "" or [] mean TMDB has no
                # translation for this field in the requested language.
                # Whitespace-only strings count as missing as well.
                if isinstance(value, (str, list, tuple)) or value is None:
                    return True
            if isinstance(value, (dict, list, tuple)) and _payload_needs_fallback(
                value, _depth + 1
            ):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(
            isinstance(item, (dict, list, tuple))
            and _payload_needs_fallback(item, _depth + 1)
            for item in payload
        )
    return False


def _localized_request(
    path: str,
    *,
    token: str,
    params: dict[str, str | int | bool],
    language: str,
) -> dict[str, Any]:
    """Fetch TMDB in `language`, filling only missing fields from en-US.

    The English request is sent only when the primary payload actually has
    missing localizable data. A primary-request error never blocks the
    English fallback, and a fallback failure never discards primary data.
    """
    primary: dict[str, Any] | None = None
    primary_error: Exception | None = None
    try:
        primary = request_json(path, token=token, params={**params, "language": language})
    except TmdbError as error:
        primary_error = error
    if language == DEFAULT_LANGUAGE:
        if primary is None:
            raise primary_error  # type: ignore[misc]
        return primary
    if primary is not None and not _payload_needs_fallback(primary):
        return primary
    try:
        fallback = request_json(
            path,
            token=token,
            params={**params, "language": DEFAULT_LANGUAGE},
        )
    except TmdbError:
        if primary is not None:
            return primary
        if primary_error is not None:
            raise primary_error from None
        raise
    if primary is None:
        return fallback
    return merge_localized_payloads(primary, fallback)


def _image_language_order(language: str) -> tuple[str | None, ...]:
    return (
        ("fa", "en", None)
        if language == PERSIAN_LANGUAGE
        else ("en", None)
    )


def _prioritize_posters(payload: dict[str, Any], language: str) -> dict[str, Any]:
    images = payload.get("images")
    if not isinstance(images, dict):
        return payload
    posters = [
        item
        for item in images.get("posters", ())
        if isinstance(item, dict) and item.get("file_path")
    ]
    if not posters:
        return payload
    priorities = {
        image_language: index
        for index, image_language in enumerate(_image_language_order(language))
    }
    posters.sort(
        key=lambda item: (
            priorities.get(item.get("iso_639_1"), len(priorities)),
            -float(item.get("vote_average") or 0),
            -int(item.get("vote_count") or 0),
        )
    )
    images["posters"] = posters
    payload["poster_path"] = str(posters[0]["file_path"])
    return payload


def _summary_file(
    media_type: str,
    tmdb_id: int,
    *,
    language: str | None = None,
) -> Path:
    # Cache is keyed by resource ID + content type + language.
    namespace = "movie" if media_type == "movie" else "tv"
    effective_language = _effective_language(language)
    suffix = "" if effective_language == DEFAULT_LANGUAGE else f"-{effective_language}"
    return metadata_cache_dir() / f"{namespace}-{tmdb_id}{suffix}.json"


def load_summary(
    media_type: str,
    tmdb_id: int,
    *,
    max_age_seconds: float | None = None,
    language: str | None = None,
) -> dict[str, Any] | None:
    destination = _summary_file(media_type, tmdb_id, language=language)
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
    *,
    language: str | None = None,
) -> Path:
    destination = _summary_file(media_type, tmdb_id, language=language)
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
    try:
        response = image_http.get_client().get(
            f"{API_ROOT}{path}",
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )
        code = response.status_code
        if code == 401:
            raise TmdbError("TMDB rejected the read token (HTTP 401).") from None
        if not 200 <= code < 300:
            raise TmdbError(f"TMDB request failed with HTTP {code}.") from None
        payload = response.json()
        if not isinstance(payload, dict):
            raise TmdbError("TMDB returned an invalid response.")
        return payload
    except (httpx.TimeoutException, httpx.TransportError) as error:
        raise TmdbError(f"Could not reach TMDB: {error}") from None
    except ValueError as error:
        raise TmdbError(f"TMDB returned invalid JSON: {error}") from None


def fetch_explore_page(
    token: str,
    media_type: str,
    page: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch one pageable Explore feed while keeping anime distinct from TV."""
    page = max(1, page)
    effective_language = _effective_language(language)
    common: dict[str, str | int | bool] = {"page": page}
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
    payload = _localized_request(
        path,
        token=token,
        params=params,
        language=effective_language,
    )
    results = payload.get("results", [])
    return {
        "page": int(payload.get("page") or page),
        "total_pages": int(payload.get("total_pages") or page),
        "results": [item for item in results if isinstance(item, dict)],
    }


def fetch_explore(
    token: str, *, language: str | None = None
) -> dict[str, list[dict[str, Any]]]:
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
    language: str | None = None,
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
    effective_language = _effective_language(language)
    payload = _localized_request(
        path,
        token=token,
        params={
            "query": normalized_query,
            "include_adult": "false",
            "page": page,
        },
        language=effective_language,
    )
    results = [item for item in payload.get("results", ()) if isinstance(item, dict)]
    if media_type == "Anime":
        results = [item for item in results if 16 in item.get("genre_ids", ())]
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
    language: str | None = None,
) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    rating_resource = "release_dates" if namespace == "movie" else "content_ratings"
    effective_language = _effective_language(language)
    image_languages = image_language_param(effective_language)
    payload = _localized_request(
        f"/{namespace}/{tmdb_id}",
        token=token,
        params={
            "append_to_response": (
                f"credits,videos,images,recommendations,{rating_resource}"
            ),
            "include_image_language": image_languages,
        },
        language=effective_language,
    )
    return _prioritize_posters(payload, effective_language)


def fetch_episode_details(
    token: str,
    series_id: int,
    season_number: int,
    episode_number: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch metadata belonging to one TV episode, including its still image."""
    effective_language = _effective_language(language)
    return _localized_request(
        f"/tv/{series_id}/season/{season_number}/episode/{episode_number}",
        token=token,
        params={},
        language=effective_language,
    )


def fetch_season_details(
    token: str,
    series_id: int,
    season_number: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch every episode of one TV season with a single TMDB request."""
    effective_language = _effective_language(language)
    return _localized_request(
        f"/tv/{series_id}/season/{season_number}",
        token=token,
        params={},
        language=effective_language,
    )


def image_language_param(language: str | None = None) -> str:
    """Return include_image_language for TMDB image endpoints."""
    effective = _effective_language(language)
    return ",".join(
        "null" if value is None else value
        for value in _image_language_order(effective)
    )


def fetch_person_details(
    token: str,
    person_id: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch a person (name, biography, images) with per-field fallback."""
    effective_language = _effective_language(language)
    return _localized_request(
        f"/person/{person_id}",
        token=token,
        params={
            "append_to_response": "images,combined_credits",
            "include_image_language": image_language_param(effective_language),
        },
        language=effective_language,
    )


def fetch_collection_details(
    token: str,
    collection_id: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch a collection (name, overview, images) with per-field fallback."""
    effective_language = _effective_language(language)
    return _localized_request(
        f"/collection/{collection_id}",
        token=token,
        params={
            "include_image_language": image_language_param(effective_language),
        },
        language=effective_language,
    )


def clear_metadata_cache() -> None:
    """Remove only language-dependent TMDB metadata (keeps downloaded images)."""
    try:
        shutil.rmtree(metadata_cache_dir())
    except FileNotFoundError:
        pass
    except OSError as error:
        raise TmdbError(f"Could not clear the TMDB metadata cache: {error}") from None


def clear_language_cache() -> None:
    """Alias kept for the settings UI: drop language-keyed metadata."""
    clear_metadata_cache()


def fetch_summary(
    token: str,
    media_type: str,
    tmdb_id: int,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    namespace = "movie" if media_type == "movie" else "tv"
    effective_language = _effective_language(language)
    payload = _localized_request(
        f"/{namespace}/{tmdb_id}",
        token=token,
        params={},
        language=effective_language,
    )
    store_summary(namespace, tmdb_id, payload, language=effective_language)
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
