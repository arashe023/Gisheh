#!/usr/bin/env python3
"""Create an executable launcher that Meson and GNOME Builder can discover."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
