"""UI transaction boundaries for personal data and local persistence failures."""

from copy import deepcopy
from functools import wraps
from gettext import gettext as _

STATE_ATTRIBUTES = (
    "bookmarks",
    "favorites",
    "completed",
    "ratings",
    "status_overrides",
    "episode_status_overrides",
    "episode_watched_at",
    "title_watched_at",
    "local_library_records",
    "records",
    "records_by_id",
    "library_ids",
    "color_scheme",
    "content_language",
    "auto_sync",
    "auto_calendar_refresh",
    "default_media",
    "preferred_view_mode",
    "view_mode",
    "library_mode",
)


def persisted_change(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        depth = getattr(self, "_state_transaction_depth", 0)
        if depth:
            return method(self, *args, **kwargs)
        snapshot = {
            key: deepcopy(getattr(self, key))
            for key in STATE_ATTRIBUTES
            if hasattr(self, key)
        }
        self._state_transaction_depth = 1
        try:
            return method(self, *args, **kwargs)
        except OSError as error:
            remote = getattr(self, "_remote_commit", False)
            committed = getattr(error, "committed", False)
            if not remote and not committed:
                for key, value in snapshot.items():
                    setattr(self, key, value)
                rebuild = getattr(self, "_rebuild_record_aliases", None)
                if rebuild and hasattr(self, "_library_records_by_canonical"):
                    rebuild()
                from .services import tmdb_client

                tmdb_client.set_content_language(
                    getattr(self, "content_language", "system")
                )
            self._toast(
                _(
                    "The data was saved, but its durability could not be confirmed. Check the device storage."
                )
                if committed
                else _(
                    "Simkl was updated, but saving on this device failed. Do not repeat the operation; sync again after fixing storage."
                )
                if remote
                else _(
                    "Your change could not be saved. The previous local state has been restored."
                )
            )
            self._app_log("Local persistence failed: %s", error)
            # Do not close the window following a failed persistence operation.
            return True if method.__name__ == "_on_window_close_request" else None
        finally:
            self._state_transaction_depth = 0
            self._remote_commit = False

    return guarded
