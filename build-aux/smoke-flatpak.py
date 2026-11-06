#!/usr/bin/env python3
"""Install and smoke-test a bundle in a disposable user Flatpak installation."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.arashe023.Gisheh"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="gisheh-flatpak-smoke-") as temporary:
        environment = os.environ.copy()
        environment["FLATPAK_USER_DIR"] = str(Path(temporary) / "installation")

        def run(*command):
            subprocess.run(
                command, env=environment, cwd=temporary, check=True, timeout=180
            )

        # Resolve dependencies from already installed system runtimes. Do not
        # install SDKs/runtimes or touch the user's normal Flatpak installation.
        run(
            "flatpak",
            "install",
            "--user",
            "--noninteractive",
            "--no-deps",
            "--no-related",
            str(bundle),
        )
        base = [
            "flatpak",
            "run",
            "--user",
            "--branch=beta",
            "--unshare=network",
            "--nosocket=wayland",
            "--socket=x11",
            "--no-a11y-bus",
            "--no-documents-portal",
            f"--filesystem={ROOT / 'tests'}:ro",
            "--env=GDK_BACKEND=x11",
            "--env=GSK_RENDERER=cairo",
            "--command=python3",
            APP_ID,
            str(ROOT / "tests/installed_smoke.py"),
            "/app",
        ]
        for language in ("en", "fa"):
            print(f"Flatpak installed smoke: {language}", flush=True)
            run(
                "xvfb-run",
                "-a",
                "dbus-run-session",
                "--",
                *base[: base.index(APP_ID)],
                f"--env=LANGUAGE={language}",
                "--env=LANG=C.UTF-8",
                *base[base.index(APP_ID) :],
            )
        print("Isolated Flatpak installation and offline startup: OK")


if __name__ == "__main__":
    main()
