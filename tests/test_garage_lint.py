"""Coverage for tools/garage_lint.py -- the R8 / AC9 drift check.

No Qt import anywhere in this file. Must pass with PySide6 absent.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import garage_lint  # noqa: E402

SAMPLE_CONFIG = """\
#ifndef CONFIG_H
#define CONFIG_H

#define GEAR1_MAX_SPEED        2u
#define MAX_SPRITES  32
#define LOADER_BG_START  ((uint8_t)(HUD_FONT_BASE + HUD_FONT_COUNT))

#endif /* CONFIG_H */
"""

MATCHING_TUNABLES = {
    "_shape": "test fixture",
    "entries": {
        "CONFIG_H": {"class": "marker", "reason": "include guard"},
        "GEAR1_MAX_SPEED": {
            "class": "tunable",
            "category": "Car Physics",
            "min": 1,
            "max": 15,
            "reason": "car feel",
        },
        "MAX_SPRITES": {"class": "structural", "reason": "OAM budget"},
        "LOADER_BG_START": {"class": "derived", "reason": "computed"},
    },
}


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, config_text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "src" / "config.h").write_text(config_text, encoding="utf-8", newline="")
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(
        ["remote", "add", "origin", "https://github.com/MatthieuGagne/gmb-nuke-raider.git"],
        path,
    )
    return path


def write_tunables(path: Path, data: dict) -> Path:
    tunables_path = path / "tunables.json"
    tunables_path.write_text(json.dumps(data), encoding="utf-8")
    return tunables_path


class TestGarageLint(unittest.TestCase):
    def test_no_game_repo_bound_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # Deliberately no sibling "nuke-raider" checkout.

            code = garage_lint.run(garage_root=garage_root)

            self.assertEqual(code, 0)

    def test_clean_schema_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", SAMPLE_CONFIG)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)

            code = garage_lint.run(garage_root=garage_root, schema_path=tunables_path)

            self.assertEqual(code, 0)

    def test_unclassified_define_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            config_with_extra = SAMPLE_CONFIG.replace(
                "#define GEAR1_MAX_SPEED        2u\n",
                "#define GEAR1_MAX_SPEED        2u\n#define NEW_UNCLASSIFIED_DEFINE 5u\n",
            )
            make_game_repo(tmp_path / "nuke-raider", config_with_extra)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)

            code = garage_lint.run(garage_root=garage_root, schema_path=tunables_path)

            self.assertEqual(code, 1)

    def test_stale_schema_entry_fails_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", SAMPLE_CONFIG)
            stale_data = json.loads(json.dumps(MATCHING_TUNABLES))
            stale_data["entries"]["GONE_FROM_HEADER"] = {
                "class": "structural",
                "reason": "used to exist",
            }
            tunables_path = write_tunables(tmp_path, stale_data)

            code = garage_lint.run(garage_root=garage_root, schema_path=tunables_path)

            self.assertEqual(code, 1)

    def test_find_drift_reports_both_directions(self):
        from tools.garage.core import config_io
        from tools.garage.core.schema import Schema

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)
            schema = Schema.load(tunables_path)

            config_text = SAMPLE_CONFIG + "#define ANOTHER_NEW_ONE 1u\n"
            config = config_io.parse(config_text, schema=schema)

            report = garage_lint.find_drift(schema, config)

            self.assertIn("ANOTHER_NEW_ONE", report.unclassified)
            self.assertFalse(report.clean)


if __name__ == "__main__":
    unittest.main()
