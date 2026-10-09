"""Constants shared by Gisheh components."""

from __future__ import annotations


APP_ID = "io.github.arashe023.Gisheh"

APP_NAME = "Gisheh"


def N_(message: str) -> str:
    """Mark a deferred user-facing string for gettext extraction."""
    return message


MEDIA_TYPES = (N_("Movies"), N_("Shows"), N_("Anime"))

COLLECTIONS = (
    (N_("Watching"), "media-playback-start-symbolic"),
    (N_("Watched"), "object-select-symbolic"),
    (N_("On Hold"), "media-playback-pause-symbolic"),
    (N_("Dropped"), "user-trash-symbolic"),
    (N_("Watchlist"), "bookmark-new-symbolic"),
)

COLLECTION_NAMES = tuple(name for name, _icon_name in COLLECTIONS)

SORT_OPTIONS = (
    ("recent", N_("Last watched")),
    ("title", N_("Title")),
    ("rating", N_("Highest rated")),
    ("year", N_("Release year")),
)

EXPLORE_SORT_OPTIONS = (
    ("trending", N_("Trending")),
    ("popular", N_("Popular")),
    ("rating", N_("Top rated")),
    ("upcoming", N_("Coming soon")),
)

EXPLORE_PERIODS = (N_("This month"), N_("This year"), N_("All releases"))

GRID_CARD_WIDTH = 140

GRID_CARD_HEIGHT = 210

GRID_COLUMN_GAP = 10

GRID_HORIZONTAL_PADDING = 24

GRID_MAX_COLUMNS = 6

GRID_ROW_HEIGHT = 226

CALENDAR_TIMELINE_PAGE_SIZE = 120

COLOR_SCHEMES = ("system", "light", "dark")

COLOR_SCHEME_LABELS = (N_("Follow system"), N_("Light"), N_("Dark"))
