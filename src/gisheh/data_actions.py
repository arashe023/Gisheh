"""Portal-backed import/export UI for the local library."""

from gettext import gettext as _
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
from . import library_backup
from .state_store import LIBRARY_MODE_LOCAL


class LibraryDataActions:
    def __init__(self, controller):
        self.controller = controller
        self.cancellable = Gio.Cancellable()

    def add_to(self, page):
        group = Adw.PreferencesGroup(
            title=_("Local library backup"),
            description=_(
                "Export or replace your local library. Your Simkl account is not changed."
            ),
        )
        for title, callback in (
            (_("Export local library"), self.export),
            (_("Restore local library"), self.restore),
        ):
            row = Adw.ActionRow(title=title, activatable=True)
            row.add_suffix(
                Gtk.Image(
                    icon_name="document-save-symbolic"
                    if callback == self.export
                    else "document-open-symbolic"
                )
            )
            row.connect("activated", callback)
            group.add(row)
        page.add(group)

    def _allowed(self):
        if getattr(self.controller, "_closed", False):
            return False
        if self.controller.library_mode == LIBRARY_MODE_LOCAL:
            return True
        self.controller._toast(
            _("Switch to Local-first mode to export or restore your local library.")
        )
        return False

    def _error(self, error):
        if self.cancellable.is_cancelled():
            return
        self.controller._toast(
            _("Library operation failed: {error}").format(error=error)
        )

    def export(self, *_args):
        if not self._allowed():
            return
        try:
            self.controller._save_user_state()
            contents = library_backup.export_library(self.controller.state_file)
        except (OSError, ValueError) as error:
            self._error(error)
            return
        dialog = Gtk.FileDialog(
            title=_("Export local library"), initial_name="gisheh-library.json"
        )

        def selected(dialog, result):
            try:
                destination = dialog.save_finish(result)
            except GLib.Error as error:
                if not error.matches(
                    Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED
                ):
                    self._error(error)
                return
            destination.replace_contents_async(
                contents, None, False, Gio.FileCreateFlags.PRIVATE, None, saved
            )

        def saved(destination, result):
            try:
                destination.replace_contents_finish(result)
                self.controller._toast(_("Local library exported"))
            except GLib.Error as error:
                self._error(error)

        dialog.save(self.controller.window, self.cancellable, selected)

    def restore(self, *_args):
        if not self._allowed():
            return
        dialog = Gtk.FileDialog(title=_("Restore local library"))

        def selected(dialog, result):
            try:
                source = dialog.open_finish(result)
            except GLib.Error as error:
                if not error.matches(
                    Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED
                ):
                    self._error(error)
                return
            source.load_contents_async(self.cancellable, loaded)

        def loaded(source, result):
            try:
                _success, contents, _etag = source.load_contents_finish(result)
                payload = library_backup.parse_export(contents)
            except (GLib.Error, ValueError, UnicodeError) as error:
                self._error(error)
                return
            self._confirm(payload)

        dialog.open(self.controller.window, self.cancellable, selected)

    def _confirm(self, payload):
        dialog = Adw.AlertDialog(
            heading=_("Replace local library?"),
            body=_(
                "This backup contains {count} titles. It will replace your local library. A backup of your current data will be kept."
            ).format(count=len(payload["localLibrary"])),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("restore", _("Restore"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response != "restore" or not self._allowed():
                return
            try:
                library_backup.import_library(payload, self.controller.state_file)
            except (OSError, ValueError) as error:
                self._error(error)
                return
            controller = self.controller
            application = controller.window.get_application()
            controller.close_background_jobs()
            controller.settings_dialog.force_close()
            controller.window.destroy()
            application._open_main_window(LIBRARY_MODE_LOCAL)

        dialog.connect("response", respond)
        dialog.present(self.controller.window)
