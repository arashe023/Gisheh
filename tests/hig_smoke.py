"""Render installed native dialogs at constrained sizes in an isolated profile.

Usage: hig_smoke.py INSTALL_PREFIX CAPTURE_DIRECTORY
Optional HIG_WIDTH (360 by default), HIG_LARGE_TEXT=1 and ADW_DEBUG_HIGH_CONTRAST=1.
No personal state or live service is read or changed.
"""

from pathlib import Path
import os
import sys
import tempfile


def main():
    prefix = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(next(prefix.glob("lib*/python*/site-packages"))))
    with tempfile.TemporaryDirectory(prefix="gisheh-hig-") as temporary:
        for name in ("STATE", "CACHE", "CONFIG", "DATA"):
            os.environ[f"XDG_{name}_HOME"] = str(Path(temporary) / name.lower())
        os.environ["GISHEH_STATE_FILE"] = str(Path(temporary) / "state.json")
        os.environ["GSETTINGS_BACKEND"] = "memory"
        os.environ["GSETTINGS_SCHEMA_DIR"] = str(prefix / "share/glib-2.0/schemas")
        os.environ["GTK_A11Y"] = "test"
        os.environ["GIO_USE_VFS"] = "local"
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk
        from gisheh import main as entry, state_store
        from gisheh.services import tmdb_client, simkl_client

        entry._configure_i18n()
        Gtk.init()
        Adw.init()
        entry._configure_text_direction()
        resource = entry._register_resources()
        assert resource is not None
        tmdb_client.read_token = lambda: None
        simkl_client.read_token = lambda: None
        simkl_client.read_client_id = lambda: None
        if os.environ.get("HIG_LARGE_TEXT") == "1":
            Gtk.Settings.get_default().set_property("gtk-font-name", "Sans 16")
        if os.environ.get("ADW_DEBUG_HIGH_CONTRAST") == "1":
            assert Adw.StyleManager.get_default().get_high_contrast()
        state_store.save_library_mode("local")
        from gisheh.application import GishehApplication

        app = GishehApplication()
        assert app.register(None)
        app.activate()
        controller = app.controller
        assert controller is not None
        if os.environ.get("HIG_STYLE") == "light":
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        width = int(os.environ.get("HIG_WIDTH", "360"))
        controller.window.set_default_size(width + 10, 650)
        pending = ["library", "preferences", "log", "shortcuts", "menu"]
        if os.environ.get("HIG_PROFILE") == "1":
            pending = [
                "profile-empty",
                "profile-month",
                "profile-year",
                "profile-library",
                "profile-ratings",
            ]
        errors = []
        loop = GLib.MainLoop()

        def capture(name):
            try:
                actual = controller.window.get_width()
                assert width <= actual <= width + 10, (width, actual)
                direction = controller.window.get_direction()
                workspace = controller.workspace
                assert workspace.get_sidebar_position() == Gtk.PackType.START
                if not workspace.get_collapsed():
                    ok, sidebar_bounds = workspace.get_sidebar().compute_bounds(workspace)
                    assert ok
                    ok, content_bounds = workspace.get_content().compute_bounds(workspace)
                    assert ok
                    assert (sidebar_bounds.get_x() > content_bounds.get_x()) == (
                        direction == Gtk.TextDirection.RTL
                    ), "sidebar is on the wrong physical edge"
                dialog = controller.window.get_visible_dialog()
                if dialog:
                    assert dialog.get_direction() == direction
                    assert dialog.get_width() <= actual, (
                        name,
                        "dialog width",
                        dialog.get_width(),
                        actual,
                    )
                    if name in ("preferences", "log"):
                        assert dialog.get_focus() is not None, (
                            name,
                            "no initial focus",
                        )
                if name == "menu":
                    assert Gtk.Widget.get_direction(controller.main_menu_button) == direction, ("menu button", Gtk.Widget.get_direction(controller.main_menu_button), direction)
                    assert controller.main_menu_button.get_popover().get_direction() == direction, ("menu popover", controller.main_menu_button.get_popover().get_direction(), direction)
                    assert controller.main_menu_button.get_popover().get_mapped(), (
                        "main menu was not mapped"
                    )
                paintable = Gtk.WidgetPaintable.new(controller.window)
                snapshot = Gtk.Snapshot()
                paintable.snapshot(snapshot, actual, controller.window.get_height())
                node = snapshot.to_node()
                assert node is not None
                texture = controller.window.get_renderer().render_texture(node, None)
                assert texture.save_to_png(str(output / f"{name}.png"))
                print(
                    f"{name}: {actual}×{controller.window.get_height()}, {controller.window.get_direction().value_nick}"
                )
            except Exception as error:
                errors.append((name, error))
            finally:
                dialog = controller.window.get_visible_dialog()
                if dialog:
                    dialog.close()
                if name == "menu":
                    controller.main_menu_button.popdown()
            GLib.timeout_add(250, advance)
            return GLib.SOURCE_REMOVE

        def advance():
            if not pending:
                controller.close_background_jobs()
                controller.window.destroy()
                loop.quit()
                return GLib.SOURCE_REMOVE
            name = pending.pop(0)
            if name.startswith("profile-"):
                from profile_samples import profile_stats

                controller._on_profile_clicked(None)
                controller.profile_view.set_identity(
                    "Alex Morgan", controller.profile_view.source_label.get_label()
                )
                controller.profile_view.update(
                    profile_stats(empty=name == "profile-empty")
                )
                if name == "profile-year":
                    controller.profile_view.period.set_active_name("year")
                if name in ("profile-library", "profile-ratings"):
                    controller.profile_view._expanders["ratings"].set_expanded(True)
                    adjustment = controller.profile_scroller.get_vadjustment()
                    GLib.timeout_add(
                        150,
                        lambda: (
                            adjustment.set_value(
                                adjustment.get_upper()
                                if name == "profile-ratings"
                                else 460
                            ),
                            False,
                        )[1],
                    )
                else:
                    controller.profile_scroller.get_vadjustment().set_value(0)
            if name == "preferences":
                controller._on_preferences_clicked(None)
            elif name == "log":
                controller.show_application_log()
            elif name == "shortcuts":
                controller._show_shortcuts()
            elif name == "menu":
                controller._show_main_menu()
            GLib.timeout_add(400, capture, name)
            return GLib.SOURCE_REMOVE

        def settle():
            controller.window.set_default_size(width + 11, 650)
            controller.window.set_default_size(width + 10, 650)
            GLib.timeout_add(300, advance)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(400, settle)
        loop.run()
        if errors:
            raise AssertionError(errors)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
