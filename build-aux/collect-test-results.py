"""Publish test results without copying the runner's inherited environment."""

import json
from pathlib import Path
import sys

source, destination = map(Path, sys.argv[1:3])
destination.mkdir(parents=True, exist_ok=True)
log = source / "testlog.json"
if log.exists():
    rows = []
    for line in log.read_text().splitlines():
        result = json.loads(line)
        rows.append(
            {
                key: result[key]
                for key in (
                    "name",
                    "result",
                    "is_fail",
                    "duration",
                    "returncode",
                    "stdout",
                    "stderr",
                )
                if key in result
            }
        )
    (destination / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
else:
    (destination / "results.txt").write_text(
        "Tests did not produce a result log. Inspect the CI build step.\n"
    )
