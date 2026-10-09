"""Versioned, private state with atomic replacement and explicit recovery."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

APP_ID = "io.github.arashe023.Gisheh"
LIBRARY_MODE_LOCAL = "local"
LIBRARY_MODE_SIMKL = "simkl"
LIBRARY_MODES = (LIBRARY_MODE_LOCAL, LIBRARY_MODE_SIMKL)
SCHEMA_VERSION = 1
_LOCK = threading.RLock()


class StateError(OSError):
    """A state file must not be replaced until the problem is resolved."""


class StateDurabilityError(StateError):
    """Replacement succeeded but directory durability could not be confirmed."""

    committed = True


@dataclass(frozen=True)
class StateResult:
    status: str
    payload: dict[str, Any]
    error: str = ""


def user_state_file() -> Path:
    configured = os.environ.get("GISHEH_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base.expanduser() / APP_ID / "state.json"


def validate_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("State must be a JSON object.")
    version = payload.get("schema_version", 0)
    if type(version) is not int or version < 0:
        raise ValueError("Invalid state schema version.")
    if version > SCHEMA_VERSION:
        raise StateError("This data was saved by a newer version of Gisheh.")
    for key in (
        "preferences",
        "localProfile",
        "collectionState",
        "ratings",
        "statusOverrides",
        "episodeStatusOverrides",
        "episodeWatchedAt",
        "titleWatchedAt",
    ):
        if key in payload and not isinstance(payload[key], dict):
            raise ValueError(f"Invalid state field: {key}.")
    for key in ("localLibrary", "bookmarks", "favorites", "completed"):
        if key in payload and not isinstance(payload[key], list):
            raise ValueError(f"Invalid state field: {key}.")
    collection_state = payload.get("collectionState", {})
    if "views" in collection_state and not isinstance(collection_state["views"], dict):
        raise ValueError("Invalid collection views.")
    profiles = [payload]
    if "localProfile" in payload:
        profiles.append(payload["localProfile"])
    for profile in profiles:
        for key in ("bookmarks", "favorites", "completed"):
            if key in profile and (
                not isinstance(profile[key], list)
                or not all(isinstance(item, str) for item in profile[key])
            ):
                raise ValueError(f"Invalid profile field: {key}.")
        for key in (
            "ratings",
            "statusOverrides",
            "episodeStatusOverrides",
            "episodeWatchedAt",
            "titleWatchedAt",
        ):
            if key in profile and not isinstance(profile[key], dict):
                raise ValueError(f"Invalid profile field: {key}.")
        if any(
            type(value) is not int or not 1 <= value <= 10
            for value in profile.get("ratings", {}).values()
        ):
            raise ValueError("Invalid personal rating.")
        if any(
            type(value) is not bool
            for value in profile.get("episodeStatusOverrides", {}).values()
        ):
            raise ValueError("Invalid episode status.")
        for key in ("episodeWatchedAt", "titleWatchedAt"):
            if any(
                not isinstance(value, str) for value in profile.get(key, {}).values()
            ):
                raise ValueError("Invalid watch date.")
    for raw in payload.get("localLibrary", []):
        if not isinstance(raw, dict):
            raise ValueError("Invalid local library record.")
        try:
            from .models import TitleRecord

            TitleRecord.from_mapping(raw)
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            OverflowError,
        ) as error:
            raise ValueError(f"Invalid local library record: {error}") from error
    result = deepcopy(payload)
    result["schema_version"] = SCHEMA_VERSION
    return result


def inspect_state(path: Path | None = None) -> StateResult:
    source = path or user_state_file()
    try:
        contents = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        return StateResult("missing", {})
    except OSError as error:
        return StateResult("unreadable", {}, str(error))
    except UnicodeError as error:
        return StateResult("corrupt", {}, str(error))
    try:
        return StateResult("healthy", validate_state(json.loads(contents)))
    except StateError as error:
        return StateResult("future", {}, str(error))
    except (ValueError, TypeError) as error:
        return StateResult("corrupt", {}, str(error))


def read_state(path: Path | None = None) -> dict[str, Any]:
    result = inspect_state(path)
    if result.status not in ("missing", "healthy"):
        raise StateError(result.error)
    return result.payload


def _atomic_bytes(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.tmp-", dir=destination.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(destination)
        try:
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError as error:
            raise StateDurabilityError(str(error)) from error
    finally:
        temporary.unlink(missing_ok=True)


def backup_file(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def write_state(payload: dict[str, Any], path: Path | None = None) -> Path:
    destination = path or user_state_file()
    normalized = validate_state(payload)
    content = (
        json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    with _LOCK:
        previous = inspect_state(destination)
        if previous.status not in ("healthy", "missing"):
            raise StateError(previous.error)
        if previous.status == "healthy":
            try:
                _atomic_bytes(backup_file(destination), destination.read_bytes())
            except StateDurabilityError as error:
                # Only the backup changed; the primary state is still untouched.
                raise StateError(str(error)) from error
        _atomic_bytes(destination, content)
    return destination


def archive_state(path: Path | None = None) -> Path | None:
    """Keep an immutable recovery point across later ordinary state writes."""
    destination = path or user_state_file()
    with _LOCK:
        try:
            content = destination.read_bytes()
        except FileNotFoundError:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = destination.with_name(f"{destination.name}.recovery-{stamp}")
        _atomic_bytes(archive, content)
        return archive


def recover_state(path: Path | None = None, *, use_backup: bool) -> Path:
    """Explicit user recovery; keep the original bytes before any replacement."""
    destination = path or user_state_file()
    with _LOCK:
        payload: dict[str, Any] = {}
        if use_backup:
            result = inspect_state(backup_file(destination))
            if result.status != "healthy":
                raise StateError("No valid backup is available.")
            payload = result.payload
        original = None
        try:
            original = destination.read_bytes()
        except FileNotFoundError:
            pass
        if original is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            _atomic_bytes(
                destination.with_name(f"{destination.name}.recovery-{stamp}"), original
            )
        content = (
            json.dumps(validate_state(payload), ensure_ascii=False, indent=2) + "\n"
        ).encode()
        _atomic_bytes(destination, content)
    return destination


def selected_library_mode(path: Path | None = None) -> str | None:
    payload = read_state(path)
    if payload.get("onboardingComplete") is not True:
        return None
    preferences = payload.get("preferences", {})
    mode = preferences.get("libraryMode")
    return str(mode) if mode in LIBRARY_MODES else None


def save_library_mode(mode: str, path: Path | None = None) -> Path:
    if mode not in LIBRARY_MODES:
        raise ValueError(f"Unsupported library mode: {mode}")
    with _LOCK:
        payload = read_state(path)
        preferences = dict(payload.get("preferences", {}))
        preferences["libraryMode"] = mode
        payload["preferences"] = preferences
        payload["onboardingComplete"] = True
        return write_state(payload, path)


def clear_state(path: Path | None = None) -> None:
    destination = path or user_state_file()
    with _LOCK:
        for item in (
            destination,
            backup_file(destination),
            *destination.parent.glob(destination.name + ".recovery-*"),
        ):
            item.unlink(missing_ok=True)
