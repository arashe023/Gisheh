"""Installed and development entry point for CineShelf."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from gi.repository import Gio


def _register_resources() -> Gio.Resource | None:
    configured = os.environ.get("CINESHELF_RESOURCE_FILE")
    resource_file = (
        Path(configured)
        if configured
        else Path(__file__).with_name("cineshelf.gresource")
    )
    if not resource_file.is_file():
        return None
    resource = Gio.Resource.load(str(resource_file))
    resource._register()
    return resource


def main() -> int:
    resource = _register_resources()
    from .application import CineShelfApplication

    application = CineShelfApplication()
    result = application.run(sys.argv)
    if resource is not None:
        resource._unregister()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
