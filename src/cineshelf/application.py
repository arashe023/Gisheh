"""Application lifecycle and global actions for CineShelf."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .services import simkl_client
from .window import APP_ID, APP_NAME, APP_VERSION, CineShelfWindow


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

        logs_action = Gio.SimpleAction.new("logs", None)
        logs_action.connect("activate", self._show_logs)
        self.add_action(logs_action)

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
            developer_name="CineShelf",
            version=APP_VERSION,
            comments="A native GTK4 and Libadwaita media tracker.",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(window)

    def _show_logs(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self.controller is not None:
            self.controller.show_application_log()
