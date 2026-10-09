"""Native, adaptive profile presentation, independent of account/storage logic."""

from datetime import date
from gettext import gettext as _, ngettext

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .localization import localize_genre_name
from .models import format_watch_time


class ProfileView(Gtk.Box):
    def __init__(self, *, on_preferences, on_explore):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        self._stats = None
        self._expanders = {}
        self.add_css_class("profile-content")

        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        identity.set_halign(Gtk.Align.FILL)
        self.avatar = Adw.Avatar(size=72, show_initials=True)
        self.avatar.set_halign(Gtk.Align.CENTER)
        identity.append(self.avatar)
        self.name_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.name_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.name_label.add_css_class("title-1")
        identity.append(self.name_label)
        self.source_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.source_label.add_css_class("dim-label")
        identity.append(self.source_label)
        preferences = Gtk.Button(label=_("Profile Settings"), halign=Gtk.Align.CENTER)
        preferences.add_css_class("pill")
        preferences.set_margin_top(8)
        preferences.connect("clicked", lambda _button: on_preferences())
        identity.append(preferences)
        self.append(identity)

        self.empty = Adw.StatusPage(
            icon_name="video-x-generic-symbolic",
            title=_("Your viewing story starts here"),
            description=_(
                "Mark a movie or episode as watched to see your activity here."
            ),
        )
        self.empty.add_css_class("compact")
        explore = Gtk.Button(label=_("Explore Titles"), halign=Gtk.Align.CENTER)
        explore.add_css_class("pill")
        explore.add_css_class("suggested-action")
        explore.connect("clicked", lambda _button: on_explore())
        self.empty.set_child(explore)
        self.append(self.empty)

        self.activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        activity_heading = Gtk.Label(label=_("Viewing Activity"), xalign=0)
        activity_heading.add_css_class("heading")
        self.activity.append(activity_heading)
        self.period = Adw.ToggleGroup(halign=Gtk.Align.CENTER)
        self.period.add(Adw.Toggle(name="month", label=_("This Month")))
        self.period.add(Adw.Toggle(name="year", label=_("This Year")))
        self.period.set_active_name("month")
        self.period.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Activity period")]
        )
        self.period.connect("notify::active-name", self._period_changed)
        self.activity.append(self.period)
        self.summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.summary.add_css_class("card")
        self.summary.add_css_class("profile-summary")
        self.period_label = Gtk.Label()
        self.period_label.add_css_class("dim-label")
        self.summary.append(self.period_label)
        self.time_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.time_label.add_css_class("title-1")
        self.summary.append(self.time_label)
        caption = Gtk.Label(label=_("Watch time"))
        caption.add_css_class("dim-label")
        self.summary.append(caption)
        self.summary.append(Gtk.Separator())
        metrics = Gtk.Box(spacing=12, homogeneous=True)
        self.metric_values = []
        for title in (_("Movies"), _("Episodes"), _("Active days")):
            metric = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            value = Gtk.Label()
            value.add_css_class("title-3")
            label = Gtk.Label(label=title, wrap=True, justify=Gtk.Justification.CENTER)
            label.add_css_class("caption")
            label.add_css_class("dim-label")
            metric.append(value)
            metric.append(label)
            metrics.append(metric)
            self.metric_values.append(value)
        self.summary.append(metrics)
        self.period_note = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.period_note.add_css_class("dim-label")
        self.period_note.add_css_class("caption")
        self.summary.append(self.period_note)
        self.activity.append(self.summary)
        self.year_group = Adw.PreferencesGroup()
        self.activity.append(self.year_group)
        self.append(self.activity)

        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        self.append(self.details)

    def set_identity(self, name, source, texture=None):
        self.avatar.set_text(name)
        self.avatar.set_custom_image(texture)
        self.name_label.set_label(name)
        self.source_label.set_label(source)

    @staticmethod
    def _row(title, value, *, subtitle=None, icon=None):
        row = Adw.ActionRow(title=title, subtitle=subtitle or "", use_markup=False)
        row.set_title_lines(0)
        row.set_subtitle_lines(0)
        if icon:
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        result = Gtk.Label(label=str(value), valign=Gtk.Align.CENTER)
        result.add_css_class("heading")
        result.add_css_class("numeric")
        row.add_suffix(result)
        row.update_property([Gtk.AccessibleProperty.LABEL], [f"{title}: {value}"])
        return row

    @staticmethod
    def _clear(box):
        while box.get_first_child() is not None:
            box.remove(box.get_first_child())

    def _expander(self, key, title, subtitle, expanded):
        row = Adw.ExpanderRow(title=title, subtitle=subtitle, use_markup=False)
        row.set_expanded(expanded.get(key, False))
        self._expanders[key] = row
        return row

    def update(self, stats):
        self._stats = stats
        expanded = {key: row.get_expanded() for key, row in self._expanders.items()}
        self._expanders = {}
        has_history = bool(
            stats["watched_records"]
            or stats["episode_count"]
            or stats["rating_count"]
            or stats["activity"]
            or stats["total_minutes"]
        )
        self.empty.set_visible(not has_history)
        self.activity.set_visible(has_history)
        self.details.set_visible(has_history)
        self._clear(self.details)
        # Replace the twelve static month rows without disturbing the period control.
        if hasattr(self, "year_row"):
            self.year_group.remove(self.year_row)
        self.year_row = self._expander(
            "months",
            _("Monthly Breakdown"),
            _("Movies and episodes watched this year"),
            expanded,
        )
        today = date.today()
        for month in range(1, 13):
            self.year_row.add_row(
                self._row(
                    date(today.year, month, 1).strftime("%B"),
                    stats["year_month_activity"].get(month, 0),
                )
            )
        self.year_group.add(self.year_row)
        self._period_changed()

        library = Adw.PreferencesGroup(
            title=_("Your Library"), description=_("All-time viewing totals")
        )
        library.add(
            self._row(
                _("Total watch time"),
                format_watch_time(stats["total_minutes"]),
                icon="document-open-recent-symbolic",
            )
        )
        library.add(
            self._row(
                _("Completed titles"),
                len(stats["watched_records"]),
                icon="object-select-symbolic",
            )
        )
        library.add(
            self._row(
                _("Episodes watched"),
                stats["episode_count"],
                icon="media-playback-start-symbolic",
            )
        )
        breakdown = self._expander(
            "totals",
            _("Viewing Breakdown"),
            _("Movies, television and anime"),
            expanded,
        )
        for title, value in (
            (_("Movies"), stats["movie_count"]),
            (_("Movie time"), format_watch_time(stats["movie_minutes"])),
            (_("TV & anime time"), format_watch_time(stats["television_minutes"])),
        ):
            breakdown.add_row(self._row(title, value))
        library.add(breakdown)
        self.details.append(library)

        genres = Adw.PreferencesGroup(
            title=_("Favorite Genres"),
            description=_("Most watched genres in your library"),
        )
        top_genres = stats["genres"].most_common(6)
        if not top_genres:
            genres.add(
                Adw.ActionRow(
                    title=_("No genres yet"),
                    subtitle=_(
                        "Genres appear when watched titles have catalog information."
                    ),
                )
            )
        for genre, count in top_genres:
            genres.add(self._row(localize_genre_name(genre), count))
        self.details.append(genres)

        ratings = Adw.PreferencesGroup(title=_("Your Ratings"))
        if stats["rating_count"]:
            average = (
                sum(score * count for score, count in stats["rating_histogram"].items())
                / stats["rating_count"]
            )
            ratings.add(
                self._row(
                    _("Average rating"), f"{average:.1f} / 10", icon="starred-symbolic"
                )
            )
            distribution = self._expander(
                "ratings",
                _("Rating Distribution"),
                ngettext(
                    "{count} rated title", "{count} rated titles", stats["rating_count"]
                ).format(count=stats["rating_count"]),
                expanded,
            )
            for score in range(10, 0, -1):
                distribution.add_row(
                    self._row(
                        _("{score} out of 10").format(score=score),
                        stats["rating_histogram"].get(score, 0),
                    )
                )
            ratings.add(distribution)
        else:
            ratings.add(
                Adw.ActionRow(
                    title=_("No ratings yet"),
                    subtitle=_("Rate a title to start building your rating history."),
                )
            )
        self.details.append(ratings)

    def _period_changed(self, *_args):
        if self._stats is None:
            return
        stats = self._stats
        period = self.period.get_active_name()
        if period not in ("month", "year"):
            return
        today = date.today()
        self.period_label.set_label(
            today.strftime("%B %Y") if period == "month" else str(today.year)
        )
        self.time_label.set_label(format_watch_time(stats[f"{period}_minutes"]))
        days = (
            len(stats["month_activity"])
            if period == "month"
            else stats["active_days_year"]
        )
        for widget, value, title in zip(
            self.metric_values,
            (stats[f"{period}_movie_count"], stats[f"{period}_episode_count"], days),
            (_("Movies"), _("Episodes"), _("Active days")),
        ):
            widget.set_label(str(value))
            widget.update_property(
                [Gtk.AccessibleProperty.LABEL], [f"{title}: {value}"]
            )
        self.period_note.set_label(
            _("Based on saved watch dates")
            if days
            else _("No viewing history in this period")
        )
        self.year_group.set_visible(period == "year")
