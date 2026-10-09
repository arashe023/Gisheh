from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gi.repository import Adw, GLib, Gtk
from gisheh.data_actions import LibraryDataActions
from gisheh import library_backup


class DataDialogTests(unittest.TestCase):
    def setUp(self):
        self.controller = SimpleNamespace(
            library_mode="local",
            window=None,
            state_file=None,
            _toast=Mock(),
            _save_user_state=Mock(),
        )
        self.actions = LibraryDataActions(self.controller)

    def test_cancelled_file_chooser_never_imports(self):
        with (
            patch.object(Gtk, "FileDialog") as factory,
            patch.object(library_backup, "import_library") as restore,
        ):
            dialog = factory.return_value
            dialog.open_finish.side_effect = GLib.Error.new_literal(
                Gtk.dialog_error_quark(), "Dismissed", Gtk.DialogError.DISMISSED
            )
            dialog.open.side_effect = lambda parent, cancellable, callback: callback(
                dialog, None
            )
            self.actions.restore()
            restore.assert_not_called()
            self.controller._toast.assert_not_called()

    def test_cancelled_confirmation_never_imports(self):
        with (
            patch.object(Adw, "AlertDialog") as factory,
            patch.object(library_backup, "import_library") as restore,
        ):
            self.actions._confirm({"localLibrary": []})
            factory.return_value.connect.call_args.args[1](None, "cancel")
            restore.assert_not_called()

    def test_simkl_mode_never_opens_import_dialog(self):
        self.controller.library_mode = "simkl"
        with patch.object(Gtk, "FileDialog") as factory:
            self.actions.restore()
            factory.assert_not_called()
            self.controller._toast.assert_called_once()

    def test_export_writes_private_file_with_real_gio(self):
        from pathlib import Path
        import tempfile
        from gi.repository import Gio

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "backup.json"
            loop = GLib.MainLoop()
            self.controller._toast.side_effect = lambda _text: loop.quit()
            timeout = GLib.timeout_add(2000, lambda: (loop.quit(), False)[1])
            with (
                patch.object(Gtk, "FileDialog") as factory,
                patch.object(
                    library_backup, "export_library", return_value=b'{"test": true}'
                ),
            ):
                dialog = factory.return_value
                dialog.save_finish.return_value = Gio.File.new_for_path(
                    str(destination)
                )
                dialog.save.side_effect = lambda parent, cancellable, callback: (
                    callback(dialog, None)
                )
                self.actions.export()
                loop.run()
            GLib.source_remove(timeout)
            self.assertEqual(destination.read_bytes(), b'{"test": true}')
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                self.controller._toast.call_args.args[0], "Local library exported"
            )
