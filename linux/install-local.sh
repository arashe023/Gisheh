#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
bin_dir="$HOME/.local/bin"
app_id="io.github.cineshelf.CineShelf"
app_dir="$data_home/$app_id"
desktop_dir="$data_home/applications"
icon_dir="$data_home/icons/hicolor/scalable/apps"
launcher="$bin_dir/cineshelf"

payload_files=(
  "cineshelf.py"
  "tmdb_client.py"
  "simkl_client.py"
  "image_http.py"
  "cineshelf.ui"
  "cineshelf.css"
  "library.json"
)

for payload in "${payload_files[@]}" "$app_id.desktop.in" "$app_id.svg"; do
  if [[ ! -f "$script_dir/$payload" ]]; then
    echo "Required file is missing: $script_dir/$payload" >&2
    exit 1
  fi
done

python3 - <<'PY'
import cairo
import gi
import httpx
import sys

if sys.version_info < (3, 10):
    raise SystemExit("CineShelf requires Python 3.10 or newer.")

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

gtk_version = (
    Gtk.get_major_version(),
    Gtk.get_minor_version(),
    Gtk.get_micro_version(),
)
adw_version = (
    Adw.get_major_version(),
    Adw.get_minor_version(),
    Adw.get_micro_version(),
)

if gtk_version < (4, 12, 0):
    raise SystemExit("CineShelf requires GTK 4.12 or newer.")

if adw_version < (1, 9, 0) or not hasattr(Adw, "ToggleGroup"):
    raise SystemExit("CineShelf requires libadwaita 1.9 or newer.")
PY

install -d "$bin_dir" "$desktop_dir" "$icon_dir"
rm -rf -- "$app_dir"
install -d "$app_dir"
install -m 755 "$script_dir/cineshelf.py" "$app_dir/cineshelf.py"
install -m 644 "$script_dir/tmdb_client.py" "$app_dir/tmdb_client.py"
install -m 644 "$script_dir/simkl_client.py" "$app_dir/simkl_client.py"
install -m 644 "$script_dir/image_http.py" "$app_dir/image_http.py"
install -m 644 "$script_dir/cineshelf.ui" "$app_dir/cineshelf.ui"
install -m 644 "$script_dir/cineshelf.css" "$app_dir/cineshelf.css"
install -m 644 "$script_dir/library.json" "$app_dir/library.json"
install -m 644 "$script_dir/$app_id.svg" "$icon_dir/$app_id.svg"

printf '#!/usr/bin/env sh\nexec python3 "%s/cineshelf.py" "$@"\n' "$app_dir" > "$launcher"
chmod 755 "$launcher"

sed "s|@EXECUTABLE@|$launcher|g" \
  "$script_dir/$app_id.desktop.in" \
  > "$desktop_dir/$app_id.desktop"
chmod 644 "$desktop_dir/$app_id.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "CineShelf was installed for the current user."
echo "Launch it from the application menu or run: $launcher"
