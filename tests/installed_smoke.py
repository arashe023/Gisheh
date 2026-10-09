"""Smoke-test the installed package without source paths or network access."""

from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile


def main():
    prefix = Path(sys.argv[1]).resolve()
    screenshot_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    fixture = Path(__file__).parent / "fixtures/library.json"
    packages = list(prefix.glob("lib*/python*/site-packages"))
    if not packages:
        raise RuntimeError("Installed Python package was not found")
    sys.path.insert(0, str(packages[0]))
    with tempfile.TemporaryDirectory(prefix="gisheh-installed-") as temporary:
        os.chdir(temporary)
        for name in ("STATE", "CONFIG", "CACHE", "DATA"):
            os.environ[f"XDG_{name}_HOME"] = str(Path(temporary) / name.lower())
        os.environ["GISHEH_STATE_FILE"] = str(Path(temporary) / "state.json")
        os.environ["GSETTINGS_SCHEMA_DIR"] = str(prefix / "share/glib-2.0/schemas")
        os.environ["GSETTINGS_BACKEND"] = "memory"
        os.environ["GIO_USE_VFS"] = "local"
        os.environ["GTK_A11Y"] = "none"
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk

        Gtk.init()
        Adw.init()
        if os.environ.get("ADW_DEBUG_HIGH_CONTRAST") == "1":
            assert Adw.StyleManager.get_default().get_high_contrast()
            print("High contrast is active")
        from gisheh import main as entry, state_store
        from gisheh.services import tmdb_client, simkl_client

        # Only this isolated smoke process is offline. No installed files change.
        tmdb_client.read_token = lambda: None
        simkl_client.read_token = lambda: None
        entry._configure_i18n()
        entry._configure_text_direction()
        resource = entry._register_resources()
        assert resource is not None
        assert Path(entry._locale_dir()).is_relative_to(prefix)
        from gisheh.application import GishehApplication

        app = GishehApplication()
        assert app.register(None)
        assert Gtk.Window.get_default_icon_name() == "io.github.arashe023.Gisheh"
        app.activate()
        assert app.welcome_window is not None
        app.welcome_window.destroy()
        app.welcome_window = None
        state_store.save_library_mode("local")
        if screenshot_dir:
            from gisheh.models import load_catalog, title_record_to_mapping

            records, _, _ = load_catalog(sample_data_path=fixture)
            records = records[:6]
            state = state_store.read_state()
            state["localLibrary"] = [
                title_record_to_mapping(record) for record in records
            ]
            state["localProfile"] = {
                "bookmarks": [r.id for r in records if r.status == "Watchlist"],
                "completed": [r.id for r in records if r.status == "Watched"],
                "ratings": {r.id: r.user_rating for r in records if r.user_rating},
            }
            state_store.write_state(state)
        app.activate()
        assert app.controller is not None
        controller = app.controller
        controller.window.set_default_size(1100, 700)
        errors = []
        loop = GLib.MainLoop()

        def check():
            try:
                assert controller.window.get_mapped()
                controller._save_user_state()
                assert state_store.selected_library_mode() == "local"
                if screenshot_dir:
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    paintable = Gtk.WidgetPaintable.new(controller.window)
                    snapshot = Gtk.Snapshot()
                    paintable.snapshot(
                        snapshot,
                        controller.window.get_width(),
                        controller.window.get_height(),
                    )
                    node = snapshot.to_node()
                    assert node is not None
                    texture = controller.window.get_renderer().render_texture(
                        node, None
                    )
                    assert texture.save_to_png(
                        str(screenshot_dir / "local-library.png")
                    )
                assert controller.window.child_focus(Gtk.DirectionType.TAB_FORWARD)
                assert controller.window.get_focus() is not None
            except Exception as error:
                errors.append(error)
            finally:
                controller.close_background_jobs()
                controller.window.destroy()
                loop.quit()
            return GLib.SOURCE_REMOVE

        if os.environ.get("GISHEH_SMOKE_MATRIX"):
            variants = [
                (width, scheme)
                for scheme in (Adw.ColorScheme.FORCE_LIGHT, Adw.ColorScheme.FORCE_DARK)
                for width in (360, 720, 1100, 1366)
            ]
            manager = Adw.StyleManager.get_default()

            def next_variant():
                if not variants:
                    check()
                    return GLib.SOURCE_REMOVE
                width, scheme = variants.pop(0)
                manager.set_color_scheme(scheme)
                controller.window.set_default_size(width, 700)

                def capture():
                    try:
                        actual = controller.window.get_width()
                        if os.environ.get("GISHEH_MEASURE") and width == 360:

                            def measure(widget, depth=0):
                                if not widget.get_visible():
                                    return
                                minimum, natural, _, _ = widget.measure(
                                    Gtk.Orientation.HORIZONTAL, -1
                                )
                                if minimum > 340:
                                    print(
                                        "MEASURE",
                                        depth,
                                        widget.__class__.__name__,
                                        widget.get_name(),
                                        minimum,
                                        natural,
                                    )
                                child = widget.get_first_child()
                                while child is not None:
                                    measure(child, depth + 1)
                                    child = child.get_next_sibling()

                            measure(controller.window)
                        assert width - 20 <= actual <= width and controller.window.get_mapped(), (
                            width,
                            actual,
                        )
                        print(
                            f"UI matrix: requested={width}, actual={actual}, scheme={scheme.value_nick}, direction={controller.window.get_direction().value_nick}"
                        )
                        if screenshot_dir:
                            paintable = Gtk.WidgetPaintable.new(controller.window)
                            snapshot = Gtk.Snapshot()
                            paintable.snapshot(
                                snapshot, actual, controller.window.get_height()
                            )
                            node = snapshot.to_node()
                            assert node is not None
                            assert controller.window.get_renderer().render_texture(
                                node, None
                            ).save_to_png(
                                str(screenshot_dir / f"{width}-{scheme.value_nick}.png")
                            )
                    except Exception as error:
                        errors.append(error)
                    GLib.timeout_add(150, next_variant)
                    return GLib.SOURCE_REMOVE

                if screenshot_dir:
                    screenshot_dir.mkdir(parents=True, exist_ok=True)

                # The first allocation may collapse a sidebar/header and lower
                # the minimum. Request the target again after that transition.
                def settle():
                    controller.window.set_default_size(width + 1, 700)
                    controller.window.set_default_size(width, 700)
                    GLib.timeout_add(350, capture)
                    return GLib.SOURCE_REMOVE

                GLib.timeout_add(350, settle)
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(800, next_variant)
        else:
            GLib.timeout_add(800, check)
        loop.run()
        resource._unregister()
        if errors:
            raise errors[0]
        print("Installed startup, onboarding, resources, local state and window: OK")


if __name__ == "__main__":
    main()
