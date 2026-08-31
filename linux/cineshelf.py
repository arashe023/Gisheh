#!/usr/bin/env python3
"""CineShelf: a lightweight native GTK4/libadwaita movie library."""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmdb_client  # noqa: E402


APP_ID = "io.github.cineshelf.CineShelf"
APP_NAME = "CineShelf"
APP_VERSION = "1.3.0"
RESOURCE_DIR = Path(__file__).resolve().parent
UI_FILE = RESOURCE_DIR / "cineshelf.ui"
CSS_FILE = RESOURCE_DIR / "cineshelf.css"
DATA_FILE = RESOURCE_DIR / "library.json"

MEDIA_TYPES = ("Movies", "Shows", "Anime")
STATUSES = ("Watchlist", "Watched", "Calendar", "Dropped")
SORT_OPTIONS = (
    ("recent", "Last watched"),
    ("title", "Title"),
    ("rating", "Highest rated"),
    ("year", "Release year"),
)
EXPLORE_SORT_OPTIONS = (
    ("trending", "Trending"),
    ("popular", "Popular"),
    ("rating", "Top rated"),
    ("upcoming", "Coming soon"),
)
EXPLORE_PERIODS = ("This month", "This year", "All releases")

STATUS_ICONS = {
    "Watchlist": "bookmark-new-symbolic",
    "Watched": "emblem-ok-symbolic",
    "Calendar": "x-office-calendar-symbolic",
    "Dropped": "user-trash-symbolic",
}

COLLECTIONS = (
    ("Favorites", "starred-symbolic", 12),
    ("Weekend picks", "media-playback-start-symbolic", 8),
    ("Modern classics", "non-starred-symbolic", 16),
)

LANGUAGE_BY_COUNTRY = {
    "Algeria": "AR",
    "Germany": "DE",
    "Iran": "FA",
    "Japan": "JA",
    "United Kingdom": "EN",
    "United States": "EN",
}

TMDB_GENRES = {
    12: "Adventure",
    14: "Fantasy",
    16: "Animation",
    18: "Drama",
    27: "Horror",
    28: "Action",
    35: "Comedy",
    36: "History",
    37: "Western",
    53: "Thriller",
    80: "Crime",
    99: "Documentary",
    878: "Science Fiction",
    9648: "Mystery",
    10402: "Music",
    10749: "Romance",
    10751: "Family",
    10752: "War",
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
}


def user_state_file() -> Path:
    configured = os.environ.get("CINESHELF_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / APP_ID / "state.json"


@dataclass(frozen=True, slots=True)
class CastMember:
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class EpisodeInfo:
    id: str
    number: int
    title: str
    date: str
    description: str
    watched: bool | None
    image_variant: int


@dataclass(frozen=True, slots=True)
class SeasonInfo:
    id: str
    number: int
    title: str
    watched: int
    episodes: int
    episode_items: tuple[EpisodeInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class TitleRecord:
    id: str
    title: str
    media_type: str
    status: str
    date: str
    year: int
    runtime: str
    rating: float
    user_rating: int | None
    genres: tuple[str, ...]
    country: str
    creator: str
    description: str
    poster_palette: tuple[str, str, str]
    poster_variant: int
    order: int
    certification: str
    language: str
    availability: str
    network: str
    external_ratings: tuple[tuple[str, str], ...]
    cast: tuple[CastMember, ...]
    seasons: tuple[SeasonInfo, ...]
    recommendations: tuple[str, ...]
    discover_period: str
    featured: bool
    popularity: int
    release_rank: int
    discover_layout: str
    tmdb_id: int | None = None
    tmdb_media_type: str | None = None
    artwork_file: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "TitleRecord":
        media_type = str(raw["type"])
        country = str(raw["country"])
        discover_period = str(raw.get("discoverPeriod", "All releases"))
        period_rank = {
            "This month": 0,
            "This year": 1,
            "All releases": 2,
        }.get(discover_period, 3)
        order = int(raw["order"])

        def parse_season(item: dict[str, Any], position: int) -> SeasonInfo:
            title = str(item["title"])
            default_number = 0 if title.casefold() == "specials" else position
            number = int(item.get("number", default_number))
            season_id = str(
                item.get("id", "specials" if number == 0 else f"s{number}")
            )
            return SeasonInfo(
                id=season_id,
                number=number,
                title=title,
                watched=int(item.get("watched", 0)),
                episodes=int(item["episodes"]),
                episode_items=tuple(
                    EpisodeInfo(
                        id=str(episode.get("id", f"e{episode_position}")),
                        number=int(episode.get("number", episode_position)),
                        title=str(
                            episode.get("title", f"Episode {episode_position}")
                        ),
                        date=str(episode.get("date", str(raw["year"]))),
                        description=str(
                            episode.get("description", raw["description"])
                        ),
                        watched=(
                            bool(episode["watched"])
                            if "watched" in episode
                            else None
                        ),
                        image_variant=int(
                            episode.get("imageVariant", episode_position)
                        ),
                    )
                    for episode_position, episode in enumerate(
                        item.get("episodeItems", ()), start=1
                    )
                ),
            )

        return cls(
            id=str(raw["id"]),
            title=str(raw["title"]),
            media_type=media_type,
            status=str(raw["status"]),
            date=str(raw["date"]),
            year=int(raw["year"]),
            runtime=str(raw["runtime"]),
            rating=float(raw["rating"]),
            user_rating=(
                int(raw["userRating"])
                if raw.get("userRating") is not None
                else None
            ),
            genres=tuple(str(value) for value in raw["genres"]),
            country=country,
            creator=str(raw["creator"]),
            description=str(raw["description"]),
            poster_palette=tuple(str(value) for value in raw["posterPalette"]),
            poster_variant=int(raw["posterVariant"]),
            order=order,
            certification=str(
                raw.get("certification", "TV-MA" if media_type != "Movies" else "NR")
            ),
            language=str(raw.get("language", LANGUAGE_BY_COUNTRY.get(country, "—"))),
            availability=str(
                raw.get(
                    "availability",
                    "Upcoming"
                    if "discoverPeriod" in raw
                    else "Airing" if media_type != "Movies" else "Released",
                )
            ),
            network=str(raw.get("network", "CineShelf")),
            external_ratings=tuple(
                (str(item["source"]), str(item["value"]))
                for item in raw.get("externalRatings", ())
            ),
            cast=tuple(
                CastMember(str(item["name"]), str(item["role"]))
                for item in raw.get("cast", ())
            ),
            seasons=tuple(
                parse_season(item, position)
                for position, item in enumerate(raw.get("seasons", ()), start=1)
            ),
            recommendations=tuple(str(value) for value in raw.get("recommendations", ())),
            discover_period=discover_period,
            featured=bool(raw.get("featured", False)),
            popularity=int(raw.get("popularity", order)),
            release_rank=int(raw.get("releaseRank", period_rank * 1000 - order)),
            discover_layout=str(raw.get("layout", "poster")),
            tmdb_id=(int(raw["tmdbId"]) if raw.get("tmdbId") is not None else None),
            tmdb_media_type=(
                str(raw["tmdbMediaType"])
                if raw.get("tmdbMediaType") is not None
                else None
            ),
            artwork_file=(
                str(raw["artworkFile"])
                if raw.get("artworkFile") is not None
                else None
            ),
        )


def load_catalog() -> tuple[
    tuple[TitleRecord, ...],
    tuple[TitleRecord, ...],
    dict[str, dict[str, int]],
]:
    with DATA_FILE.open(encoding="utf-8") as source:
        payload = json.load(source)

    records = tuple(TitleRecord.from_mapping(raw) for raw in payload["library"])
    explore_records = tuple(
        TitleRecord.from_mapping(raw) for raw in payload.get("explore", ())
    )
    totals = {
        str(media): {str(status): int(count) for status, count in values.items()}
        for media, values in payload["totals"].items()
    }
    return records, explore_records, totals


def _tmdb_palette(tmdb_id: int) -> tuple[str, str, str]:
    red = 36 + tmdb_id * 37 % 92
    green = 42 + tmdb_id * 53 % 90
    blue = 54 + tmdb_id * 71 % 110
    return (
        f"#{red // 2:02x}{green // 2:02x}{blue // 2:02x}",
        f"#{red:02x}{green:02x}{blue:02x}",
        f"#{min(255, red + 74):02x}{min(255, green + 74):02x}{min(255, blue + 74):02x}",
    )


def title_record_from_tmdb(
    raw: dict[str, Any],
    media_type: str,
    position: int,
    artwork_file: str | None,
) -> TitleRecord:
    tmdb_id = int(raw["id"])
    tmdb_namespace = "movie" if media_type == "Movies" else "tv"
    title = str(raw.get("title") or raw.get("name") or "Untitled")
    release_date = str(raw.get("release_date") or raw.get("first_air_date") or "")
    year = int(release_date[:4]) if release_date[:4].isdigit() else datetime.now().year
    genres = tuple(
        TMDB_GENRES[genre_id]
        for genre_id in raw.get("genre_ids", ())
        if genre_id in TMDB_GENRES
    ) or ("Uncategorized",)
    origin = raw.get("origin_country") or ()
    country = str(origin[0]) if origin else "—"
    rating = round(float(raw.get("vote_average") or 0), 1)
    layout = "hero" if position == 1 else "landscape" if position % 6 == 0 else "poster"

    return TitleRecord(
        id=f"tmdb-{tmdb_namespace}-{tmdb_id}",
        title=title,
        media_type=media_type,
        status="Watchlist",
        date=release_date or "Release date unavailable",
        year=year,
        runtime="Runtime unavailable",
        rating=rating,
        user_rating=None,
        genres=genres,
        country=country,
        creator="TMDB",
        description=str(raw.get("overview") or "No overview is available yet."),
        poster_palette=_tmdb_palette(tmdb_id),
        poster_variant=tmdb_id % 6 + 1,
        order=max(1, 1000 - position),
        certification="NR",
        language=str(raw.get("original_language") or "—").upper(),
        availability="Released" if media_type == "Movies" else "Airing",
        network="TMDB",
        external_ratings=(("TMDB", f"{rating:.1f}"),),
        cast=(),
        seasons=(),
        recommendations=(),
        discover_period="This month",
        featured=position == 1,
        popularity=round(float(raw.get("popularity") or 0)),
        release_rank=position,
        discover_layout=layout,
        tmdb_id=tmdb_id,
        tmdb_media_type=tmdb_namespace,
        artwork_file=artwork_file,
    )


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _rounded_rectangle(
    context: cairo.Context,
    x: float,
    y: float,
    width: float,
    height: float,
    radius: float,
) -> None:
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    context.close_path()


class GeneratedPosterWidget(Gtk.DrawingArea):
    """Tiny native poster renderer; no image decoder or browser is required."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
    ) -> None:
        super().__init__()
        self.record = record
        self.variant_offset = variant_offset
        self.show_text = show_text
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_size_request(width, height)
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Poster artwork for {record.title}"],
        )
        self.set_draw_func(self._draw)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        context: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        first, second, third = (_hex_to_rgb(color) for color in self.record.poster_palette)
        radius = min(11.0, width * 0.12)

        context.save()
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.clip()

        gradient = cairo.LinearGradient(0, 0, width, height)
        gradient.add_color_stop_rgb(0, *first)
        gradient.add_color_stop_rgb(0.58, *second)
        gradient.add_color_stop_rgb(1, *third)
        context.set_source(gradient)
        context.paint()

        self._draw_art(context, width, height, third)

        if not self.show_text:
            fade = cairo.LinearGradient(0, height * 0.54, 0, height)
            fade.add_color_stop_rgba(0, 0, 0, 0, 0)
            fade.add_color_stop_rgba(1, 0, 0, 0, 0.48)
            context.set_source(fade)
            context.rectangle(0, height * 0.54, width, height * 0.46)
            context.fill()
            context.restore()
            context.set_line_width(1)
            context.set_source_rgba(1, 1, 1, 0.16)
            _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
            context.stroke()
            return

        context.set_source_rgba(0, 0, 0, 0.58)
        context.rectangle(0, height * 0.73, width, height * 0.27)
        context.fill()

        context.set_source_rgb(1, 1, 1)
        title = self.record.title.upper()
        context.move_to(width * 0.08, height * 0.87)
        title_layout = PangoCairo.create_layout(context)
        title_layout.set_text(title, -1)
        title_layout.set_width(int(width * 0.84 * Pango.SCALE))
        title_layout.set_ellipsize(Pango.EllipsizeMode.END)
        title_layout.set_single_paragraph_mode(True)
        title_font = Pango.FontDescription("Sans Bold")
        title_font.set_absolute_size(int(max(7.0, width * 0.085) * Pango.SCALE))
        title_layout.set_font_description(title_font)
        PangoCairo.show_layout(context, title_layout)

        context.set_source_rgba(1, 1, 1, 0.78)
        context.move_to(width * 0.08, height * 0.95)
        year_layout = PangoCairo.create_layout(context)
        year_layout.set_text(str(self.record.year), -1)
        year_font = Pango.FontDescription("Sans")
        year_font.set_absolute_size(int(max(6.0, width * 0.07) * Pango.SCALE))
        year_layout.set_font_description(year_font)
        PangoCairo.show_layout(context, year_layout)

        context.restore()

        context.set_line_width(1)
        context.set_source_rgba(1, 1, 1, 0.16)
        _rounded_rectangle(context, 0.5, 0.5, width - 1, height - 1, radius)
        context.stroke()

    def _draw_art(
        self,
        context: cairo.Context,
        width: int,
        height: int,
        accent: tuple[float, float, float],
    ) -> None:
        variant = ((self.record.poster_variant - 1 + self.variant_offset) % 6) + 1
        context.set_line_width(max(1.0, width * 0.018))

        if variant == 1:
            context.set_source_rgba(*accent, 0.9)
            context.arc(width * 0.68, height * 0.23, width * 0.2, 0, math.tau)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.75, height * 0.18, width * 0.18, 0, math.tau)
            context.fill()
            context.arc(width * 0.5, height * 0.5, width * 0.1, 0, math.tau)
            context.fill()
            context.rectangle(width * 0.4, height * 0.57, width * 0.2, height * 0.26)
            context.fill()
        elif variant == 2:
            context.set_source_rgba(0, 0, 0, 0.56)
            for center_x in (0.36, 0.64):
                context.arc(width * center_x, height * 0.48, width * 0.14, 0, math.tau)
                context.fill()
                context.rectangle(
                    width * (center_x - 0.13),
                    height * 0.56,
                    width * 0.26,
                    height * 0.27,
                )
                context.fill()
        elif variant == 3:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.55, height * 0.4, width * 0.27, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 0.78, 0.25, 0.72)
            for index in range(12):
                angle = math.tau * index / 12
                context.move_to(
                    width * 0.55 + math.cos(angle) * width * 0.31,
                    height * 0.4 + math.sin(angle) * width * 0.31,
                )
                context.line_to(
                    width * 0.55 + math.cos(angle) * width * 0.44,
                    height * 0.4 + math.sin(angle) * width * 0.44,
                )
            context.stroke()
        elif variant == 4:
            context.set_source_rgba(1, 1, 1, 0.78)
            context.rectangle(width * 0.08, height * 0.1, width * 0.38, height * 0.6)
            context.fill()
            context.set_source_rgba(0, 0, 0, 0.7)
            context.rectangle(width * 0.14, height * 0.18, width * 0.2, height * 0.22)
            context.fill()
            context.set_source_rgba(*accent, 0.86)
            context.rectangle(width * 0.5, height * 0.28, width * 0.42, height * 0.25)
            context.fill()
        elif variant == 5:
            context.set_source_rgba(*accent, 0.74)
            for index in range(5):
                angle = -math.pi / 2 + index * math.tau / 5
                next_angle = angle + math.tau * 2 / 5
                context.move_to(
                    width * 0.5 + math.cos(angle) * width * 0.33,
                    height * 0.42 + math.sin(angle) * width * 0.33,
                )
                context.line_to(
                    width * 0.5 + math.cos(next_angle) * width * 0.33,
                    height * 0.42 + math.sin(next_angle) * width * 0.33,
                )
            context.stroke()
            context.set_source_rgba(0, 0, 0, 0.55)
            context.arc(width * 0.5, height * 0.43, width * 0.16, 0, math.tau)
            context.fill()
        else:
            context.set_source_rgba(*accent, 0.72)
            context.arc(width * 0.62, height * 0.29, width * 0.25, 0, math.tau)
            context.fill()
            context.set_source_rgba(1, 1, 1, 0.38)
            context.move_to(width * 0.08, height * 0.67)
            context.curve_to(
                width * 0.32,
                height * 0.48,
                width * 0.6,
                height * 0.8,
                width * 0.94,
                height * 0.56,
            )
            context.line_to(width * 0.94, height * 0.78)
            context.line_to(width * 0.08, height * 0.78)
            context.close_path()
            context.fill()


class PosterWidget(Gtk.Overlay):
    """Display cached TMDB artwork, falling back to the local poster renderer."""

    def __init__(
        self,
        record: TitleRecord,
        width: int,
        height: int,
        *,
        variant_offset: int = 0,
        show_text: bool = True,
    ) -> None:
        super().__init__()
        self.set_size_request(width, height)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_tooltip_text(f"{record.title}, {record.year}")
        self.set_accessible_role(Gtk.AccessibleRole.IMG)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Artwork for {record.title}"],
        )

        artwork_path = Path(record.artwork_file) if record.artwork_file else None
        if artwork_path is not None and artwork_path.is_file():
            picture = Gtk.Picture.new_for_filename(str(artwork_path))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_can_shrink(True)
            picture.set_hexpand(True)
            picture.set_vexpand(True)
            self.set_child(picture)
        else:
            generated = GeneratedPosterWidget(
                record,
                width,
                height,
                variant_offset=variant_offset,
                show_text=show_text,
            )
            generated.set_hexpand(True)
            generated.set_vexpand(True)
            self.set_child(generated)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(
        self,
        key: str,
        label: str,
        icon_name: str,
        count: int,
    ) -> None:
        super().__init__()
        self.key = key

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        content.set_margin_start(8)
        content.set_margin_end(8)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        title = Gtk.Label(label=label, xalign=0)
        title.set_hexpand(True)
        self.count_label = Gtk.Label(label=str(count))
        self.count_label.add_css_class("caption")
        self.count_label.add_css_class("numeric")

        content.append(icon)
        content.append(title)
        content.append(self.count_label)
        self.set_child(content)

    def set_count(self, count: int) -> None:
        self.count_label.set_label(str(count))


class CineShelfWindow:
    """Controller for the Gtk.Builder-defined window."""

    def __init__(self, application: Adw.Application) -> None:
        missing = [path.name for path in (UI_FILE, CSS_FILE, DATA_FILE) if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing application files: {', '.join(missing)}")

        self.records, self.explore_records, self.totals = load_catalog()
        self.library_ids = {record.id for record in self.records}
        self.explore_ids = {record.id for record in self.explore_records}
        if self.library_ids & self.explore_ids:
            raise ValueError("Library and Explore record IDs must be unique")
        self.records_by_id = {
            record.id: record for record in (*self.records, *self.explore_records)
        }

        self.active_destination = "library"
        self.active_media = "Movies"
        self.active_status = "Watched"
        self.genre = "All genres"
        self.sort_key = "recent"
        self.sort_reversed = False
        self.view_mode = "list"
        self.selected_id: str | None = "hush-girls"
        self.library_selected_id: str | None = self.selected_id
        self.explore_selected_id: str | None = None
        self.visible_records: tuple[TitleRecord, ...] = ()
        self.explore_visible_records: tuple[TitleRecord, ...] = ()
        self.explore_sort_key = "trending"
        self.explore_period = "This month"
        self.explore_genre = "All genres"
        self.explore_columns = 4
        self._explore_resize_source_id = 0
        self._last_explore_layout_width = 0

        self.bookmarks = {"hush-girls", "dune-two", "past-lives", "pluto"}
        self.favorites = {"oppenheimer", "perfect-days", "frieren"}
        self.completed = {
            record.id for record in self.records if record.status == "Watched"
        }
        self.ratings = {
            record.id: record.user_rating
            for record in self.records
            if record.user_rating is not None
        }
        self.status_overrides: dict[str, str] = {}
        self.episode_status_overrides: dict[str, bool] = {}
        self.episode_watched_at: dict[str, str] = {}
        self.tmdb_token = tmdb_client.read_token()
        self._tmdb_details_loading: set[str] = set()
        self._tmdb_details_loaded: set[str] = set()
        self.state_file = user_state_file()
        self._load_user_state()

        self._updating = False
        self._updating_details = False
        self._updating_season_switcher = False
        self.details_open = False
        self.detail_record_id: str | None = None
        self.current_season_index = 0
        self.current_episode_index = 0
        self.status_rows: dict[str, SidebarRow] = {}

        self.builder = Gtk.Builder.new_from_file(str(UI_FILE))
        self.window: Adw.ApplicationWindow = self._object("window")
        self.window.set_application(application)
        self.window.set_size_request(940, 600)

        self._load_css()
        self._bind_objects()
        self.details_surface.set_visible(False)
        self._build_browser_stack()
        self._configure_accessibility()
        self._build_header_controls()
        self._build_sidebar()
        self._build_result_views()
        self._build_explore_view()
        self._build_detail_sections()
        self._connect_signals(application)
        self._update_genre_model()
        self._refresh_results()
        if self.tmdb_token:
            self._load_tmdb_explore_async()

    def _object(self, name: str) -> Any:
        obj = self.builder.get_object(name)
        if obj is None:
            raise RuntimeError(f"The UI is missing required object '{name}'")
        return obj

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS_FILE))
        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.detail_tint_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            self.window.get_display(),
            self.detail_tint_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
        )

    def _bind_objects(self) -> None:
        names = (
            "toast_overlay",
            "media_switcher",
            "main_menu_button",
            "search_button",
            "add_sidebar_button",
            "destination_list",
            "status_list",
            "collections_list",
            "storage_button",
            "storage_progress",
            "preferences_button",
            "main_workspace",
            "library_pane",
            "eyebrow_label",
            "section_title",
            "section_count",
            "add_title_button",
            "search_entry",
            "sort_dropdown",
            "genre_dropdown",
            "view_switcher",
            "result_count",
            "result_description",
            "sort_direction_button",
            "results_scroller",
            "details_surface",
            "detail_navigation",
            "title_detail_page",
            "details_scroller",
            "detail_box",
            "detail_poster_host",
            "detail_status_label",
            "detail_overline",
            "detail_title",
            "community_rating",
            "detail_ratings_host",
            "watched_button",
            "favorite_button",
            "bookmark_button",
            "more_button",
            "runtime_label",
            "genres_label",
            "overview_label",
            "quick_actions_host",
            "creator_row",
            "release_row",
            "country_row",
            "activity_row",
            "activity_status",
            "activity_percentage",
            "activity_progress",
            "rating_value",
            "rating_grid",
            "detail_extra_sections",
            "explore_pane",
            "explore_header",
            "explore_eyebrow_label",
            "explore_count_label",
            "explore_filter_bar",
            "explore_sort_dropdown",
            "explore_period_dropdown",
            "explore_genre_dropdown",
            "explore_calendar_button",
            "explore_scroller",
            "explore_feed_box",
        )
        for name in names:
            setattr(self, name, self._object(name))

    def _build_browser_stack(self) -> None:
        """Place the XML-defined Library and Explore panes in one native stack."""
        self.main_workspace.remove(self.library_pane)
        self.browser_stack = Gtk.Stack()
        self.browser_stack.set_hexpand(True)
        self.browser_stack.set_vexpand(True)
        self.browser_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.browser_stack.set_transition_duration(160)
        self.browser_stack.add_named(self.library_pane, "library")
        self.browser_stack.add_named(self.explore_pane, "explore")
        self.browser_stack.set_visible_child_name("library")
        self.main_workspace.prepend(self.browser_stack)

    def _configure_accessibility(self) -> None:
        self.storage_progress.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Local library storage usage"],
        )
        self.activity_progress.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Watch progress"],
        )

    def _load_user_state(self) -> None:
        try:
            with self.state_file.open(encoding="utf-8") as source:
                payload = json.load(source)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as error:
            print(f"CineShelf could not read user state: {error}", file=sys.stderr)
            return

        valid_ids = set(self.records_by_id)
        is_valid_id = lambda value: value in valid_ids or str(value).startswith("tmdb-")
        self.bookmarks = {
            value
            for value in payload.get("bookmarks", self.bookmarks)
            if is_valid_id(value)
        }
        self.favorites = {
            value
            for value in payload.get("favorites", self.favorites)
            if is_valid_id(value)
        }
        self.completed = {
            value
            for value in payload.get("completed", self.completed)
            if is_valid_id(value)
        }
        self.ratings = {
            record_id: int(score)
            for record_id, score in payload.get("ratings", self.ratings).items()
            if is_valid_id(record_id) and isinstance(score, int) and 1 <= score <= 10
        }
        self.status_overrides = {
            record_id: status
            for record_id, status in payload.get("statusOverrides", {}).items()
            if is_valid_id(record_id) and status in STATUSES
        }
        self.episode_status_overrides = {
            str(key): value
            for key, value in payload.get("episodeStatusOverrides", {}).items()
            if isinstance(value, bool)
            and is_valid_id(str(key).split("/", 1)[0])
        }
        self.episode_watched_at = {
            str(key): str(value)
            for key, value in payload.get("episodeWatchedAt", {}).items()
            if isinstance(value, str)
            and is_valid_id(str(key).split("/", 1)[0])
        }

        for record_id, status in self.status_overrides.items():
            if status == "Watched":
                self.completed.add(record_id)
            else:
                self.completed.discard(record_id)

    def _save_user_state(self) -> None:
        payload = {
            "bookmarks": sorted(self.bookmarks),
            "favorites": sorted(self.favorites),
            "completed": sorted(self.completed),
            "ratings": dict(sorted(self.ratings.items())),
            "statusOverrides": dict(sorted(self.status_overrides.items())),
            "episodeStatusOverrides": dict(
                sorted(self.episode_status_overrides.items())
            ),
            "episodeWatchedAt": dict(sorted(self.episode_watched_at.items())),
        }
        temporary = self.state_file.with_name(f".{self.state_file.name}.tmp")
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.state_file)
        except OSError as error:
            print(f"CineShelf could not save user state: {error}", file=sys.stderr)

    def _build_header_controls(self) -> None:
        for media_type in MEDIA_TYPES:
            self.media_switcher.add(
                Adw.Toggle(name=media_type.lower(), label=media_type)
            )
        self.media_switcher.set_active_name("movies")

        self.view_switcher.add(
            Adw.Toggle(
                name="list",
                icon_name="view-list-symbolic",
                tooltip="List view",
            )
        )
        self.view_switcher.add(
            Adw.Toggle(
                name="grid",
                icon_name="view-grid-symbolic",
                tooltip="Grid view",
            )
        )
        self.view_switcher.set_active_name("list")

        self.rating_buttons: dict[int, Gtk.ToggleButton] = {}
        rating_leader: Gtk.ToggleButton | None = None
        for score in range(1, 11):
            button = Gtk.ToggleButton(label=str(score))
            button.set_tooltip_text(f"{score} out of 10")
            if rating_leader is None:
                rating_leader = button
            else:
                button.set_group(rating_leader)
            button.connect("toggled", self._on_rating_button_toggled, score)
            self.rating_grid.attach(button, (score - 1) % 5, (score - 1) // 5, 1, 1)
            self.rating_buttons[score] = button

        sort_labels = [label for _key, label in SORT_OPTIONS]
        self.sort_dropdown.set_model(Gtk.StringList.new(sort_labels))
        self.sort_dropdown.set_selected(0)

        explore_sort_labels = [label for _key, label in EXPLORE_SORT_OPTIONS]
        self.explore_sort_dropdown.set_model(Gtk.StringList.new(explore_sort_labels))
        self.explore_sort_dropdown.set_selected(0)
        self.explore_period_dropdown.set_model(
            Gtk.StringList.new(list(EXPLORE_PERIODS))
        )
        self.explore_period_dropdown.set_selected(0)

        menu = Gio.Menu()
        menu.append("About CineShelf", "app.about")
        menu.append("Quit", "app.quit")
        self.main_menu_button.set_menu_model(menu)

    def _build_sidebar(self) -> None:
        self.library_row = SidebarRow(
            "library",
            "Library",
            "folder-symbolic",
            self._library_total(self.active_media),
        )
        self.explore_row = SidebarRow(
            "explore",
            "Explore",
            "find-location-symbolic",
            self._explore_total(self.active_media),
        )
        self.destination_list.append(self.library_row)
        self.destination_list.append(self.explore_row)

        for status in STATUSES:
            row = SidebarRow(
                status,
                status,
                STATUS_ICONS[status],
                self._status_total(self.active_media, status),
            )
            self.status_rows[status] = row
            self.status_list.append(row)

        self._updating = True
        self.destination_list.select_row(self.library_row)
        self.status_list.select_row(self.status_rows[self.active_status])
        self._updating = False

        for label, icon_name, count in COLLECTIONS:
            self.collections_list.append(
                SidebarRow(label, label, icon_name, count)
            )

    def _build_result_views(self) -> None:
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_activate_on_single_click(True)
        self.list_box.set_show_separators(True)
        self.list_box.add_css_class("boxed-list")

        self.grid_box = Gtk.FlowBox()
        self.grid_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.grid_box.set_activate_on_single_click(True)
        self.grid_box.set_homogeneous(False)
        self.grid_box.set_min_children_per_line(1)
        self.grid_box.set_max_children_per_line(8)
        self.grid_box.set_row_spacing(16)
        self.grid_box.set_column_spacing(12)
        self.grid_box.set_valign(Gtk.Align.START)
        self.grid_box.add_css_class("movie-grid")

        self.empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="No titles found",
            description="Try a different search term or clear the genre filter.",
        )
        self.empty_page.add_css_class("empty-status")
        clear_button = Gtk.Button(label="Clear filters")
        clear_button.set_halign(Gtk.Align.CENTER)
        clear_button.add_css_class("pill")
        clear_button.connect("clicked", self._on_clear_filters)
        self.empty_page.set_child(clear_button)

    def _build_explore_view(self) -> None:
        self.explore_empty_page = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="Nothing new here yet",
            description="Try another period or clear the genre filter.",
        )
        self.explore_empty_page.add_css_class("empty-status")
        reset_button = Gtk.Button(label="Reset Explore filters")
        reset_button.set_halign(Gtk.Align.CENTER)
        reset_button.add_css_class("pill")
        reset_button.connect("clicked", self._on_clear_explore_filters)
        self.explore_empty_page.set_child(reset_button)

        self.explore_grid = Gtk.Grid()
        self.explore_grid.set_column_homogeneous(True)
        self.explore_grid.set_column_spacing(12)
        self.explore_grid.set_row_spacing(12)
        self.explore_grid.set_hexpand(True)
        self.explore_grid.set_valign(Gtk.Align.START)
        self.explore_grid.add_css_class("explore-grid")

        self._update_explore_genre_model()

    def _build_detail_sections(self) -> None:
        self.image_mode = "backdrops"

        self.cast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.cast_section = self._detail_section(
            "Cast & Crew",
            self._horizontal_scroller(self.cast_box, 116),
            action_label="See all",
        )

        self.episode_cards_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
        self.seasons_list = Gtk.ListBox()
        self.seasons_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.seasons_list.set_show_separators(True)
        self.seasons_list.add_css_class("boxed-list")
        series_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        series_content.append(self.episode_cards_box)
        series_content.append(self.seasons_list)
        self.series_section = self._detail_section("Episodes & Seasons", series_content)

        self.videos_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.videos_section = self._detail_section(
            "Videos",
            self._horizontal_scroller(self.videos_box, 126),
        )

        self.images_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.image_switcher = Adw.ToggleGroup()
        self.image_switcher.add(Adw.Toggle(name="backdrops", label="Backdrops"))
        self.image_switcher.add(Adw.Toggle(name="posters", label="Posters"))
        self.image_switcher.set_active_name("backdrops")
        self.images_section = self._detail_section(
            "Images",
            self._horizontal_scroller(self.images_box, 154),
            end_widget=self.image_switcher,
        )

        self.recommendations_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )
        self.recommendations_section = self._detail_section(
            "More like this",
            self._horizontal_scroller(self.recommendations_box, 186),
        )

        for section in (
            self.cast_section,
            self.series_section,
            self.videos_section,
            self.images_section,
            self.recommendations_section,
        ):
            self.detail_extra_sections.append(section)

        self._build_episode_navigation_pages()

    def _build_episode_navigation_pages(self) -> None:
        self.season_header_title = Adw.WindowTitle(title="Season", subtitle="")
        season_header = Adw.HeaderBar()
        season_header.set_show_start_title_buttons(False)
        season_header.set_show_end_title_buttons(False)
        season_header.set_show_back_button(True)
        season_header.set_title_widget(self.season_header_title)

        self.season_switcher = Adw.ToggleGroup()
        self.season_switcher_record_id: str | None = None
        self.season_switcher.set_halign(Gtk.Align.START)
        season_switcher_scroller = Gtk.ScrolledWindow()
        season_switcher_scroller.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.NEVER,
        )
        season_switcher_scroller.set_propagate_natural_height(True)
        season_switcher_scroller.set_child(self.season_switcher)

        self.season_summary_label = Gtk.Label(xalign=0)
        self.season_summary_label.add_css_class("dim-label")

        season_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            homogeneous=True,
        )
        self.season_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        self.season_comments_button = self._detail_navigation_action(
            "mail-unread-symbolic",
            "Comments",
        )
        season_actions.append(self.season_watched_button)
        season_actions.append(self.season_comments_button)

        episodes_heading = Gtk.CenterBox()
        episodes_title = Gtk.Label(label="Episodes", xalign=0)
        episodes_title.add_css_class("title-4")
        self.season_episode_count = Gtk.Label()
        self.season_episode_count.add_css_class("caption")
        self.season_episode_count.add_css_class("dim-label")
        episodes_heading.set_start_widget(episodes_title)
        episodes_heading.set_end_widget(self.season_episode_count)

        self.season_episodes_list = Gtk.ListBox()
        self.season_episodes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.season_episodes_list.set_activate_on_single_click(True)
        self.season_episodes_list.set_show_separators(True)
        self.season_episodes_list.add_css_class("boxed-list")
        self.season_episodes_list.add_css_class("episode-list")

        self.season_detail_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.season_detail_box.set_vexpand(True)
        self.season_detail_box.set_margin_top(16)
        self.season_detail_box.set_margin_bottom(28)
        self.season_detail_box.set_margin_start(16)
        self.season_detail_box.set_margin_end(16)
        self.season_detail_box.add_css_class("detail-page")
        self.season_detail_box.add_css_class("detail-subpage-content")
        self.season_detail_box.append(season_switcher_scroller)
        self.season_detail_box.append(self.season_summary_label)
        self.season_detail_box.append(season_actions)
        self.season_detail_box.append(Gtk.Separator())
        self.season_detail_box.append(episodes_heading)
        self.season_detail_box.append(self.season_episodes_list)

        self.season_details_scroller = Gtk.ScrolledWindow()
        self.season_details_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.season_details_scroller.set_vexpand(True)
        self.season_details_scroller.add_css_class("detail-tint-surface")
        self.season_details_scroller.set_child(self.season_detail_box)

        season_toolbar = Adw.ToolbarView()
        season_toolbar.add_css_class("detail-subpage-toolbar")
        season_toolbar.add_top_bar(season_header)
        season_toolbar.set_content(self.season_details_scroller)
        self.season_detail_page = Adw.NavigationPage.new_with_tag(
            season_toolbar,
            "Season",
            "season",
        )

        self.episode_header_title = Adw.WindowTitle(title="Episode", subtitle="")
        episode_header = Adw.HeaderBar()
        episode_header.set_show_start_title_buttons(False)
        episode_header.set_show_end_title_buttons(False)
        episode_header.set_show_back_button(True)
        episode_header.set_title_widget(self.episode_header_title)

        self.episode_position_label = Gtk.Label(xalign=0)
        self.episode_position_label.add_css_class("dim-label")
        self.episode_position_dots = Gtk.Label(xalign=1)
        self.episode_position_dots.add_css_class("numeric")
        self.episode_position_dots.add_css_class("dim-label")
        episode_position = Gtk.CenterBox()
        episode_position.set_start_widget(self.episode_position_label)
        episode_position.set_end_widget(self.episode_position_dots)

        self.episode_hero_host = Gtk.Box()
        self.episode_hero_host.set_halign(Gtk.Align.CENTER)
        self.episode_hero_host.set_hexpand(True)
        self.episode_hero_host.set_size_request(-1, 200)

        self.episode_title_label = Gtk.Label(xalign=0)
        self.episode_title_label.set_wrap(True)
        self.episode_title_label.add_css_class("title-1")
        self.episode_date_label = Gtk.Label(xalign=0)
        self.episode_date_label.add_css_class("dim-label")

        episode_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
        self.episode_watched_button = self._detail_navigation_action(
            "object-select-symbolic",
            "Watched",
        )
        self.episode_comments_button = self._detail_navigation_action(
            "mail-unread-symbolic",
            "Comments",
        )
        self.episode_check_in_button = self._detail_navigation_action(
            "media-playback-start-symbolic",
            "Check in",
        )
        episode_actions.append(self.episode_watched_button)
        episode_actions.append(self.episode_comments_button)
        episode_actions.append(self.episode_check_in_button)

        self.episode_watched_at_label = Gtk.Label(xalign=0.5)
        self.episode_watched_at_label.set_wrap(True)
        self.episode_watched_at_label.add_css_class("caption")
        self.episode_watched_at_label.add_css_class("dim-label")

        overview_title = Gtk.Label(label="Overview", xalign=0)
        overview_title.add_css_class("title-4")
        self.episode_overview_label = Gtk.Label(xalign=0)
        self.episode_overview_label.set_wrap(True)
        self.episode_overview_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.episode_overview_label.add_css_class("dim-label")

        cast_heading = Gtk.Label(label="Cast & Crew", xalign=0)
        cast_heading.add_css_class("title-4")
        self.episode_cast_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )

        self.episode_detail_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.episode_detail_box.set_vexpand(True)
        self.episode_detail_box.set_margin_top(14)
        self.episode_detail_box.set_margin_bottom(28)
        self.episode_detail_box.set_margin_start(16)
        self.episode_detail_box.set_margin_end(16)
        self.episode_detail_box.add_css_class("detail-page")
        self.episode_detail_box.add_css_class("detail-subpage-content")
        self.episode_detail_box.append(episode_position)
        self.episode_detail_box.append(self.episode_hero_host)
        self.episode_detail_box.append(self.episode_title_label)
        self.episode_detail_box.append(self.episode_date_label)
        self.episode_detail_box.append(episode_actions)
        self.episode_detail_box.append(self.episode_watched_at_label)
        self.episode_detail_box.append(Gtk.Separator())
        self.episode_detail_box.append(overview_title)
        self.episode_detail_box.append(self.episode_overview_label)
        self.episode_detail_box.append(Gtk.Separator())
        self.episode_detail_box.append(cast_heading)
        self.episode_detail_box.append(
            self._horizontal_scroller(self.episode_cast_box, 116)
        )

        self.episode_details_scroller = Gtk.ScrolledWindow()
        self.episode_details_scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.episode_details_scroller.set_vexpand(True)
        self.episode_details_scroller.add_css_class("detail-tint-surface")
        self.episode_details_scroller.set_child(self.episode_detail_box)

        episode_toolbar = Adw.ToolbarView()
        episode_toolbar.add_css_class("detail-subpage-toolbar")
        episode_toolbar.add_top_bar(episode_header)
        episode_toolbar.set_content(self.episode_details_scroller)
        self.episode_detail_page = Adw.NavigationPage.new_with_tag(
            episode_toolbar,
            "Episode",
            "episode",
        )

        self.detail_navigation.add(self.season_detail_page)
        self.detail_navigation.add(self.episode_detail_page)

    @staticmethod
    def _detail_navigation_action(icon_name: str, label: str) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        caption = Gtk.Label(label=label)
        caption.set_wrap(True)
        caption.add_css_class("caption")
        content.append(icon)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("flat")
        button.add_css_class("detail-action-button")
        button.action_label = caption
        return button

    def _detail_section(
        self,
        title: str,
        content: Gtk.Widget,
        *,
        action_label: str | None = None,
        end_widget: Gtk.Widget | None = None,
    ) -> Gtk.Box:
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        section.add_css_class("detail-section")

        heading = Gtk.CenterBox()
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        heading.set_start_widget(label)

        if end_widget is not None:
            heading.set_end_widget(end_widget)
        elif action_label is not None:
            action = Gtk.Button(label=action_label)
            action.add_css_class("flat")
            action.add_css_class("caption")
            action.connect(
                "clicked",
                lambda _button, section_title=title: self._toast(
                    f"Open all {section_title.lower()}"
                ),
            )
            heading.set_end_widget(action)

        section.append(heading)
        section.append(content)
        return section

    @staticmethod
    def _horizontal_scroller(child: Gtk.Widget, height: int) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_min_content_height(height)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(child)
        return scroller

    def _connect_signals(self, application: Adw.Application) -> None:
        self.media_switcher.connect("notify::active-name", self._on_media_changed)
        self.view_switcher.connect("notify::active-name", self._on_view_changed)
        self.destination_list.connect(
            "row-selected",
            self._on_destination_selected,
        )
        self.status_list.connect("row-selected", self._on_status_selected)
        self.collections_list.connect("row-activated", self._on_collection_activated)
        self.list_box.connect("row-selected", self._on_list_selected)
        self.list_box.connect("row-activated", self._on_list_activated)
        self.grid_box.connect("selected-children-changed", self._on_grid_selected)
        self.grid_box.connect("child-activated", self._on_grid_activated)
        self.seasons_list.connect("row-activated", self._on_season_activated)
        self.season_episodes_list.connect(
            "row-activated",
            self._on_episode_activated,
        )

        self.search_entry.connect("search-changed", self._on_search_changed)
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        self.genre_dropdown.connect("notify::selected", self._on_genre_changed)
        self.explore_sort_dropdown.connect(
            "notify::selected",
            self._on_explore_sort_changed,
        )
        self.explore_period_dropdown.connect(
            "notify::selected",
            self._on_explore_period_changed,
        )
        self.explore_genre_dropdown.connect(
            "notify::selected",
            self._on_explore_genre_changed,
        )
        self.explore_calendar_button.connect(
            "clicked",
            lambda *_args: self._toast("Release calendar opened"),
        )
        self.sort_direction_button.connect("clicked", self._on_reverse_sort)
        self.image_switcher.connect("notify::active-name", self._on_image_mode_changed)
        self.season_switcher.connect(
            "notify::active-name",
            self._on_season_switch_changed,
        )

        self.search_button.connect("clicked", self._on_search_requested)
        self.add_sidebar_button.connect(
            "clicked", lambda *_args: self._toast("Add dialog opened")
        )
        self.add_title_button.connect(
            "clicked",
            lambda *_args: self._toast(
                f"Add {self.active_media.lower()} to {self.active_status.lower()}"
            ),
        )
        self.storage_button.connect(
            "clicked", lambda *_args: self._toast("Library storage: 68% used")
        )
        self.preferences_button.connect(
            "clicked", lambda *_args: self._toast("Preferences opened")
        )
        self.more_button.connect("clicked", self._on_more_clicked)
        self.watched_button.connect("clicked", self._on_watched_clicked)
        self.favorite_button.connect("toggled", self._on_favorite_toggled)
        self.bookmark_button.connect("toggled", self._on_bookmark_toggled)
        self.season_watched_button.connect(
            "clicked",
            self._on_season_watched_clicked,
        )
        self.season_comments_button.connect(
            "clicked",
            lambda *_args: self._toast("Season comments opened"),
        )
        self.episode_watched_button.connect(
            "clicked",
            self._on_episode_watched_clicked,
        )
        self.episode_comments_button.connect(
            "clicked",
            lambda *_args: self._toast("Episode comments opened"),
        )
        self.episode_check_in_button.connect(
            "clicked",
            lambda *_args: self._toast("Episode check-in recorded"),
        )

        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", self._on_search_requested)
        self.window.add_action(search_action)
        application.set_accels_for_action("win.search", ["<primary>k"])

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_search_key_pressed)
        self.search_entry.add_controller(key_controller)

        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.connect("notify::dark", self._on_style_scheme_changed)
        self.window.connect("realize", self._on_window_realized)

    def _on_window_realized(self, window: Gtk.Window) -> None:
        surface = window.get_surface()
        if surface is None:
            return
        surface.connect("notify::width", self._on_surface_width_changed)
        self._queue_explore_resize()

    def _on_surface_width_changed(
        self,
        _surface: Gdk.Surface,
        _parameter: Any,
    ) -> None:
        self._queue_explore_resize()

    def _queue_explore_resize(self) -> None:
        if self._explore_resize_source_id:
            GLib.source_remove(self._explore_resize_source_id)
        self._explore_resize_source_id = GLib.timeout_add(
            90,
            self._apply_explore_resize,
        )

    def _apply_explore_resize(self) -> bool:
        self._explore_resize_source_id = 0
        width = self.explore_pane.get_width() or self.library_pane.get_width()
        if width <= 0:
            return GLib.SOURCE_REMOVE
        columns = self._explore_columns_for_width(width)
        columns_changed = columns != self.explore_columns
        width_changed = abs(width - self._last_explore_layout_width) >= 12
        self._last_explore_layout_width = width
        self.explore_columns = columns
        if (
            self.active_destination == "explore"
            and self.explore_visible_records
            and (columns_changed or width_changed)
        ):
            scroll_value = self.explore_scroller.get_vadjustment().get_value()
            self._populate_explore_feed()
            self._scroll_to_value(self.explore_scroller, scroll_value)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _explore_columns_for_width(width: int) -> int:
        return 4 if width >= 620 else 3 if width >= 430 else 2

    def _explore_card_height(self, kind: str) -> int:
        """Size a card from its real grid span instead of its child request."""
        pane_width = (
            self._last_explore_layout_width
            or self.explore_pane.get_width()
            or self.library_pane.get_width()
            or 620
        )
        content_width = max(280, pane_width - 48)
        columns = max(2, self.explore_columns)
        column_width = max(96, (content_width - 12 * (columns - 1)) / columns)
        if kind == "hero":
            span = columns
        elif kind == "landscape":
            span = min(2, columns)
        else:
            span = 1
        card_width = column_width * span + 12 * (span - 1)

        if kind == "hero":
            return round(min(360, max(220, card_width / 2)))
        if kind == "landscape":
            return round(min(300, max(190, card_width * 0.72)))
        return round(min(320, max(220, card_width * 1.5)))

    def _update_genre_model(self) -> None:
        genres = sorted(
            {
                genre
                for record in self.records
                if record.media_type == self.active_media
                for genre in record.genres
            }
        )
        self.genre_options = ("All genres", *genres)
        self._updating = True
        self.genre_dropdown.set_model(Gtk.StringList.new(list(self.genre_options)))
        self.genre_dropdown.set_selected(0)
        self.genre = "All genres"
        self._updating = False

    def _update_explore_genre_model(self, *, preserve: bool = True) -> None:
        previous_genre = self.explore_genre
        genres = sorted(
            {
                genre
                for record in self.explore_records
                if record.media_type == self.active_media
                for genre in record.genres
            }
        )
        self.explore_genre_options = ("All genres", *genres)
        selected_genre = (
            previous_genre
            if preserve and previous_genre in self.explore_genre_options
            else "All genres"
        )
        self._updating = True
        self.explore_genre_dropdown.set_model(
            Gtk.StringList.new(list(self.explore_genre_options))
        )
        self.explore_genre_dropdown.set_selected(
            self.explore_genre_options.index(selected_genre)
        )
        self.explore_genre = selected_genre
        self._updating = False

    def _load_tmdb_explore_async(self) -> None:
        token = self.tmdb_token
        if not token:
            return
        threading.Thread(
            target=self._load_tmdb_explore_worker,
            args=(token,),
            name="cineshelf-tmdb-explore",
            daemon=True,
        ).start()

    def _load_tmdb_explore_worker(self, token: str) -> None:
        try:
            collections = tmdb_client.fetch_explore(token)
            records: list[TitleRecord] = []
            for media_type in MEDIA_TYPES:
                for position, raw in enumerate(
                    collections.get(media_type, ())[:18],
                    start=1,
                ):
                    image_path = raw.get("poster_path")
                    if position == 1 or position % 6 == 0:
                        image_path = raw.get("backdrop_path") or image_path
                    artwork_file = tmdb_client.cache_image(
                        str(image_path) if image_path else None,
                        size="w780" if position == 1 or position % 6 == 0 else "w500",
                    )
                    records.append(
                        title_record_from_tmdb(
                            raw,
                            media_type,
                            position,
                            artwork_file,
                        )
                    )
            if not records:
                raise tmdb_client.TmdbError("TMDB returned no titles.")
        except tmdb_client.TmdbError as error:
            GLib.idle_add(self._on_tmdb_explore_failed, str(error))
            return
        GLib.idle_add(self._apply_tmdb_explore, tuple(records))

    def _apply_tmdb_explore(self, records: tuple[TitleRecord, ...]) -> bool:
        self.explore_records = records
        self.explore_ids = {record.id for record in records}
        self.records_by_id = {
            record.id: record for record in (*self.records, *self.explore_records)
        }
        self.explore_selected_id = None
        self._update_sidebar_counts()
        self._update_explore_genre_model(preserve=False)
        if self.active_destination == "explore":
            self._refresh_explore()
        self._toast("Live TMDB data loaded")
        return GLib.SOURCE_REMOVE

    def _on_tmdb_explore_failed(self, message: str) -> bool:
        print(f"CineShelf TMDB: {message}", file=sys.stderr)
        self._toast("TMDB unavailable — showing local sample data")
        return GLib.SOURCE_REMOVE

    def _load_tmdb_details_async(self, record: TitleRecord) -> None:
        if (
            not self.tmdb_token
            or record.tmdb_id is None
            or record.tmdb_media_type is None
            or record.id in self._tmdb_details_loading
            or record.id in self._tmdb_details_loaded
        ):
            return
        self._tmdb_details_loading.add(record.id)
        threading.Thread(
            target=self._load_tmdb_details_worker,
            args=(record, self.tmdb_token),
            name=f"cineshelf-tmdb-{record.tmdb_id}",
            daemon=True,
        ).start()

    def _load_tmdb_details_worker(self, record: TitleRecord, token: str) -> None:
        try:
            payload = tmdb_client.fetch_details(
                token,
                record.tmdb_media_type or "movie",
                record.tmdb_id or 0,
            )
            artwork_file = tmdb_client.cache_image(
                str(payload.get("backdrop_path") or payload.get("poster_path") or ""),
                size="w780",
            )
            genres = tuple(
                str(item["name"])
                for item in payload.get("genres", ())
                if isinstance(item, dict) and item.get("name")
            ) or record.genres
            cast = tuple(
                CastMember(str(item.get("name", "—")), str(item.get("character", "Cast")))
                for item in payload.get("credits", {}).get("cast", ())[:8]
                if isinstance(item, dict)
            )
            if record.tmdb_media_type == "movie":
                runtime_minutes = int(payload.get("runtime") or 0)
                directors = [
                    str(item.get("name"))
                    for item in payload.get("credits", {}).get("crew", ())
                    if isinstance(item, dict) and item.get("job") == "Director"
                ]
                creator = ", ".join(directors[:2]) or record.creator
                seasons: tuple[SeasonInfo, ...] = ()
            else:
                runtimes = payload.get("episode_run_time") or ()
                runtime_minutes = int(runtimes[0]) if runtimes else 0
                creators = [
                    str(item.get("name"))
                    for item in payload.get("created_by", ())
                    if isinstance(item, dict) and item.get("name")
                ]
                creator = ", ".join(creators[:2]) or record.creator
                seasons = tuple(
                    SeasonInfo(
                        id=f"s{int(item.get('season_number', position))}",
                        number=int(item.get("season_number", position)),
                        title=str(item.get("name") or f"Season {position}"),
                        watched=0,
                        episodes=int(item.get("episode_count") or 0),
                    )
                    for position, item in enumerate(payload.get("seasons", ()), start=1)
                    if isinstance(item, dict)
                )
            runtime = (
                f"{runtime_minutes // 60}h {runtime_minutes % 60:02d}m"
                if runtime_minutes >= 60
                else f"{runtime_minutes}m" if runtime_minutes else record.runtime
            )
            countries = [
                str(item.get("name"))
                for item in payload.get("production_countries", ())
                if isinstance(item, dict) and item.get("name")
            ]
            networks = [
                str(item.get("name"))
                for item in payload.get("networks", ())
                if isinstance(item, dict) and item.get("name")
            ]
            updated = replace(
                record,
                runtime=runtime,
                genres=genres,
                country=", ".join(countries[:2]) or record.country,
                creator=creator,
                description=str(payload.get("overview") or record.description),
                availability=str(payload.get("status") or record.availability),
                network=", ".join(networks[:2]) or record.network,
                cast=cast or record.cast,
                seasons=seasons or record.seasons,
                artwork_file=artwork_file or record.artwork_file,
            )
        except tmdb_client.TmdbError as error:
            GLib.idle_add(self._on_tmdb_details_failed, record.id, str(error))
            return
        GLib.idle_add(self._apply_tmdb_details, updated)

    def _apply_tmdb_details(self, updated: TitleRecord) -> bool:
        self._tmdb_details_loading.discard(updated.id)
        self._tmdb_details_loaded.add(updated.id)
        self.records_by_id[updated.id] = updated
        self.explore_records = tuple(
            updated if record.id == updated.id else record
            for record in self.explore_records
        )
        if self.selected_id == updated.id:
            self._update_details()
        return GLib.SOURCE_REMOVE

    def _on_tmdb_details_failed(self, record_id: str, message: str) -> bool:
        self._tmdb_details_loading.discard(record_id)
        print(f"CineShelf TMDB details: {message}", file=sys.stderr)
        return GLib.SOURCE_REMOVE

    def _effective_status(self, record: TitleRecord) -> str:
        return self.status_overrides.get(record.id, record.status)

    def _status_total(self, media_type: str, status: str) -> int:
        total = self.totals[media_type][status]
        total += sum(
            record.id in self.bookmarks
            and record.media_type == media_type
            and self._effective_status(record) == status
            for record in self.explore_records
        )
        for record_id, override in self.status_overrides.items():
            if record_id not in self.library_ids:
                continue
            record = self.records_by_id[record_id]
            if record.media_type != media_type or override == record.status:
                continue
            if record.status == status:
                total -= 1
            if override == status:
                total += 1
        return total

    def _explore_total(self, media_type: str) -> int:
        return sum(
            record.media_type == media_type for record in self.explore_records
        )

    def _library_total(self, media_type: str) -> int:
        return sum(self._status_total(media_type, status) for status in STATUSES)

    def _filtered_explore_records(self) -> tuple[TitleRecord, ...]:
        records = []
        for record in self.explore_records:
            if record.media_type != self.active_media:
                continue
            if (
                self.explore_period == "This month"
                and record.discover_period != "This month"
            ):
                continue
            if (
                self.explore_period == "This year"
                and record.discover_period not in ("This month", "This year")
            ):
                continue
            if (
                self.explore_genre != "All genres"
                and self.explore_genre not in record.genres
            ):
                continue
            records.append(record)

        if self.explore_sort_key == "rating":
            key_function = lambda item: (item.rating, item.order)
            reverse = True
        elif self.explore_sort_key == "popular":
            key_function = lambda item: (item.popularity, item.order)
            reverse = True
        elif self.explore_sort_key == "upcoming":
            key_function = lambda item: (item.release_rank, -item.order)
            reverse = False
        else:
            key_function = lambda item: item.order
            reverse = True
        records.sort(key=key_function, reverse=reverse)
        return tuple(records)

    def _library_records(self) -> tuple[TitleRecord, ...]:
        promoted = tuple(
            record for record in self.explore_records if record.id in self.bookmarks
        )
        return (*self.records, *promoted)

    def _filtered_records(self) -> tuple[TitleRecord, ...]:
        query = self.search_entry.get_text().strip().casefold()
        records = []
        for record in self._library_records():
            haystack = " ".join(
                (record.title, record.description, record.creator, *record.genres)
            ).casefold()
            if record.media_type != self.active_media:
                continue
            if self._effective_status(record) != self.active_status:
                continue
            if self.genre != "All genres" and self.genre not in record.genres:
                continue
            if query and query not in haystack:
                continue
            records.append(record)

        if self.sort_key == "title":
            key_function = lambda item: item.title.casefold()
            base_reverse = False
        elif self.sort_key == "rating":
            key_function = lambda item: item.rating
            base_reverse = True
        elif self.sort_key == "year":
            key_function = lambda item: item.year
            base_reverse = True
        else:
            key_function = lambda item: item.order
            base_reverse = True

        records.sort(
            key=key_function,
            reverse=base_reverse ^ self.sort_reversed,
        )
        return tuple(records)

    def _refresh_results(self) -> None:
        self.visible_records = self._filtered_records()
        visible_ids = {record.id for record in self.visible_records}
        if self.selected_id not in visible_ids:
            self.selected_id = self.visible_records[0].id if self.visible_records else None
        self.library_selected_id = self.selected_id

        self._clear_container(self.list_box)
        self._clear_container(self.grid_box)

        list_rows: dict[str, Gtk.ListBoxRow] = {}
        grid_children: dict[str, Gtk.FlowBoxChild] = {}
        for record in self.visible_records:
            row = self._create_list_row(record)
            list_rows[record.id] = row
            self.list_box.append(row)

            child = self._create_grid_child(record)
            grid_children[record.id] = child
            self.grid_box.append(child)

        self._list_rows = list_rows
        self._grid_children = grid_children
        self._sync_results_child()

        self._updating = True
        if self.selected_id is not None:
            if self.selected_id in list_rows:
                self.list_box.select_row(list_rows[self.selected_id])
            if self.selected_id in grid_children:
                self.grid_box.select_child(grid_children[self.selected_id])
        self._updating = False

        total = self._status_total(self.active_media, self.active_status)
        sample_count = len(self.visible_records)
        has_filters = bool(self.search_entry.get_text().strip()) or self.genre != "All genres"
        if has_filters:
            description = f"{sample_count} matching {'title' if sample_count == 1 else 'titles'}"
        else:
            description = f"Showing {sample_count} recent {'entry' if sample_count == 1 else 'entries'}"

        self.eyebrow_label.set_label(f"My library / {self.active_media}")
        self.section_title.set_label(self.active_status)
        self.section_count.set_label(str(total))
        self.result_count.set_label(f"All ({total})")
        self.result_description.set_label(description)
        self.search_entry.set_placeholder_text(
            f"Search {self.active_media.lower()}…"
        )
        self._update_sort_icon()
        self._update_details()

    def _refresh_explore(self, *, reset_scroll: bool = True) -> None:
        scroll_value = self.explore_scroller.get_vadjustment().get_value()
        self.explore_visible_records = self._filtered_explore_records()
        visible_ids = {record.id for record in self.explore_visible_records}
        if self.explore_selected_id not in visible_ids:
            self.explore_selected_id = (
                self.explore_visible_records[0].id
                if self.explore_visible_records
                else None
            )
        self.selected_id = self.explore_selected_id

        self.explore_eyebrow_label.set_label(
            f"Discover / {self.active_media}"
        )
        self.explore_count_label.set_label(str(len(self.explore_visible_records)))
        self.explore_row.set_count(self._explore_total(self.active_media))
        self._populate_explore_feed()
        self._update_details()
        if reset_scroll:
            self._scroll_to_top(self.explore_scroller)
        else:
            self._scroll_to_value(self.explore_scroller, scroll_value)

    def _explore_layout_kind(self, record: TitleRecord) -> str:
        """Use the editorial mosaic only for the unfiltered Trending feed."""
        if (
            self.explore_sort_key != "trending"
            or self.explore_period != "This month"
            or self.explore_genre != "All genres"
        ):
            return "poster"
        kind = record.discover_layout
        if kind not in ("hero", "landscape", "poster"):
            return "poster"
        # Three equal columns cannot tile two-wide landscapes without holes.
        if self.explore_columns == 3 and kind == "landscape":
            return "poster"
        return kind

    def _populate_explore_feed(self) -> None:
        self._clear_container(self.explore_feed_box)
        self._clear_container(self.explore_grid)
        self._explore_card_buttons: dict[str, Gtk.Button] = {}

        if not self.explore_visible_records:
            self.explore_feed_box.append(self.explore_empty_page)
            return

        records = list(self.explore_visible_records)
        columns = self.explore_columns

        row = 0
        column = 0
        for record in records:
            kind = self._explore_layout_kind(record)
            if kind == "hero":
                if column:
                    row += 1
                    column = 0
                span = columns
            elif kind == "landscape":
                span = min(2, columns)
                if column + span > columns:
                    row += 1
                    column = 0
            else:
                span = 1
                if column >= columns:
                    row += 1
                    column = 0

            card = self._create_explore_card(record, kind)
            self.explore_grid.attach(card, column, row, span, 1)
            self._explore_card_buttons[record.id] = card

            if kind == "hero":
                row += 1
                column = 0
            else:
                column += span
                if column >= columns:
                    row += 1
                    column = 0

        self.explore_feed_box.append(self.explore_grid)
        if any(record.tmdb_id is not None for record in self.explore_visible_records):
            attribution = Gtk.Label(label="Data & images provided by TMDB")
            attribution.set_halign(Gtk.Align.START)
            attribution.set_margin_top(2)
            attribution.add_css_class("caption")
            attribution.add_css_class("dim-label")
            self.explore_feed_box.append(attribution)
        self._sync_explore_selection_style()

    def _create_explore_card(
        self,
        record: TitleRecord,
        kind: str,
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_vexpand(False)
        button.set_tooltip_text(f"Open {record.title}")
        button.set_overflow(Gtk.Overflow.HIDDEN)
        button.add_css_class("flat")
        button.add_css_class("explore-card")
        button.add_css_class(f"explore-card-{kind}")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"{record.title}, {record.year}, rated {record.rating:.1f}"],
        )

        overlay = Gtk.Overlay()
        card_height = self._explore_card_height(kind)
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        overlay.set_size_request(-1, card_height)
        art_width = 600 if kind == "hero" else 320 if kind == "landscape" else 160
        art_height = card_height
        artwork = PosterWidget(
            record,
            art_width,
            art_height,
            variant_offset=1 if kind == "landscape" else 0,
            show_text=False,
        )
        artwork.set_hexpand(True)
        artwork.set_vexpand(True)
        artwork.set_size_request(-1, -1)
        overlay.set_child(artwork)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.set_halign(Gtk.Align.FILL)
        copy.set_valign(Gtk.Align.END)
        copy.set_hexpand(True)
        copy.add_css_class("explore-card-copy")

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("explore-card-title")
        if kind == "hero":
            title.add_css_class("title-3")
        else:
            title.add_css_class("heading")
        copy.append(title)

        if kind != "poster":
            subtitle = Gtk.Label(
                label=f"{record.year}  ·  {' · '.join(record.genres[:2])}",
                xalign=0,
            )
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle.add_css_class("caption")
            subtitle.add_css_class("explore-card-subtitle")
            copy.append(subtitle)
        overlay.add_overlay(copy)

        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.set_halign(Gtk.Align.END)
        rating.set_valign(Gtk.Align.START)
        rating.set_margin_top(8)
        rating.set_margin_end(8)
        rating.add_css_class("row-rating")
        overlay.add_overlay(rating)

        if record.id in self.bookmarks:
            saved = Gtk.Image.new_from_icon_name("bookmark-new-symbolic")
            saved.set_halign(Gtk.Align.START)
            saved.set_valign(Gtk.Align.START)
            saved.set_margin_top(8)
            saved.set_margin_start(8)
            saved.add_css_class("explore-saved-badge")
            overlay.add_overlay(saved)

        button.set_child(overlay)
        button.connect(
            "clicked",
            lambda _button, record_id=record.id: self._on_explore_card_clicked(
                record_id
            ),
        )
        return button

    def _sync_explore_selection_style(self) -> None:
        for record_id, button in self._explore_card_buttons.items():
            selected = record_id == self.explore_selected_id
            button.update_state(
                [Gtk.AccessibleState.SELECTED],
                [int(selected)],
            )
            if selected:
                button.add_css_class("selected")
            else:
                button.remove_css_class("selected")

    @staticmethod
    def _clear_container(container: Gtk.Widget) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child

    def _sync_results_child(self) -> None:
        if not self.visible_records:
            child: Gtk.Widget = self.empty_page
        elif self.view_mode == "grid":
            child = self.grid_box
        else:
            child = self.list_box

        if self.results_scroller.get_child() is not child:
            self.results_scroller.set_child(child)

    def _create_list_row(self, record: TitleRecord) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.record = record

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content.add_css_class("movie-row-content")
        content.append(self._create_poster_overlay(record, 76, 114))
        content.append(self._create_record_copy(record, compact=False))

        menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
        menu_button.set_tooltip_text(f"More options for {record.title}")
        menu_button.set_valign(Gtk.Align.START)
        menu_button.add_css_class("flat")
        menu_button.add_css_class("circular")
        menu_button.connect(
            "clicked",
            lambda _button, title=record.title: self._toast(f"More options for {title}"),
        )
        content.append(menu_button)
        row.set_child(content)
        return row

    def _create_grid_child(self, record: TitleRecord) -> Gtk.FlowBoxChild:
        child = Gtk.FlowBoxChild()
        child.record = record

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.set_size_request(124, 221)
        card.set_hexpand(False)
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.START)
        card.add_css_class("poster-grid-card")
        card.append(self._create_poster_overlay(record, 112, 168))

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(14)
        title.set_hexpand(False)
        title.set_size_request(112, 38)
        title.set_tooltip_text(record.title)
        title.add_css_class("poster-grid-title")
        card.append(title)
        child.set_child(card)
        return child

    def _create_poster_overlay(
        self,
        record: TitleRecord,
        width: int,
        height: int,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        overlay.set_size_request(width, height)
        overlay.set_hexpand(False)
        overlay.set_halign(Gtk.Align.CENTER)
        overlay.set_valign(Gtk.Align.START)
        overlay.set_child(PosterWidget(record, width, height))

        score = self.ratings.get(record.id)
        if score is not None:
            rating = Gtk.Label(label=str(score))
            rating.set_halign(Gtk.Align.START)
            rating.set_valign(Gtk.Align.START)
            rating.set_margin_top(4)
            rating.set_margin_start(4)
            rating.add_css_class("row-rating")
            rating.add_css_class("numeric")
            overlay.add_overlay(rating)

        if record.id in self.completed:
            watched = Gtk.Label(label="✓")
            watched.set_halign(Gtk.Align.END)
            watched.set_valign(Gtk.Align.START)
            watched.set_margin_top(4)
            watched.set_margin_end(4)
            watched.add_css_class("watched-badge")
            overlay.add_overlay(watched)

        return overlay

    def _create_record_copy(
        self,
        record: TitleRecord,
        *,
        compact: bool,
    ) -> Gtk.Box:
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        copy.set_hexpand(True)
        copy.set_valign(Gtk.Align.CENTER)

        top = Gtk.CenterBox()
        date = Gtk.Label(label=record.date, xalign=0)
        date.add_css_class("dim-label")
        date.add_css_class("caption")
        rating = Gtk.Label(label=f"★ {record.rating:.1f}")
        rating.add_css_class("numeric")
        rating.add_css_class("caption")
        top.set_start_widget(date)
        top.set_end_widget(rating)

        title = Gtk.Label(label=record.title, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.add_css_class("title-3")

        description = Gtk.Label(label=record.description, xalign=0)
        description.set_wrap(True)
        description.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        description.set_lines(2)
        description.set_ellipsize(Pango.EllipsizeMode.END)
        description.add_css_class("dim-label")
        description.add_css_class("caption" if compact else "body")

        metadata_values = (str(record.year), record.runtime, *record.genres[:2])
        metadata = Gtk.Label(label="  ·  ".join(metadata_values), xalign=0)
        metadata.set_ellipsize(Pango.EllipsizeMode.END)
        metadata.add_css_class("dim-label")
        metadata.add_css_class("caption")

        copy.append(top)
        copy.append(title)
        copy.append(description)
        copy.append(metadata)
        return copy

    def _apply_detail_tint(self, record: TitleRecord) -> None:
        red, green, blue = _hex_to_rgb(record.poster_palette[1])
        accent = tuple(round(channel * 255) for channel in (red, green, blue))
        is_dark = self.style_manager.get_dark() if hasattr(self, "style_manager") else True
        top_alpha = 0.18 if is_dark else 0.09

        css = f"""
        .detail-tint-surface,
        .detail-tint-surface > viewport {{
          background-color: @secondary_sidebar_bg_color;
          background-image: linear-gradient(
            to bottom,
            rgba({accent[0]}, {accent[1]}, {accent[2]}, {top_alpha}),
            rgba({accent[0]}, {accent[1]}, {accent[2]}, 0.06) 360px,
            rgba({accent[0]}, {accent[1]}, {accent[2]}, 0.00) 620px
          );
        }}
        .detail-tint-content,
        .detail-subpage-content,
        .detail-page {{
          background-color: transparent;
        }}
        """
        self.detail_tint_provider.load_from_string(css)

    def _build_detail_hero(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_poster_host)
        overlay = Gtk.Overlay()
        overlay.set_child(PosterWidget(record, 356, 192, show_text=False))

        trailer_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        trailer_content.append(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
        trailer_content.append(Gtk.Label(label="Watch trailer"))
        trailer = Gtk.Button()
        trailer.set_child(trailer_content)
        trailer.set_halign(Gtk.Align.CENTER)
        trailer.set_valign(Gtk.Align.CENTER)
        trailer.add_css_class("pill")
        trailer.add_css_class("detail-hero-button")
        trailer.set_tooltip_text(f"Play the trailer for {record.title}")
        trailer.connect(
            "clicked",
            lambda _button, title=record.title: self._toast(f"Playing trailer for {title}"),
        )
        overlay.add_overlay(trailer)

        close_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_button.set_halign(Gtk.Align.END)
        close_button.set_valign(Gtk.Align.START)
        close_button.set_margin_top(8)
        close_button.set_margin_end(8)
        close_button.set_tooltip_text("Close details")
        close_button.add_css_class("circular")
        close_button.add_css_class("osd")
        close_button.connect("clicked", self._on_details_close_clicked)
        overlay.add_overlay(close_button)
        self.detail_poster_host.append(overlay)

    def _rating_sources(self, record: TitleRecord) -> tuple[tuple[str, str], ...]:
        if record.external_ratings:
            return record.external_ratings[:4]
        return (
            ("CineShelf", f"{record.rating:.1f}"),
            ("IMDb", f"{min(10.0, record.rating + 0.1):.1f}"),
            ("Meta", str(min(99, round(record.rating * 10)))),
            ("Match", f"{min(99, round(record.rating * 10 + 8))}%"),
        )

    def _populate_detail_ratings(self, record: TitleRecord) -> None:
        self._clear_container(self.detail_ratings_host)
        for source, value in self._rating_sources(record):
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            chip.add_css_class("detail-metric")
            score = Gtk.Label(label=value)
            score.add_css_class("numeric")
            score.add_css_class("heading")
            source_label = Gtk.Label(label=source)
            source_label.set_ellipsize(Pango.EllipsizeMode.END)
            source_label.add_css_class("caption")
            source_label.add_css_class("dim-label")
            chip.append(score)
            chip.append(source_label)
            self.detail_ratings_host.append(chip)

    def _populate_quick_actions(self, record: TitleRecord) -> None:
        self._clear_container(self.quick_actions_host)
        fourth_action = "Check in" if record.media_type == "Movies" else "Drop"
        actions = (
            ("starred-symbolic", "Rate"),
            ("mail-unread-symbolic", "Comments"),
            ("document-edit-symbolic", "Note"),
            ("media-playback-stop-symbolic", fourth_action),
        )
        for icon_name, label in actions:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.append(Gtk.Image.new_from_icon_name(icon_name))
            caption = Gtk.Label(label=label)
            caption.set_wrap(True)
            caption.add_css_class("caption")
            content.append(caption)

            button = Gtk.Button()
            button.set_child(content)
            button.add_css_class("flat")
            button.add_css_class("detail-action-button")
            button.set_tooltip_text(f"{label}: {record.title}")
            button.connect(
                "clicked",
                lambda _button, action=label, title=record.title: self._toast(
                    f"{action} for {title}"
                ),
            )
            self.quick_actions_host.append(button)

    @staticmethod
    def _cast_members(record: TitleRecord) -> tuple[CastMember, ...]:
        if record.cast:
            return record.cast[:6]
        return (
            CastMember(record.creator, "Director / Creator"),
            CastMember("Lead Ensemble", "Cast"),
            CastMember("Supporting Ensemble", "Cast"),
            CastMember("Guest Artist", "Cast"),
        )

    def _populate_cast(self, record: TitleRecord) -> None:
        self._populate_cast_container(self.cast_box, record)

    def _populate_cast_container(
        self,
        container: Gtk.Box,
        record: TitleRecord,
    ) -> None:
        self._clear_container(container)
        for member in self._cast_members(record):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.set_valign(Gtk.Align.START)
            card.add_css_class("cast-card")

            avatar = Adw.Avatar(size=58, text=member.name, show_initials=True)
            avatar.set_halign(Gtk.Align.CENTER)
            avatar.set_tooltip_text(f"{member.name}, {member.role}")

            name = Gtk.Label(label=member.name)
            name.set_wrap(True)
            name.set_lines(2)
            name.set_max_width_chars(12)
            name.set_justify(Gtk.Justification.CENTER)
            name.add_css_class("caption")
            name.add_css_class("cast-name")

            role = Gtk.Label(label=member.role)
            role.set_ellipsize(Pango.EllipsizeMode.END)
            role.set_max_width_chars(12)
            role.add_css_class("caption")
            role.add_css_class("dim-label")

            card.append(avatar)
            card.append(name)
            card.append(role)
            container.append(card)

    def _series_seasons(self, record: TitleRecord) -> tuple[SeasonInfo, ...]:
        if record.seasons:
            return record.seasons

        numbers = [int(value) for value in record.runtime.split() if value.isdigit()]
        is_completed = record.id in self.completed
        if "episodes" in record.runtime:
            episode_count = numbers[0] if numbers else 12
            return (
                SeasonInfo(
                    "s1",
                    1,
                    "Season 1",
                    episode_count if is_completed else 0,
                    episode_count,
                ),
            )

        season_count = max(1, numbers[0] if numbers else 1)
        return tuple(
            SeasonInfo(
                f"s{index}",
                index,
                f"Season {index}",
                10 if is_completed else 0,
                10,
            )
            for index in range(1, season_count + 1)
        )

    def _episodes_for_season(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> tuple[EpisodeInfo, ...]:
        seasons = self._series_seasons(record)
        if not seasons:
            return ()
        season_index = max(0, min(season_index, len(seasons) - 1))
        season = seasons[season_index]
        provided = {episode.number: episode for episode in season.episode_items}
        episodes: list[EpisodeInfo] = []
        for number in range(1, season.episodes + 1):
            episode = provided.get(number)
            if episode is None:
                episode = EpisodeInfo(
                    id=f"e{number}",
                    number=number,
                    title=f"Episode {number}",
                    date=str(record.year + season_index),
                    description=record.description,
                    watched=None,
                    image_variant=number + season_index * 2,
                )
            episodes.append(episode)
        return tuple(episodes)

    @staticmethod
    def _season_short_label(season: SeasonInfo) -> str:
        return f"S{season.number}"

    @staticmethod
    def _watched_timestamp() -> str:
        now = datetime.now().astimezone()
        hour = now.strftime("%I").lstrip("0") or "12"
        return (
            f"{now.strftime('%b')} {now.day}, {now.year} at "
            f"{hour}:{now.strftime('%M %p')}"
        )

    def _episode_key(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> str:
        season = self._series_seasons(record)[season_index]
        return f"{record.id}/{season.id}/{episode.id}"

    def _episode_code(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> str:
        season = self._series_seasons(record)[season_index]
        return f"{self._season_short_label(season)}E{episode.number}"

    def _episode_is_watched(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> bool:
        key = self._episode_key(record, season_index, episode)
        if key in self.episode_status_overrides:
            return self.episode_status_overrides[key]
        seasons = self._series_seasons(record)
        season = seasons[season_index]
        default = episode.watched
        return episode.number <= season.watched if default is None else default

    def _season_watched_count(
        self,
        record: TitleRecord,
        season_index: int,
    ) -> int:
        return sum(
            self._episode_is_watched(record, season_index, episode)
            for episode in self._episodes_for_season(record, season_index)
        )

    def _episode_artwork(
        self,
        record: TitleRecord,
        episode: EpisodeInfo,
        width: int,
        height: int,
    ) -> Gtk.Overlay:
        overlay = Gtk.Overlay()
        overlay.set_child(
            PosterWidget(
                record,
                width,
                height,
                variant_offset=episode.image_variant,
                show_text=False,
            )
        )
        number = Gtk.Label(label=str(episode.number))
        number.set_halign(Gtk.Align.END)
        number.set_valign(Gtk.Align.END)
        number.set_margin_end(5)
        number.set_margin_bottom(5)
        number.add_css_class("episode-number-badge")
        number.add_css_class("numeric")
        overlay.add_overlay(number)
        overlay.set_tooltip_text(f"Episode {episode.number}: {episode.title}")
        return overlay

    @staticmethod
    def _episode_card(label: str, value: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.add_css_class("episode-card")
        overline = Gtk.Label(label=label, xalign=0)
        overline.add_css_class("caption")
        overline.add_css_class("dim-label")
        title = Gtk.Label(label=value, xalign=0)
        title.add_css_class("heading")
        detail = Gtk.Label(label=subtitle, xalign=0)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        detail.add_css_class("caption")
        detail.add_css_class("dim-label")
        card.append(overline)
        card.append(title)
        card.append(detail)
        return card

    def _populate_series(self, record: TitleRecord) -> None:
        episodic = record.media_type != "Movies"
        self.series_section.set_visible(episodic)
        if not episodic:
            return

        seasons = self._series_seasons(record)
        self._clear_container(self.episode_cards_box)
        self._clear_container(self.seasons_list)

        next_item: tuple[int, EpisodeInfo] | None = None
        last_item: tuple[int, EpisodeInfo] | None = None
        for season_index, _season in enumerate(seasons):
            for episode in self._episodes_for_season(record, season_index):
                if self._episode_is_watched(record, season_index, episode):
                    last_item = (season_index, episode)
                elif next_item is None:
                    next_item = (season_index, episode)

        if next_item is None:
            next_episode = "Up to date"
            next_subtitle = record.availability
        else:
            next_season_index, next_info = next_item
            next_episode = self._episode_code(record, next_season_index, next_info)
            next_subtitle = next_info.title

        if last_item is None:
            last_episode = "Not started"
            last_subtitle = record.network
        else:
            last_season_index, last_info = last_item
            last_episode = self._episode_code(record, last_season_index, last_info)
            last_subtitle = last_info.title
        self.episode_cards_box.append(
            self._episode_card("Next episode", next_episode, next_subtitle)
        )
        self.episode_cards_box.append(
            self._episode_card("Last episode", last_episode, last_subtitle)
        )

        for season_index, season in enumerate(seasons):
            watched = self._season_watched_count(record, season_index)
            row = Adw.ActionRow(
                title=season.title,
                subtitle=f"{watched}/{season.episodes} episodes",
            )
            row.season_index = season_index
            row.set_activatable(True)
            row.set_tooltip_text(f"Open {season.title} of {record.title}")
            progress = Gtk.Label(label=f"{watched}/{season.episodes}")
            progress.add_css_class("caption")
            progress.add_css_class("dim-label")
            row.add_suffix(progress)
            icon = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic"
                if watched >= season.episodes
                else "media-playback-start-symbolic"
            )
            if watched >= season.episodes:
                icon.add_css_class("success")
            row.add_suffix(icon)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.seasons_list.append(row)

    def _populate_season_page(
        self,
        record: TitleRecord,
        season_index: int,
        *,
        reset_scroll: bool = True,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons:
            return
        season_index = max(0, min(season_index, len(seasons) - 1))
        season = seasons[season_index]
        episodes = self._episodes_for_season(record, season_index)
        watched = self._season_watched_count(record, season_index)

        self.detail_record_id = record.id
        self.current_season_index = season_index
        self.season_header_title.set_title(season.title)
        self.season_header_title.set_subtitle(record.title)
        self.season_summary_label.set_label(
            f"{watched} of {len(episodes)} episodes watched · {record.network}"
        )
        self.season_episode_count.set_label(f"{len(episodes)} episodes")
        self.season_watched_button.action_label.set_label(
            "Mark unwatched" if watched == len(episodes) else "Mark watched"
        )

        self._updating_season_switcher = True
        rebuild_switcher = (
            self.season_switcher_record_id != record.id
            or self.season_switcher.get_n_toggles() != len(seasons)
        )
        if rebuild_switcher:
            self.season_switcher.remove_all()
            for index, item in enumerate(seasons):
                item_watched = self._season_watched_count(record, index)
                self.season_switcher.add(
                    Adw.Toggle(
                        name=f"season-{index}",
                        label=(
                            f"{self._season_short_label(item)}  "
                            f"{item_watched}/{item.episodes}"
                        ),
                    )
                )
            self.season_switcher_record_id = record.id
        else:
            for index, item in enumerate(seasons):
                item_watched = self._season_watched_count(record, index)
                self.season_switcher.get_toggle(index).set_label(
                    f"{self._season_short_label(item)}  "
                    f"{item_watched}/{item.episodes}"
                )
        self.season_switcher.set_active_name(f"season-{season_index}")
        self._updating_season_switcher = False

        self._clear_container(self.season_episodes_list)
        for episode_index, episode in enumerate(episodes):
            row = Adw.ActionRow(
                title=episode.title,
                subtitle=f"{episode.date}\n{episode.description}",
            )
            row.set_title_lines(1)
            row.set_subtitle_lines(2)
            row.set_activatable(True)
            row.season_index = season_index
            row.episode_index = episode_index
            row.add_prefix(self._episode_artwork(record, episode, 112, 64))

            watched_icon = Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic"
                if self._episode_is_watched(record, season_index, episode)
                else "media-playback-start-symbolic"
            )
            if self._episode_is_watched(record, season_index, episode):
                watched_icon.add_css_class("success")
            row.add_suffix(watched_icon)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.set_tooltip_text(f"Open episode {episode.number}: {episode.title}")
            self.season_episodes_list.append(row)

        self._apply_detail_tint(record)
        if reset_scroll:
            self._scroll_to_top(self.season_details_scroller)

    def _populate_episode_page(
        self,
        record: TitleRecord,
        season_index: int,
        episode_index: int,
    ) -> None:
        seasons = self._series_seasons(record)
        if not seasons:
            return
        season_index = max(0, min(season_index, len(seasons) - 1))
        episodes = self._episodes_for_season(record, season_index)
        if not episodes:
            return
        episode_index = max(0, min(episode_index, len(episodes) - 1))
        season = seasons[season_index]
        episode = episodes[episode_index]

        self.detail_record_id = record.id
        self.current_season_index = season_index
        self.current_episode_index = episode_index
        self.episode_header_title.set_title(f"Episode {episode.number}")
        self.episode_header_title.set_subtitle(season.title)
        self.episode_position_label.set_label(
            f"Episode {episode.number} of {len(episodes)}"
        )
        if len(episodes) <= 7:
            dots = "  ".join(
                "●" if index == episode_index else "•"
                for index in range(len(episodes))
            )
        else:
            dots = f"{episode.number}/{len(episodes)}  •••"
        self.episode_position_dots.set_label(dots)

        self._clear_container(self.episode_hero_host)
        self.episode_hero_host.append(
            self._episode_artwork(record, episode, 356, 200)
        )
        self.episode_title_label.set_label(episode.title)
        self.episode_date_label.set_label(episode.date)
        self.episode_overview_label.set_label(episode.description)
        self._populate_cast_container(self.episode_cast_box, record)
        self._update_episode_watch_controls(record, season_index, episode)
        self._apply_detail_tint(record)
        self._scroll_to_top(self.episode_details_scroller)

    def _update_episode_watch_controls(
        self,
        record: TitleRecord,
        season_index: int,
        episode: EpisodeInfo,
    ) -> None:
        watched = self._episode_is_watched(record, season_index, episode)
        self.episode_watched_button.action_label.set_label(
            "Watched" if watched else "Mark watched"
        )
        watched_at = self.episode_watched_at.get(
            self._episode_key(record, season_index, episode)
        )
        if watched and watched_at:
            status = f"Watched · {watched_at}"
        elif watched:
            status = "Watched"
        else:
            status = "Not watched yet"
        self.episode_watched_at_label.set_label(status)

    @staticmethod
    def _scroll_to_value(scroller: Gtk.ScrolledWindow, value: float) -> None:
        def reset_adjustment() -> bool:
            scroller.get_vadjustment().set_value(value)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(reset_adjustment)

    @staticmethod
    def _scroll_to_top(scroller: Gtk.ScrolledWindow) -> None:
        CineShelfWindow._scroll_to_value(scroller, 0)

    def _video_card(
        self,
        record: TitleRecord,
        title: str,
        variant_offset: int,
    ) -> Gtk.Button:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        overlay = Gtk.Overlay()
        overlay.set_child(
            PosterWidget(record, 156, 88, variant_offset=variant_offset)
        )
        play = Gtk.Label(label="▶")
        play.set_halign(Gtk.Align.CENTER)
        play.set_valign(Gtk.Align.CENTER)
        play.add_css_class("rating-badge")
        overlay.add_overlay(play)
        caption = Gtk.Label(label=title, xalign=0)
        caption.set_ellipsize(Pango.EllipsizeMode.END)
        caption.add_css_class("caption")
        content.append(overlay)
        content.append(caption)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("flat")
        button.add_css_class("detail-media-card")
        button.set_tooltip_text(f"Play {title} for {record.title}")
        button.connect(
            "clicked",
            lambda _button, video_title=title: self._toast(f"Playing {video_title}"),
        )
        return button

    def _populate_videos(self, record: TitleRecord) -> None:
        self._clear_container(self.videos_box)
        self.videos_box.append(self._video_card(record, "New trailer", 1))
        self.videos_box.append(self._video_card(record, "Official trailer", 2))

    def _populate_images(self, record: TitleRecord) -> None:
        self._clear_container(self.images_box)
        is_poster = self.image_mode == "posters"
        width, height, count = (96, 144, 3) if is_poster else (180, 104, 2)
        for index in range(count):
            button = Gtk.Button()
            button.set_child(
                PosterWidget(record, width, height, variant_offset=index + 1)
            )
            button.add_css_class("flat")
            button.add_css_class("detail-media-card")
            button.set_tooltip_text(
                f"Open {self.image_mode[:-1]} {index + 1} for {record.title}"
            )
            button.connect(
                "clicked",
                lambda _button, image_number=index + 1: self._toast(
                    f"Opened image {image_number}"
                ),
            )
            self.images_box.append(button)

    def _related_records(self, record: TitleRecord) -> tuple[TitleRecord, ...]:
        related: list[TitleRecord] = []
        for record_id in record.recommendations:
            candidate = self.records_by_id.get(record_id)
            if candidate is not None and candidate.id != record.id and candidate not in related:
                related.append(candidate)

        if len(related) < 3:
            for candidate in self.records:
                if candidate.id == record.id or candidate in related:
                    continue
                shares_genre = bool(set(candidate.genres).intersection(record.genres))
                if candidate.media_type == record.media_type or shares_genre:
                    related.append(candidate)
                if len(related) == 3:
                    break
        return tuple(related[:3])

    def _populate_recommendations(self, record: TitleRecord) -> None:
        self._clear_container(self.recommendations_box)
        for related in self._related_records(record):
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.append(PosterWidget(related, 88, 132))
            title = Gtk.Label(label=related.title, xalign=0)
            title.set_wrap(True)
            title.set_lines(2)
            title.set_max_width_chars(13)
            title.add_css_class("caption")
            year = Gtk.Label(label=str(related.year), xalign=0)
            year.add_css_class("caption")
            year.add_css_class("dim-label")
            content.append(title)
            content.append(year)

            button = Gtk.Button()
            button.set_child(content)
            button.add_css_class("flat")
            button.add_css_class("recommendation-card")
            button.set_tooltip_text(f"Open {related.title}")
            button.connect(
                "clicked",
                lambda _button, title_name=related.title: self._toast(
                    f"Open {title_name}"
                ),
            )
            self.recommendations_box.append(button)

    def _populate_detail_sections(self, record: TitleRecord) -> None:
        self._populate_detail_ratings(record)
        self._populate_quick_actions(record)
        self._populate_cast(record)
        self._populate_series(record)
        self._populate_videos(record)
        self._populate_images(record)
        self._populate_recommendations(record)

    def _reset_detail_navigation(self) -> None:
        if self.detail_navigation.get_visible_page_tag() != "title":
            self.detail_navigation.pop_to_tag("title")

    def _update_details(self) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is None:
            self._reset_detail_navigation()
            self.detail_record_id = None
            self.detail_box.set_visible(False)
            return

        record_changed = self.detail_record_id != record.id
        self._reset_detail_navigation()
        self.detail_record_id = record.id
        self.detail_box.set_visible(True)
        self.detail_poster_host.set_visible(True)
        self._apply_detail_tint(record)
        self._build_detail_hero(record)

        is_completed = record.id in self.completed
        is_explore_view = (
            self.active_destination == "explore" and record.id in self.explore_ids
        )
        self.detail_status_label.set_label(
            (
                "In watchlist"
                if record.id in self.bookmarks
                else record.availability
            )
            if is_explore_view
            else self._effective_status(record)
        )
        self.detail_overline.set_label(" · ".join(record.genres))
        self.detail_title.set_label(record.title)
        self.community_rating.set_label(f"★ {record.rating:.1f}")
        if is_explore_view:
            self.watched_button.set_label(
                "✓  In watchlist"
                if record.id in self.bookmarks
                else "＋  Add to watchlist"
            )
        else:
            self.watched_button.set_label(
                "✓  Watched" if is_completed else "＋  Mark watched"
            )
        self.runtime_label.set_label(
            f"{record.certification} · {record.language} · {record.runtime}"
        )
        self.genres_label.set_label(f"{record.year} · {record.availability}")
        self.overview_label.set_label(record.description)
        self.creator_row.set_title(
            "Director" if record.media_type == "Movies" else "Creator"
        )
        self.creator_row.set_subtitle(record.creator)
        self.release_row.set_subtitle(f"{record.year} · {record.availability}")
        self.country_row.set_subtitle(record.country)
        self.activity_row.set_subtitle(record.date)
        self.activity_status.set_label("Completed" if is_completed else "Not watched yet")
        self.activity_percentage.set_label("100%" if is_completed else "0%")
        self.activity_progress.set_fraction(1.0 if is_completed else 0.0)

        self._updating_details = True
        self.favorite_button.set_active(record.id in self.favorites)
        self.bookmark_button.set_visible(not is_explore_view)
        self.bookmark_button.set_active(record.id in self.bookmarks)
        score = self.ratings.get(record.id)
        for value, button in self.rating_buttons.items():
            button.set_active(value == score)
        self.rating_value.set_label("Not rated" if score is None else f"{score}/10")
        self._updating_details = False
        self._populate_detail_sections(record)
        if record_changed:
            self._scroll_to_top(self.details_scroller)

    def _update_sidebar_counts(self) -> None:
        for status, row in self.status_rows.items():
            row.set_count(self._status_total(self.active_media, status))
        self.library_row.set_count(self._library_total(self.active_media))
        self.explore_row.set_count(self._explore_total(self.active_media))

    def _update_sort_icon(self) -> None:
        base_reverse = self.sort_key != "title"
        descending = base_reverse ^ self.sort_reversed
        icon_name = (
            "view-sort-descending-symbolic"
            if descending
            else "view-sort-ascending-symbolic"
        )
        self.sort_direction_button.set_icon_name(icon_name)
        self.sort_direction_button.set_tooltip_text(
            "Descending order" if descending else "Ascending order"
        )

    def _on_media_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        if self._updating:
            return
        active = group.get_active_name()
        if not active:
            return
        media_type = active.title()
        if media_type not in MEDIA_TYPES:
            return
        self._set_details_open(False)
        self.active_media = media_type
        self._update_sidebar_counts()
        if self.active_destination == "explore":
            self._update_genre_model()
            self._update_explore_genre_model(preserve=False)
            self._refresh_explore()
        else:
            self._updating = True
            self.search_entry.set_text("")
            self._updating = False
            self._update_genre_model()
            self._refresh_results()

    def _on_destination_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self._set_details_open(False)
        if row.key == "library":
            if self.active_destination == "library":
                return
            self.explore_selected_id = self.selected_id
            self.active_destination = "library"
            self.browser_stack.set_visible_child_name("library")
            self.selected_id = self.library_selected_id
            self._updating = True
            self.status_list.select_row(self.status_rows[self.active_status])
            self._updating = False
            self._refresh_results()
            return
        if row.key != "explore":
            return
        if self.active_destination == "library":
            self.library_selected_id = self.selected_id
        self.active_destination = "explore"
        self._updating = True
        self.status_list.unselect_all()
        self._updating = False
        self.browser_stack.set_visible_child_name("explore")
        self._update_explore_genre_model()
        self._refresh_explore()
        self._queue_explore_resize()

    def _on_status_selected(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self._set_details_open(False)
        returning_to_library = self.active_destination == "explore"
        previous_status = self.active_status
        if self.active_destination == "explore":
            self.explore_selected_id = self.selected_id
            self.active_destination = "library"
            self._updating = True
            self.destination_list.select_row(self.library_row)
            self._updating = False
            self.browser_stack.set_visible_child_name("library")
            self.selected_id = self.library_selected_id
        self.active_status = row.key
        if not returning_to_library or row.key != previous_status:
            self._updating = True
            self.search_entry.set_text("")
            self.genre_dropdown.set_selected(0)
            self.genre = "All genres"
            self._updating = False
        self._refresh_results()

    def _on_collection_activated(
        self,
        _list_box: Gtk.ListBox,
        row: SidebarRow,
    ) -> None:
        self._toast(f"{row.key} selected")

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if not self._updating:
            self._refresh_results()

    def _on_search_requested(self, *_args: Any) -> None:
        if self.active_destination == "explore":
            self.status_list.select_row(self.status_rows[self.active_status])
        self.search_entry.grab_focus()

    def _on_sort_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(SORT_OPTIONS):
            return
        self.sort_key = SORT_OPTIONS[selected][0]
        self.sort_reversed = False
        self._refresh_results()

    def _on_genre_changed(self, dropdown: Gtk.DropDown, _parameter: Any) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.genre_options):
            return
        self.genre = self.genre_options[selected]
        self._refresh_results()

    def _on_reverse_sort(self, _button: Gtk.Button) -> None:
        self.sort_reversed = not self.sort_reversed
        self._refresh_results()

    def _on_explore_sort_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(EXPLORE_SORT_OPTIONS):
            return
        self.explore_sort_key = EXPLORE_SORT_OPTIONS[selected][0]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_explore_period_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(EXPLORE_PERIODS):
            return
        self.explore_period = EXPLORE_PERIODS[selected]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_explore_genre_changed(
        self,
        dropdown: Gtk.DropDown,
        _parameter: Any,
    ) -> None:
        if self._updating:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.explore_genre_options):
            return
        self.explore_genre = self.explore_genre_options[selected]
        if self.active_destination == "explore":
            self._refresh_explore()

    def _on_clear_explore_filters(self, _button: Gtk.Button) -> None:
        self._updating = True
        self.explore_sort_dropdown.set_selected(0)
        self.explore_period_dropdown.set_selected(0)
        self.explore_genre_dropdown.set_selected(0)
        self.explore_sort_key = "trending"
        self.explore_period = "This month"
        self.explore_genre = "All genres"
        self._updating = False
        self._refresh_explore()

    def _on_explore_card_clicked(self, record_id: str) -> None:
        if record_id not in self.explore_ids:
            return
        self.explore_selected_id = record_id
        self.selected_id = record_id
        self._sync_explore_selection_style()
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[record_id])

    def _on_view_changed(self, group: Adw.ToggleGroup, _parameter: Any) -> None:
        if self._updating:
            return
        active = group.get_active_name()
        if active not in ("list", "grid"):
            return
        self.view_mode = active
        self._sync_results_child()

    def _on_image_mode_changed(
        self,
        group: Adw.ToggleGroup,
        _parameter: Any,
    ) -> None:
        active = group.get_active_name()
        if active not in ("backdrops", "posters"):
            return
        self.image_mode = active
        record = self.records_by_id.get(self.selected_id or "")
        if record is not None:
            self._populate_images(record)

    def _on_season_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        season_index = getattr(row, "season_index", None)
        if record is None or season_index is None or record.media_type == "Movies":
            return
        self._populate_season_page(record, int(season_index))
        self.detail_navigation.push_by_tag("season")

    def _on_season_switch_changed(
        self,
        group: Adw.ToggleGroup,
        _parameter: Any,
    ) -> None:
        if self._updating_season_switcher:
            return
        active = group.get_active_name()
        if not active or not active.startswith("season-"):
            return
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        try:
            season_index = int(active.removeprefix("season-"))
        except ValueError:
            return
        self._populate_season_page(record, season_index)

    def _on_episode_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        season_index = getattr(row, "season_index", None)
        episode_index = getattr(row, "episode_index", None)
        if record is None or season_index is None or episode_index is None:
            return
        self._populate_episode_page(
            record,
            int(season_index),
            int(episode_index),
        )
        self.detail_navigation.push_by_tag("episode")

    def _on_season_watched_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        episodes = self._episodes_for_season(record, self.current_season_index)
        if not episodes:
            return
        watched = self._season_watched_count(record, self.current_season_index)
        new_status = watched < len(episodes)
        timestamp = self._watched_timestamp() if new_status else None
        for episode in episodes:
            key = self._episode_key(record, self.current_season_index, episode)
            self.episode_status_overrides[key] = new_status
            if timestamp is None:
                self.episode_watched_at.pop(key, None)
            else:
                self.episode_watched_at[key] = timestamp
        self._save_user_state()
        self._populate_series(record)
        self._populate_season_page(record, self.current_season_index)
        self._toast(
            "Season marked as watched"
            if new_status
            else "Season marked as unwatched"
        )

    def _on_episode_watched_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.detail_record_id or "")
        if record is None:
            return
        episodes = self._episodes_for_season(record, self.current_season_index)
        if not episodes or self.current_episode_index >= len(episodes):
            return
        episode = episodes[self.current_episode_index]
        new_status = not self._episode_is_watched(
            record,
            self.current_season_index,
            episode,
        )
        key = self._episode_key(record, self.current_season_index, episode)
        self.episode_status_overrides[key] = new_status
        if new_status:
            self.episode_watched_at[key] = self._watched_timestamp()
        else:
            self.episode_watched_at.pop(key, None)
        self._save_user_state()
        self._populate_series(record)
        season_scroll = self.season_details_scroller.get_vadjustment().get_value()
        self._populate_season_page(
            record,
            self.current_season_index,
            reset_scroll=False,
        )
        self._scroll_to_value(self.season_details_scroller, season_scroll)
        self._update_episode_watch_controls(
            record,
            self.current_season_index,
            episode,
        )
        self._toast(
            "Episode marked as watched"
            if new_status
            else "Episode marked as unwatched"
        )

    def _on_style_scheme_changed(
        self,
        _manager: Adw.StyleManager,
        _parameter: Any,
    ) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is not None:
            self._apply_detail_tint(record)

    def _on_list_selected(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if self._updating or row is None:
            return
        self.selected_id = row.record.id
        self.library_selected_id = self.selected_id
        self._updating = True
        grid_child = self._grid_children.get(self.selected_id)
        if grid_child is not None:
            self.grid_box.select_child(grid_child)
        self._updating = False
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_list_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow,
    ) -> None:
        self.selected_id = row.record.id
        self.library_selected_id = self.selected_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_grid_selected(self, flow_box: Gtk.FlowBox) -> None:
        if self._updating:
            return
        selected = flow_box.get_selected_children()
        if not selected:
            return
        child = selected[0]
        self.selected_id = child.record.id
        self.library_selected_id = self.selected_id
        self._updating = True
        list_row = self._list_rows.get(self.selected_id)
        if list_row is not None:
            self.list_box.select_row(list_row)
        self._updating = False
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _on_grid_activated(
        self,
        _flow_box: Gtk.FlowBox,
        child: Gtk.FlowBoxChild,
    ) -> None:
        self.selected_id = child.record.id
        self.library_selected_id = self.selected_id
        self._update_details()
        self._set_details_open(True)
        self._load_tmdb_details_async(self.records_by_id[self.selected_id])

    def _set_details_open(self, open_details: bool) -> None:
        if self.details_open == open_details:
            return
        self.details_open = open_details
        self.details_surface.set_visible(open_details)
        if not open_details:
            self._reset_detail_navigation()
        self._queue_explore_resize()

    def _on_details_close_clicked(self, _button: Gtk.Button) -> None:
        self._set_details_open(False)
        self.window.set_focus(None)

    def _on_clear_filters(self, _button: Gtk.Button) -> None:
        self._updating = True
        self.search_entry.set_text("")
        self.genre_dropdown.set_selected(0)
        self.genre = "All genres"
        self._updating = False
        self._refresh_results()

    def _on_search_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval != Gdk.KEY_Escape:
            return False
        self.search_entry.set_text("")
        self.window.set_focus(None)
        return True

    def _on_watched_clicked(self, _button: Gtk.Button) -> None:
        if self.selected_id is None:
            return
        record = self.records_by_id[self.selected_id]
        if self.active_destination == "explore" and record.id in self.explore_ids:
            if record.id in self.bookmarks:
                self.bookmarks.discard(record.id)
                self.status_overrides.pop(record.id, None)
                self.completed.discard(record.id)
                message = "Removed from watchlist"
            else:
                self.bookmarks.add(record.id)
                if record.status != "Watchlist":
                    self.status_overrides[record.id] = "Watchlist"
                message = "Added to watchlist"
            self._save_user_state()
            self._update_sidebar_counts()
            self._refresh_explore(reset_scroll=False)
            self._toast(message)
            return
        if self.selected_id in self.completed:
            self.completed.remove(self.selected_id)
            self.status_overrides[self.selected_id] = "Watchlist"
            message = "Marked as unwatched"
        else:
            self.completed.add(self.selected_id)
            self.status_overrides[self.selected_id] = "Watched"
            message = "Marked as watched"
        if self.status_overrides[self.selected_id] == record.status:
            self.status_overrides.pop(self.selected_id)
        self._save_user_state()
        self._update_sidebar_counts()
        if self.active_destination == "explore":
            self._refresh_explore(reset_scroll=False)
        else:
            self._refresh_results()
        self._toast(message)

    def _on_favorite_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        if button.get_active():
            self.favorites.add(self.selected_id)
            message = "Added to favorites"
        else:
            self.favorites.discard(self.selected_id)
            message = "Removed from favorites"
        self._save_user_state()
        self._toast(message)

    def _on_bookmark_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._updating_details or self.selected_id is None:
            return
        if button.get_active():
            self.bookmarks.add(self.selected_id)
            message = "Added to watchlist"
        else:
            self.bookmarks.discard(self.selected_id)
            message = "Removed from watchlist"
            if self.selected_id in self.explore_ids:
                self.status_overrides.pop(self.selected_id, None)
                self.completed.discard(self.selected_id)
        self._save_user_state()
        if self.active_destination == "explore":
            self._refresh_explore(reset_scroll=False)
        elif self.selected_id in self.explore_ids:
            self._update_sidebar_counts()
            self._refresh_results()
        self._toast(message)

    def _on_more_clicked(self, _button: Gtk.Button) -> None:
        record = self.records_by_id.get(self.selected_id or "")
        if record is not None:
            self._toast(f"More options for {record.title}")

    def _on_rating_button_toggled(
        self,
        button: Gtk.ToggleButton,
        score: int,
    ) -> None:
        if self._updating_details or self.selected_id is None or not button.get_active():
            return
        self.ratings[self.selected_id] = score
        self._save_user_state()
        if self.active_destination == "explore":
            self._refresh_explore(reset_scroll=False)
        else:
            self._refresh_results()
        self._toast(f"Your rating is now {score}/10")

    def _toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)


class CineShelfApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.controller: CineShelfWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_args: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about_dialog)
        self.add_action(about_action)

    def do_activate(self) -> None:
        if self.props.active_window is None:
            try:
                self.controller = CineShelfWindow(self)
            except Exception as error:
                print(f"CineShelf failed to start: {error}", file=sys.stderr)
                window = Adw.ApplicationWindow(application=self, title=APP_NAME)
                window.set_default_size(720, 480)
                window.set_content(
                    Adw.StatusPage(
                        icon_name="dialog-error-symbolic",
                        title="Unable to start CineShelf",
                        description=str(error),
                    )
                )
        window = self.props.active_window
        if window is not None:
            window.present()

    def _show_about_dialog(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        window = self.props.active_window
        if window is None:
            return
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="CineShelf",
            version=APP_VERSION,
            comments="A lightweight native GTK4 movie library built with Gtk.Builder XML.",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(window)


def main() -> int:
    application = CineShelfApplication()
    return application.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
