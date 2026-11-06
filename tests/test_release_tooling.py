"""Release gates must reject mismatched or tampered artifacts."""

from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
CHECKS = runpy.run_path(str(ROOT / "build-aux/check-release.py"))
APP_ID = CHECKS["APP_ID"]


class ReleaseToolingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gisheh-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("VERSION", "1.5.0-rc1\n")
        self.write("RELEASE_DATE", "2026-10-09\n")
        self.write("CHANGELOG.md", "## 1.5.0-rc1 — 2026-10-09\n\nRelease notes.\n")
        self.write(
            f"data/{APP_ID}.metainfo.xml.in",
            f"""<component>
<id>{APP_ID}</id><releases><release version="@PROJECT_VERSION@"
date="@RELEASE_DATE@" type="development"/></releases></component>""",
        )
        self.manifest = {
            "app-id": APP_ID,
            "command": "gisheh",
            "runtime": "org.gnome.Platform",
            "runtime-version": "50",
        }
        self.write(f"build-aux/flatpak/{APP_ID}.json", json.dumps(self.manifest))

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def artifacts(self):
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Fixture",
        )
        self.directory = self.root / "dist"
        self.directory.mkdir()
        self.source = self.directory / "Gisheh-1.5.0-rc1-source.tar.gz"
        self.git("archive", "--format=tar.gz", f"--output={self.source}", "HEAD")
        self.bundle = self.directory / "Gisheh-1.5.0-rc1-x86_64.flatpak"
        self.bundle.write_bytes(b"unit-test integrity fixture, not a runnable Flatpak")
        self.info = {
            "application": APP_ID,
            "version": "1.5.0-rc1",
            "branch": "beta",
            "architecture": "x86_64",
            "source_commit": self.git("rev-parse", "HEAD"),
            "runtime": "org.gnome.Platform/50",
            "build_method": "flatpak-builder",
        }
        self.update_checksums()

    def update_checksums(self):
        checksums = {}
        for path in (self.source, self.bundle):
            with path.open("rb") as stream:
                checksums[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        self.info["sha256"] = checksums
        (self.directory / "build-info.json").write_text(json.dumps(self.info))
        (self.directory / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in checksums.items())
        )

    def verify(self):
        return CHECKS["check_artifacts"](
            self.root, self.directory, "1.5.0-rc1", self.manifest
        )

    def test_matching_metadata_and_tag(self):
        version, manifest = CHECKS["check_metadata"](self.root, "v1.5.0-rc1")
        self.assertEqual(version, "1.5.0-rc1")
        self.assertEqual(manifest, self.manifest)

    def test_mismatched_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "tag"):
            CHECKS["check_metadata"](self.root, "v1.5.0")

    def test_future_date_is_rejected(self):
        self.write("RELEASE_DATE", f"{date.today() + timedelta(days=1)}\n")
        with self.assertRaisesRegex(ValueError, "future"):
            CHECKS["check_metadata"](self.root)

    def test_stable_version_requires_stable_appstream(self):
        self.write("VERSION", "1.5.0\n")
        self.write("CHANGELOG.md", "## 1.5.0 — 2026-10-09\n")
        with self.assertRaisesRegex(ValueError, "type must be stable"):
            CHECKS["check_metadata"](self.root)

    def test_matching_artifacts(self):
        self.artifacts()
        self.assertEqual(self.verify(), self.info["source_commit"])

    def test_changed_bundle_is_rejected(self):
        self.artifacts()
        self.bundle.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.verify()

    def test_changed_source_is_rejected_even_with_updated_checksum(self):
        self.artifacts()
        with tarfile.open(self.source, "w:gz") as archive:
            data = b"different source"
            entry = tarfile.TarInfo("VERSION")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        self.update_checksums()
        with self.assertRaisesRegex(ValueError, "Source archive differs"):
            self.verify()

    def test_wrong_source_revision_is_rejected(self):
        self.artifacts()
        self.info["source_commit"] = "0" * 40
        self.update_checksums()
        with self.assertRaisesRegex(ValueError, "another commit"):
            self.verify()

    def test_duplicate_checksum_is_rejected(self):
        self.artifacts()
        checksum_file = self.directory / "SHA256SUMS"
        checksum_file.write_text(checksum_file.read_text() * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate checksum"):
            self.verify()

    def test_source_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryFile() as stream:
            with tarfile.open(fileobj=stream, mode="w") as archive:
                archive.addfile(tarfile.TarInfo("../outside"))
            stream.seek(0)
            with (
                tarfile.open(fileobj=stream) as archive,
                self.assertRaisesRegex(ValueError, "Unsafe source archive"),
            ):
                CHECKS["archive_contents"](archive)

    def test_public_links_and_screenshot_are_checked_without_authentication(self):
        self.write(
            f"data/{APP_ID}.metainfo.xml.in",
            """<component>
<url type="homepage">https://example.invalid/app</url>
<screenshots><screenshot><image>https://example.invalid/screen.png</image>
</screenshot></screenshots></component>""",
        )
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.headers = {"Content-Type": "image/png"}
        with patch("urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(CHECKS["check_public_urls"](self.root), 2)
            self.assertEqual(request.call_count, 2)
            for call in request.call_args_list:
                self.assertNotIn("Authorization", call.args[0].headers)

    def test_private_or_missing_public_link_is_rejected(self):
        self.write(
            f"data/{APP_ID}.metainfo.xml.in",
            """<component>
<url type="homepage">https://example.invalid/private</url></component>""",
        )
        error = HTTPError("https://example.invalid/private", 404, "Not Found", {}, None)
        with (
            patch("urllib.request.urlopen", side_effect=error),
            self.assertRaisesRegex(ValueError, "HTTP 404"),
        ):
            CHECKS["check_public_urls"](self.root)
