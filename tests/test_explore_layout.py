#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


LINUX_DIR = Path(__file__).resolve().parents[1] / "linux"
sys.path.insert(0, str(LINUX_DIR))
SPEC = importlib.util.spec_from_file_location("cineshelf", LINUX_DIR / "cineshelf.py")
assert SPEC and SPEC.loader
cineshelf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cineshelf
SPEC.loader.exec_module(cineshelf)


class ExploreLayoutTests(unittest.TestCase):
    def test_rows_fill_without_using_a_full_width_card(self) -> None:
        for columns in (2, 3, 4, 5):
            for count in range(1, 24):
                plan = cineshelf.build_explore_layout_plan(count, columns, seed=91)
                self.assertEqual(sum(len(row) for row in plan), count)
                for row_index, row in enumerate(plan):
                    used_columns = sum(span for _kind, span in row)
                    self.assertLessEqual(used_columns, columns)
                    if row_index < len(plan) - 1:
                        self.assertEqual(used_columns, columns)
                    for _kind, span in row:
                        self.assertLess(span, columns)
                        self.assertLessEqual(span / columns, 3 / 5)

    def test_plan_is_varied_and_stable_for_a_seed(self) -> None:
        first = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        second = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        self.assertEqual(first, second)
        kinds = {kind for row in first for kind, _span in row}
        self.assertGreaterEqual(len(kinds), 2)


class ProfileFormattingTests(unittest.TestCase):
    def test_runtime_minutes_handles_catalog_durations(self) -> None:
        self.assertEqual(cineshelf.runtime_minutes("2h 04m"), 124)
        self.assertEqual(cineshelf.runtime_minutes("45m"), 45)
        self.assertEqual(cineshelf.runtime_minutes("3 seasons"), 0)

    def test_watch_time_and_dates_are_stable(self) -> None:
        self.assertEqual(cineshelf.format_watch_time(6502), "4d 12h 22m")
        parsed = cineshelf.parse_watched_date("Aug 8, 2026 at 2:49 AM")
        self.assertEqual(parsed.isoformat() if parsed else None, "2026-08-08")


if __name__ == "__main__":
    unittest.main()
