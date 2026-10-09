"""Startup recovery UI: invalid state never becomes an empty profile implicitly."""

from gettext import gettext as _

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .state_store import backup_file, inspect_state, recover_state, user_state_file


def present_recovery(application, error):
    window = Adw.ApplicationWindow(application=application, title="Gisheh")
    window.set_default_size(600, 420)
    page = Adw.StatusPage(
        title=_("Your library needs attention"),
        description=_(
            "Your saved data has not been changed. You can retry, restore a backup, or start again."
        )
        + "\n\n"
        + str(error),
        icon_name="dialog-warning-symbolic",
    )
    actions = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER
    )
    page.set_child(actions)
    window.set_content(page)

    def reopen():
        window.destroy()
        application.do_activate()

    retry = Gtk.Button(label=_("Retry"))
    retry.connect("clicked", lambda _button: reopen())
    actions.append(retry)

    def recover(use_backup):
        dialog = Adw.AlertDialog(
            heading=_("Restore backup?") if use_backup else _("Start a new library?"),
            body=_(
                "A separate copy of the current file will be kept before replacing it."
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("replace", _("Continue"))
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def respond(_dialog, response):
            if response != "replace":
                return
            try:
                recover_state(use_backup=use_backup)
            except OSError as failure:
                page.set_description(str(failure))
                return
            reopen()

        dialog.connect("response", respond)
        dialog.present(window)

    restore = Gtk.Button(label=_("Restore backup"))
    restore.set_sensitive(
        inspect_state(backup_file(user_state_file())).status == "healthy"
    )
    restore.connect("clicked", lambda _button: recover(True))
    actions.append(restore)
    fresh = Gtk.Button(label=_("Start again"))
    fresh.connect("clicked", lambda _button: recover(False))
    actions.append(fresh)
    window.present()
