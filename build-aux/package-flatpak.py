#!/usr/bin/env python3
"""Build a standalone beta bundle from an exact, clean Git revision."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.arashe023.Gisheh"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def output(*args):
    return run(*args, capture_output=True, text=True).stdout.strip()


def main():
    if output("git", "status", "--porcelain"):
        raise SystemExit("Commit or stash changes before packaging an exact revision.")
    revision = output("git", "rev-parse", "HEAD")
    version = (ROOT / "VERSION").read_text().strip()
    arch = output("flatpak", "--default-arch")
    builder = shutil.which("flatpak-builder")
    command = [builder] if builder else [
        "flatpak", "run", f"--filesystem={ROOT}", "org.flatpak.Builder"
    ]
    state = ROOT / "flatpak-state"
    state.mkdir(exist_ok=True)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    source_archive = dist / f"Gisheh-{version}-source.tar.gz"
    run("git", "archive", "--format=tar.gz", f"--output={source_archive}", revision)
    with tempfile.TemporaryDirectory(prefix="source-", dir=state) as temporary:
        source = Path(temporary)
        with tarfile.open(source_archive) as archive:
            archive.extractall(source, filter="data")
        manifest = source / "build-aux/flatpak" / f"{APP_ID}.json"
        run(*command, "--force-clean", "--default-branch=beta",
            f"--state-dir={state / 'builder'}", f"--repo={ROOT / 'flatpak-repo'}",
            str(ROOT / "flatpak-build"), str(manifest))
    bundle = dist / f"Gisheh-{version}-{arch}.flatpak"
    run("flatpak", "build-bundle", str(ROOT / "flatpak-repo"), str(bundle),
        APP_ID, "beta", f"--arch={arch}",
        "--runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo")
    checksums = {}
    for path in (source_archive, bundle):
        with path.open("rb") as stream:
            checksums[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    (dist / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items())
    )
    (dist / "build-info.json").write_text(json.dumps({
        "application": APP_ID, "version": version, "architecture": arch,
        "branch": "beta", "source_commit": revision,
        "runtime": "org.gnome.Platform/50", "sha256": checksums,
    }, indent=2) + "\n")
    print(f"Built {bundle}\nSource commit: {revision}")


if __name__ == "__main__":
    main()
