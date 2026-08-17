"""Coverage for tools/garage_lint.py -- the R8 / AC9 drift check.

No Qt import anywhere in this file. Must pass with PySide6 absent.
"""
import contextlib
import io
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
from tools.garage.core import config_io, project  # noqa: E402
from tools.garage.core.schema import Schema, find_drift  # noqa: E402

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


def run_lint(**kwargs):
    """`garage_lint.run` with its stdout captured, as `(code, output)`.

    Captured rather than let through, for two reasons. Half the calls
    below drive deliberately drifted fixtures, so a *passing* `make test`
    printed `garage_lint: FAIL -- ...` several times over -- exit codes
    were never affected and the suite was genuinely green, but a passing
    run that prints "FAIL" trains a reader to skim past the word, which is
    the one word this check exists to make them read.

    And the messages are the check's whole product: a drift report nobody
    can act on is no better than a silent failure. Asserting on the text
    turns the noise into coverage of what the report actually says.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = garage_lint.run(**kwargs)
    return code, buffer.getvalue()


class TestTheBoundGameRepositoryIsInStep(unittest.TestCase):
    """AC9's first half: a `#define` added to the game repository's
    `src/config.h` with no classification makes *this repository's* test
    suite fail.

    Every other test in this file drives the check with fixtures, which
    proves the comparison but never looks at the real header — so real
    drift would pass a green suite. This one runs the check exactly as
    `python tools/garage_lint.py` runs it, against whatever this checkout
    is bound to.

    It skips when no game repository is bound. That is the CI case (this
    repository is checked out alone), and R8 asks the drift to fail the
    suite, not the absence of a checkout to fail it.
    """

    def test_the_classification_matches_the_headers_defines(self):
        try:
            binding = project.bind()
        except project.BindingError as exc:
            self.skipTest(f"no game repository bound: {exc}")

        schema = Schema.load()
        config = config_io.read(binding, schema)
        drift = find_drift(schema, config.defines.keys())

        self.assertTrue(
            drift.clean,
            "tools/garage/tunables.json has drifted from "
            f"{binding.config_h}:\n"
            + "".join(
                f"  - '{name}' is in src/config.h and classified nowhere; add "
                f"it as tunable/structural/derived/marker.\n"
                for name in drift.unclassified
            )
            + "".join(
                f"  - '{name}' is classified in tunables.json but is no "
                f"longer in src/config.h; remove it.\n"
                for name in drift.stale
            ),
        )

    def test_the_drift_check_script_agrees_with_it(self):
        # The script is what a developer and CI run by hand; this keeps it
        # from drifting away from the test above.
        code, output = run_lint()
        self.assertEqual(code, 0)
        self.assertIn("garage_lint:", output)


class TestGarageLint(unittest.TestCase):
    def test_no_game_repo_bound_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # Deliberately no sibling "nuke-raider" checkout.

            code, output = run_lint(garage_root=garage_root)

            self.assertEqual(code, 0)
            # It exits 0, so it has to say why it did nothing -- silence
            # here reads as "checked, and clean".
            self.assertIn("no game repository is bound", output)
            self.assertIn("skipping the drift check", output)

    def test_clean_schema_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", SAMPLE_CONFIG)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 0)
            self.assertIn("garage_lint: OK", output)

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

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 1)
            # "names it" is in this test's name and was never asserted:
            # a report that says only "drifted" leaves the reader to
            # diff the header against tunables.json by hand.
            self.assertIn("NEW_UNCLASSIFIED_DEFINE", output)
            self.assertIn("tunable/structural/derived/marker", output)

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

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 1)
            self.assertIn("GONE_FROM_HEADER", output)
            self.assertIn("remove it from tunables.json", output)

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
