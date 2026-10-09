"""Models shared by Gisheh components."""

from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from gettext import gettext as _, ngettext
from pathlib import Path
from typing import Any
from .services import simkl_client, tmdb_client
from .constants import (
    COLLECTION_NAMES,
    MEDIA_TYPES,
)
from .localization import (
    TMDB_GENRES,
    _normalize_stored_country,
    _normalize_stored_fallback,
    _normalize_stored_genres,
    localize_countries,
    localize_country_name,
    localize_genre_names,
    localize_tmdb_status,
)


def should_show_completion_progress(media_type: str) -> bool:
    """Return whether episodic completion progress belongs in title details."""
    return media_type != "Movies"


def is_episode_group_complete(watched: int, total: int) -> bool:
    """Treat a season as complete only when it has episodes and all are watched."""
    return total > 0 and watched >= total


def certification_from_tmdb(payload: dict[str, Any], media_type: str) -> str:
    """Return the best available regional certification from TMDB details."""
    namespace = "movie" if media_type == "movie" else "tv"
    resource = "release_dates" if namespace == "movie" else "content_ratings"
    result_items = payload.get(resource, {}).get("results", ())
    results = [item for item in result_items if isinstance(item, dict)]

    origin_codes = [
        str(code).upper() for code in payload.get("origin_country", ()) if code
    ]
    origin_codes.extend(
        str(item.get("iso_3166_1") or "").upper()
        for item in payload.get("production_countries", ())
        if isinstance(item, dict) and item.get("iso_3166_1")
    )
    preferred_regions = tuple(dict.fromkeys(("US", *origin_codes, "GB", "CA", "AU")))

    def value_for(item: dict[str, Any]) -> str:
        if namespace == "tv":
            return str(item.get("rating") or "").strip()
        release_items = [
            release
            for release in item.get("release_dates", ())
            if isinstance(release, dict)
            and str(release.get("certification") or "").strip()
        ]
        release_priority = {3: 0, 2: 1, 4: 2, 5: 3, 6: 4, 1: 5}
        release_items.sort(
            key=lambda release: release_priority.get(
                int(release.get("type") or 0),
                9,
            )
        )
        return (
            str(release_items[0].get("certification") or "").strip()
            if release_items
            else ""
        )

    by_region = {
        str(item.get("iso_3166_1") or "").upper(): item
        for item in results
        if item.get("iso_3166_1")
    }
    for region in preferred_regions:
        certification = value_for(by_region.get(region, {}))
        if certification:
            return certification
    for item in results:
        certification = value_for(item)
        if certification:
            return certification
    return _("Unrated")


def runtime_minutes(value: str) -> int:
    """Convert the catalog's compact duration strings to minutes.

    Parses both the compact English forms (e.g. "2h 04m", "4d 12h 22m")
    and translated unit words (e.g. Persian "ساعت"/"دقیقه"/"روز"), so
    durations formatted via ``format_watch_time`` in any language — as
    well as previously stored English values — keep working.
    """
    text = value.strip().casefold()
    if not text:
        return 0
    days = re.search(r"(\d+)\s*(?:d\b|day|days|روز)", text)
    hours = re.search(r"(\d+)\s*(?:h\b|hour|hours|ساعت)", text)
    minutes = re.search(r"(\d+)\s*(?:m\b|min|mins|minute|minutes|دقیقه)", text)
    if days or hours or minutes:
        return (
            (int(days.group(1)) * 24 * 60 if days else 0)
            + (int(hours.group(1)) * 60 if hours else 0)
            + (int(minutes.group(1)) if minutes else 0)
        )
    return 0


def parse_watched_datetime(value: str) -> datetime | None:
    """Parse canonical ISO 8601 or legacy watched timestamps."""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%b %d, %Y at %I:%M %p").replace(
                tzinfo=datetime.now().astimezone().tzinfo
            )
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def parse_watched_date(value: str) -> date | None:
    parsed = parse_watched_datetime(value)
    return parsed.date() if parsed is not None else None


def watched_now_iso() -> str:
    """Return the current local time as a canonical ISO 8601 timestamp."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def watched_datetime_from_parts(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    *,
    hour_is_12h: bool = False,
    is_pm: bool = False,
) -> datetime | None:
    """Build a timezone-aware local datetime from dialog controls."""
    try:
        year, month, day, hour, minute = (
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
        )
    except (TypeError, ValueError):
        return None
    if hour_is_12h:
        if not 1 <= hour <= 12:
            return None
        hour = (hour % 12) + (12 if is_pm else 0)
    elif not 0 <= hour <= 23:
        return None
    if not 0 <= minute <= 59:
        return None
    try:
        moment = datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=datetime.now().astimezone().tzinfo,
        )
    except ValueError:
        return None
    return moment


def validate_watched_iso(
    value: str,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return an error message for an invalid watched timestamp, else None."""
    parsed = parse_watched_datetime(value)
    if parsed is None:
        return _("The selected date and time are not valid.")
    reference = now if now is not None else datetime.now().astimezone()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=datetime.now().astimezone().tzinfo)
    if parsed > reference:
        return _("The watched time cannot be in the future.")
    return None


def format_watched_iso(value: str) -> str:
    """Format a canonical or legacy watched timestamp for display."""
    parsed = parse_watched_datetime(value)
    if parsed is None:
        return value
    hour = parsed.strftime("%I").lstrip("0") or "12"
    # Translators: date part of a watched timestamp, e.g. "Sep 5, 2026".
    # Keep the placeholders; reorder them to match your language, e.g.
    # Persian: "{day} {month} {year}".
    date_part = _("{month} {day}, {year}").format(
        month=parsed.strftime("%b"),
        day=parsed.day,
        year=parsed.year,
    )
    # Translators: time part of a watched timestamp, e.g. "3:04 PM".
    # "{hour}" is 1-12 without leading zero, "{minute}" is 00-59 and
    # "{ampm}" is AM/PM. Reorder or replace AM/PM to match your language.
    time_part = _("{hour}:{minute} {ampm}").format(
        hour=hour,
        minute=parsed.strftime("%M"),
        ampm=parsed.strftime("%p"),
    )
    # Translators: full watched timestamp combining date and time.
    return _("{date} at {time}").format(date=date_part, time=time_part)


def simkl_history_changed(result: object) -> bool:
    """Return whether a /sync/history response recorded anything new.

    Simkl ignores a history write for an already-completed item (all
    ``added`` counts stay zero). Callers use this to tell "saved" apart
    from "already had it, nothing changed".
    """
    return simkl_client.history_sync_result(result).changed


def format_watch_time(minutes: int) -> str:
    """Format a minute count with translatable, plural-aware duration units."""
    days, remainder = divmod(max(0, minutes), 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        # Translators: "{count}" is a number of days, e.g. "2d".
        # Replace the unit to match your language (Persian: "روز").
        parts.append(ngettext("{count}d", "{count}d", days).format(count=days))
    if hours:
        # Translators: "{count}" is a number of hours, e.g. "3h".
        # Replace the unit to match your language (Persian: "ساعت").
        parts.append(ngettext("{count}h", "{count}h", hours).format(count=hours))
    if minutes or not parts:
        # Translators: "{count}" is a number of minutes, e.g. "44m".
        # Replace the unit to match your language (Persian: "دقیقه").
        parts.append(ngettext("{count}m", "{count}m", minutes).format(count=minutes))
    # Translators: separator joining duration parts (e.g. "1h 44m").
    # Languages such as Persian may use " و " (e.g. "۱ ساعت و ۴۴ دقیقه").
    return _(" ").join(parts)


def merge_tmdb_season_episodes(
    episodes: tuple[EpisodeInfo, ...],
    tmdb_episodes: Any,
    *,
    cached_image_lookup: Any = None,
) -> tuple[EpisodeInfo, ...]:
    """Merge one TMDB season response into existing episodes by episode number.

    Matching uses ``episode_number`` (not list position) so specials and
    unusual orders stay correct. Empty TMDB values never replace useful
    existing values. Malformed items are skipped without affecting valid ones.
    """
    if not isinstance(tmdb_episodes, (list, tuple)):
        return episodes
    by_number: dict[int, dict[str, Any]] = {}
    for item in tmdb_episodes:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("episode_number"))
        except (TypeError, ValueError):
            continue
        if number not in by_number:
            by_number[number] = item

    def resolve_artwork(still_path: str) -> str | None:
        if cached_image_lookup is not None:
            try:
                return cached_image_lookup(still_path)
            except (OSError, RuntimeError):
                return None
        try:
            return tmdb_client.cached_image(still_path, size="w780")
        except OSError:
            return None

    merged: list[EpisodeInfo] = []
    for episode in episodes:
        payload = by_number.get(episode.number)
        if payload is None:
            merged.append(episode)
            continue
        try:
            title_value = str(payload.get("name") or "").strip()
            title = title_value if title_value else episode.title
            date_value = str(payload.get("air_date") or "").strip()
            date = date_value if date_value else episode.date
            description_value = str(payload.get("overview") or "").strip()
            description = (
                description_value if description_value else episode.description
            )
            try:
                runtime_value = int(payload.get("runtime") or 0)
            except (TypeError, ValueError):
                runtime_value = 0
            runtime = (
                format_watch_time(runtime_value)
                if runtime_value > 0
                else episode.runtime
            )
            guest_stars = payload.get("guest_stars")
            if isinstance(guest_stars, list) and guest_stars:
                cast_items: list[CastMember] = []
                for member in guest_stars[:12]:
                    if not isinstance(member, dict):
                        continue
                    profile_path = str(member.get("profile_path") or "")
                    try:
                        profile_file = (
                            tmdb_client.cached_image(profile_path, size="w185")
                            if profile_path
                            else None
                        )
                    except OSError:
                        profile_file = None
                    cast_items.append(
                        CastMember(
                            name=str(member.get("name") or _("Unknown")),
                            role=str(member.get("character") or _("Guest star")),
                            profile_file=profile_file,
                        )
                    )
                cast: tuple[CastMember, ...] = (
                    tuple(cast_items) if cast_items else episode.cast
                )
            else:
                cast = episode.cast
            still_path = str(payload.get("still_path") or "").strip()
            if still_path:
                artwork_file = resolve_artwork(still_path) or episode.artwork_file
            else:
                artwork_file = episode.artwork_file
            merged.append(
                replace(
                    episode,
                    title=title,
                    date=date,
                    description=description,
                    runtime=runtime,
                    cast=cast,
                    artwork_file=artwork_file,
                )
            )
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            merged.append(episode)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class CastMember:
    name: str
    role: str
    profile_file: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeInfo:
    id: str
    number: int
    title: str
    date: str
    description: str
    watched: bool | None
    image_variant: int
    artwork_file: str | None = None
    runtime: str = ""
    cast: tuple[CastMember, ...] = ()


@dataclass(frozen=True, slots=True)
class EpisodeWatch:
    season: int
    episode: int
    watched_at: str = ""


@dataclass(frozen=True, slots=True)
class SeasonInfo:
    id: str
    number: int
    title: str
    watched: int
    episodes: int
    episode_items: tuple[EpisodeInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class VideoInfo:
    title: str
    key: str
    site: str = "YouTube"
    thumbnail_file: str | None = None

    @property
    def url(self) -> str | None:
        if self.site.casefold() == "youtube" and self.key:
            return f"https://www.youtube.com/watch?v={self.key}"
        return None


def main_progress_season_indexes(seasons: tuple[SeasonInfo, ...]) -> tuple[int, ...]:
    """Use regular seasons for progress, falling back to Specials-only catalogs."""
    regular_indexes = tuple(
        index for index, season in enumerate(seasons) if season.number > 0
    )
    return regular_indexes or tuple(range(len(seasons)))


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
    simkl_id: int | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    mal_id: int | None = None
    artwork_file: str | None = None
    poster_file: str | None = None
    backdrop_file: str | None = None
    gallery_backdrops: tuple[str, ...] = ()
    gallery_posters: tuple[str, ...] = ()
    video_titles: tuple[str, ...] = ()
    videos: tuple[VideoInfo, ...] = ()
    episode_history: tuple[EpisodeWatch, ...] = ()
    episode_history_loaded: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> TitleRecord:
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
            season_id = str(item.get("id", "specials" if number == 0 else f"s{number}"))
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
                            episode.get(
                                "title",
                                _("Episode {number}").format(number=episode_position),
                            )
                        ),
                        date=str(episode.get("date", str(raw["year"]))),
                        description=str(episode.get("description", raw["description"])),
                        watched=(
                            bool(episode["watched"]) if "watched" in episode else None
                        ),
                        image_variant=int(
                            episode.get("imageVariant", episode_position)
                        ),
                        artwork_file=(
                            str(episode["artworkFile"])
                            if episode.get("artworkFile") is not None
                            else None
                        ),
                        runtime=str(episode.get("runtime", "")),
                        cast=tuple(
                            CastMember(
                                str(member["name"]),
                                str(member["role"]),
                                str(member.get("profileFile") or "") or None,
                            )
                            for member in episode.get("cast", ())
                            if isinstance(member, dict)
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
            date=_normalize_stored_fallback(str(raw["date"])),
            year=int(raw["year"]),
            runtime=_normalize_stored_fallback(str(raw["runtime"])),
            rating=float(raw["rating"]),
            user_rating=(
                int(raw["userRating"]) if raw.get("userRating") is not None else None
            ),
            genres=_normalize_stored_genres(
                tuple(str(value) for value in raw["genres"])
            ),
            country=_normalize_stored_country(country),
            creator=str(raw["creator"]),
            description=_normalize_stored_fallback(str(raw["description"])),
            poster_palette=tuple(str(value) for value in raw["posterPalette"]),
            poster_variant=int(raw["posterVariant"]),
            order=order,
            certification=(
                _("Unrated")
                if str(raw.get("certification", "Unrated")).strip().casefold()
                == "unrated"
                else str(raw.get("certification", "Unrated"))
            ),
            language=str(raw.get("language", "—")),
            availability=localize_tmdb_status(
                str(
                    raw.get(
                        "availability",
                        "Upcoming"
                        if "discoverPeriod" in raw
                        else "Airing"
                        if media_type != "Movies"
                        else "Released",
                    )
                )
            ),
            network=str(raw.get("network", "Gisheh")),
            external_ratings=tuple(
                (str(item["source"]), str(item["value"]))
                for item in raw.get("externalRatings", ())
            ),
            cast=tuple(
                CastMember(
                    str(item["name"]),
                    str(item["role"]),
                    str(item.get("profileFile") or "") or None,
                )
                for item in raw.get("cast", ())
            ),
            seasons=tuple(
                parse_season(item, position)
                for position, item in enumerate(raw.get("seasons", ()), start=1)
            ),
            recommendations=tuple(
                str(value) for value in raw.get("recommendations", ())
            ),
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
            simkl_id=(int(raw["simklId"]) if raw.get("simklId") is not None else None),
            imdb_id=str(raw.get("imdbId") or "").strip() or None,
            tvdb_id=(int(raw["tvdbId"]) if raw.get("tvdbId") is not None else None),
            mal_id=(int(raw["malId"]) if raw.get("malId") is not None else None),
            artwork_file=(
                str(raw["artworkFile"]) if raw.get("artworkFile") is not None else None
            ),
            poster_file=(
                str(raw["posterFile"]) if raw.get("posterFile") is not None else None
            ),
            backdrop_file=(
                str(raw["backdropFile"])
                if raw.get("backdropFile") is not None
                else None
            ),
            gallery_backdrops=tuple(
                str(value) for value in raw.get("galleryBackdrops", ())
            ),
            gallery_posters=tuple(
                str(value) for value in raw.get("galleryPosters", ())
            ),
            video_titles=tuple(str(value) for value in raw.get("videoTitles", ())),
            videos=tuple(
                VideoInfo(
                    title=str(item.get("title") or "Trailer"),
                    key=str(item.get("key") or ""),
                    site=str(item.get("site") or "YouTube"),
                    thumbnail_file=(
                        str(item["thumbnailFile"])
                        if item.get("thumbnailFile") is not None
                        else None
                    ),
                )
                for item in raw.get("videos", ())
                if isinstance(item, dict) and item.get("key")
            ),
            episode_history=tuple(
                EpisodeWatch(
                    season=int(item["season"]),
                    episode=int(item["episode"]),
                    watched_at=str(item.get("watchedAt", "")),
                )
                for item in raw.get("episodeHistory", ())
                if isinstance(item, dict)
                and item.get("season") is not None
                and item.get("episode") is not None
            ),
            episode_history_loaded=bool(raw.get("episodeHistoryLoaded", False)),
        )


def title_record_to_mapping(record: TitleRecord) -> dict[str, Any]:
    """Serialize one locally owned library record without losing rich metadata."""
    return {
        "id": record.id,
        "title": record.title,
        "type": record.media_type,
        "status": record.status,
        "date": record.date,
        "year": record.year,
        "runtime": record.runtime,
        "rating": record.rating,
        "userRating": record.user_rating,
        "genres": list(record.genres),
        "country": record.country,
        "creator": record.creator,
        "description": record.description,
        "posterPalette": list(record.poster_palette),
        "posterVariant": record.poster_variant,
        "order": record.order,
        "certification": record.certification,
        "language": record.language,
        "availability": record.availability,
        "network": record.network,
        "externalRatings": [
            {"source": source, "value": value}
            for source, value in record.external_ratings
        ],
        "cast": [
            {
                "name": member.name,
                "role": member.role,
                "profileFile": member.profile_file,
            }
            for member in record.cast
        ],
        "seasons": [
            {
                "id": season.id,
                "number": season.number,
                "title": season.title,
                "watched": season.watched,
                "episodes": season.episodes,
                "episodeItems": [
                    {
                        "id": episode.id,
                        "number": episode.number,
                        "title": episode.title,
                        "date": episode.date,
                        "description": episode.description,
                        "watched": episode.watched,
                        "imageVariant": episode.image_variant,
                        "artworkFile": episode.artwork_file,
                        "runtime": episode.runtime,
                        "cast": [
                            {
                                "name": member.name,
                                "role": member.role,
                                "profileFile": member.profile_file,
                            }
                            for member in episode.cast
                        ],
                    }
                    for episode in season.episode_items
                ],
            }
            for season in record.seasons
        ],
        "recommendations": list(record.recommendations),
        "discoverPeriod": record.discover_period,
        "featured": record.featured,
        "popularity": record.popularity,
        "releaseRank": record.release_rank,
        "layout": record.discover_layout,
        "tmdbId": record.tmdb_id,
        "tmdbMediaType": record.tmdb_media_type,
        "simklId": record.simkl_id,
        "imdbId": record.imdb_id,
        "tvdbId": record.tvdb_id,
        "malId": record.mal_id,
        "artworkFile": record.artwork_file,
        "posterFile": record.poster_file,
        "backdropFile": record.backdrop_file,
        "galleryBackdrops": list(record.gallery_backdrops),
        "galleryPosters": list(record.gallery_posters),
        "videoTitles": list(record.video_titles),
        "videos": [
            {
                "title": item.title,
                "key": item.key,
                "site": item.site,
                "thumbnailFile": item.thumbnail_file,
            }
            for item in record.videos
        ],
        "episodeHistory": [
            {
                "season": item.season,
                "episode": item.episode,
                "watchedAt": item.watched_at,
            }
            for item in record.episode_history
        ],
        "episodeHistoryLoaded": record.episode_history_loaded,
    }


def load_catalog(
    *,
    sample_data_path: Path | None = None,
) -> tuple[
    tuple[TitleRecord, ...],
    tuple[TitleRecord, ...],
    dict[str, dict[str, int]],
]:
    if sample_data_path is not None:
        with sample_data_path.open(encoding="utf-8") as source:
            payload = json.load(source)
    else:
        payload = {"library": (), "explore": ()}

    # Production callers omit the fixture path, so both the personal library
    # and Explore start empty and are populated only by user actions or APIs.
    records = tuple(TitleRecord.from_mapping(raw) for raw in payload["library"])
    explore_records = tuple(
        TitleRecord.from_mapping(raw) for raw in payload.get("explore", ())
    )
    totals = {
        media_type: {status: 0 for status in COLLECTION_NAMES}
        for media_type in MEDIA_TYPES
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


def tmdb_rating_from_payload(payload: dict[str, Any]) -> float | None:
    """Return a real TMDB rating only when TMDB reports at least one vote."""
    vote_count = payload.get("vote_count")
    vote_average = payload.get("vote_average")
    if (
        not isinstance(vote_count, int)
        or isinstance(vote_count, bool)
        or vote_count <= 0
        or not isinstance(vote_average, (int, float))
        or isinstance(vote_average, bool)
    ):
        return None
    rating = float(vote_average)
    if not math.isfinite(rating) or not 0.0 <= rating <= 10.0:
        return None
    return round(rating, 1)


def title_record_from_tmdb(
    raw: dict[str, Any],
    media_type: str,
    position: int,
    poster_file: str | None,
    backdrop_file: str | None,
) -> TitleRecord:
    tmdb_id = int(raw["id"])
    tmdb_namespace = "movie" if media_type == "Movies" else "tv"
    title = str(raw.get("title") or raw.get("name") or _("Untitled"))
    release_date = str(raw.get("release_date") or raw.get("first_air_date") or "")
    year = (
        int(release_date[:4])
        if release_date[:4].isdigit()
        else datetime.now().astimezone().year
    )
    genres = tuple(
        _(TMDB_GENRES[genre_id])
        for genre_id in raw.get("genre_ids", ())
        if genre_id in TMDB_GENRES
    ) or (_("Uncategorized"),)
    origin = raw.get("origin_country") or ()
    country = localize_country_name(str(origin[0])) if origin else _("Unknown country")
    tmdb_rating = tmdb_rating_from_payload(raw)
    rating = tmdb_rating if tmdb_rating is not None else 0.0
    return TitleRecord(
        id=f"tmdb-{tmdb_namespace}-{tmdb_id}",
        title=title,
        media_type=media_type,
        status="Watchlist",
        date=release_date or _("Release date unavailable"),
        year=year,
        runtime=_("Runtime unavailable"),
        rating=rating,
        user_rating=None,
        genres=genres,
        country=country,
        creator="TMDB",
        description=str(raw.get("overview") or _("No overview is available yet.")),
        poster_palette=_tmdb_palette(tmdb_id),
        poster_variant=tmdb_id % 6 + 1,
        order=max(1, 1000 - position),
        certification=_("Loading…"),
        language=str(raw.get("original_language") or "—").upper(),
        availability=localize_tmdb_status(
            "Released" if media_type == "Movies" else "Airing"
        ),
        network="TMDB",
        external_ratings=(
            (("TMDB", f"{tmdb_rating:.1f}"),) if tmdb_rating is not None else ()
        ),
        cast=(),
        seasons=(),
        recommendations=(),
        discover_period="This month",
        featured=position == 1,
        popularity=round(float(raw.get("popularity") or 0)),
        release_rank=position,
        discover_layout="poster",
        tmdb_id=tmdb_id,
        tmdb_media_type=tmdb_namespace,
        artwork_file=poster_file or backdrop_file,
        poster_file=poster_file,
        backdrop_file=backdrop_file,
    )


def recommendation_records_from_tmdb(
    items: Any,
    parent: TitleRecord,
    *,
    start_position: int = 1,
) -> tuple[TitleRecord, ...]:
    """Normalize TMDB recommendation results into openable title records.

    Matches the shared ``title_record_from_tmdb()`` path used by Explore and
    search results. Skips the parent title and duplicate TMDB IDs, preserves
    TMDB order, and caps the result at 12 entries.
    """
    if not isinstance(items, (list, tuple)):
        return ()
    parent_ids = {parent.tmdb_id} if parent.tmdb_id is not None else set()
    seen: set[int] = set(parent_ids)
    records: list[TitleRecord] = []
    position = max(1, start_position)
    for item in items:
        if len(records) >= 12:
            break
        if not isinstance(item, dict):
            continue
        try:
            tmdb_id = int(item["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if tmdb_id in seen:
            continue
        seen.add(tmdb_id)
        kind = str(item.get("media_type") or "").lower()
        if kind == "movie":
            media_type = "Movies"
        elif kind == "tv":
            media_type = (
                parent.media_type
                if parent.media_type in ("Shows", "Anime")
                else "Shows"
            )
        elif parent.media_type in ("Movies", "Shows", "Anime"):
            media_type = parent.media_type
        elif (parent.tmdb_media_type or "movie") == "movie":
            media_type = "Movies"
        else:
            media_type = "Shows"
        try:
            poster_file = tmdb_client.cached_image(
                str(item.get("poster_path") or ""),
                size="w342",
            )
            backdrop_file = tmdb_client.cached_image(
                str(item.get("backdrop_path") or ""),
                size="w780",
            )
        except OSError:
            poster_file, backdrop_file = None, None
        try:
            record = title_record_from_tmdb(
                item,
                media_type,
                position,
                poster_file,
                backdrop_file,
            )
        except (TypeError, ValueError, KeyError):
            continue
        if record.id == parent.id:
            continue
        records.append(record)
        position += 1
    return tuple(records)


def video_infos_from_tmdb(items: Any) -> tuple[VideoInfo, ...]:
    """Normalize playable YouTube videos and attach any cached thumbnails."""
    if not isinstance(items, (list, tuple)):
        return ()
    videos: list[VideoInfo] = []
    seen: set[str] = set()
    for item in items:
        if len(videos) >= 8:
            break
        if not isinstance(item, dict):
            continue
        site = str(item.get("site") or "")
        key = str(item.get("key") or "").strip()
        if site.casefold() != "youtube" or not key or key in seen:
            continue
        seen.add(key)
        videos.append(
            VideoInfo(
                title=str(item.get("name") or _("Trailer")),
                key=key,
                site=site,
                thumbnail_file=tmdb_client.cached_youtube_thumbnail(key),
            )
        )
    return tuple(videos)


def runtime_from_tmdb(payload: dict[str, Any], fallback: str) -> str:
    """Read a useful duration even when TMDB omits episode_run_time."""
    candidates: list[Any] = [payload.get("runtime")]
    episode_runtimes = payload.get("episode_run_time")
    if isinstance(episode_runtimes, (list, tuple)):
        candidates.extend(episode_runtimes)
    if fallback in {
        "",
        _("Loading from TMDB…"),
        _("Runtime unavailable"),
        # English fallbacks kept for records stored before translation.
        "Loading from TMDB…",
        "Runtime unavailable",
    }:
        for episode_key in ("last_episode_to_air", "next_episode_to_air"):
            episode = payload.get(episode_key)
            if isinstance(episode, dict):
                candidates.append(episode.get("runtime"))
    for candidate in candidates:
        try:
            minutes = int(candidate or 0)
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            return format_watch_time(minutes)
    return fallback


def enrich_record_from_tmdb(
    record: TitleRecord,
    payload: dict[str, Any],
    *,
    poster_file: str | None = None,
    backdrop_file: str | None = None,
) -> TitleRecord:
    """Apply TMDB-owned catalog metadata while preserving Simkl user state."""
    title = str(payload.get("title") or payload.get("name") or record.title)
    release_date = str(
        payload.get("release_date") or payload.get("first_air_date") or ""
    )
    year = int(release_date[:4]) if release_date[:4].isdigit() else record.year
    genre_items = payload.get("genres", ())
    genres = localize_genre_names(
        tuple(
            str(item["name"])
            for item in genre_items
            if isinstance(item, dict) and item.get("name")
        )
    )
    if not genres:
        genres = (
            tuple(
                _(TMDB_GENRES[genre_id])
                for genre_id in payload.get("genre_ids", ())
                if genre_id in TMDB_GENRES
            )
            or record.genres
        )

    runtime = runtime_from_tmdb(payload, record.runtime)

    countries = [
        str(item.get("name") or item.get("iso_3166_1"))
        for item in payload.get("production_countries", ())
        if isinstance(item, dict) and (item.get("name") or item.get("iso_3166_1"))
    ]
    if not countries:
        countries = [str(value) for value in payload.get("origin_country", ()) if value]
    creators = [
        str(item.get("name"))
        for item in payload.get("created_by", ())
        if isinstance(item, dict) and item.get("name")
    ]
    if not creators:
        creators = [
            str(item.get("name"))
            for item in payload.get("production_companies", ())[:2]
            if isinstance(item, dict) and item.get("name")
        ]
    networks = [
        str(item.get("name"))
        for item in payload.get("networks", ())
        if isinstance(item, dict) and item.get("name")
    ]
    tmdb_rating = tmdb_rating_from_payload(payload)
    external_ratings = (
        (("TMDB", f"{tmdb_rating:.1f}"),) if tmdb_rating is not None else ()
    )
    if record.user_rating is not None:
        external_ratings += (("Your rating", str(record.user_rating)),)

    poster_path = str(payload.get("poster_path") or "")
    backdrop_path = str(payload.get("backdrop_path") or "")
    poster_file = poster_file or tmdb_client.cached_image(poster_path, size="w500")
    backdrop_file = backdrop_file or tmdb_client.cached_image(
        backdrop_path,
        size="w780",
    )
    return replace(
        record,
        title=title,
        year=year,
        runtime=runtime,
        rating=tmdb_rating if tmdb_rating is not None else 0.0,
        genres=genres,
        country=", ".join(localize_countries(tuple(countries[:2]))) or record.country,
        creator=", ".join(creators[:2]) or "TMDB",
        description=str(payload.get("overview") or record.description),
        certification=certification_from_tmdb(
            payload,
            record.tmdb_media_type or "movie",
        ),
        language=str(payload.get("original_language") or record.language).upper(),
        availability=localize_tmdb_status(
            str(payload.get("status") or record.availability),
            fallback=record.availability,
        ),
        network=", ".join(networks[:2]) or "TMDB",
        external_ratings=external_ratings,
        popularity=round(float(payload.get("popularity") or record.popularity)),
        artwork_file=poster_file or backdrop_file or record.artwork_file,
        poster_file=poster_file or record.poster_file,
        backdrop_file=backdrop_file or record.backdrop_file,
    )


def enrich_records_from_tmdb_cache(
    records: tuple[TitleRecord, ...],
) -> tuple[TitleRecord, ...]:
    enriched: list[TitleRecord] = []
    for record in records:
        if record.tmdb_id is None or record.tmdb_media_type is None:
            enriched.append(record)
            continue
        summary = tmdb_client.load_summary(
            record.tmdb_media_type,
            record.tmdb_id,
        )
        enriched.append(
            enrich_record_from_tmdb(record, summary) if summary is not None else record
        )
    return tuple(enriched)


def title_records_from_simkl(payload: dict[str, Any]) -> tuple[TitleRecord, ...]:
    status_map = {
        "plantowatch": "Watchlist",
        "watching": "Watching",
        "hold": "On Hold",
        "completed": "Watched",
        "dropped": "Dropped",
    }
    media_map = {
        "movies": ("Movies", "movie", "movie"),
        "shows": ("Shows", "show", "tv"),
        "anime": ("Anime", "show", "tv"),
    }
    sortable: list[tuple[str, TitleRecord]] = []
    for group, (media_type, object_key, tmdb_namespace) in media_map.items():
        items = payload.get(group, ())
        if not isinstance(items, list):
            continue
        for position, entry in enumerate(items, start=1):
            if not isinstance(entry, dict):
                continue
            media = entry.get(object_key)
            if not isinstance(media, dict):
                continue
            ids = media.get("ids") if isinstance(media.get("ids"), dict) else {}
            simkl_id = ids.get("simkl")
            try:
                numeric_simkl_id = int(simkl_id)
            except (TypeError, ValueError):
                continue
            user_rating = entry.get("user_rating")
            raw_status = str(entry.get("status") or "")
            if raw_status not in status_map:
                continue
            status = status_map[raw_status]
            try:
                watched_count = int(entry.get("watched_episodes_count") or 0)
                total_count = int(entry.get("total_episodes_count") or 0)
            except (TypeError, ValueError):
                continue
            try:
                simkl_runtime_minutes = int(media.get("runtime") or 0)
            except (TypeError, ValueError):
                simkl_runtime_minutes = 0
            simkl_runtime = (
                format_watch_time(simkl_runtime_minutes)
                if simkl_runtime_minutes > 0
                else _("Runtime unavailable")
            )
            raw_seasons = entry.get("seasons")
            episode_history: list[EpisodeWatch] = []
            if isinstance(raw_seasons, list):
                for raw_season in raw_seasons:
                    if not isinstance(raw_season, dict):
                        continue
                    try:
                        season_number = int(raw_season.get("number") or 0)
                    except (TypeError, ValueError):
                        continue
                    raw_episodes = raw_season.get("episodes")
                    if not isinstance(raw_episodes, list):
                        continue
                    for raw_episode in raw_episodes:
                        if not isinstance(raw_episode, dict):
                            continue
                        mapping = raw_episode.get("tvdb")
                        mapped_season = season_number
                        mapped_episode = raw_episode.get("number")
                        if isinstance(mapping, dict):
                            mapped_season = mapping.get("season", mapped_season)
                            mapped_episode = mapping.get("episode", mapped_episode)
                        try:
                            mapped_season = int(mapped_season)
                            mapped_episode = int(mapped_episode)
                        except (TypeError, ValueError):
                            continue
                        watched_value = raw_episode.get("watched")
                        if mapped_episode <= 0 or (
                            watched_value is not None and not bool(watched_value)
                        ):
                            continue
                        episode_history.append(
                            EpisodeWatch(
                                season=mapped_season,
                                episode=mapped_episode,
                                watched_at=str(raw_episode.get("watched_at") or ""),
                            )
                        )
            last_activity = str(
                entry.get("last_watched_at") or entry.get("added_to_watchlist_at") or ""
            )
            tmdb_value = ids.get("tmdb")
            try:
                tmdb_id = int(tmdb_value) if tmdb_value is not None else None
            except (TypeError, ValueError):
                tmdb_id = None
            record = TitleRecord(
                id=f"simkl-{group}-{simkl_id}",
                title=_("Loading from TMDB…"),
                media_type=media_type,
                status=status,
                date=last_activity or _("Synced from Simkl"),
                year=0,
                runtime=simkl_runtime,
                rating=0.0,
                user_rating=(
                    int(user_rating)
                    if isinstance(user_rating, int) and 1 <= user_rating <= 10
                    else None
                ),
                genres=(_("Loading from TMDB"),),
                country="—",
                creator="TMDB",
                description=_("Catalog metadata is loading from TMDB."),
                poster_palette=_tmdb_palette(numeric_simkl_id),
                poster_variant=numeric_simkl_id % 6 + 1,
                order=max(1, 100000 - position),
                certification=_("Loading…"),
                language="—",
                availability=localize_tmdb_status(
                    str(entry.get("status") or "Synced").replace(
                        "plantowatch", "Plan to watch"
                    )
                ),
                network="TMDB",
                external_ratings=(
                    (("Your rating", str(user_rating)),)
                    if isinstance(user_rating, int) and 1 <= user_rating <= 10
                    else ()
                ),
                cast=(),
                seasons=(
                    (
                        SeasonInfo(
                            id="s1",
                            number=1,
                            title=_("Progress"),
                            watched=watched_count,
                            episodes=total_count,
                        ),
                    )
                    if media_type != "Movies" and total_count
                    else ()
                ),
                recommendations=(),
                discover_period="All releases",
                featured=False,
                popularity=0,
                release_rank=position,
                discover_layout="poster",
                tmdb_id=tmdb_id,
                tmdb_media_type=tmdb_namespace if tmdb_id is not None else None,
                simkl_id=numeric_simkl_id,
                imdb_id=str(ids.get("imdb") or "").strip() or None,
                tvdb_id=(
                    int(ids["tvdb"]) if str(ids.get("tvdb") or "").isdigit() else None
                ),
                mal_id=(
                    int(ids["mal"]) if str(ids.get("mal") or "").isdigit() else None
                ),
                episode_history=tuple(episode_history),
                episode_history_loaded=isinstance(raw_seasons, list),
            )
            sortable.append((last_activity, record))
    sortable.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    return tuple(
        replace(record, order=max(1, len(sortable) - position))
        for position, (_activity, record) in enumerate(sortable)
    )
