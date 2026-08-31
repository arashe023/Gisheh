#!/usr/bin/env python3
"""Simkl authentication and user-state sync client."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import image_http


APP_ID = "io.github.cineshelf.CineShelf"
APP_NAME = "cineshelf"
APP_VERSION = "1.3.0"
API_ROOT = "https://api.simkl.com"
USER_AGENT = f"CineShelf/{APP_VERSION}"
LIBRARY_GROUPS = {
    "movies": "movie",
    "shows": "show",
    "anime": "show",
}


class SimklError(RuntimeError):
    """Safe error that never contains an access token."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


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
    return os.environ.get("SIMKL_CLIENT_ID", "").strip() or _read_text(
        client_id_file()
    )


def read_token() -> str | None:
    return os.environ.get("SIMKL_ACCESS_TOKEN", "").strip() or _read_text(token_file())


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


def store_token(token: str) -> Path:
    return _store_private_text(token_file(), token)


def clear_token() -> None:
    try:
        token_file().unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SimklError(f"Could not remove the Simkl token: {error}") from None


def clear_account_cache() -> None:
    for path in (snapshot_file(), cache_dir() / "images" / "avatar.jpg"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise SimklError(f"Could not remove cached Simkl data: {error}") from None


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
    not_found = result.get("not_found", {})
    if isinstance(not_found, dict) and any(
        isinstance(items, list) and items for items in not_found.values()
    ):
        raise SimklError("Simkl could not match this TMDB title.")
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
) -> dict[str, Any]:
    if group not in LIBRARY_GROUPS:
        raise SimklError("The requested Simkl media type is not valid.")
    if watched:
        return _write_sync_json(
            "/sync/history",
            client_id=client_id,
            token=token,
            payload={group: [{"status": "completed", "ids": ids}]},
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
        params={"date_from": date_from},
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
