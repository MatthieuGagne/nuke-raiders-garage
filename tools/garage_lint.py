#!/usr/bin/env python3
"""Garage's drift check (R8 / AC9).

tools/garage/tunables.json is the single source of truth for which
#defines in the game repository's src/config.h Garage may edit. This
script fails when the two disagree:

  - a #define exists in config.h but tunables.json places it in none of
    the four classes ("unclassified" -- config.h has drifted ahead), or
  - tunables.json names a #define that no longer exists in config.h
    ("stale" -- config.h has since dropped it).

When no game repository is bound (no sibling checkout, or a recorded
binding that no longer resolves), this succeeds and says so -- CI without
a game repository checkout must stay green.

Usage: python tools/garage_lint.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.garage.core import config_io, project
from tools.garage.core.schema import (
    DriftReport,
    Schema,
    SchemaError,
    find_drift as schema_drift,
)


def find_drift(schema: Schema, config: config_io.ConfigFile) -> DriftReport:
    """The comparison itself lives in `tools.garage.core.schema`, so the
    Doctor reports at startup exactly what this check fails the suite over
    (R8). This wrapper keeps the script's own signature, which takes the
    parsed header.
    """
    return schema_drift(schema, config.defines.keys())


def run(garage_root: Path = None, schema_path: Path = None) -> int:
    """Run the drift check. Returns a process exit code (0 = pass).

    `garage_root` and `schema_path` are override hooks for tests; a real
    invocation (`python tools/garage_lint.py`) leaves both as None and
    resolves this repository and its tunables.json normally.
    """
    try:
        binding = project.bind(garage_root)
    except project.BindingError as e:
        print(
            "garage_lint: no game repository is bound "
            f"({e}); skipping the drift check."
        )
        return 0

    try:
        schema = Schema.load(schema_path)
    except SchemaError as e:
        print(f"garage_lint: FAIL -- {e}")
        return 1

    config = config_io.read(binding, schema)
    report = find_drift(schema, config)

    if report.clean:
        print(
            "garage_lint: OK -- every #define in "
            f"'{binding.config_h}' is classified in tunables.json, and "
            "every tunables.json entry still exists in the header."
        )
        return 0

    print("garage_lint: FAIL -- tunables.json has drifted from src/config.h")
    for name in report.unclassified:
        print(
            f"  - '{name}' is defined in src/config.h but is not classified "
            "in tunables.json (add it as tunable/structural/derived/marker)."
        )
    for name in report.stale:
        print(
            f"  - '{name}' is classified in tunables.json but no longer "
            "exists in src/config.h (remove it from tunables.json)."
        )
    return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
