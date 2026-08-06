"""Panel coverage. Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` (tests/garage/ has no __init__.py,
so default discovery never descends into it). Run via `make test-garage`.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import QApplication

from tools.garage.app import GarageWindow
from tools.garage.core import config_io, project
from tools.garage.core.schema import Schema
from tools.garage.panels.tuner import TunerPanel, compute_derived_dependents

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

_app = QApplication.instance() or QApplication([])


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def make_game_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


# -- Tuner panel fixtures ---------------------------------------------------
#
# A small, self-contained config.h + tunables.json, independent of the real
# game repo. Mirrors its shape closely enough to exercise the same rules:
# a plain tunable (GEAR1_MAX_SPEED), a structural entry that must never be
# offered (MAX_SPRITES, echoing AC8), and a tunable/derived dependent pair
# (RACER_HP -> PATROL_HP) matching the real header's relationship.

PANEL_CONFIG_TEXT = """\
#ifndef CONFIG_H
#define CONFIG_H

#define GEAR1_MAX_SPEED        2u
#define PLAYER_ARMOR     5   /* reduces damage */
#define MAX_SPRITES  32
#define RACER_HP              5u   /* bullet hits to destroy a racer */
#define PATROL_HP             RACER_HP   /* 5 bullet hits to destroy */

#endif /* CONFIG_H */
"""

PANEL_TUNABLES = {
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
        "PLAYER_ARMOR": {
            "class": "tunable",
            "category": "Combat",
            "min": 0,
            "max": 15,
            "reason": "damage reduction",
        },
        "MAX_SPRITES": {"class": "structural", "reason": "OAM budget; AC8: never offered"},
        "RACER_HP": {
            "class": "tunable",
            "category": "Enemies",
            "min": 1,
            "max": 20,
            "reason": "bullet hits to destroy a racer; also the source PATROL_HP derives from",
        },
        "PATROL_HP": {"class": "derived", "reason": "Expression: RACER_HP"},
    },
}


def make_game_repo_with_config(path: Path, config_text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "src" / "config.h").write_bytes(config_text.encode("utf-8"))
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_panel_binding(tmp_path: Path):
    """Build a real Binding over a throwaway game repo carrying
    PANEL_CONFIG_TEXT, plus the matching Schema. Never touches
    C:/Code/nuke-raider.
    """
    garage_root = tmp_path / "nuke-raider-garage"
    garage_root.mkdir()
    make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
    binding = project.bind(garage_root)
    schema = Schema.load(write_json(tmp_path / "tunables.json", PANEL_TUNABLES))
    return binding, schema


class TestGarageWindow(unittest.TestCase):
    def test_window_builds_and_header_shows_active_worktree_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)

            self.assertEqual(window.windowTitle(), "Garage")
            self.assertIsNotNone(window.binding)
            self.assertIsNone(window.binding_error)

            header_text = window.header_label.text()
            self.assertIn(str(game_repo), header_text)
            self.assertIn("master", header_text)

            # AC7/AC8 wiring: the Tuner panel replaces the placeholder body.
            # This fixture repo has no src/config.h at all, so the panel
            # must explain that rather than crash the window.
            self.assertIsInstance(window.tuner_panel, TunerPanel)
            self.assertEqual(window.tuner_panel._rows, {})

    def test_window_wires_real_tuner_panel_against_real_schema(self):
        # Uses the real game repo's src/config.h (read-only) copied into a
        # throwaway worktree, exercised against the real tunables.json --
        # never writes to C:/Code/nuke-raider.
        real_config_text = Path("C:/Code/nuke-raider/src/config.h").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo_with_config(tmp_path / "nuke-raider", real_config_text)

            window = GarageWindow(garage_root=garage_root)

            self.assertIsNotNone(window.binding)
            self.assertIsInstance(window.tuner_panel, TunerPanel)
            self.assertIn("GEAR1_MAX_SPEED", window.tuner_panel._rows)
            self.assertNotIn("MAX_SPRITES", window.tuner_panel._rows)
            self.assertNotIn("PATROL_HP", window.tuner_panel._rows)

    def test_window_shows_failure_and_does_not_crash_on_bad_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": str(tmp_path / "does-not-exist"),
                        "worktree_root": str(tmp_path / "worktrees"),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )

            window = GarageWindow(garage_root=garage_root)

            self.assertIsNone(window.binding)
            self.assertIsNotNone(window.binding_error)
            header_text = window.header_label.text()
            self.assertIn("game_repo", header_text)
            self.assertIn("failed", header_text.lower())

            # The Tuner must still open and explain why it is empty rather
            # than crash the window.
            self.assertIsInstance(window.tuner_panel, TunerPanel)
            self.assertEqual(window.tuner_panel._rows, {})
            explanation = window.tuner_panel.explanation_text()
            self.assertIn("game_repo", explanation)


class TestComputeDerivedDependents(unittest.TestCase):
    def test_racer_hp_dependent_found_from_header_text_not_a_hardcoded_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            config = config_io.read(binding, schema)

            dependents = compute_derived_dependents(schema, config)

            self.assertEqual(dependents.get("RACER_HP"), ["PATROL_HP"])
            # A tunable with no derived reader has no entry (or an empty list).
            self.assertFalse(dependents.get("PLAYER_ARMOR"))

    def test_real_config_racer_hp_drives_patrol_hp(self):
        # Same check against the real header/schema (read-only).
        real_config_text = Path("C:/Code/nuke-raider/src/config.h").read_text(encoding="utf-8")
        schema = Schema.load()
        config = config_io.parse(real_config_text, schema=schema)

        dependents = compute_derived_dependents(schema, config)

        self.assertIn("PATROL_HP", dependents.get("RACER_HP", []))


class TestTunerPanel(unittest.TestCase):
    def test_panel_lists_only_tunables_grouped_by_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)

            self.assertEqual(
                set(panel._rows.keys()), {"GEAR1_MAX_SPEED", "PLAYER_ARMOR", "RACER_HP"}
            )

    def test_ac8_max_sprites_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)

            self.assertNotIn("MAX_SPRITES", panel._rows)
            self.assertNotIn("PATROL_HP", panel._rows)
            self.assertNotIn("CONFIG_H", panel._rows)

    def test_editor_clamps_at_both_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            spin = panel._rows["GEAR1_MAX_SPEED"].spin

            spin.setValue(999)
            self.assertEqual(spin.value(), 15)

            spin.setValue(-50)
            self.assertEqual(spin.value(), 1)

    def test_editor_range_is_visible_without_trial_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            self.assertEqual(row.spin.minimum(), 1)
            self.assertEqual(row.spin.maximum(), 15)
            self.assertIn("1", row.range_label.text())
            self.assertIn("15", row.range_label.text())

    def test_reason_reachable_as_tooltip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["RACER_HP"]

            self.assertIn("PATROL_HP", row.spin.toolTip() + row.name_label.toolTip())

    def test_changed_row_marked_pending_and_count_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            self.assertEqual(panel.pending_count(), 0)
            self.assertFalse(panel._rows["GEAR1_MAX_SPEED"].is_dirty())

            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)

            self.assertTrue(panel._rows["GEAR1_MAX_SPEED"].is_dirty())
            self.assertEqual(panel.pending_count(), 1)
            self.assertIn("1", panel.status_text())

            # Setting it back to the original value clears the pending mark.
            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(2)
            self.assertFalse(panel._rows["GEAR1_MAX_SPEED"].is_dirty())
            self.assertEqual(panel.pending_count(), 0)

    def test_racer_hp_row_shows_its_derived_dependent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["RACER_HP"]

            self.assertIn("PATROL_HP", row.dependents_label.text())
            # A tunable with no derived reader shows no such note.
            self.assertEqual(panel._rows["PLAYER_ARMOR"].dependents_label.text(), "")

    def test_save_round_trips_a_value_into_a_temp_config_and_reports_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            config_path = binding.config_h
            self.assertNotEqual(config_path, Path("C:/Code/nuke-raider/src/config.h"))

            panel = TunerPanel(binding, schema=schema)
            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)
            panel._rows["PLAYER_ARMOR"].spin.setValue(3)

            result = panel.save()

            self.assertIn("2", result)
            new_text = config_path.read_text(encoding="utf-8")
            self.assertIn("#define GEAR1_MAX_SPEED        9u", new_text)
            self.assertIn("#define PLAYER_ARMOR     3   /* reduces damage */", new_text)
            # Untouched lines survive byte-for-byte (R10/AC7).
            self.assertIn("#define RACER_HP              5u   /* bullet hits to destroy a racer */", new_text)
            self.assertIn("#define PATROL_HP             RACER_HP   /* 5 bullet hits to destroy */", new_text)

            self.assertEqual(panel.pending_count(), 0)
            self.assertIn("2", panel.status_text())

    def test_save_with_no_changes_reports_nothing_to_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            result = panel.save()

            self.assertIn("0", result)

    def test_binding_error_shows_explanation_without_crashing(self):
        error = project.BindingError("game_repo", "No sibling 'nuke-raider' directory found.")

        panel = TunerPanel(None, binding_error=error)

        self.assertEqual(panel._rows, {})
        self.assertIn("game_repo", panel.explanation_text())

    def test_missing_config_h_shows_explanation_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")  # no src/config.h at all

            binding = project.bind(garage_root)
            panel = TunerPanel(binding)

            self.assertEqual(panel._rows, {})
            self.assertTrue(panel.explanation_text())


# -- AC10/R9: HEAD values and revert -----------------------------------------


class TestTunerPanelRevert(unittest.TestCase):
    def test_row_differing_from_head_before_launch_shows_head_value(self):
        # Case 1: the file was hand-edited (or a previous session saved) --
        # this must show up on launch, not only after an in-session edit.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            binding.config_h.write_text(
                PANEL_CONFIG_TEXT.replace(
                    "#define GEAR1_MAX_SPEED        2u",
                    "#define GEAR1_MAX_SPEED        9u",
                ),
                encoding="utf-8",
            )

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            self.assertEqual(row.spin.value(), 9)  # current (unsaved) value
            self.assertEqual(row.head_value, 2)  # committed value
            self.assertTrue(row.differs_from_head())
            self.assertIn("2", row.head_label.text())
            self.assertFalse(row.head_label.isHidden())
            self.assertFalse(row.revert_button.isHidden())
            # Never touched this session -- "changed" means "differs from
            # HEAD", not "touched in this session", so this is NOT pending.
            self.assertFalse(row.is_dirty())

    def test_row_matching_head_hides_head_value_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            self.assertFalse(row.differs_from_head())
            self.assertTrue(row.head_label.isHidden())
            self.assertTrue(row.revert_button.isHidden())

    def test_editing_then_editing_back_to_head_value_hides_head_display_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            row.spin.setValue(9)
            self.assertTrue(row.differs_from_head())
            self.assertFalse(row.head_label.isHidden())

            row.spin.setValue(2)
            self.assertFalse(row.differs_from_head())
            self.assertTrue(row.head_label.isHidden())

    def test_per_row_revert_of_unsaved_edit_simply_clears_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            row.spin.setValue(9)
            self.assertTrue(row.is_dirty())

            panel.revert_row("GEAR1_MAX_SPEED")

            self.assertEqual(row.spin.value(), 2)
            self.assertFalse(row.is_dirty())
            self.assertEqual(panel.pending_count(), 0)
            # Revert never saves -- the file on disk is untouched.
            self.assertEqual(
                binding.config_h.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
            )

    def test_revert_of_value_that_differed_before_launch_marks_pending_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            hand_edited_text = PANEL_CONFIG_TEXT.replace(
                "#define GEAR1_MAX_SPEED        2u",
                "#define GEAR1_MAX_SPEED        9u",
            )
            binding.config_h.write_text(hand_edited_text, encoding="utf-8")

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            self.assertFalse(row.is_dirty())  # matches on-disk file untouched this session

            panel.revert_row("GEAR1_MAX_SPEED")

            self.assertEqual(row.spin.value(), 2)
            self.assertTrue(row.is_dirty())  # now differs from the on-disk file: pending
            self.assertEqual(panel.pending_count(), 1)

            # Still not written -- only Save writes.
            self.assertEqual(
                binding.config_h.read_text(encoding="utf-8"), hand_edited_text
            )

            result = panel.save()

            self.assertIn("1", result)
            saved_text = binding.config_h.read_text(encoding="utf-8")
            self.assertIn("#define GEAR1_MAX_SPEED        2u", saved_text)

    def test_revert_all_restores_every_differing_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)

            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)
            panel._rows["PLAYER_ARMOR"].spin.setValue(3)
            self.assertEqual(panel.pending_count(), 2)

            panel.revert_all()

            self.assertEqual(panel._rows["GEAR1_MAX_SPEED"].spin.value(), 2)
            self.assertEqual(panel._rows["PLAYER_ARMOR"].spin.value(), 5)
            self.assertEqual(panel._rows["RACER_HP"].spin.value(), 5)
            self.assertEqual(panel.pending_count(), 0)
            self.assertEqual(
                binding.config_h.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
            )

    def test_revert_all_button_wired_to_revert_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)

            panel._revert_all_button.click()

            self.assertEqual(panel._rows["GEAR1_MAX_SPEED"].spin.value(), 2)

    def test_per_row_revert_button_wired_to_revert_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)

            row.revert_button.click()

            self.assertEqual(row.spin.value(), 2)

    def test_head_values_read_once_per_refresh_not_once_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)

            with mock.patch(
                "tools.garage.panels.tuner.config_io.read_config_at_head",
                wraps=config_io.read_config_at_head,
            ) as spy:
                panel = TunerPanel(binding, schema=schema)

            self.assertGreaterEqual(len(panel._rows), 2)
            self.assertEqual(spy.call_count, 1)

    def test_no_head_available_does_not_crash_and_explains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = tmp_path / "nuke-raider"
            (game_repo / "src").mkdir(parents=True)
            (game_repo / "src" / "config.h").write_text(PANEL_CONFIG_TEXT, encoding="utf-8")
            _run_git(["init", "-b", "master"], game_repo)
            _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], game_repo)
            # Deliberately no commit -- HEAD does not exist yet.

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )
            binding = project.bind(garage_root)
            schema = Schema.load(write_json(tmp_path / "tunables.json", PANEL_TUNABLES))

            panel = TunerPanel(binding, schema=schema)

            # A missing HEAD is not fatal -- rows still build and are
            # still editable/saveable.
            self.assertIn("GEAR1_MAX_SPEED", panel._rows)
            row = panel._rows["GEAR1_MAX_SPEED"]
            self.assertIsNone(row.head_value)
            self.assertFalse(row.differs_from_head())
            self.assertTrue(row.head_label.isHidden())
            self.assertTrue(row.revert_button.isHidden())

            self.assertTrue(panel.head_status_text())
            self.assertIn("commit", panel.head_status_text().lower())

            # Revert is a safe no-op when there is no HEAD value to revert to.
            panel.revert_row("GEAR1_MAX_SPEED")
            panel.revert_all()
            self.assertEqual(row.spin.value(), 2)

    def test_config_h_missing_at_head_does_not_crash_and_explains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")  # commit has no src/config.h
            (game_repo / "src").mkdir(parents=True)
            (game_repo / "src" / "config.h").write_text(PANEL_CONFIG_TEXT, encoding="utf-8")
            # Deliberately left uncommitted.

            binding = project.bind(garage_root)
            schema = Schema.load(write_json(tmp_path / "tunables.json", PANEL_TUNABLES))

            panel = TunerPanel(binding, schema=schema)

            self.assertIn("GEAR1_MAX_SPEED", panel._rows)
            row = panel._rows["GEAR1_MAX_SPEED"]
            self.assertIsNone(row.head_value)
            self.assertTrue(panel.head_status_text())
            self.assertIn("config.h", panel.head_status_text().lower())


if __name__ == "__main__":
    unittest.main()
