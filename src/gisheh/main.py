"""Installed and development entry point for Gisheh."""

from __future__ import annotations

import gettext
import locale
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, Gtk

GETTEXT_DOMAIN = "gisheh"
RTL_LANGUAGES = frozenset({"ar", "fa", "he", "ur"})


def _locale_dir() -> Path:
    """Return the installed catalog directory, with a source-tree fallback."""
    configured = os.environ.get("GISHEH_LOCALE_DIR", "").strip()
    if configured:
        return Path(configured)
    try:
        from ._build_config import LOCALE_DIR

        return Path(LOCALE_DIR)
    except ImportError:
        return Path(__file__).resolve().parents[2] / "build" / "po"


def _configure_i18n() -> None:
    """Bind Python and GtkBuilder translations before importing application UI."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    locale_dir = str(_locale_dir())
    gettext.bindtextdomain(GETTEXT_DOMAIN, locale_dir)
    gettext.textdomain(GETTEXT_DOMAIN)
    bindtextdomain = getattr(locale, "bindtextdomain", None)
    if bindtextdomain is not None:
        bindtextdomain(GETTEXT_DOMAIN, locale_dir)
    textdomain = getattr(locale, "textdomain", None)
    if textdomain is not None:
        textdomain(GETTEXT_DOMAIN)


def _application_text_direction() -> Gtk.TextDirection:
    """Return the direction matching the effective application language."""
    candidates = (
        os.environ.get("LANGUAGE", "").split(":", 1)[0],
        os.environ.get("LC_ALL", ""),
        os.environ.get("LC_MESSAGES", ""),
        os.environ.get("LANG", ""),
    )
    language = next(
        (
            value
            for value in candidates
            if value.strip() and value.strip().casefold() != "system"
        ),
        "en",
    )
    language_code = (
        language.strip().split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    ).split("-", 1)[0].casefold()
    return (
        Gtk.TextDirection.RTL
        if language_code in RTL_LANGUAGES
        else Gtk.TextDirection.LTR
    )


def _configure_text_direction() -> None:
    """Set the inherited GTK direction before any application widget is built."""
    Gtk.Widget.set_default_direction(_application_text_direction())


def _register_resources() -> Gio.Resource | None:
    configured = os.environ.get("GISHEH_RESOURCE_FILE")
    resource_file = (
        Path(configured) if configured else Path(__file__).with_name("gisheh.gresource")
    )
    if not resource_file.is_file():
        return None
    resource = Gio.Resource.load(str(resource_file))
    resource._register()
    return resource


def main() -> int:
    _configure_i18n()
    Gtk.init()
    _configure_text_direction()
    resource = _register_resources()
    from .application import GishehApplication

    application = GishehApplication()
    result = application.run(sys.argv)
    if resource is not None:
        resource._unregister()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
