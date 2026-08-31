#!/usr/bin/env bash
set -euo pipefail

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
app_id="io.github.cineshelf.CineShelf"
app_dir="$data_home/$app_id"
desktop_file="$data_home/applications/$app_id.desktop"
icon_file="$data_home/icons/hicolor/scalable/apps/$app_id.svg"
launcher="$HOME/.local/bin/cineshelf"

rm -f -- "$launcher" "$desktop_file" "$icon_file"
rm -rf -- "$app_dir"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$data_home/applications" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "CineShelf was removed for the current user."
