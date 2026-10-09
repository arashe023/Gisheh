"""Regression tests for release-version and date consistency."""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "src"
sys.path.insert(0, str(SOURCE_DIR))

from gisheh import __version__
from gisheh.services import image_http, simkl_client, tmdb_client
from gisheh.version import APP_VERSION


class ReleaseMetadataTests(unittest.TestCase):
    def test_version_is_valid_semver_and_shared_by_runtime_clients(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

        self.assertRegex(version, r"^\d+\.\d+\.\d+(?:-rc[1-9]\d*)?$")
        self.assertEqual(__version__, version)
        self.assertEqual(APP_VERSION, version)
        self.assertEqual(simkl_client.APP_VERSION, version)
        self.assertEqual(image_http.USER_AGENT, f"Gisheh/{version}")
        self.assertEqual(simkl_client.USER_AGENT, f"Gisheh/{version}")
        self.assertEqual(tmdb_client.USER_AGENT, f"Gisheh/{version}")

    def test_meson_and_appstream_are_generated_from_release_sources(self) -> None:
        root_meson = (ROOT / "meson.build").read_text(encoding="utf-8")
        metainfo = (ROOT / "data/io.github.arashe023.Gisheh.metainfo.xml.in").read_text(
            encoding="utf-8"
        )

        self.assertIn("version: files('VERSION')", root_meson)
        self.assertIn('version="@PROJECT_VERSION@"', metainfo)
        self.assertIn('date="@RELEASE_DATE@"', metainfo)
        self.assertIn('version="1.3.0" date="2026-08-08"', metainfo)

    def test_changelog_matches_canonical_version_and_release_date(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        release_date = (ROOT / "RELEASE_DATE").read_text(encoding="utf-8").strip()
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        date.fromisoformat(release_date)
        self.assertIn(f"## {version} — {release_date}", changelog)

    def test_current_version_is_not_hardcoded_in_python_sources(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        offenders = []
        for source in (ROOT / "src/gisheh").rglob("*.py"):
            if version in source.read_text(encoding="utf-8"):
                offenders.append(str(source.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_release_files_contain_one_normalized_line(self) -> None:
        for filename, pattern in (
            ("VERSION", r"\d+\.\d+\.\d+(?:-rc[1-9]\d*)?\n"),
            ("RELEASE_DATE", r"\d{4}-\d{2}-\d{2}\n"),
        ):
            contents = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIsNotNone(re.fullmatch(pattern, contents), filename)


if __name__ == "__main__":
    unittest.main()
