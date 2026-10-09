#!/usr/bin/env python3
"""Build a standalone beta bundle from an exact, clean Git revision."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.arashe023.Gisheh"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def output(*args):
    return run(*args, capture_output=True, text=True).stdout.strip()


def build_with_runtime(source, manifest, state, arch):
    """Assemble pure Python/resources with host tools when the SDK is unavailable."""
    spec = json.loads(manifest.read_text())
    build = ROOT / "flatpak-build"
    if build.exists():
        shutil.rmtree(build)
    run("flatpak", "build-init", str(build), APP_ID,
        spec["runtime"], spec["runtime"], spec["runtime-version"])
    native = source / "_native-build"
    run("meson", "setup", str(native), str(source), "--prefix=/app", "-Dtests=false",
        "-Dpython.purelibdir=lib/python3/site-packages",
        "-Dpython.platlibdir=lib/python3/site-packages")
    run("meson", "compile", "-C", str(native))
    stage = source / "_native-install"
    run("meson", "install", "-C", str(native), "--destdir", str(stage))
    shutil.copytree(stage / "app", build / "files", dirs_exist_ok=True)
    wheels = state / "wheels"
    wheels.mkdir(exist_ok=True)
    dependencies = next(module for module in spec["modules"]
                        if module["name"] == "python3-httpx")
    wheel_paths = []
    for dependency in dependencies["sources"]:
        filename = dependency["url"].rsplit("/", 1)[-1]
        if not filename.endswith("-none-any.whl"):
            raise SystemExit("Runtime assembly only supports pure Python wheels.")
        path = wheels / filename
        if not path.exists():
            cached = next((state / "builder").rglob(filename), None)
            if cached:
                shutil.copyfile(cached, path)
            else:
                urllib.request.urlretrieve(dependency["url"], path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != dependency["sha256"]:
            raise SystemExit(f"Checksum mismatch: {filename}")
        wheel_paths.append(str(path))
    run("python3", "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
        "--target", str(build / "files/lib/python3/site-packages"), *wheel_paths)
    for cache in (build / "files").rglob("__pycache__"):
        shutil.rmtree(cache)
    run("glib-compile-schemas", str(build / "files/share/glib-2.0/schemas"))
    run("flatpak", "build-finish", "--command=gisheh",
        f"--sdk={spec['sdk']}/{arch}/{spec['runtime-version']}",
        *spec["finish-args"], str(build))
    run("flatpak", "build-export", str(ROOT / "flatpak-repo"), str(build), "beta")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true",
                        help="assemble pure Python/resources with host tools and the installed runtime")
    args = parser.parse_args()
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
        if args.native:
            build_with_runtime(source, manifest, state, arch)
        else:
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
        "build_method": "native-pure-python" if args.native else "flatpak-builder",
        "runtime": "org.gnome.Platform/50", "sha256": checksums,
    }, indent=2) + "\n")
    print(f"Built {bundle}\nSource commit: {revision}")


if __name__ == "__main__":
    main()
