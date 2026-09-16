"""Persistent user-state helpers shared by startup and the main window."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


APP_ID = "io.github.arashe023.Gisheh"
LIBRARY_MODE_LOCAL = "local"
LIBRARY_MODE_SIMKL = "simkl"
LIBRARY_MODES = (LIBRARY_MODE_LOCAL, LIBRARY_MODE_SIMKL)


def user_state_file() -> Path:
    configured = os.environ.get("GISHEH_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return base / APP_ID / "state.json"


def read_state(path: Path | None = None) -> dict[str, Any]:
    source = path or user_state_file()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_state(payload: dict[str, Any], path: Path | None = None) -> Path:
    destination = path or user_state_file()
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(destination)
        os.chmod(destination, 0o600)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return destination


def selected_library_mode(path: Path | None = None) -> str | None:
    payload = read_state(path)
    if payload.get("onboardingComplete") is not True:
        return None
    preferences = payload.get("preferences")
    if not isinstance(preferences, dict):
        return None
    mode = preferences.get("libraryMode")
    return str(mode) if mode in LIBRARY_MODES else None


def save_library_mode(mode: str, path: Path | None = None) -> Path:
    if mode not in LIBRARY_MODES:
        raise ValueError(f"Unsupported library mode: {mode}")
    payload = read_state(path)
    preferences = payload.get("preferences")
    if not isinstance(preferences, dict):
        preferences = {}
    else:
        preferences = dict(preferences)
    preferences["libraryMode"] = mode
    payload["preferences"] = preferences
    payload["onboardingComplete"] = True
    return write_state(payload, path)


def clear_state(path: Path | None = None) -> None:
    """Remove all persisted Gisheh preferences and personal library state."""
    destination = path or user_state_file()
    try:
        destination.unlink()
    except FileNotFoundError:
        pass
