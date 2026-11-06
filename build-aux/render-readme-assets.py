#!/usr/bin/env python3
"""Render Gisheh's README covers from its existing icon and outlined typography.

Requires the project's Cairo/PyGObject dependencies, PangoCairo, rsvg-convert,
Noto Sans and Vazirmatn. No network requests or application data are used.
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "data/icons/hicolor/scalable/apps/io.github.arashe023.Gisheh.svg"
PALETTES = {
    "light": ("#f6f2f8", "#eee6f3", "#291e31", "#705d7b", "#cab8d4"),
    "dark": ("#201b25", "#2b2233", "#f9f4fc", "#c9b9d3", "#665070"),
}


def text_path(text, x, y, size, color, *, language="en", weight="Regular", right=False):
    surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    context = cairo.Context(surface)
    layout = PangoCairo.create_layout(context)
    font = Pango.FontDescription(
        f"{'Vazirmatn' if language == 'fa' else 'Noto Sans'} {weight}"
    )
    font.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    width, _ = layout.get_pixel_size()
    context.move_to(x - width if right else x, y)
    PangoCairo.layout_path(context, layout)
    commands = []
    for kind, coordinates in context.copy_path():
        operator = {
            cairo.PATH_MOVE_TO: "M",
            cairo.PATH_LINE_TO: "L",
            cairo.PATH_CURVE_TO: "C",
            cairo.PATH_CLOSE_PATH: "Z",
        }[kind]
        commands.append(operator + " ".join(f"{value:.2f}" for value in coordinates))
    return f'<path fill="{color}" d="{" ".join(commands)}"/>'


def cover(language, theme, *, social=False):
    background, stub, foreground, muted, rule = PALETTES[theme]
    height = 800 if social else 600
    offset = 100 if social else 0
    rtl = language == "fa"
    division = 650 if rtl else 950
    title = "گیشه — کتابخانهٔ شخصی تماشا" if rtl else "Gisheh — your personal watchlist"
    description = (
        "کاور گیشه با آیکن بلیت بنفش و نشانک سفید، در قالب یک بلیت سینما."
        if rtl
        else "Gisheh's purple saved-ticket icon on a quiet, perforated cinema-ticket cover."
    )
    # The illustration uses the unchanged paths of the shipped app icon.
    icon = ET.parse(ICON).getroot()
    icon_paths = "".join(
        ET.tostring(node, encoding="unicode").strip()
        for node in icon
        if node.tag.endswith("}path")
    )
    icon_x = 128 if rtl else 1088
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" '
        f'viewBox="0 0 1600 {height}" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="description">{escape(description)}</desc>',
        '<defs><mask id="ticket"><rect width="1600" height="800" fill="white"/>',
        "" if social else f'<circle cx="{division}" cy="0" r="20" fill="black"/>',
        ""
        if social
        else f'<circle cx="{division}" cy="{height}" r="20" fill="black"/>',
        '</mask></defs><g mask="url(#ticket)">',
        f'<rect width="1600" height="{height}" fill="{background}"/>',
        f'<rect x="{0 if rtl else division}" width="{division if rtl else 1600 - division}" '
        f'height="{height}" fill="{stub}"/>',
        f'<path d="M{division} 46V{height - 46}" stroke="{rule}" stroke-width="2" '
        'stroke-dasharray="7 12" stroke-linecap="round"/>',
        f'<g transform="translate(0 {offset})">',
        f'<g transform="translate({icon_x} 108) scale(3)">{icon_paths}</g>',
    ]
    if rtl:
        labels = [
            ("کتابخانهٔ شخصی فیلم و سریال", 1504, 102, 25, muted, "Medium"),
            ("گیشه", 1504, 160, 170, foreground, "Bold"),
            ("برای هر چیزی که تماشا می‌کنی.", 1504, 370, 35, muted, "Regular"),
            ("فیلم  /  سریال  /  انیمه", 1504, 495, 24, muted, "Medium"),
        ]
    else:
        labels = [
            ("A PERSONAL WATCHLIST FOR LINUX", 96, 104, 21, muted, "Medium"),
            ("Gisheh", 88, 148, 168, foreground, "Bold"),
            ("For everything you watch.", 96, 365, 36, muted, "Regular"),
            ("MOVIES  /  SHOWS  /  ANIME", 96, 498, 22, muted, "Medium"),
        ]
    for text, x, y, size, color, weight in labels:
        parts.append(
            text_path(
                text, x, y, size, color, language=language, weight=weight, right=rtl
            )
        )
    line_start, line_end = (778, 1504) if rtl else (96, 822)
    parts.append(f'<path d="M{line_start} 465H{line_end}" stroke="{rule}"/>')
    parts.append("</g></g></svg>")
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/assets")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for language in ("en", "fa"):
        for theme in PALETTES:
            svg = args.output_dir / f"cover-{language}-{theme}.svg"
            svg.write_text(cover(language, theme), encoding="utf-8")
            subprocess.run(
                ["rsvg-convert", str(svg), "-o", str(svg.with_suffix(".png"))],
                check=True,
            )
    social = args.output_dir / "social-preview.svg"
    social.write_text(cover("en", "light", social=True), encoding="utf-8")
    subprocess.run(
        [
            "rsvg-convert",
            "--width=1280",
            "--height=640",
            str(social),
            "-o",
            str(social.with_suffix(".png")),
        ],
        check=True,
    )
    print(
        f"Rendered four theme/language covers and the 1280×640 social preview: {args.output_dir}"
    )


if __name__ == "__main__":
    main()
