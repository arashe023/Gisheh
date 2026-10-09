"""Service orchestration independent of GTK, with explicitly supplied clients."""


class CalendarController:
    def __init__(self, client):
        self.client = client

    def fetch_month(self, client_id, year, month, display_timezone, force=False):
        snapshots, errors = [], []
        for media in ("movies", "shows", "anime"):
            try:
                snapshots.append(
                    self.client.fetch_calendar(
                        media,
                        client_id=client_id,
                        year=year,
                        month=month,
                        display_timezone=display_timezone,
                        force=force,
                    )
                )
            except self.client.SimklError as error:
                errors.append(str(error))
        if not snapshots:
            raise self.client.SimklError(
                errors[0] if errors else "Calendar is unavailable."
            )
        return self.client.merge_calendar_snapshots(snapshots), errors[
            0
        ] if errors else None

    @staticmethod
    def visible_events(snapshot, month, resolve_record, in_library, effective_status):
        if snapshot is None:
            return ()
        visible = []
        for event in snapshot.events:
            moment = event.local_datetime
            if moment is None or (moment.year, moment.month) != (
                month.year,
                month.month,
            ):
                continue
            record = resolve_record(event)
            if (
                record is not None
                and in_library(record)
                and effective_status(record) in {"Watching", "Watchlist", "On Hold"}
            ):
                visible.append(event)
        return tuple(visible)

    @staticmethod
    def group_days(events):
        ordered = sorted(
            (e for e in events if e.local_datetime is not None),
            key=lambda e: (e.local_datetime, e.title.title.casefold(), e.simkl_id),
        )
        grouped = []
        for event in ordered:
            day = event.local_datetime.date()
            if grouped and grouped[-1][0] == day:
                grouped[-1] = (day, (*grouped[-1][1], event))
            else:
                grouped.append((day, (event,)))
        return tuple(grouped)

    @staticmethod
    def page(groups, limit):
        visible, shown = [], 0
        for group in groups:
            if shown >= limit:
                break
            visible.append(group)
            shown += len(group[1])
        return tuple(visible), shown


class ExploreController:
    def __init__(self, client):
        self.client = client

    def fetch(self, token):
        return self.client.fetch_explore(token)

    def page(self, token, media, page):
        return self.client.fetch_explore_page(token, media, page)

    def search(self, token, media, query, page):
        return self.client.search_titles_page(token, media, query, page)


class DetailsController:
    def __init__(self, client):
        self.client = client

    def fetch(self, token, media, title_id):
        return self.client.fetch_details(token, media, title_id)

    def season(self, token, title_id, season):
        return self.client.fetch_season_details(token, title_id, season)

    def episode(self, token, title_id, season, episode):
        return self.client.fetch_episode_details(token, title_id, season, episode)


class SyncController:
    def __init__(self, client):
        self.client = client

    def library(
        self,
        client_id,
        token,
        *,
        cached_library,
        cached_activities,
        activities,
        last_sync,
        incremental,
    ):
        if not incremental:
            return self.client.fetch_library(client_id, token)
        if activities.get("all") == last_sync:
            return cached_library
        delta = self.client.fetch_library_delta(client_id, token, last_sync)
        valid_ids = None
        if self.client.removals_changed(cached_activities, activities):
            valid_ids = self.client.library_ids(
                self.client.fetch_library_ids(client_id, token)
            )
        return self.client.merge_library(cached_library, delta, valid_ids)
