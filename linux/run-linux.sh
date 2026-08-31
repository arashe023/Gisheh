#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

for payload in cineshelf.py cineshelf.ui cineshelf.css library.json; do
  if [[ ! -f "$script_dir/$payload" ]]; then
    echo "Required file is missing: $script_dir/$payload" >&2
    exit 1
  fi
done

exec python3 "$script_dir/cineshelf.py" "$@"
