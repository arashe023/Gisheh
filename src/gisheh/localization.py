"""Localization shared by Gisheh components."""

from __future__ import annotations
from gettext import gettext as _
from .constants import (
    COLLECTIONS,
    N_,
)


TMDB_GENRES = {
    12: N_("Adventure"),
    14: N_("Fantasy"),
    16: N_("Animation"),
    18: N_("Drama"),
    27: N_("Horror"),
    28: N_("Action"),
    35: N_("Comedy"),
    36: N_("History"),
    37: N_("Western"),
    53: N_("Thriller"),
    80: N_("Crime"),
    99: N_("Documentary"),
    878: N_("Science Fiction"),
    9648: N_("Mystery"),
    10402: N_("Music"),
    10749: N_("Romance"),
    10751: N_("Family"),
    10752: N_("War"),
    10759: N_("Action & Adventure"),
    10762: N_("Kids"),
    10763: N_("News"),
    10764: N_("Reality"),
    10765: N_("Sci-Fi & Fantasy"),
    10766: N_("Soap"),
    10767: N_("Talk"),
    10768: N_("War & Politics"),
}

TMDB_GENRE_EN_NAME_TO_ID = {
    "adventure": 12,
    "fantasy": 14,
    "animation": 16,
    "drama": 18,
    "horror": 27,
    "action": 28,
    "comedy": 35,
    "history": 36,
    "western": 37,
    "thriller": 53,
    "crime": 80,
    "documentary": 99,
    "science fiction": 878,
    "sci-fi": 878,
    "mystery": 9648,
    "music": 10402,
    "romance": 10749,
    "family": 10751,
    "war": 10752,
    "action & adventure": 10759,
    "kids": 10762,
    "news": 10763,
    "reality": 10764,
    "sci-fi & fantasy": 10765,
    "science fiction & fantasy": 10765,
    "soap": 10766,
    "talk": 10767,
    "war & politics": 10768,
}

TMDB_STATUS_LABELS = {
    "released": N_("Released"),
    "returning series": N_("Returning Series"),
    "in production": N_("In Production"),
    "planned": N_("Planned"),
    "ended": N_("Ended"),
    "cancelled": N_("Cancelled"),
    "canceled": N_("Cancelled"),
    "pilot": N_("Pilot"),
    "upcoming": N_("Upcoming"),
    "airing": N_("Airing"),
    "synced": N_("Synced"),
    "plan to watch": N_("Plan to watch"),
    "watchlist": N_("Watchlist"),
    "watching": N_("Watching"),
    "watched": N_("Watched"),
    "on hold": N_("On Hold"),
    "hold": N_("On Hold"),
    "completed": N_("Watched"),
    "dropped": N_("Dropped"),
}

TMDB_COUNTRY_LABELS = {
    "united states of america": N_("United States of America"),
    "us": N_("United States of America"),
    "usa": N_("United States of America"),
    "united kingdom": N_("United Kingdom"),
    "gb": N_("United Kingdom"),
    "uk": N_("United Kingdom"),
    "iran": N_("Iran"),
    "ir": N_("Iran"),
    "france": N_("France"),
    "fr": N_("France"),
    "germany": N_("Germany"),
    "de": N_("Germany"),
    "japan": N_("Japan"),
    "jp": N_("Japan"),
    "south korea": N_("South Korea"),
    "kr": N_("South Korea"),
    "korea": N_("South Korea"),
    "india": N_("India"),
    "in": N_("India"),
    "canada": N_("Canada"),
    "ca": N_("Canada"),
    "australia": N_("Australia"),
    "au": N_("Australia"),
    "italy": N_("Italy"),
    "it": N_("Italy"),
    "spain": N_("Spain"),
    "es": N_("Spain"),
    "russia": N_("Russia"),
    "ru": N_("Russia"),
    "china": N_("China"),
    "cn": N_("China"),
    "turkey": N_("Turkey"),
    "tr": N_("Turkey"),
    "brazil": N_("Brazil"),
    "br": N_("Brazil"),
    "mexico": N_("Mexico"),
    "mx": N_("Mexico"),
    "netherlands": N_("Netherlands"),
    "nl": N_("Netherlands"),
    "sweden": N_("Sweden"),
    "se": N_("Sweden"),
    "norway": N_("Norway"),
    "no": N_("Norway"),
    "denmark": N_("Denmark"),
    "dk": N_("Denmark"),
}


def localize_genre_name(name: str) -> str:
    """Map an English TMDB genre name to its translated label."""
    genre_id = TMDB_GENRE_EN_NAME_TO_ID.get(name.strip().casefold())
    if genre_id is not None and genre_id in TMDB_GENRES:
        return _(TMDB_GENRES[genre_id])
    return name


def localize_genre_names(names: tuple[str, ...]) -> tuple[str, ...]:
    """Translate a tuple of English TMDB genre names for display."""
    return tuple(localize_genre_name(name) for name in names)


def localize_tmdb_status(value: str, fallback: str = "") -> str:
    """Map an English TMDB/Simkl status to its translated label."""
    label = TMDB_STATUS_LABELS.get(value.strip().casefold())
    if label is not None:
        return _(label)
    return value or fallback


def localize_country_name(value: str) -> str:
    """Map an English country name/code to its translated label."""
    label = TMDB_COUNTRY_LABELS.get(value.strip().casefold())
    if label is not None:
        return _(label)
    return value


def localize_countries(values: tuple[str, ...]) -> tuple[str, ...]:
    """Translate country names/codes for display."""
    return tuple(localize_country_name(value) for value in values)


def localize_collection_status(value: str) -> str:
    """Translate an internal library collection name for display.

    Collection names ("Watching", "Watched", ...) stay English inside
    records and filters; this maps them to the translated label only
    where they are shown to the user.
    """
    for name, _icon_name in COLLECTIONS:
        if value == name:
            return _(name)
    return value


STORED_FALLBACK_LABELS = {
    "Runtime unavailable": N_("Runtime unavailable"),
    "Loading from TMDB…": N_("Loading from TMDB…"),
    "Loading from TMDB": N_("Loading from TMDB"),
    "Uncategorized": N_("Uncategorized"),
    "Release date unavailable": N_("Release date unavailable"),
    "No overview is available yet.": N_("No overview is available yet."),
    "Synced from Simkl": N_("Synced from Simkl"),
    "Air date unavailable": N_("Air date unavailable"),
    "No episode overview is available.": N_("No episode overview is available."),
    "Unknown country": N_("Unknown country"),
    "Untitled": N_("Untitled"),
}


def _normalize_stored_fallback(value: str) -> str:
    """Translate a known English stored fallback sentence for display."""
    label = STORED_FALLBACK_LABELS.get(value.strip())
    if label is not None:
        return _(label)
    return value


def _normalize_stored_genres(values: tuple[str, ...]) -> tuple[str, ...]:
    """Translate stored genre values (names or old English fallbacks)."""
    normalized = []
    for value in values:
        fallback = STORED_FALLBACK_LABELS.get(value.strip())
        if fallback is not None:
            normalized.append(_(fallback))
        else:
            normalized.append(localize_genre_name(value))
    return tuple(normalized)


def _normalize_stored_country(value: str) -> str:
    """Translate a stored country value (possibly a comma-joined pair)."""
    parts = [part.strip() for part in value.split(",")]
    if len(parts) > 1:
        return ", ".join(
            _normalize_stored_fallback(part)
            if part in STORED_FALLBACK_LABELS
            else localize_country_name(part)
            for part in parts
        )
    if value.strip() in STORED_FALLBACK_LABELS:
        return _normalize_stored_fallback(value)
    return localize_country_name(value)
