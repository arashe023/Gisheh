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
    def test_every_row_fills_the_grid_without_holes(self) -> None:
        for columns in (2, 3, 4, 5):
            for count in range(1, 24):
                plan = cineshelf.build_explore_layout_plan(count, columns, seed=91)
                self.assertEqual(sum(len(row) for row in plan), count)
                for row in plan:
                    self.assertEqual(sum(span for _kind, span in row), columns)

    def test_plan_is_varied_and_stable_for_a_seed(self) -> None:
        first = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        second = cineshelf.build_explore_layout_plan(18, 4, seed=2026)
        self.assertEqual(first, second)
        kinds = {kind for row in first for kind, _span in row}
        self.assertGreaterEqual(len(kinds), 2)


if __name__ == "__main__":
    unittest.main()
