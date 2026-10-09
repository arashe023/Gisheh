"""Portable local-library interchange; no credentials, cache paths or cloud writes."""

from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
from typing import Any

from .constants import COLLECTION_NAMES, MEDIA_TYPES
from .models import TitleRecord, title_record_to_mapping
from .state_store import LIBRARY_MODE_LOCAL, archive_state, read_state, write_state
from .version import APP_VERSION

FORMAT = "io.github.arashe023.Gisheh.local-library"
FORMAT_VERSION = 1
PERSONAL_FIELDS = {
    "bookmarks": list,
    "favorites": list,
    "completed": list,
    "ratings": dict,
    "statusOverrides": dict,
    "episodeStatusOverrides": dict,
    "episodeWatchedAt": dict,
    "titleWatchedAt": dict,
}
MAX_IMPORT_BYTES = 50 * 1024 * 1024


def _portable(value):
    if isinstance(value, dict):
        return {
            key: _portable(item)
            for key, item in value.items()
            if not key.endswith("File")
            and key not in ("galleryBackdrops", "galleryPosters")
        }
    if isinstance(value, list):
        return [_portable(item) for item in value]
    return value


def _check_shape(raw, normalized):
    """Reject coercible malformed input, including nested episodes and casts."""
    if normalized is None:
        if raw is not None:
            raise ValueError("Invalid optional title value.")
    elif isinstance(normalized, dict):
        if not isinstance(raw, dict):
            raise ValueError("Expected a title object.")
        for key, value in normalized.items():
            if key in raw:
                _check_shape(raw[key], value)
    elif isinstance(normalized, list):
        if not isinstance(raw, list) or len(raw) != len(normalized):
            raise ValueError("Invalid title list.")
        for original, value in zip(raw, normalized):
            _check_shape(original, value)
    elif type(normalized) is float:
        if type(raw) not in (float, int) or not math.isfinite(raw):
            raise ValueError("Invalid numeric title value.")
    elif type(raw) is not type(normalized):
        raise ValueError("Invalid title value type.")


def _record(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Each title must be an object.")
    for key in (
        "id",
        "title",
        "type",
        "status",
        "date",
        "runtime",
        "country",
        "creator",
        "description",
    ):
        if not isinstance(raw.get(key), str):
            raise ValueError(f"Invalid title field: {key}.")
    if not raw["id"] or "/" in raw["id"] or not raw["title"].strip():
        raise ValueError("A title needs a valid ID and name.")
    if raw["type"] not in MEDIA_TYPES or raw["status"] not in COLLECTION_NAMES:
        raise ValueError("Invalid title type or status.")
    for key in ("year", "order", "posterVariant"):
        if type(raw.get(key)) is not int:
            raise ValueError(f"Invalid title number: {key}.")
    for key in ("genres", "posterPalette"):
        if not isinstance(raw.get(key), list) or not all(
            isinstance(v, str) for v in raw[key]
        ):
            raise ValueError(f"Invalid title list: {key}.")
    if len(raw["posterPalette"]) != 3 or not all(
        re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in raw["posterPalette"]
    ):
        raise ValueError("A poster palette needs three colors.")
    rating = raw.get("rating")
    if (
        type(rating) not in (int, float)
        or not math.isfinite(rating)
        or not 0 <= rating <= 10
    ):
        raise ValueError("Invalid title rating.")
    if raw.get("userRating") is not None and (
        type(raw["userRating"]) is not int or not 1 <= raw["userRating"] <= 10
    ):
        raise ValueError("Invalid personal rating.")
    try:
        normalized = title_record_to_mapping(TitleRecord.from_mapping(raw))
        _check_shape(raw, normalized)
        return _portable(normalized)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        raise ValueError(f"Invalid title data: {error}") from error


def validate_export(payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("This is not a Gisheh local-library backup.")
    if (
        type(payload.get("format_version")) is not int
        or payload["format_version"] != FORMAT_VERSION
    ):
        raise ValueError("Unsupported library backup version.")
    records = payload.get("localLibrary")
    profile = payload.get("localProfile")
    if not isinstance(records, list) or not isinstance(profile, dict):
        raise ValueError("The library and profile are required.")
    records = [_record(raw) for raw in records]
    ids = {raw["id"] for raw in records}
    if len(ids) != len(records):
        raise ValueError("Duplicate title IDs are not allowed.")
    normalized = {}
    for key, kind in PERSONAL_FIELDS.items():
        value = profile.get(key, kind())
        if not isinstance(value, kind):
            raise ValueError(f"Invalid profile field: {key}.")
        for record_id in value:
            if not isinstance(record_id, str) or record_id.split("/", 1)[0] not in ids:
                raise ValueError(f"Unknown title in {key}.")
        if key == "ratings" and any(
            type(v) is not int or not 1 <= v <= 10 for v in value.values()
        ):
            raise ValueError("Ratings must be integers from 1 to 10.")
        if key == "statusOverrides" and any(
            v not in COLLECTION_NAMES for v in value.values()
        ):
            raise ValueError("Invalid collection status.")
        if key == "episodeStatusOverrides" and any(
            type(v) is not bool for v in value.values()
        ):
            raise ValueError("Episode status must be boolean.")
        if key in ("episodeWatchedAt", "titleWatchedAt"):
            for date_value in value.values():
                if not isinstance(date_value, str):
                    raise ValueError("Watch dates must be strings.")
                # Legacy display dates remain compatible with existing state.
                from .models import parse_watched_datetime

                if parse_watched_datetime(date_value) is None:
                    raise ValueError("Invalid watch date.")
        normalized[key] = deepcopy(value)
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": str(payload.get("app_version", "")),
        "exported_at": str(payload.get("exported_at", "")),
        "localLibrary": records,
        "localProfile": normalized,
    }


def export_library(path=None) -> bytes:
    state = read_state(path)
    profile = state.get("localProfile", state)
    payload = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": APP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "localLibrary": state.get("localLibrary", []),
        "localProfile": {
            key: profile.get(key, kind()) for key, kind in PERSONAL_FIELDS.items()
        },
    }
    return (
        json.dumps(
            validate_export(payload), ensure_ascii=False, indent=2, allow_nan=False
        )
        + "\n"
    ).encode()


def parse_export(contents: bytes) -> dict:
    if len(contents) > MAX_IMPORT_BYTES:
        raise ValueError("The backup exceeds the 50 MiB import limit.")
    return validate_export(json.loads(contents))


def import_library(payload: dict, path=None) -> int:
    validated = validate_export(payload)
    state = read_state(path)
    if state.get("preferences", {}).get("libraryMode") != LIBRARY_MODE_LOCAL:
        raise ValueError("Switch to Local-first mode before restoring a library.")
    state["localLibrary"] = validated["localLibrary"]
    state["localProfile"] = validated["localProfile"]
    state.update(deepcopy(validated["localProfile"]))
    # Selection/scroll may refer to records replaced by this import.
    state.pop("collectionState", None)
    archive_state(path)
    write_state(state, path)
    return len(validated["localLibrary"])
