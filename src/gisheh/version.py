"""Canonical application version for installed and source-tree runs."""

from __future__ import annotations

from pathlib import Path

try:
    from ._build_config import APP_VERSION
except ImportError:
    # Meson generates _build_config.py for installed builds. Tests and direct
    # source-tree runs intentionally read the same canonical VERSION file.
    APP_VERSION = (
        Path(__file__).resolve().parents[2] / "VERSION"
    ).read_text(encoding="utf-8").strip()

__version__ = APP_VERSION
