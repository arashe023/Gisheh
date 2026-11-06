#!/usr/bin/env python3
"""Check release metadata and optionally verify exact-commit release artifacts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.arashe023.Gisheh"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_metadata(root, tag=None):
    version_text = (root / "VERSION").read_text(encoding="utf-8")
    require(
        re.fullmatch(r"\d+\.\d+\.\d+(?:-rc[1-9]\d*)?\n", version_text),
        "VERSION must contain one semantic version and a newline",
    )
    version = version_text.strip()
    date_text = (root / "RELEASE_DATE").read_text(encoding="utf-8")
    require(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}\n", date_text),
        "RELEASE_DATE must contain one ISO date and a newline",
    )
    released = date.fromisoformat(date_text.strip())
    require(released <= date.today(), "RELEASE_DATE is in the future")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    require(
        f"## {version} — {released}" in changelog,
        "CHANGELOG.md does not match VERSION and RELEASE_DATE",
    )
    metadata = ET.parse(root / "data" / f"{APP_ID}.metainfo.xml.in").getroot()
    require(metadata.findtext("id") == APP_ID, "AppStream application ID mismatch")
    release = metadata.find("releases/release")
    require(release is not None, "AppStream has no release")
    require(
        release.get("version") == "@PROJECT_VERSION@"
        and release.get("date") == "@RELEASE_DATE@",
        "AppStream release must use the canonical version and date",
    )
    expected_type = "development" if "-rc" in version else "stable"
    require(
        release.get("type") == expected_type,
        f"AppStream release type must be {expected_type}",
    )
    manifest = json.loads((root / "build-aux/flatpak" / f"{APP_ID}.json").read_text())
    require(manifest["app-id"] == APP_ID, "Flatpak application ID mismatch")
    require(manifest["command"] == "gisheh", "Flatpak launcher mismatch")
    if tag:
        require(tag == f"v{version}", f"Release tag must be v{version}")
    return version, manifest


def archive_contents(archive):
    contents = {}
    for member in archive.getmembers():
        path = Path(member.name)
        require(
            not path.is_absolute() and ".." not in path.parts,
            f"Unsafe source archive entry: {member.name}",
        )
        if member.isdir():
            continue
        require(member.name not in contents, f"Duplicate archive entry: {member.name}")
        if member.issym():
            contents[member.name] = ("symlink", member.linkname, member.mode)
        else:
            require(member.isfile(), f"Unsupported source entry: {member.name}")
            with archive.extractfile(member) as stream:
                contents[member.name] = (
                    "file",
                    hashlib.file_digest(stream, "sha256").hexdigest(),
                    member.mode,
                )
    return contents


def check_public_urls(root):
    metadata = ET.parse(root / "data" / f"{APP_ID}.metainfo.xml.in").getroot()
    images = {
        node.text.strip() for node in metadata.findall("screenshots/screenshot/image")
    }
    urls = sorted(images | {node.text.strip() for node in metadata.findall("url")})
    require(urls, "AppStream has no public URLs")

    def check(url):
        try:
            require(url.startswith("https://"), f"Public URL must use HTTPS: {url}")
            request = urllib.request.Request(
                url, headers={"User-Agent": "Gisheh-release-check"}
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                require(response.status == 200, f"HTTP {response.status}: {url}")
                if url in images:
                    require(
                        response.headers.get("Content-Type", "").startswith("image/"),
                        f"Screenshot URL does not serve an image: {url}",
                    )
            return None
        except urllib.error.HTTPError as error:
            return f"HTTP {error.code}: {url}"
        except (ValueError, OSError) as error:
            return f"{type(error).__name__}: {url}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        errors = [result for result in pool.map(check, urls) if result]
    require(not errors, "Public URL checks failed:\n" + "\n".join(errors))
    return len(urls)


def check_artifacts(root, directory, version, manifest):
    info = json.loads((directory / "build-info.json").read_text())
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    require(info["application"] == APP_ID, "Artifact application ID mismatch")
    require(info["version"] == version, "Artifact version mismatch")
    require(
        info["source_commit"] == revision, "Artifacts were built from another commit"
    )
    require(info["branch"] == "beta", "Expected the standalone beta branch")
    require(
        info["runtime"] == f"{manifest['runtime']}/{manifest['runtime-version']}",
        "Artifact runtime mismatch",
    )
    require(
        info["build_method"] in ("flatpak-builder", "native-pure-python"),
        "Unknown artifact build method",
    )
    architecture = info["architecture"]
    require(architecture in ("x86_64", "aarch64"), "Unsupported artifact architecture")
    source_name = f"Gisheh-{version}-source.tar.gz"
    bundle_name = f"Gisheh-{version}-{architecture}.flatpak"
    require(
        set(info["sha256"]) == {source_name, bundle_name},
        "build-info.json must identify exactly the source and bundle",
    )
    checksums = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([^/\\]+)", line)
        require(match is not None, "Invalid SHA256SUMS entry")
        digest, name = match.groups()
        require(name not in checksums, f"Duplicate checksum: {name}")
        checksums[name] = digest
    require(checksums == info["sha256"], "SHA256SUMS and build-info.json disagree")
    for name, expected in checksums.items():
        with (directory / name).open("rb") as stream:
            require(
                hashlib.file_digest(stream, "sha256").hexdigest() == expected,
                f"Checksum mismatch: {name}",
            )
    # Compare file contents, executable modes and symlinks with a fresh Git archive.
    # A checksum alone cannot prove the archive contains the claimed source commit.
    with tempfile.TemporaryDirectory(prefix="gisheh-source-check-") as temporary:
        expected = Path(temporary) / "expected.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", f"--output={expected}", revision],
            cwd=root,
            check=True,
        )
        with tarfile.open(expected) as archive:
            expected_files = archive_contents(archive)
        with tarfile.open(directory / source_name) as archive:
            require(
                archive_contents(archive) == expected_files,
                "Source archive differs from the claimed Git revision",
            )
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="require a tag exactly matching v<VERSION>")
    parser.add_argument(
        "--artifacts", type=Path, help="verify a packaged artifact directory"
    )
    parser.add_argument(
        "--public-urls",
        action="store_true",
        help="check that AppStream links and screenshots are public HTTPS URLs",
    )
    args = parser.parse_args()
    try:
        version, manifest = check_metadata(ROOT, args.tag)
        print(f"Release metadata: OK ({version})")
        if args.artifacts:
            revision = check_artifacts(ROOT, args.artifacts, version, manifest)
            print(f"Artifact checksums and archived Git source: OK ({revision})")
            print(
                "This verifies archive provenance; run the Flatpak smoke test separately."
            )
        if args.public_urls:
            count = check_public_urls(ROOT)
            print(f"Public AppStream URLs: OK ({count})")
    except (
        ValueError,
        OSError,
        KeyError,
        ET.ParseError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(1, f"Release check failed: {error}\n")


if __name__ == "__main__":
    main()
