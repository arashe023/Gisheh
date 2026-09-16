"""Application lifecycle and global actions for Gisheh."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .onboarding import WelcomeTour
from .services import simkl_client
from .state_store import (
    LIBRARY_MODE_LOCAL,
    LIBRARY_MODE_SIMKL,
    save_library_mode,
    selected_library_mode,
)
from .window import APP_ID, APP_NAME, APP_VERSION, GishehWindow


TMDB_URL = "https://www.themoviedb.org"
SIMKL_URL = "https://simkl.com"
TMDB_LOGO_RESOURCE = "/io/github/arashe023/Gisheh/assets/tmdb-logo.svg"
TMDB_NOTICE = (
    "This product uses the TMDB API but is not endorsed or certified by TMDB."
)


class GishehApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.controller: GishehWindow | None = None
        self.welcome_window: WelcomeTour | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_args: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._show_about_dialog)
        self.add_action(about_action)

        credits_action = Gio.SimpleAction.new("credits", None)
        credits_action.connect("activate", self._show_credits_dialog)
        self.add_action(credits_action)

        tour_action = Gio.SimpleAction.new("tour", None)
        tour_action.connect("activate", self._show_welcome_tour)
        self.add_action(tour_action)

        logs_action = Gio.SimpleAction.new("logs", None)
        logs_action.connect("activate", self._show_logs)
        self.add_action(logs_action)

    def do_activate(self) -> None:
        if self.props.active_window is None:
            mode = selected_library_mode()
            if mode is None:
                self._present_welcome_tour()
                return
            self._open_main_window(mode)
        window = self.props.active_window
        if window is not None:
            window.present()

    def _open_main_window(
        self,
        library_mode: str,
        *,
        connect_simkl: bool = False,
    ) -> None:
        try:
            self.controller = GishehWindow(self, library_mode=library_mode)
        except Exception as error:
            print(f"Gisheh failed to start: {error}", file=sys.stderr)
            window = Adw.ApplicationWindow(application=self, title=APP_NAME)
            window.set_default_size(720, 480)
            window.set_content(
                Adw.StatusPage(
                    icon_name="dialog-error-symbolic",
                    title="Unable to start Gisheh",
                    description=str(error),
                )
            )
            window.present()
            return
        self.controller.window.present()
        if (
            connect_simkl
            and library_mode == LIBRARY_MODE_SIMKL
            and not self.controller.simkl_token
        ):
            GLib.idle_add(self.controller.begin_simkl_connection)

    def _present_welcome_tour(self, *, revisit: bool = False) -> None:
        current_mode = (
            self.controller.library_mode
            if self.controller is not None
            else LIBRARY_MODE_LOCAL
        )

        def complete(mode: str) -> None:
            try:
                save_library_mode(mode)
            except OSError as error:
                if self.welcome_window is not None:
                    dialog = Adw.AlertDialog(
                        heading="Could not save your choice",
                        body=str(error),
                    )
                    dialog.add_response("close", "Close")
                    dialog.present(self.welcome_window)
                return

            welcome = self.welcome_window
            self.welcome_window = None
            if welcome is not None:
                welcome.destroy()
            if revisit and self.controller is not None:
                self.controller.set_library_mode(mode)
                self.controller.window.present()
                return
            self._open_main_window(
                mode,
                connect_simkl=mode == LIBRARY_MODE_SIMKL,
            )

        self.welcome_window = WelcomeTour(
            self,
            simkl_available=bool(simkl_client.read_client_id()),
            on_complete=complete,
            initial_mode=current_mode,
        )
        if revisit and self.controller is not None:
            self.welcome_window.set_transient_for(self.controller.window)
            self.welcome_window.set_modal(True)
        self.welcome_window.present()

    def _show_welcome_tour(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self.welcome_window is not None:
            self.welcome_window.present()
            return
        self._present_welcome_tour(revisit=self.controller is not None)

    def do_shutdown(self) -> None:
        simkl_client.close_image_http_client()
        Adw.Application.do_shutdown(self)

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
            developer_name="Gisheh",
            version=APP_VERSION,
            comments="A native GTK4 and Libadwaita media tracker.",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.add_acknowledgement_section(
            "Data providers",
            ["The Movie Database (TMDB)", "Simkl"],
        )
        dialog.add_legal_section(
            "The Movie Database (TMDB)",
            None,
            Gtk.License.CUSTOM,
            TMDB_NOTICE,
        )
        dialog.add_link("The Movie Database", TMDB_URL)
        dialog.add_link("Simkl", SIMKL_URL)
        dialog.present(window)

    def _show_credits_dialog(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        window = self.props.active_window
        if window is None:
            return

        dialog = Adw.AlertDialog(
            heading="Credits & Data Sources",
            body="Gisheh uses the following independent data services.",
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        tmdb_logo = Gtk.Picture.new_for_resource(TMDB_LOGO_RESOURCE)
        tmdb_logo.set_size_request(180, 30)
        tmdb_logo.set_can_shrink(True)
        tmdb_logo.set_content_fit(Gtk.ContentFit.CONTAIN)
        tmdb_logo.set_halign(Gtk.Align.CENTER)
        tmdb_logo.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["The Movie Database (TMDB)"],
        )
        content.append(tmdb_logo)

        notice = Gtk.Label(label=TMDB_NOTICE)
        notice.set_wrap(True)
        notice.set_justify(Gtk.Justification.CENTER)
        notice.set_max_width_chars(54)
        content.append(notice)

        tmdb_link = Gtk.LinkButton(uri=TMDB_URL, label="Visit The Movie Database")
        tmdb_link.set_halign(Gtk.Align.CENTER)
        content.append(tmdb_link)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.append(separator)

        simkl_credit = Gtk.Label()
        simkl_credit.set_markup(
            "Watch history, ratings and account synchronization are provided "
            f'by <a href="{SIMKL_URL}">Simkl</a>.'
        )
        simkl_credit.set_wrap(True)
        simkl_credit.set_justify(Gtk.Justification.CENTER)
        simkl_credit.set_max_width_chars(54)
        content.append(simkl_credit)

        dialog.set_extra_child(content)
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.present(window)

    def _show_logs(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self.controller is not None:
            self.controller.show_application_log()
