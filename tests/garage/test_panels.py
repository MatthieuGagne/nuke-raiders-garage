"""Panel coverage. Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` (tests/garage/ has no __init__.py,
so default discovery never descends into it). Run via `make test-garage`.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
)

from tools.garage import theme
from tools.garage.app import GarageWindow, format_header, format_header_html
from tools.garage.core import (
    budgets as budgets_core,
    commit as commit_core,
    config_io,
    diff as diff_core,
    doctor as doctor_core,
    emulicious,
    make_runner,
    project,
    worktrees as worktrees_core,
)
from tools.garage.core.schema import Schema
from tools.garage.panels.budgets import BudgetsPanel
from tools.garage.panels.commit import CommitPanel
from tools.garage.panels.compile_bar import CompileBar
from tools.garage.panels.diff_view import DiffPanel
from tools.garage.panels.doctor import DoctorPanel
from tools.garage.panels.tuner import TunerPanel, compute_derived_dependents
from tools.garage.panels.worktrees import WorktreesPanel

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

# The verbatim tool output the core suite parses, imported rather than
# copied: two fixtures that could drift apart would let the panel be tested
# against text `make memory-check` never prints.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_garage_core import (  # noqa: E402
    BANK_REPORT_OUTPUT,
    MEMORY_CHECK_OUTPUT,
    NO_GAME_REPO,
    NO_GAME_REPO_REASON,
    REAL_CONFIG_H_PATH,
    tmp_root,
)

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
    PANEL_CONFIG_TEXT, plus the matching Schema. Never touches the
    bound game repository.
    """
    garage_root = tmp_path / "nuke-raider-garage"
    garage_root.mkdir()
    make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
    binding = project.bind(garage_root)
    schema = Schema.load(write_json(tmp_path / "tunables.json", PANEL_TUNABLES))
    return binding, schema


# A single wide-range tunable (0-999), used only to exercise the
# multi-digit-typing case ("100" typed digit by digit must not write 1,
# then 10, then 100) -- PANEL_TUNABLES' entries all top out at 20.

WIDE_CONFIG_TEXT = """\
#ifndef CONFIG_H
#define CONFIG_H

#define SPEED        5u

#endif /* CONFIG_H */
"""

WIDE_TUNABLES = {
    "_shape": "test fixture",
    "entries": {
        "CONFIG_H": {"class": "marker", "reason": "include guard"},
        "SPEED": {
            "class": "tunable",
            "category": "Misc",
            "min": 0,
            "max": 999,
            "reason": "speed",
        },
    },
}


def make_wide_panel_binding(tmp_path: Path):
    garage_root = tmp_path / "nuke-raider-garage"
    garage_root.mkdir()
    make_game_repo_with_config(tmp_path / "nuke-raider", WIDE_CONFIG_TEXT)
    binding = project.bind(garage_root)
    schema = Schema.load(write_json(tmp_path / "tunables.json", WIDE_TUNABLES))
    return binding, schema


class TestGarageWindow(unittest.TestCase):
    def test_window_builds_and_header_shows_active_worktree_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
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

    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_window_wires_real_tuner_panel_against_real_schema(self):
        # Uses the real game repo's src/config.h (read-only) copied into a
        # throwaway worktree, exercised against the real tunables.json --
        # never writes to the bound game repository.
        real_config_text = REAL_CONFIG_H_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
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
            tmp_path = tmp_root(tmp)
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
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            config = config_io.read(binding, schema)

            dependents = compute_derived_dependents(schema, config)

            self.assertEqual(dependents.get("RACER_HP"), ["PATROL_HP"])
            # A tunable with no derived reader has no entry (or an empty list).
            self.assertFalse(dependents.get("PLAYER_ARMOR"))

    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_real_config_racer_hp_drives_patrol_hp(self):
        # Same check against the real header/schema (read-only).
        real_config_text = REAL_CONFIG_H_PATH.read_text(encoding="utf-8")
        schema = Schema.load()
        config = config_io.parse(real_config_text, schema=schema)

        dependents = compute_derived_dependents(schema, config)

        self.assertIn("PATROL_HP", dependents.get("RACER_HP", []))


class TestTunerPanel(unittest.TestCase):
    def test_panel_lists_only_tunables_grouped_by_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)

            self.assertEqual(
                set(panel._rows.keys()), {"GEAR1_MAX_SPEED", "PLAYER_ARMOR", "RACER_HP"}
            )

    def test_ac8_max_sprites_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)

            self.assertNotIn("MAX_SPRITES", panel._rows)
            self.assertNotIn("PATROL_HP", panel._rows)
            self.assertNotIn("CONFIG_H", panel._rows)

    def test_editor_clamps_at_both_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            spin = panel._rows["GEAR1_MAX_SPEED"].spin

            spin.setValue(999)
            self.assertEqual(spin.value(), 15)

            spin.setValue(-50)
            self.assertEqual(spin.value(), 1)

    def test_editor_range_is_visible_without_trial_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            self.assertEqual(row.spin.minimum(), 1)
            self.assertEqual(row.spin.maximum(), 15)
            self.assertIn("1", row.range_label.text())
            self.assertIn("15", row.range_label.text())

    def test_reason_reachable_as_tooltip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["RACER_HP"]

            self.assertIn("PATROL_HP", row.spin.toolTip() + row.name_label.toolTip())

    def test_racer_hp_row_shows_its_derived_dependent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["RACER_HP"]

            self.assertIn("PATROL_HP", row.dependents_label.text())
            # A tunable with no derived reader shows no such note.
            self.assertEqual(panel._rows["PLAYER_ARMOR"].dependents_label.text(), "")

    def test_editing_finished_writes_the_value_immediately(self):
        # There is no Save button anymore: committing an edit (the
        # spinbox's editingFinished signal -- Enter or focus-out) writes
        # config.h at once.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            config_path = binding.config_h
            self.assertNotEqual(config_path, REAL_CONFIG_H_PATH)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)
            # Nothing written yet -- only editingFinished writes.
            self.assertEqual(
                config_path.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
            )

            row.spin.editingFinished.emit()

            new_text = config_path.read_text(encoding="utf-8")
            self.assertIn("#define GEAR1_MAX_SPEED        9u", new_text)
            # Untouched lines survive byte-for-byte (R10/AC7).
            self.assertIn("#define RACER_HP              5u   /* bullet hits to destroy a racer */", new_text)
            self.assertIn("#define PATROL_HP             RACER_HP   /* 5 bullet hits to destroy */", new_text)
            self.assertEqual(row.persisted_value, 9)

    def test_committing_the_value_already_on_disk_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write"
            ) as write_spy:
                row.spin.editingFinished.emit()  # value unchanged from load (2)

            write_spy.assert_not_called()

    def test_intermediate_value_while_typing_does_not_write(self):
        # AC/spec: "100" typed digit by digit must not write 1, then 10,
        # then 100 -- only editingFinished (Enter, here) writes, and only
        # the final value.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_wide_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["SPEED"]
            row.spin.show()
            row.spin.setFocus()
            row.spin.selectAll()

            written = []
            real_write = config_io.write

            def spy_write(binding_, schema_, changes):
                written.append(dict(changes))
                return real_write(binding_, schema_, changes)

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", side_effect=spy_write
            ):
                QTest.keyClicks(row.spin, "100")
                self.assertEqual(row.spin.value(), 100)
                # Still nothing written while typing.
                self.assertEqual(written, [])
                self.assertEqual(
                    binding.config_h.read_text(encoding="utf-8"), WIDE_CONFIG_TEXT
                )

                QTest.keyClick(row.spin, Qt.Key_Return)  # commits the edit

            # Exactly one write, of the final value -- never 1, then 10.
            self.assertEqual(written, [{"SPEED": 100}])
            new_text = binding.config_h.read_text(encoding="utf-8")
            self.assertIn("#define SPEED        100u", new_text)

    def test_binding_error_shows_explanation_without_crashing(self):
        error = project.BindingError("game_repo", "No sibling 'nuke-raider' directory found.")

        panel = TunerPanel(None, binding_error=error)

        self.assertEqual(panel._rows, {})
        self.assertIn("game_repo", panel.explanation_text())

    def test_missing_config_h_shows_explanation_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
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
            tmp_path = tmp_root(tmp)
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

            self.assertEqual(row.spin.value(), 9)  # value currently on disk
            self.assertEqual(row.head_value, 2)  # committed value
            self.assertTrue(row.differs_from_head())
            self.assertIn("2", row.head_label.text())
            self.assertFalse(row.head_label.isHidden())
            self.assertFalse(row.revert_button.isHidden())

    def test_row_matching_head_hides_head_value_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)

            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            self.assertFalse(row.differs_from_head())
            self.assertTrue(row.head_label.isHidden())
            self.assertTrue(row.revert_button.isHidden())

    def test_editing_then_editing_back_to_head_value_hides_head_display_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            row.spin.setValue(9)
            self.assertTrue(row.differs_from_head())
            self.assertFalse(row.head_label.isHidden())

            row.spin.setValue(2)
            self.assertFalse(row.differs_from_head())
            self.assertTrue(row.head_label.isHidden())

    def test_per_row_revert_writes_head_value_at_once(self):
        # A row that has been hand-edited (or written by a previous
        # session) differs from HEAD from launch. Revert restores it and
        # writes it -- there is no "pending" state to clear first.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
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
            self.assertTrue(row.differs_from_head())

            panel.revert_row("GEAR1_MAX_SPEED")

            self.assertEqual(row.spin.value(), 2)
            self.assertFalse(row.differs_from_head())
            # Written immediately -- no separate save step.
            self.assertEqual(
                binding.config_h.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
            )

    def test_revert_all_restores_every_differing_row_in_one_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)

            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)
            panel._rows["GEAR1_MAX_SPEED"].spin.editingFinished.emit()
            panel._rows["PLAYER_ARMOR"].spin.setValue(3)
            panel._rows["PLAYER_ARMOR"].spin.editingFinished.emit()
            self.assertTrue(panel._rows["GEAR1_MAX_SPEED"].differs_from_head())
            self.assertTrue(panel._rows["PLAYER_ARMOR"].differs_from_head())

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                panel.revert_all()

            # Revert All writes every differing row in a single pass, not
            # one write per row.
            write_spy.assert_called_once()
            self.assertEqual(panel._rows["GEAR1_MAX_SPEED"].spin.value(), 2)
            self.assertEqual(panel._rows["PLAYER_ARMOR"].spin.value(), 5)
            self.assertEqual(panel._rows["RACER_HP"].spin.value(), 5)
            self.assertFalse(panel._rows["GEAR1_MAX_SPEED"].differs_from_head())
            self.assertEqual(
                binding.config_h.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
            )

    def test_revert_all_is_a_no_op_when_nothing_differs_from_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write"
            ) as write_spy:
                panel.revert_all()

            write_spy.assert_not_called()

    def test_revert_all_button_wired_to_revert_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            panel._rows["GEAR1_MAX_SPEED"].spin.setValue(9)
            panel._rows["GEAR1_MAX_SPEED"].spin.editingFinished.emit()

            panel._revert_all_button.click()

            self.assertEqual(panel._rows["GEAR1_MAX_SPEED"].spin.value(), 2)
            self.assertIn(
                "#define GEAR1_MAX_SPEED        2u",
                binding.config_h.read_text(encoding="utf-8"),
            )

    def test_per_row_revert_button_wired_to_revert_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)
            row.spin.editingFinished.emit()

            row.revert_button.click()

            self.assertEqual(row.spin.value(), 2)
            self.assertIn(
                "#define GEAR1_MAX_SPEED        2u",
                binding.config_h.read_text(encoding="utf-8"),
            )

    def test_head_values_read_once_per_refresh_not_once_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
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
            tmp_path = tmp_root(tmp)
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
            tmp_path = tmp_root(tmp)
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


# -- R19/AC19/AC2: diff panel, header dirty mark and master warning --------


class TestDiffPanel(unittest.TestCase):
    def test_clean_worktree_shows_clean_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, _schema = make_panel_binding(tmp_path)

            panel = DiffPanel(binding)

            self.assertIn("clean", panel.status_text().lower())
            self.assertEqual(panel.file_paths(), [])
            self.assertEqual(panel.untracked_files(), [])

    def test_modified_file_shows_hunks_and_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, _schema = make_panel_binding(tmp_path)
            binding.config_h.write_text(
                PANEL_CONFIG_TEXT.replace(
                    "#define GEAR1_MAX_SPEED        2u",
                    "#define GEAR1_MAX_SPEED        9u",
                ),
                encoding="utf-8",
            )

            panel = DiffPanel(binding)

            self.assertIn("src/config.h", panel.file_paths())
            headers = [
                w.text() for w in panel.findChildren(QLabel, "diff-file-header")
            ]
            self.assertTrue(any("src/config.h" in h for h in headers))
            hunk_headers = panel.findChildren(QLabel, "diff-hunk-header")
            self.assertTrue(len(hunk_headers) >= 1)
            line_labels = panel.findChildren(QLabel, "diff-line")
            texts = [l.text() for l in line_labels]
            self.assertTrue(any(t.startswith("- ") and "2u" in t for t in texts))
            self.assertTrue(any(t.startswith("+ ") and "9u" in t for t in texts))
            kinds = {l.property("diffKind") for l in line_labels}
            self.assertIn("add", kinds)
            self.assertIn("remove", kinds)

    def test_untracked_file_listed_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, _schema = make_panel_binding(tmp_path)
            (binding.game_repo / "assets" / "sprites").mkdir(parents=True)
            (binding.game_repo / "assets" / "sprites" / "car-2.xcf").write_bytes(b"\x00\x01")

            panel = DiffPanel(binding)

            self.assertEqual(panel.untracked_files(), ["assets/sprites/car-2.xcf"])
            self.assertEqual(panel.file_paths(), [])
            untracked_labels = panel.findChildren(
                QLabel, "diff-untracked-file"
            )
            self.assertTrue(
                any("car-2.xcf" in w.text() for w in untracked_labels)
            )

    def test_binding_error_shows_explanation_without_crashing(self):
        error = project.BindingError("game_repo", "No sibling 'nuke-raider' directory found.")

        panel = DiffPanel(None, binding_error=error)

        self.assertIn("game_repo", panel.explanation_text())

    def test_refresh_picks_up_new_untracked_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, _schema = make_panel_binding(tmp_path)

            panel = DiffPanel(binding)
            self.assertEqual(panel.untracked_files(), [])

            (binding.game_repo / "new.txt").write_text("hi\n", encoding="utf-8")
            panel.refresh()

            self.assertEqual(panel.untracked_files(), ["new.txt"])


class TestDriftIsReportedAtStartup(unittest.TestCase):
    """AC9's second half, in the window: a `#define` the classification
    file does not place makes Garage say so when it starts, without the
    user opening anything.

    The fixture repository's config.h deliberately does not match the
    tunables.json this repository ships, which is exactly the drifted
    state -- so the Doctor's real check has something true to report.
    """

    def _window(self, tmp_path):
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
        window = GarageWindow(garage_root=garage_root)
        self.addCleanup(window.close)
        return window

    def test_the_doctor_carries_a_classification_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))

            self.assertIn("classification", window.doctor_panel.check_keys())
            self.assertEqual(window.doctor_panel.verdict_of("classification"), "fail")
            self.assertIn(
                "GEAR1_MAX_SPEED", window.doctor_panel.detail_of("classification")
            )
            self.assertIn(
                "tunables.json", window.doctor_panel.prevents_of("classification")
            )

    def test_the_window_states_it_without_anything_being_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))

            self.assertTrue(window.toolchain_label.isVisibleTo(window))
            self.assertIn("classification", window.toolchain_label.text())


class TestDiffNamesItsWorktree(unittest.TestCase):
    """With several checkouts of one repository open (R3), a diff that does
    not name its worktree is a diff the user has to take on trust.
    """

    def _window(self, tmp_path):
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
        window = GarageWindow(garage_root=garage_root)
        self.addCleanup(window.close)
        return window

    def test_the_panel_names_the_worktree_and_branch_it_is_diffing(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))

            subject = window.diff_panel.subject_text()

            self.assertIn(str(window.binding.active_worktree.path), subject)
            self.assertIn("master", subject)
            self.assertIn("against HEAD", subject)

    def test_the_dialog_title_names_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))

            title = window.diff_dialog.windowTitle()

            self.assertIn("nuke-raider", title)
            self.assertIn("master", title)

    def test_the_menu_action_says_which_tree_it_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))

            self.assertIn("Active Worktree", window.show_diff_action.text())

    def test_both_follow_a_worktree_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._window(tmp_root(tmp))
            window.worktrees_panel.create_worktree("feat/other")
            spike = next(
                w for w in window.worktrees_panel.worktrees()
                if w.branch == "feat/other"
            )

            window.activate_worktree(spike)

            self.assertIn(str(spike.path), window.diff_panel.subject_text())
            self.assertIn("feat/other", window.diff_panel.subject_text())
            self.assertIn("feat-other", window.diff_dialog.windowTitle())


class TestFormatHeader(unittest.TestCase):
    """The redesigned header (R2/AC2): totals only, never a per-file list,
    so its length depends only on digit counts, never on how many files
    or lines actually changed.
    """

    def _binding_on(self, tmp_path: Path, branch: str) -> project.Binding:
        game_repo = make_game_repo(tmp_path / "nuke-raider")
        if branch != "master":
            _run_git(["checkout", "-b", branch], game_repo)
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        return project.bind(garage_root)

    def test_clean_shows_no_changes_and_no_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=0, untracked_count=0, added_lines=0, removed_lines=0
            )

            text = format_header(binding, None, summary)

            self.assertIn("no changes", text)
            self.assertNotIn("●", text)
            self.assertNotIn("commit blocked", text.lower())

    def test_one_file_singular_with_line_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=5, removed_lines=5
            )

            text = format_header(binding, None, summary)

            self.assertIn("1 file ", text)
            self.assertNotIn("1 files", text)
            self.assertIn("+5", text)
            self.assertIn("−5", text)
            self.assertIn("●", text)

    def test_several_files_plural_with_line_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=12, untracked_count=0, added_lines=847, removed_lines=203
            )

            text = format_header(binding, None, summary)

            self.assertIn("12 files", text)
            self.assertIn("+847", text)
            self.assertIn("−203", text)

    def test_untracked_present_appended_after_file_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=1, added_lines=5, removed_lines=5
            )

            text = format_header(binding, None, summary)

            self.assertIn("1 file +5 −5 · 1 untracked", text)

    def test_untracked_absent_omits_the_untracked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=5, removed_lines=5
            )

            text = format_header(binding, None, summary)

            self.assertNotIn("untracked", text)

    def test_master_appends_commit_blocked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "master")
            summary = diff_core.ChangeSummary(
                changed_file_count=0, untracked_count=0, added_lines=0, removed_lines=0
            )

            text = format_header(binding, None, summary)

            self.assertIn("commit blocked on master", text)

    def test_off_master_omits_commit_blocked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=1, removed_lines=1
            )

            text = format_header(binding, None, summary)

            self.assertNotIn("commit blocked", text.lower())

    def test_dirty_master_still_shows_mark_and_commit_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._binding_on(tmp_path, "master")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=1, removed_lines=1
            )

            text = format_header(binding, None, summary)

            self.assertIn("●", text)
            self.assertIn("commit blocked on master", text)


class TestGarageWindowDiffIntegration(unittest.TestCase):
    def test_diff_dialog_is_closed_on_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)

            self.assertIsInstance(window.diff_panel, DiffPanel)
            self.assertFalse(window.diff_dialog.isVisible())

    def test_menu_action_opens_diff_dialog_and_it_can_be_closed_and_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)
            self.assertFalse(window.diff_dialog.isVisible())

            window.show_diff_action.trigger()
            self.assertTrue(window.diff_dialog.isVisible())
            self.assertIn("clean", window.diff_panel.status_text().lower())

            window.diff_dialog.close()
            self.assertFalse(window.diff_dialog.isVisible())
            # The Tuner underneath must be unaffected by opening/closing the
            # dialog -- it is a separate window, not part of the central
            # widget's layout, so it is still the (enabled, intact) central
            # widget's body.
            self.assertIsInstance(window.tuner_panel, TunerPanel)
            self.assertTrue(window.centralWidget().isAncestorOf(window.tuner_panel))
            self.assertTrue(window.tuner_panel.isEnabled())

            window.show_diff_action.trigger()
            self.assertTrue(window.diff_dialog.isVisible())

    def test_ac20_header_reads_no_changes_and_untracked_for_untracked_only_tree(self):
        # AC20 against a real bound repository: two untracked files, no
        # tracked change at all. The "●" mark stands for a tracked file
        # differing from HEAD, so it must not appear here; "no changes"
        # names the tracked state, "2 untracked" the rest.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            _run_git(["checkout", "-b", "feat"], game_repo)
            (game_repo / "a.txt").write_text("x\n", encoding="utf-8")
            (game_repo / "b.txt").write_text("y\n", encoding="utf-8")

            window = GarageWindow(garage_root=garage_root)

            header_text = window.header_label.text()
            self.assertNotIn("●", header_text)
            self.assertIn("no changes · 2 untracked", header_text)

    def test_header_shows_dirty_mark_for_a_tracked_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            _run_git(["checkout", "-b", "feat"], game_repo)
            (game_repo / "README.md").write_text("changed\n", encoding="utf-8")

            window = GarageWindow(garage_root=garage_root)

            header_text = window.header_label.text()
            self.assertIn("●", header_text)
            self.assertIn("1 file", header_text)

    def test_header_states_commit_blocked_on_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)

            self.assertIn("commit blocked", window.header_label.text().lower())

    def test_tuner_write_refreshes_header_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
            _run_git(["checkout", "-b", "feat"], game_repo)
            write_json(tmp_path / "tunables.json", PANEL_TUNABLES)
            # Point the schema the Tuner loads at our fixture tunables.json
            # by binding with default schema discovery bypassed: build the
            # window, then swap in a fixture-backed TunerPanel the same way
            # other tests reach into the window's wiring.
            window = GarageWindow(garage_root=garage_root)
            schema = Schema.load(tmp_path / "tunables.json")
            window.tuner_panel = TunerPanel(window.binding, window.binding_error, schema=schema)
            window.tuner_panel.written.connect(window._on_tuner_written)

            self.assertIn("no changes", window.header_label.text())
            self.assertNotIn("●", window.header_label.text())

            row = window.tuner_panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)
            row.spin.editingFinished.emit()  # committing the edit writes at once

            header_text = window.header_label.text()
            self.assertIn("●", header_text)
            self.assertIn("1 file", header_text)
            self.assertIn("+1", header_text)
            self.assertIn("−1", header_text)

    def test_tuner_write_refreshes_open_diff_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
            _run_git(["checkout", "-b", "feat"], game_repo)
            write_json(tmp_path / "tunables.json", PANEL_TUNABLES)
            window = GarageWindow(garage_root=garage_root)
            schema = Schema.load(tmp_path / "tunables.json")
            window.tuner_panel = TunerPanel(window.binding, window.binding_error, schema=schema)
            window.tuner_panel.written.connect(window._on_tuner_written)
            window.open_diff()
            self.assertIn("clean", window.diff_panel.status_text().lower())

            row = window.tuner_panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)
            row.spin.editingFinished.emit()

            self.assertIn("src/config.h", window.diff_panel.file_paths())


# -- R18/AC18: the dark stylesheet -------------------------------------------


PANEL_SOURCE_FILES = [
    *sorted((REPO_ROOT / "tools" / "garage" / "panels").glob("*.py")),
    REPO_ROOT / "tools" / "garage" / "app.py",
]

# A bare 6-digit hex literal, the way a colour is written in QSS/Python
# ("#RRGGBB"). Word-bounded so it doesn't false-positive on a longer hash
# (e.g. a commit SHA) that happens to start with 6 hex digits.
_HEX_COLOUR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_QT_COLOUR_CONSTANT_RE = re.compile(
    r"\bQt\.(?:GlobalColor\.)?(?:black|white|red|green|blue|yellow|cyan|magenta|"
    r"gray|grey|darkGray|darkGrey|lightGray|lightGrey)\b"
)


class TestNoColourLiteralInPanelSource(unittest.TestCase):
    """AC18: "no panel holds one [a colour literal]". A real grep over the
    source files, not a one-time claim -- this keeps holding as the panels
    change. tools/garage/theme/ is the one place a literal is allowed to
    live and is deliberately not in PANEL_SOURCE_FILES.
    """

    def test_no_hex_colour_literal(self):
        for path in PANEL_SOURCE_FILES:
            text = path.read_text(encoding="utf-8")
            match = _HEX_COLOUR_RE.search(text)
            self.assertIsNone(
                match,
                f"{path} holds a colour literal ({match.group(0) if match else ''}); "
                "move it into tools/garage/theme/tokens.py",
            )

    def test_no_qcolor_construction(self):
        for path in PANEL_SOURCE_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("QColor(", text, f"{path} constructs a QColor directly")

    def test_no_qt_colour_constant(self):
        for path in PANEL_SOURCE_FILES:
            text = path.read_text(encoding="utf-8")
            match = _QT_COLOUR_CONSTANT_RE.search(text)
            self.assertIsNone(
                match, f"{path} uses a Qt colour constant ({match.group(0) if match else ''})"
            )

    def test_no_direct_setstylesheet_call(self):
        # Every panel takes its appearance from the one stylesheet applied
        # at startup (tools.garage.theme.apply); a panel calling
        # setStyleSheet itself would be a second, untracked source of
        # appearance.
        for path in PANEL_SOURCE_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "setStyleSheet(", text, f"{path} sets a stylesheet directly"
            )


class TestThemeAppliesAtStartup(unittest.TestCase):
    def test_apply_installs_a_nonempty_stylesheet_built_from_the_tokens(self):
        theme.apply(_app)

        sheet = _app.styleSheet()

        self.assertTrue(sheet.strip())
        # Spot-check that the installed sheet really is theme.build_stylesheet()
        # -- i.e. that apply() didn't silently no-op -- by looking for a
        # couple of tokens that must be in it.
        self.assertIn(theme.TOKENS["bg"], sheet)
        self.assertIn(theme.TOKENS["accent"], sheet)

    def test_dark_tokens_match_the_prototypes_dark_set(self):
        # The spec's source of truth: garage/index.html's
        # :root[data-theme="dark"] block. Pinning these here means a future
        # edit to tokens.py that drifts from the prototype fails loudly.
        expected = {
            "bg": "#0E120F", "surface": "#171C18", "surface-2": "#1E241F",
            "surface-3": "#272E28", "line": "#343C35", "line-soft": "#242B25",
            "text": "#E6EAE2", "text-2": "#A6AFA5", "text-3": "#79837A",
            "accent": "#D2683F", "accent-ink": "#1A0E08", "accent-soft": "#2C1D15",
            "accent-line": "#573224", "pass": "#86B45A", "warn": "#D9AE3C",
            "fail": "#E0647C", "pass-soft": "#1D2717", "warn-soft": "#2C2412",
            "fail-soft": "#2E1720",
        }
        self.assertEqual(theme.TOKENS, expected)


class TestTunerChangedRowStyling(unittest.TestCase):
    """AC18: "A row differing from HEAD must be visibly distinct". The
    theme applies a left accent stripe (garage/index.html's `.prow.changed`)
    via the "changed" dynamic property tuner.py sets; this checks the
    property lands on a differing row and not on an equal one.
    """

    def test_changed_property_set_on_differing_row_and_not_on_equal_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            other = panel._rows["PLAYER_ARMOR"]

            self.assertFalse(row.name_label.property("changed"))
            self.assertFalse(row.field_container.property("changed"))

            row.spin.setValue(9)
            row.spin.editingFinished.emit()

            self.assertTrue(row.differs_from_head())
            self.assertTrue(row.name_label.property("changed"))
            self.assertTrue(row.field_container.property("changed"))
            # A row that was never touched stays untouched.
            self.assertFalse(other.differs_from_head())
            self.assertFalse(other.name_label.property("changed"))
            self.assertFalse(other.field_container.property("changed"))

    def test_reverting_clears_the_changed_property(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            row.spin.setValue(9)
            row.spin.editingFinished.emit()
            self.assertTrue(row.name_label.property("changed"))

            panel.revert_row("GEAR1_MAX_SPEED")

            self.assertFalse(row.differs_from_head())
            self.assertFalse(row.name_label.property("changed"))
            self.assertFalse(row.field_container.property("changed"))


class TestDiffLineDistinctRoles(unittest.TestCase):
    """AC18/R19: "must mark an added line and a removed line distinctly".
    Iteration 4 left this to a "+ "/"- " prefix and bold weight (the
    non-colour cue, kept); iteration 5 adds colour on top, via the
    `diffKind` property diff_view.py already sets on every line label.
    """

    def test_added_and_removed_lines_carry_different_diffkind_and_colour(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, _schema = make_panel_binding(tmp_path)
            binding.config_h.write_text(
                PANEL_CONFIG_TEXT.replace(
                    "#define GEAR1_MAX_SPEED        2u",
                    "#define GEAR1_MAX_SPEED        9u",
                ),
                encoding="utf-8",
            )

            panel = DiffPanel(binding)
            line_labels = panel.findChildren(QLabel, "diff-line")
            by_kind = {
                l.property("diffKind"): l
                for l in line_labels
                if l.property("diffKind") in ("add", "remove")
            }

            self.assertIn("add", by_kind)
            self.assertIn("remove", by_kind)
            # The non-colour cue survives: prefix and bold weight.
            self.assertTrue(by_kind["add"].text().startswith("+ "))
            self.assertTrue(by_kind["remove"].text().startswith("- "))
            self.assertTrue(by_kind["add"].font().bold())
            self.assertTrue(by_kind["remove"].font().bold())

        # The colour cue: the stylesheet gives "add" and "remove" distinct,
        # non-empty roles built from the pass/fail tokens respectively.
        sheet = theme.build_stylesheet()
        add_rule = re.search(r'QLabel\[diffKind="add"\]\s*\{([^}]*)\}', sheet)
        remove_rule = re.search(r'QLabel\[diffKind="remove"\]\s*\{([^}]*)\}', sheet)
        self.assertIsNotNone(add_rule)
        self.assertIsNotNone(remove_rule)
        self.assertIn(theme.TOKENS["pass"], add_rule.group(1))
        self.assertIn(theme.TOKENS["fail"], remove_rule.group(1))
        self.assertNotEqual(add_rule.group(1).strip(), remove_rule.group(1).strip())


class TestHeaderRichText(unittest.TestCase):
    """R18: "the monospace face belongs on the values, and 'commit blocked
    on master' is a warning and should read as one using the warn token."
    """

    def test_header_html_carries_the_same_words_as_the_plain_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            binding = project.bind(garage_root)
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=2, removed_lines=1
            )

            plain = format_header(binding, None, summary)
            rich = format_header_html(binding, None, summary)

            self.assertIn(str(game_repo), rich)
            self.assertIn("master", rich)
            self.assertIn("1 file +2 −1", rich)
            self.assertIn("commit blocked on master", rich)
            # Presentation only: stripping the markup leaves the same words.
            self.assertEqual(re.sub(r"<[^>]+>", "", rich), plain)

    def test_master_warning_uses_the_warn_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            make_game_repo(tmp_path / "nuke-raider")
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            binding = project.bind(garage_root)

            rich = format_header_html(binding, None, None)

            self.assertIn(theme.TOKENS["warn"], rich)

    def test_binding_error_is_escaped_and_readable(self):
        error = project.BindingError("game_repo", "No sibling 'nuke-raider' <found>.")

        rich = format_header_html(None, error, None)

        self.assertIn("game_repo", rich)
        self.assertNotIn("<found>", rich)  # escaped, not parsed as a tag
        self.assertIn("&lt;found&gt;", rich)


# -- Iteration 6 regression: stepping (arrows/arrow-keys) must write -------
#
# tools/garage/panels/tuner.py's STEP_DEBOUNCE_MS-based debounce is driven
# deterministically below by emitting the row's QTimer.timeout signal
# directly, rather than sleeping for real time: emit() invokes connected
# slots synchronously exactly as a real firing would, without waiting out
# the interval or pumping the event loop.


class TestTunerPanelStepping(unittest.TestCase):
    def test_stepup_writes_after_the_debounce_with_the_stepped_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            self.assertEqual(row.spin.value(), 2)

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                row.spin.stepUp()
                self.assertEqual(row.spin.value(), 3)
                # Debouncing -- nothing written yet.
                write_spy.assert_not_called()
                self.assertTrue(row.step_timer.isActive())
                self.assertEqual(
                    binding.config_h.read_text(encoding="utf-8"), PANEL_CONFIG_TEXT
                )

                row.step_timer.timeout.emit()  # the debounce settles

            write_spy.assert_called_once()
            self.assertEqual(row.persisted_value, 3)
            self.assertIn(
                "#define GEAR1_MAX_SPEED        3u",
                binding.config_h.read_text(encoding="utf-8"),
            )

    def test_rapid_steps_produce_one_write_carrying_the_final_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                # Five rapid ticks -- e.g. a held key or a burst of clicks --
                # each one restarts the debounce instead of writing.
                for _ in range(5):
                    row.spin.stepUp()
                self.assertEqual(row.spin.value(), 7)
                write_spy.assert_not_called()

                row.step_timer.timeout.emit()  # settles once, after the last tick

            write_spy.assert_called_once()
            self.assertEqual(write_spy.call_args[0][2], {"GEAR1_MAX_SPEED": 7})
            self.assertIn(
                "#define GEAR1_MAX_SPEED        7u",
                binding.config_h.read_text(encoding="utf-8"),
            )

    def test_typing_still_does_not_start_the_step_debounce_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_wide_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["SPEED"]
            row.spin.show()
            row.spin.setFocus()
            row.spin.selectAll()

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write"
            ) as write_spy:
                QTest.keyClicks(row.spin, "100")
                self.assertEqual(row.spin.value(), 100)
                # stepBy() is never called while typing, so the debounce
                # never starts and nothing is written.
                self.assertFalse(row.step_timer.isActive())
                write_spy.assert_not_called()

                QTest.keyClick(row.spin, Qt.Key_Return)

            write_spy.assert_called_once()

    def test_pending_step_write_flushed_by_editing_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                row.spin.stepUp()
                write_spy.assert_not_called()
                self.assertTrue(row.step_timer.isActive())

                row.spin.editingFinished.emit()  # e.g. Return, ahead of the debounce

            write_spy.assert_called_once()
            self.assertFalse(row.step_timer.isActive())
            self.assertEqual(row.persisted_value, 3)

            # The debounce, were it still armed, must not fire a second,
            # redundant write for the same value.
            row.step_timer.timeout.emit()
            write_spy.assert_called_once()

    def test_pending_step_write_flushed_by_focus_out(self):
        # Real OS-level focus transfer needs an active top-level window,
        # which an offscreen-platform test has none of (setFocus() between
        # two shown-but-not-activated widgets silently no-ops here) -- so
        # focus leaving the field is driven the same way Qt itself would
        # deliver it, by dispatching a FocusOut event straight to the
        # widget, deterministically and without needing a real window.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)
            row = panel._rows["GEAR1_MAX_SPEED"]
            row.spin.show()

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                row.spin.stepUp()
                write_spy.assert_not_called()

                focus_out = QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason)
                row.spin.focusOutEvent(focus_out)  # focus leaves -> flush, no debounce wait

            write_spy.assert_called_once()
            self.assertFalse(row.step_timer.isActive())
            self.assertEqual(row.persisted_value, 3)

    def test_pending_step_write_flushed_on_window_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
            _run_git(["checkout", "-b", "feat"], game_repo)
            write_json(tmp_path / "tunables.json", PANEL_TUNABLES)
            window = GarageWindow(garage_root=garage_root)
            schema = Schema.load(tmp_path / "tunables.json")
            window.tuner_panel = TunerPanel(window.binding, window.binding_error, schema=schema)
            window.tuner_panel.written.connect(window._on_tuner_written)
            row = window.tuner_panel._rows["GEAR1_MAX_SPEED"]

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write", wraps=config_io.write
            ) as write_spy:
                row.spin.stepUp()
                write_spy.assert_not_called()

                # A user who clicks + and immediately closes Garage must
                # still get the write -- closeEvent flushes it.
                window.close()

            write_spy.assert_called_once()
            self.assertIn(
                "#define GEAR1_MAX_SPEED        3u",
                window.binding.config_h.read_text(encoding="utf-8"),
            )

    def test_stepped_write_refreshes_header_totals_and_open_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo_with_config(tmp_path / "nuke-raider", PANEL_CONFIG_TEXT)
            _run_git(["checkout", "-b", "feat"], game_repo)
            write_json(tmp_path / "tunables.json", PANEL_TUNABLES)
            window = GarageWindow(garage_root=garage_root)
            schema = Schema.load(tmp_path / "tunables.json")
            window.tuner_panel = TunerPanel(window.binding, window.binding_error, schema=schema)
            window.tuner_panel.written.connect(window._on_tuner_written)
            window.open_diff()
            self.assertIn("clean", window.diff_panel.status_text().lower())
            self.assertNotIn("●", window.header_label.text())

            row = window.tuner_panel._rows["GEAR1_MAX_SPEED"]
            row.spin.stepUp()
            row.step_timer.timeout.emit()  # settle the debounce deterministically

            header_text = window.header_label.text()
            self.assertIn("●", header_text)
            self.assertIn("1 file", header_text)
            self.assertIn("src/config.h", window.diff_panel.file_paths())


# -- Iteration 6 regression: QSpinBox up/down sub-controls ------------------


class TestSpinBoxSubControlGeometry(unittest.TestCase):
    """Regression guard for the "+ does nothing / misaligned" rendering bug:
    once a QSpinBox picks up box styling (border/padding/background) from a
    stylesheet, Qt stops delegating its up/down sub-controls to the native
    style; without explicit ::up-button/::down-button/::up-arrow/::down-arrow
    rules (tools/garage/theme/qss.py) they fell back to a default box that
    painted nothing, at a position no longer guaranteed to line up with a
    styled field.

    TestTunerPanelStepping above proves stepUp() itself works, but that
    calls stepBy() directly and would stay green even if the arrows were
    completely invisible or the widget had shrunk to nothing -- it never
    looks at what is painted or where the actual click regions are. These
    tests do, via QStyle/QStyleOptionSpinBox, the same mechanism Qt itself
    uses to hit-test a click.
    """

    def _themed_spinbox(self) -> QSpinBox:
        theme.apply(_app)
        spin = QSpinBox()
        spin.setValue(5)
        spin.resize(120, 28)
        spin.show()
        return spin

    def test_up_and_down_hit_regions_are_present_distinct_and_in_bounds(self):
        spin = self._themed_spinbox()
        opt = QStyleOptionSpinBox()
        spin.initStyleOption(opt)
        style = spin.style()

        up = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxUp, spin
        )
        down = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxDown, spin
        )

        self.assertFalse(up.isEmpty())
        self.assertFalse(down.isEmpty())
        self.assertFalse(up.intersects(down))
        self.assertTrue(spin.rect().contains(up))
        self.assertTrue(spin.rect().contains(down))

    def test_an_arrow_is_actually_painted_in_each_button_not_just_hittable(self):
        # The geometry above can be perfectly sane while nothing is drawn in
        # it -- exactly what regressed. Render the widget and sample the
        # pixel at the centre of each button; it must differ from the
        # field's own background, i.e. an arrow is visibly there.
        spin = self._themed_spinbox()
        opt = QStyleOptionSpinBox()
        spin.initStyleOption(opt)
        style = spin.style()
        up = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxUp, spin
        )
        down = style.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt, QStyle.SubControl.SC_SpinBoxDown, spin
        )

        image = QImage(spin.size(), QImage.Format.Format_ARGB32)
        spin.render(image)
        field_bg = image.pixelColor(10, spin.height() // 2)  # inside the text area

        self.assertNotEqual(image.pixelColor(up.center()), field_bg)
        self.assertNotEqual(image.pixelColor(down.center()), field_bg)


class TestDoctorPanel(unittest.TestCase):
    """The panel renders a `doctor.Report`; what the report *says* is
    covered in tests/test_garage_core.py, with no Qt. Every report here is
    therefore built by hand -- the panel must render the same way on a
    machine that has the whole toolchain and on one that has none of it.
    """

    def _report(self):
        return doctor_core.Report(
            checks=[
                doctor_core.CheckResult(
                    key="make",
                    name="make — every build target",
                    status=doctor_core.PASS,
                    detail="C:/bin/make.exe",
                    tag="4.4.1",
                ),
                doctor_core.CheckResult(
                    key="romusage",
                    name="romusage — ROM bank budgets",
                    status=doctor_core.FAIL,
                    detail="not found on PATH — add C:/gbdk/bin",
                    prevents="The ROM bank budget check. make bank-post-build exits 2.",
                    tag="blocked",
                ),
            ]
        )

    def _panel(self, report):
        with mock.patch.object(doctor_core, "run_checks", return_value=report):
            return DoctorPanel(None, None)

    def test_renders_one_row_per_check_with_its_detail(self):
        panel = self._panel(self._report())

        self.assertEqual(panel.check_keys(), ["make", "romusage"])
        self.assertEqual(panel.detail_of("make"), "C:/bin/make.exe")
        self.assertIn("not found on PATH", panel.detail_of("romusage"))

    def test_a_failing_check_states_what_it_prevents(self):
        # AC14, as rendered: the sentence is on the row, not only in the
        # report object.
        panel = self._panel(self._report())

        self.assertIn("bank-post-build", panel.prevents_of("romusage"))
        self.assertEqual(panel.prevents_of("make"), "")

    def test_summary_line_counts_the_checks(self):
        panel = self._panel(self._report())

        self.assertIn("1 of 2 checks passing", panel.summary_text())
        self.assertIn("romusage", panel.summary_text())
        self.assertTrue(panel.has_failures())

    def test_a_whole_toolchain_has_no_failures(self):
        report = doctor_core.Report(
            checks=[
                doctor_core.CheckResult(
                    key="make", name="make", status=doctor_core.PASS, detail="ok"
                )
            ]
        )

        panel = self._panel(report)

        self.assertFalse(panel.has_failures())
        self.assertEqual(panel.summary_text(), "1 of 1 checks passing")

    def test_rows_carry_the_verdict_property_the_stylesheet_selects_on(self):
        # AC18: the panel declares no colour of its own -- it exposes the
        # result as a property and tools/garage/theme/qss.py colours it.
        panel = self._panel(self._report())

        self.assertEqual(panel.verdict_of("make"), "pass")
        self.assertEqual(panel.verdict_of("romusage"), "fail")

        chips = [
            label
            for label in panel.findChildren(QLabel)
            if label.objectName() == "doctor-verdict"
        ]
        self.assertEqual([c.text() for c in chips], ["PASS", "FAIL"])
        self.assertEqual(
            [c.property("verdict") for c in chips], ["pass", "fail"]
        )

    def test_the_stylesheet_gives_both_verdicts_a_distinct_colour(self):
        sheet = theme.build_stylesheet()

        self.assertIn('QLabel#doctor-verdict[verdict="pass"]', sheet)
        self.assertIn('QLabel#doctor-verdict[verdict="fail"]', sheet)
        self.assertIn(theme.TOKENS["pass"], sheet)
        self.assertIn(theme.TOKENS["fail"], sheet)


class TestGarageWindowDoctorIntegration(unittest.TestCase):
    def _window(self, garage_root, report):
        with mock.patch.object(doctor_core, "run_checks", return_value=report):
            return GarageWindow(garage_root=garage_root)

    def _failing_report(self):
        return doctor_core.Report(
            checks=[
                doctor_core.CheckResult(
                    key="make", name="make", status=doctor_core.PASS, detail="ok"
                ),
                doctor_core.CheckResult(
                    key="romusage",
                    name="romusage — ROM bank budgets",
                    status=doctor_core.FAIL,
                    detail="not found on PATH",
                    prevents="The ROM bank budget check.",
                ),
            ]
        )

    def _passing_report(self):
        return doctor_core.Report(
            checks=[
                doctor_core.CheckResult(
                    key="make", name="make", status=doctor_core.PASS, detail="ok"
                )
            ]
        )

    def _garage_root(self, tmp_path):
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        make_game_repo(tmp_path / "nuke-raider")
        return garage_root

    def test_a_failing_check_is_stated_in_the_window_itself(self):
        # AC14 / R14: the failure is reported at startup, without the user
        # having to open anything.
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            window = self._window(garage_root, self._failing_report())

            self.assertTrue(window.toolchain_label.isVisibleTo(window))
            text = window.toolchain_label.text()
            self.assertIn("1 check failing", text)
            self.assertIn("romusage", text)

    def test_a_whole_toolchain_shows_no_notice_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            window = self._window(garage_root, self._passing_report())

            self.assertFalse(window.toolchain_label.isVisibleTo(window))
            self.assertFalse(window.doctor_dialog.isVisible())

    def test_the_doctor_opens_itself_once_when_a_check_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            window = self._window(garage_root, self._failing_report())
            self.assertFalse(window.doctor_dialog.isVisible())

            window.show()
            try:
                self.assertTrue(window.doctor_dialog.isVisible())

                # Closed by the user, it stays closed -- showing the window
                # again (raise, restore) must not keep re-opening it.
                window.doctor_dialog.close()
                window.hide()
                window.show()
                self.assertFalse(window.doctor_dialog.isVisible())
            finally:
                window.close()

    def test_the_doctor_stays_closed_when_every_check_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            window = self._window(garage_root, self._passing_report())
            window.show()
            try:
                self.assertFalse(window.doctor_dialog.isVisible())
            finally:
                window.close()

    def test_menu_action_opens_the_doctor_and_it_can_be_closed_and_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            window = self._window(garage_root, self._passing_report())

            window.show_doctor_action.trigger()
            self.assertTrue(window.doctor_dialog.isVisible())
            self.assertIn("1 of 1 checks passing", window.doctor_panel.summary_text())

            window.doctor_dialog.close()
            self.assertFalse(window.doctor_dialog.isVisible())

            window.show_doctor_action.trigger()
            self.assertTrue(window.doctor_dialog.isVisible())
            window.doctor_dialog.close()

            # The Tuner underneath is untouched by the dialog, as with the
            # diff -- a separate window, not part of the central layout.
            self.assertTrue(window.centralWidget().isAncestorOf(window.tuner_panel))
            self.assertTrue(window.tuner_panel.isEnabled())

    def test_the_checks_run_once_at_startup_not_on_every_open(self):
        # They read the process environment, which cannot change under a
        # running Garage; re-running them would redraw the same answer and
        # cost a subprocess per tool each time.
        with tempfile.TemporaryDirectory() as tmp:
            garage_root = self._garage_root(tmp_root(tmp))

            with mock.patch.object(
                doctor_core, "run_checks", return_value=self._passing_report()
            ) as run_checks:
                window = GarageWindow(garage_root=garage_root)
                self.assertEqual(run_checks.call_count, 1)

                window.show_doctor_action.trigger()
                window.doctor_dialog.close()

                self.assertEqual(run_checks.call_count, 1)


class CompileBarFixture:
    """Shared rig for the compile-bar suites: a throwaway game repo, a
    bound panel, and the event-loop spinning a queued signal needs.

    A mixin rather than a base TestCase on purpose -- subclassing a
    TestCase re-runs every one of its tests in each subclass, and each of
    these costs a git repo and a subprocess.
    """

    def setUp(self):
        # ignore_cleanup_errors: these tests kill a process tree on
        # purpose, and a killed process's children can still hold a handle
        # under the directory when it goes away. Windows raises on that.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # A cleanup, not tearDown: unittest runs tearDown *before* every
        # cleanup, and cleanups run last-registered-first. The bar's
        # stop_and_wait, registered in _bar(), therefore runs before this
        # -- so the directory a build is running in cannot be deleted
        # while that build is still running.
        self.addCleanup(self._tmp.cleanup)
        tmp_path = tmp_root(self._tmp.name)
        garage_root = tmp_path / "nuke-raider-garage"
        garage_root.mkdir()
        make_game_repo(tmp_path / "nuke-raider")
        self.binding = project.bind(garage_root)
        self.worktree = self.binding.active_worktree.path

    def _bar(self):
        bar = CompileBar(self.binding)
        self.addCleanup(bar.stop_and_wait)
        return bar

    @staticmethod
    def _python_command(source, label="make"):
        return make_runner.Command(argv=(sys.executable, "-c", source), label=label)

    @staticmethod
    def _wait_until(predicate, timeout_ms=15000):
        """Spin the event loop until `predicate` holds. The worker thread
        delivers its lines as queued signals, so they only arrive while the
        loop runs -- a plain sleep here would hang forever.
        """
        waited = 0
        while waited < timeout_ms and not predicate():
            QTest.qWait(20)
            waited += 20
        return predicate()

    def _run_and_wait(self, bar, commands, expects_rom=False):
        bar._start(commands, expects_rom=expects_rom)
        self.assertTrue(
            self._wait_until(lambda: not bar.is_running()), "the run never finished"
        )


class TestCompileBar(CompileBarFixture, unittest.TestCase):
    """The compile bar drives `make_runner` on a worker thread. Every test
    below runs a real subprocess -- this interpreter, not `make`, so the
    suite needs no toolchain -- through the real threading path, because
    the threading is most of what this panel is.
    """

    def test_output_is_shown_and_the_command_is_echoed(self):
        bar = self._bar()

        self._run_and_wait(
            bar, [self._python_command("print('compiling'); print('done')")]
        )

        self.assertIn("$ make", bar.log_text())
        self.assertIn("compiling", bar.log_text())
        self.assertIn("done", bar.log_text())

    def test_output_appears_while_the_run_is_still_going(self):
        # R6: a display with no progress reads as a failure. The child
        # holds its second line for 400ms; the first must already be in the
        # log, with the panel still marked running.
        bar = self._bar()

        bar._start(
            [
                self._python_command(
                    "import time\n"
                    "print('first', flush=True)\n"
                    "time.sleep(0.4)\n"
                    "print('second', flush=True)\n"
                )
            ],
            expects_rom=False,
        )
        try:
            self.assertTrue(self._wait_until(lambda: "first" in bar.log_text()))
            self.assertTrue(bar.is_running())
            self.assertNotIn("second", bar.log_text())
            self.assertEqual(bar.state(), "busy")
        finally:
            self.assertTrue(self._wait_until(lambda: not bar.is_running()))
        self.assertIn("second", bar.log_text())

    def test_buttons_are_disabled_while_a_run_is_in_flight(self):
        bar = self._bar()

        bar._start(
            [self._python_command("import time; time.sleep(0.4)")], expects_rom=False
        )
        try:
            self.assertFalse(bar.build_button.isEnabled())
            self.assertFalse(bar.clean_build_button.isEnabled())
            self.assertTrue(bar.stop_button.isEnabled())
        finally:
            self.assertTrue(self._wait_until(lambda: not bar.is_running()))

        self.assertTrue(bar.build_button.isEnabled())
        self.assertFalse(bar.stop_button.isEnabled())

    def test_a_successful_run_reports_ok_and_its_duration(self):
        bar = self._bar()

        self._run_and_wait(bar, [self._python_command("print('ok')")])

        self.assertIn("make — ok in", bar.status_text())
        self.assertEqual(bar.state(), "pass")

    def test_a_failing_run_reports_the_exit_code(self):
        bar = self._bar()

        self._run_and_wait(bar, [self._python_command("raise SystemExit(2)")])

        self.assertIn("failed (exit 2)", bar.status_text())
        self.assertEqual(bar.state(), "fail")

    def test_a_stopped_run_reads_as_stopped_not_as_a_failure(self):
        bar = self._bar()

        bar._start(
            [
                self._python_command(
                    "import time\n"
                    "print('started', flush=True)\n"
                    "while True: time.sleep(0.05)\n"
                )
            ],
            expects_rom=False,
        )
        self.assertTrue(self._wait_until(lambda: "started" in bar.log_text()))

        bar.stop()

        self.assertTrue(
            self._wait_until(lambda: not bar.is_running()),
            "stop did not end the run",
        )
        self.assertIn("stopped", bar.status_text())
        self.assertNotIn("failed", bar.status_text())
        self.assertEqual(bar.state(), "idle")

    def test_a_clean_build_stops_when_the_clean_fails(self):
        bar = self._bar()

        self._run_and_wait(
            bar,
            [
                self._python_command("raise SystemExit(2)", label="make clean"),
                self._python_command("print('built')", label="make"),
            ],
        )

        self.assertIn("make clean — failed (exit 2)", bar.status_text())
        self.assertNotIn("built", bar.log_text())

    def test_a_successful_build_names_the_rom_it_produced(self):
        # AC11: the ROM lands in the active worktree, and the bar says so
        # from the file rather than from the exit code.
        bar = self._bar()
        source = (
            "import pathlib\n"
            "build = pathlib.Path('build')\n"
            "build.mkdir(exist_ok=True)\n"
            "(build / 'nuke-raider.gb').write_bytes(b'\\0' * 524288)\n"
            "print('Built build/nuke-raider.gb')\n"
        )

        self._run_and_wait(bar, [self._python_command(source)], expects_rom=True)

        self.assertTrue((self.worktree / "build" / "nuke-raider.gb").is_file())
        self.assertIn("nuke-raider.gb — 512 KB", bar.log_text())

    def test_a_build_that_writes_no_rom_says_so(self):
        bar = self._bar()

        self._run_and_wait(
            bar, [self._python_command("print('nothing to do')")], expects_rom=True
        )

        self.assertIn("was not written", bar.log_text())

    def test_the_run_happens_in_the_active_worktree(self):
        # R2: every make call resolves against the active worktree.
        bar = self._bar()

        self._run_and_wait(
            bar, [self._python_command("import os; print(os.getcwd())")]
        )

        self.assertIn(str(self.worktree), bar.log_text())

    def test_the_four_targets_r11_names_are_all_reachable(self):
        bar = self._bar()

        self.assertEqual(make_runner.make_command("build").label, "make")
        for target in ("clean", "memory-check", "bank-post-build"):
            self.assertEqual(
                make_runner.make_command(target).label, f"make {target}"
            )
        self.assertTrue(bar.memory_check_button.isEnabled())
        self.assertTrue(bar.bank_check_button.isEnabled())

    def test_a_second_run_cannot_start_while_one_is_in_flight(self):
        bar = self._bar()

        bar._start(
            [self._python_command("import time; time.sleep(0.4); print('first')")],
            expects_rom=False,
        )
        bar._start([self._python_command("print('second')")], expects_rom=False)

        self.assertTrue(self._wait_until(lambda: not bar.is_running()))
        self.assertIn("first", bar.log_text())
        self.assertNotIn("second", bar.log_text())

    def test_build_cleans_first_when_config_h_changed_since_the_compile(self):
        # The Build button must always produce a ROM carrying the values on
        # screen; with no header dependency in the game repository's
        # Makefile, that costs a full recompile in exactly this case.
        bar = self._bar()

        with mock.patch.object(make_runner, "needs_clean_build", return_value=True):
            with mock.patch.object(bar, "_start") as start:
                bar.run_build()

        commands, kwargs = start.call_args[0], start.call_args[1]
        # The measuring targets follow the build itself -- see
        # TestCompileBarBudgets for why they are part of the chain.
        self.assertEqual(
            [c.label for c in commands[0]][:2], ["make clean", "make"]
        )
        self.assertTrue(kwargs["expects_rom"])
        self.assertIn("no header dependency", bar.log_text())

    def test_build_stays_incremental_when_nothing_changed(self):
        bar = self._bar()

        with mock.patch.object(make_runner, "needs_clean_build", return_value=False):
            with mock.patch.object(bar, "_start") as start:
                bar.run_build()

        self.assertEqual([c.label for c in start.call_args[0][0]][:1], ["make"])
        self.assertEqual(bar.log_text(), "")

    def test_a_failure_names_the_toolchain_check_that_explains_it(self):
        # The real case: `make bank-post-build` dies on a missing romusage,
        # which the Doctor already reported at startup.
        bar = self._bar()
        bar.set_doctor_report(
            doctor_core.Report(
                checks=[
                    doctor_core.CheckResult(
                        key="romusage",
                        name="romusage — ROM bank budgets",
                        status=doctor_core.FAIL,
                        detail="not found on PATH — add C:/gbdk/bin",
                        prevents="The ROM bank budget check.",
                    )
                ]
            )
        )

        self._run_and_wait(
            bar,
            [
                make_runner.Command(
                    argv=(sys.executable, "-c", "raise SystemExit(1)"),
                    label="make bank-post-build",
                    target="bank-post-build",
                )
            ],
        )

        self.assertIn("add C:/gbdk/bin", bar.log_text())
        self.assertIn("ROM bank budget check", bar.log_text())

    def test_a_measuring_target_that_failed_with_no_rom_says_build_first(self):
        bar = self._bar()

        self._run_and_wait(
            bar,
            [
                make_runner.Command(
                    argv=(sys.executable, "-c", "raise SystemExit(1)"),
                    label="make memory-check",
                    target="memory-check",
                )
            ],
        )

        self.assertIn("Run Build first", bar.log_text())

    def test_a_failure_with_a_whole_toolchain_explains_nothing(self):
        # A genuine compile error must not be buried under toolchain prose.
        bar = self._bar()
        bar.set_doctor_report(
            doctor_core.Report(
                checks=[
                    doctor_core.CheckResult(
                        key="romusage",
                        name="romusage",
                        status=doctor_core.PASS,
                        detail="C:/gbdk/bin/romusage.exe",
                    )
                ]
            )
        )

        self._run_and_wait(
            bar,
            [
                make_runner.Command(
                    argv=(sys.executable, "-c", "print('error: x.c:3'); raise SystemExit(2)"),
                    label="make",
                    target="build",
                )
            ],
        )

        self.assertIn("error: x.c:3", bar.log_text())
        self.assertNotIn("Toolchain", bar.log_text())

    def test_the_window_hands_the_doctor_report_to_the_compile_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)
            self.addCleanup(window.close)

            self.assertIs(
                window.compile_bar._doctor_report, window.doctor_panel.report
            )

    def test_without_a_binding_nothing_can_be_started(self):
        error = project.BindingError("game_repo", "the recorded path is gone")

        bar = CompileBar(None, error)

        self.assertFalse(bar.build_button.isEnabled())
        self.assertIn("the recorded path is gone", bar.status_text())
        bar.run_build()
        self.assertFalse(bar.is_running())

    def test_the_stylesheet_colours_every_state_of_the_dot(self):
        sheet = theme.build_stylesheet()

        for state in ("busy", "pass", "fail"):
            self.assertIn(f'QLabel#compile-dot[state="{state}"]', sheet)


class TestGarageWindowCompileIntegration(unittest.TestCase):
    def test_the_compile_bar_is_in_the_window_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)
            self.addCleanup(window.close)

            self.assertIsInstance(window.compile_bar, CompileBar)
            self.assertIs(
                window.centralWidget(), window.compile_bar.parentWidget()
            )
            self.assertEqual(window.compile_bar.status_text(), "ready")

    def test_a_finished_run_refreshes_the_header(self):
        # A compile writes into the worktree, so the header's totals can be
        # stale the moment it ends.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)
            self.addCleanup(window.close)

            with mock.patch.object(window, "_refresh_header") as refresh:
                window.compile_bar.ran.emit([])

            refresh.assert_called_once()

    def test_closing_the_window_stops_a_run_in_flight(self):
        # A QThread still running when Qt tears its parent down is a crash,
        # and a compile that outlives its window is invisible work in the
        # user's worktree.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)
            window.compile_bar._start(
                [
                    make_runner.Command(
                        argv=(
                            sys.executable,
                            "-c",
                            "import time\nprint('x', flush=True)\n"
                            "while True: time.sleep(0.05)\n",
                        ),
                        label="make",
                    )
                ],
                expects_rom=False,
            )
            self.assertTrue(window.compile_bar.is_running())

            window.close()

            self.assertFalse(window.compile_bar.is_running())


class TestBudgetsPanel(unittest.TestCase):
    """R12: the four budgets, after a compile. The report itself is parsed
    and tested in tests/test_garage_core.py against real tool output; this
    covers what the panel does with it.
    """

    def _report(self):
        return budgets_core.build_report(MEMORY_CHECK_OUTPUT, BANK_REPORT_OUTPUT)

    def test_before_any_compile_it_says_so_rather_than_showing_empty_meters(self):
        panel = BudgetsPanel()

        self.assertIn("No compile yet", panel.status_text())
        self.assertEqual(panel.budget_keys(), [])

    def test_it_shows_the_four_budgets_r12_names(self):
        panel = BudgetsPanel()

        panel.set_report(self._report())

        self.assertEqual(
            panel.budget_keys(), ["wram", "vram", "oam", "rom-banks"]
        )

    def test_the_numbers_are_the_tools_numbers(self):
        # AC12: the same numbers as `make memory-check`.
        panel = BudgetsPanel()

        panel.set_report(self._report())

        self.assertEqual(panel.value_text("wram"), "1,534 / 8,192 bytes")
        self.assertEqual(panel.value_text("vram"), "76 / 384 tiles")
        self.assertEqual(panel.value_text("oam"), "32 / 40 sprites")
        self.assertEqual(panel.verdict_text("oam"), "WARN")
        self.assertEqual(panel.verdict_text("wram"), "PASS")

    def test_each_meter_carries_the_status_the_stylesheet_selects_on(self):
        panel = BudgetsPanel()

        panel.set_report(self._report())

        self.assertEqual(panel.status_of("wram"), "pass")
        self.assertEqual(panel.status_of("oam"), "warn")

    def test_an_unmeasured_budget_reads_as_blocked_with_no_numbers(self):
        panel = BudgetsPanel()

        panel.set_report(budgets_core.build_report(MEMORY_CHECK_OUTPUT, ""))

        self.assertEqual(panel.verdict_text("rom-banks"), "BLOCKED")
        self.assertEqual(panel.value_text("rom-banks"), "—")
        self.assertEqual(panel.status_of("rom-banks"), "blocked")

    def test_the_per_scene_oam_peaks_are_listed_with_the_busiest_marked(self):
        panel = BudgetsPanel()

        panel.set_report(self._report())

        rows = panel.scene_rows()
        self.assertEqual(len(rows), 7)
        self.assertTrue(any("Playing" in row and "32 / 40" in row for row in rows))
        peaks = [
            label.text()
            for label in panel.findChildren(QLabel)
            if label.objectName() == "budgets-scene"
            and label.property("peak") == "true"
        ]
        self.assertEqual(len(peaks), 1)
        self.assertIn("Playing", peaks[0])

    def test_a_second_report_replaces_the_first(self):
        panel = BudgetsPanel()
        panel.set_report(self._report())

        panel.set_report(budgets_core.build_report("", ""))

        self.assertEqual(panel.verdict_text("wram"), "BLOCKED")
        self.assertEqual(panel.scene_rows(), [])

    def test_the_stylesheet_colours_every_meter_status(self):
        sheet = theme.build_stylesheet()

        for status in ("pass", "warn", "fail", "blocked"):
            self.assertIn(f'QProgressBar#budgets-meter[status="{status}"]', sheet)
            self.assertIn(f'QLabel#budgets-verdict[status="{status}"]', sheet)


class TestCompileBarBudgets(CompileBarFixture, unittest.TestCase):
    """The compile bar reads the budgets out of what it just streamed, and
    gates Emulicious on them (R12, R13).
    """

    def _print_command(self, text, label, target):
        return make_runner.Command(
            argv=(sys.executable, "-c", f"print({text!r})"), label=label, target=target
        )

    def test_a_build_also_runs_the_two_measuring_targets(self):
        # R12 asks for budgets *after a compile*; a panel that only fills
        # in when the user presses a second button is usually stale.
        bar = self._bar()

        with mock.patch.object(make_runner, "needs_clean_build", return_value=False):
            with mock.patch.object(bar, "_start") as start:
                bar.run_build()

        self.assertEqual(
            [c.target for c in start.call_args[0][0]],
            ["build", "memory-check", "bank-post-build"],
        )

    def test_a_clean_build_runs_them_too(self):
        bar = self._bar()

        with mock.patch.object(bar, "_start") as start:
            bar.run_clean_build()

        self.assertEqual(
            [c.target for c in start.call_args[0][0]],
            ["clean", "build", "memory-check", "bank-post-build"],
        )

    def test_the_budgets_are_read_from_the_output_of_the_run(self):
        bar = self._bar()
        received = []
        bar.budgets_read.connect(received.append)

        self._run_and_wait(
            bar,
            [
                self._print_command(
                    MEMORY_CHECK_OUTPUT, "make memory-check", "memory-check"
                ),
                self._print_command(
                    BANK_REPORT_OUTPUT, "make bank-post-build", "bank-post-build"
                ),
            ],
        )

        report = bar.budget_report
        self.assertIsNotNone(report)
        self.assertEqual(report.budget("wram").used, 1534)
        self.assertEqual(report.budget("oam").status, budgets_core.WARN)
        self.assertEqual(report.budget("rom-banks").hint, "busiest ROM_1 100%")
        self.assertIn("budgets WARN", bar.status_text())
        self.assertEqual(received, [report])

    def test_a_run_that_measures_nothing_leaves_the_last_budgets_alone(self):
        # A bare `make clean` says nothing about memory; replacing good
        # numbers with blanks would be worse than keeping them.
        bar = self._bar()
        self._run_and_wait(
            bar,
            [
                self._print_command(
                    MEMORY_CHECK_OUTPUT, "make memory-check", "memory-check"
                )
            ],
        )
        first = bar.budget_report

        self._run_and_wait(
            bar, [self._print_command("cleaned", "make clean", "clean")]
        )

        self.assertIs(bar.budget_report, first)

    def test_a_bank_check_alone_leaves_the_memory_budgets_it_never_measured(self):
        # Found by pressing Bank check: the three memory rows came back
        # BLOCKED, reporting "could not be measured" about numbers the
        # panel was holding and could have shown.
        bar = self._bar()
        self._run_and_wait(
            bar,
            [
                self._print_command(
                    MEMORY_CHECK_OUTPUT, "make memory-check", "memory-check"
                )
            ],
        )

        self._run_and_wait(
            bar,
            [
                self._print_command(
                    BANK_REPORT_OUTPUT, "make bank-post-build", "bank-post-build"
                )
            ],
        )

        report = bar.budget_report
        self.assertEqual(report.budget("wram").used, 1534)
        self.assertEqual(report.budget("oam").status, budgets_core.WARN)
        self.assertEqual(report.budget("rom-banks").used, 31)

    def test_a_memory_check_alone_leaves_the_rom_banks_it_never_measured(self):
        bar = self._bar()
        self._run_and_wait(
            bar,
            [
                self._print_command(
                    BANK_REPORT_OUTPUT, "make bank-post-build", "bank-post-build"
                )
            ],
        )

        self._run_and_wait(
            bar,
            [
                self._print_command(
                    MEMORY_CHECK_OUTPUT, "make memory-check", "memory-check"
                )
            ],
        )

        self.assertEqual(bar.budget_report.budget("rom-banks").used, 31)
        self.assertEqual(bar.budget_report.budget("wram").used, 1534)

    def test_a_compile_invalidates_every_earlier_measurement(self):
        # Those numbers describe a ROM that no longer exists. Build chains
        # both measuring targets, so in the normal flow the cleared rows
        # are refilled by the same run -- here only one of them is, and the
        # other must read BLOCKED rather than stale.
        bar = self._bar()
        self._run_and_wait(
            bar,
            [
                self._print_command(
                    BANK_REPORT_OUTPUT, "make bank-post-build", "bank-post-build"
                )
            ],
        )

        self._run_and_wait(
            bar,
            [
                self._print_command("built", "make", "build"),
                self._print_command(
                    MEMORY_CHECK_OUTPUT, "make memory-check", "memory-check"
                ),
            ],
        )

        self.assertEqual(bar.budget_report.budget("wram").used, 1534)
        self.assertEqual(
            bar.budget_report.budget("rom-banks").status, budgets_core.BLOCKED
        )

    def test_output_is_attributed_to_the_target_that_printed_it(self):
        bar = self._bar()

        self._run_and_wait(
            bar,
            [
                self._print_command("from the build", "make", "build"),
                self._print_command("from the check", "make memory-check", "memory-check"),
            ],
        )

        self.assertIn("from the build", bar.output_for("build"))
        self.assertNotIn("from the check", bar.output_for("build"))
        self.assertIn("from the check", bar.output_for("memory-check"))


class TestEmuliciousGateInThePanel(CompileBarFixture, unittest.TestCase):
    """AC13: Garage does not start Emulicious when a memory budget result
    is FAIL. Every test here would start a real emulator if the gate let
    it through, so `emulicious.launch` is patched and its call count is the
    assertion.
    """

    def _rom(self):
        rom = self.worktree / "build" / "nuke-raider.gb"
        rom.parent.mkdir(parents=True, exist_ok=True)
        rom.write_bytes(b"\0")
        return rom

    def _jar(self):
        jar = tmp_root(self._tmp.name) / "Emulicious.jar"
        jar.write_text("", encoding="utf-8")
        return jar

    def _bar_with(self, memory_text, bank_text=BANK_REPORT_OUTPUT):
        bar = self._bar()
        self._rom()
        jar = self._jar()
        bar.emulicious_jar = lambda: jar
        bar._budget_report = budgets_core.build_report(memory_text, bank_text)
        return bar

    def test_a_failing_budget_does_not_start_the_emulator(self):
        over = MEMORY_CHECK_OUTPUT.replace(
            "WRAM:  1,534 / 8,192 bytes   (18%)  PASS",
            "WRAM:  8,400 / 8,192 bytes   (103%)  FAIL",
        )
        bar = self._bar_with(over)

        with mock.patch.object(emulicious, "launch") as launch:
            refusal = bar.launch_emulicious()

        launch.assert_not_called()
        self.assertIn("WRAM", refusal)
        self.assertIn("WRAM", bar.log_text())
        self.assertIn("refused", bar.status_text())

    def test_a_warn_build_does_start_the_emulator(self):
        # The build that ships today is OAM 32/40 WARN.
        bar = self._bar_with(MEMORY_CHECK_OUTPUT)

        with mock.patch.object(emulicious, "launch") as launch:
            refusal = bar.launch_emulicious()

        self.assertIsNone(refusal)
        launch.assert_called_once()
        self.assertIn("Emulicious started", bar.status_text())
        self.assertIn("-jar", bar.log_text())

    def test_no_rom_does_not_start_the_emulator(self):
        bar = self._bar()
        jar = self._jar()
        bar.emulicious_jar = lambda: jar

        with mock.patch.object(emulicious, "launch") as launch:
            refusal = bar.launch_emulicious()

        launch.assert_not_called()
        self.assertIn("Build first", refusal)

    def test_the_gate_can_be_read_without_pressing_the_button(self):
        over = MEMORY_CHECK_OUTPUT.replace(
            "OAM:   32 / 40 sprites  (80%)  WARN", "OAM:   48 / 40 sprites  (120%)  FAIL"
        )
        bar = self._bar_with(over)

        self.assertIn("OAM", bar.launch_refusal())

    def test_a_failing_budget_is_stated_in_the_status_line_after_the_run(self):
        # Before the user reaches for Launch and is told no.
        bar = self._bar()
        over = MEMORY_CHECK_OUTPUT.replace(
            "WRAM:  1,534 / 8,192 bytes   (18%)  PASS",
            "WRAM:  8,400 / 8,192 bytes   (103%)  FAIL",
        )

        self._run_and_wait(
            bar,
            [
                make_runner.Command(
                    argv=(sys.executable, "-c", f"print({over!r})"),
                    label="make memory-check",
                    target="memory-check",
                )
            ],
        )

        self.assertIn("launch blocked", bar.status_text())


class WorktreePanelFixture:
    """A real game repo with a second worktree, so the panel is exercised
    against `git worktree list` rather than a stand-in."""

    def setUp(self):
        # A cleanup rather than tearDown, for the ordering reason the
        # commit fixture explains. This panel's git calls are synchronous,
        # so cleanup errors are not ignored here: a handle still held after
        # them would be a leak worth failing on.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = tmp_root(self._tmp.name)
        self.garage_root = self.tmp_path / "nuke-raider-garage"
        self.garage_root.mkdir()
        self.game_repo = make_game_repo_with_config(
            self.tmp_path / "nuke-raider", PANEL_CONFIG_TEXT
        )
        self.binding = project.bind(self.garage_root)

    def panel(self):
        return WorktreesPanel(self.binding)

    def spike(self, panel, branch="feat/spike"):
        panel.create_worktree(branch)
        return next(
            w for w in panel.worktrees() if w.branch == branch
        )


class TestWorktreesPanel(WorktreePanelFixture, unittest.TestCase):
    def test_it_lists_the_worktrees_of_the_game_repository(self):
        panel = self.panel()

        self.assertEqual(panel.row_paths(), [str(self.binding.game_repo)])
        self.assertTrue(any("master" in row for row in panel.rows()))

    def test_a_created_worktree_appears_in_the_list_and_in_git(self):
        # AC3, through the panel the user actually presses.
        panel = self.panel()

        refusal = panel.create_worktree("feat/spike")

        self.assertIsNone(refusal)
        self.assertEqual(len(panel.row_paths()), 2)
        listed = subprocess.run(
            ["git", "-C", str(self.game_repo), "worktree", "list"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("feat-spike", listed)

    def test_an_invalid_branch_name_is_refused_in_the_status_line(self):
        panel = self.panel()

        refusal = panel.create_worktree("feat/..bad")

        self.assertIn("not a valid branch name", refusal)
        self.assertIn("not a valid branch name", panel.status_text())
        self.assertEqual(len(panel.row_paths()), 1)

    def test_deleting_the_active_worktree_is_refused_with_its_reason(self):
        # AC4, first half.
        panel = self.panel()
        active = self.binding.active_worktree

        refusal = panel.delete_worktree(active, active.path.name)

        self.assertIn("active worktree", refusal)
        self.assertIn("active worktree", panel.status_text())
        self.assertTrue(active.path.is_dir())

    def test_deleting_a_dirty_worktree_is_refused_with_its_reason(self):
        # AC4, second half.
        panel = self.panel()
        spike = self.spike(panel)
        (spike.path / "src" / "config.h").write_text(
            "#define A 1\n", encoding="utf-8"
        )

        refusal = panel.delete_worktree(spike, spike.path.name)

        self.assertIn("uncommitted work", refusal)
        self.assertTrue(spike.path.is_dir())

    def test_the_delete_button_is_disabled_before_it_is_pressed(self):
        # The refusal is computed while the row is built, so a button that
        # cannot act says so rather than failing on click.
        panel = self.panel()
        buttons = [
            b for b in panel.findChildren(QPushButton)
            if b.objectName() == "worktrees-delete"
        ]
        self.assertEqual(len(buttons), 1)  # the active/main worktree only
        self.assertFalse(buttons[0].isEnabled())
        self.assertIn("active worktree", buttons[0].toolTip())

    def test_the_name_must_be_typed_back(self):
        panel = self.panel()
        spike = self.spike(panel)

        refusal = panel.delete_worktree(spike, "wrong")

        self.assertIn("type its name exactly", refusal)
        self.assertTrue(spike.path.is_dir())

    def test_a_clean_worktree_is_deleted_and_its_branch_survives(self):
        panel = self.panel()
        spike = self.spike(panel, "feat/keep-me")

        refusal = panel.delete_worktree(spike, spike.path.name)

        self.assertIsNone(refusal)
        self.assertFalse(spike.path.is_dir())
        self.assertTrue(worktrees_core.branch_exists(self.game_repo, "feat/keep-me"))
        self.assertIn("branch is untouched", panel.status_text())

    def test_activating_emits_the_worktree(self):
        panel = self.panel()
        spike = self.spike(panel)
        received = []
        panel.activated.connect(received.append)

        panel.activate_worktree(spike)

        self.assertEqual(received, [spike])


class TestGarageWindowWorktreeSwitch(WorktreePanelFixture, unittest.TestCase):
    def _window(self):
        window = GarageWindow(garage_root=self.garage_root)
        self.addCleanup(window.close)
        return window

    def test_the_dialog_is_closed_at_launch_and_opens_from_the_menu(self):
        window = self._window()

        self.assertFalse(window.worktrees_dialog.isVisible())
        window.show_worktrees_action.trigger()
        self.assertTrue(window.worktrees_dialog.isVisible())
        window.worktrees_dialog.close()

    def test_activating_points_every_panel_at_the_new_worktree(self):
        window = self._window()
        spike = self.spike(window.worktrees_panel)

        window.activate_worktree(spike)

        for panel in (window.tuner_panel, window.diff_panel, window.compile_bar):
            self.assertEqual(panel.binding.active_worktree.path, spike.path)
        self.assertIn(str(spike.path), window.header_label.text())

    def test_the_choice_survives_a_restart(self):
        window = self._window()
        spike = self.spike(window.worktrees_panel)

        window.activate_worktree(spike)
        window.close()

        reopened = GarageWindow(garage_root=self.garage_root)
        self.addCleanup(reopened.close)
        self.assertEqual(
            reopened.binding.active_worktree.path, spike.path
        )

    def test_a_compile_in_flight_refuses_the_switch(self):
        # `make` is running in the tree Garage is about to stop pointing
        # at; its output would land in a window describing another one.
        window = self._window()
        spike = self.spike(window.worktrees_panel)
        window.compile_bar._start(
            [
                make_runner.Command(
                    argv=(
                        sys.executable,
                        "-c",
                        "import time\n"
                        "print('x', flush=True)\n"
                        "while True: time.sleep(0.05)\n",
                    ),
                    label="make",
                )
            ],
            expects_rom=False,
        )

        refusal = window.activate_worktree(spike)

        self.assertIn("compile is running", refusal)
        self.assertEqual(
            window.compile_bar.binding.active_worktree.path,
            self.binding.active_worktree.path,
        )
        window.compile_bar.stop_and_wait()


class CommitPanelFixture:
    """A real repo on a branch, with one tracked change ready to commit.
    No pre-commit hook is installed here: the hook is the game
    repository's, it takes ninety seconds, and what these tests cover is
    the panel around it -- the refusals, the streaming and the result.
    """

    def setUp(self):
        # Same two reasons as the compile-bar fixture: a stopped commit is
        # a killed process tree whose children may still hold a handle, and
        # the panel's stop_and_wait (registered in panel()) must run before
        # the repository it is committing in is deleted. tearDown runs
        # before every cleanup, so deleting the tree there is what turned a
        # failing assertion on a slow runner into an interpreter that died
        # without printing which assertion failed.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = tmp_root(self._tmp.name)
        self.garage_root = self.tmp_path / "nuke-raider-garage"
        self.garage_root.mkdir()
        self.game_repo = make_game_repo_with_config(
            self.tmp_path / "nuke-raider", PANEL_CONFIG_TEXT
        )
        self.binding = project.bind(self.garage_root)

    def on_branch(self, name="feat/tuning"):
        _run_git(["checkout", "-q", "-b", name], self.game_repo)
        self.binding = project.bind(self.garage_root)
        return self.binding

    def change_config(self):
        path = self.game_repo / "src" / "config.h"
        path.write_text(
            PANEL_CONFIG_TEXT.replace("GEAR1_MAX_SPEED        2u", "GEAR1_MAX_SPEED        7u"),
            encoding="utf-8",
        )

    def panel(self):
        panel = CommitPanel(self.binding)
        self.addCleanup(panel.stop_and_wait)
        return panel

    @staticmethod
    def wait_until(predicate, timeout_ms=20000):
        waited = 0
        while waited < timeout_ms and not predicate():
            QTest.qWait(20)
            waited += 20
        return predicate()

    def git_log(self):
        return _run_git(["log", "--format=%s"], self.game_repo).stdout


class TestCommitPanelRefusals(CommitPanelFixture, unittest.TestCase):
    def test_master_is_refused_and_the_button_says_so_before_it_is_pressed(self):
        # AC5: it refuses, and states the reason.
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")

        self.assertIn("master", panel.refusal())
        self.assertFalse(panel.commit_button.isEnabled())
        self.assertIn("master", panel.status_text())
        self.assertIn("master", panel.commit_button.toolTip())

    def test_pressing_commit_on_master_commits_nothing(self):
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")
        before = self.git_log()

        refusal = panel.commit()

        self.assertIn("master", refusal)
        self.assertFalse(panel.is_running())
        self.assertEqual(self.git_log(), before)

    def test_an_empty_message_disables_the_button_on_a_branch(self):
        self.on_branch()
        self.change_config()
        panel = self.panel()

        self.assertIn("message is required", panel.refusal())
        self.assertFalse(panel.commit_button.isEnabled())

        panel.set_message("tune the gears")

        self.assertIsNone(panel.refusal())
        self.assertTrue(panel.commit_button.isEnabled())
        self.assertIn("ready to commit", panel.status_text())

    def test_it_states_what_the_commit_would_carry(self):
        self.on_branch()
        self.change_config()
        (self.game_repo / "scratch.txt").write_text("notes", encoding="utf-8")
        panel = self.panel()

        self.assertIn("1 file", panel.pending_text())
        self.assertIn("1 untracked file will not be included", panel.pending_text())


class TestCommitPanelCommitting(CommitPanelFixture, unittest.TestCase):
    def test_a_commit_made_in_garage_appears_in_git_log(self):
        # AC6, through the panel, with the real git.
        self.on_branch()
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")
        received = []
        panel.committed.connect(received.append)

        panel.commit()

        self.assertTrue(self.wait_until(lambda: not panel.is_running()))
        self.assertIn("tune the gears", self.git_log())
        self.assertIn("tune the gears", panel.status_text())
        self.assertEqual(len(received), 1)
        self.assertIn("tune the gears", received[0])

    def test_the_message_is_cleared_and_the_panel_re_reads_the_worktree(self):
        self.on_branch()
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")

        panel.commit()
        self.assertTrue(self.wait_until(lambda: not panel.is_running()))

        self.assertEqual(panel.message(), "")
        self.assertIn("No tracked change", panel.pending_text())
        # The message is empty again, so that is the refusal now -- the
        # branch/message/nothing-to-commit order puts it first.
        self.assertIn("message is required", panel.refusal())
        self.assertFalse(panel.commit_button.isEnabled())

    def test_the_command_is_echoed_and_gits_output_is_shown(self):
        # R6: the verification's output arrives in the log. Here the hook
        # is absent, so what is proven is that git's own output lands
        # there, through the path the hook's output takes.
        self.on_branch()
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")

        panel.commit()
        self.assertTrue(self.wait_until(lambda: not panel.is_running()))

        self.assertIn("$ git commit -a", panel.log_text())
        self.assertIn("1 file changed", panel.log_text())

    def test_a_commit_git_rejects_is_reported_and_nothing_is_committed(self):
        self.on_branch()
        panel = self.panel()
        # Nothing changed, so git exits 1. The panel's own refusal would
        # normally catch this first; bypassing it exercises the failure
        # path a pre-commit hook takes when it rejects the commit.
        panel.set_message("nothing here")
        panel._summary = None
        before = self.git_log()

        panel.commit()

        self.assertTrue(self.wait_until(lambda: not panel.is_running()))
        self.assertIn("refused by git", panel.status_text())
        self.assertEqual(self.git_log(), before)

    def test_the_buttons_swap_while_the_verification_runs(self):
        self.on_branch()
        self.change_config()
        panel = self.panel()
        panel.set_message("tune the gears")

        panel.commit()

        # Between start and finish the message is read-only: it is the
        # message git is already using.
        if panel.is_running():
            self.assertFalse(panel.commit_button.isEnabled())
            self.assertTrue(panel.stop_button.isEnabled())
            self.assertTrue(panel.message_edit.isReadOnly())
        self.assertTrue(self.wait_until(lambda: not panel.is_running()))
        self.assertFalse(panel.stop_button.isEnabled())
        self.assertFalse(panel.message_edit.isReadOnly())


class TestCommitPanelStopLeavesTheWorktreeUsable(
    CommitPanelFixture, unittest.TestCase
):
    """The sequence the user hit: Stop during the verification, then
    Build. Garage kills the process tree, git never gets to release the
    index lock it took while staging, and every later git write in that
    worktree fails with "Another git process seems to be running".
    """

    # Long enough that the stop lands mid-verification, short enough that
    # the test cannot outlive it: killing git does not always close the
    # pipe that its hook's children inherited, so the reader can stay
    # blocked until the hook itself exits.
    SLOW_HOOK = '#!/bin/sh\ntouch "%s"\nsleep 5\n'

    def install_slow_hook(self):
        """Install a hook that is slow, and that says it ran.

        The marker exists because a Windows CI runner failed the lock wait
        below and the message could not say which half broke: a lock that
        was never taken because the hook never ran looks nothing like a
        lock that came and went between two twenty-millisecond polls, and
        the fix is different in each case.
        """
        hooks = self.game_repo / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        self.hook_marker = hooks / "pre-commit-ran"
        hook = hooks / "pre-commit"
        hook.write_text(
            self.SLOW_HOOK % self.hook_marker.as_posix(), encoding="utf-8"
        )
        return hook

    def wait_for_lock(self, panel, lock):
        """Wait for git to take the index lock, and explain a timeout.

        git stages the `-a` changes into the lock before it runs the hook,
        so stopping earlier than this would prove nothing about the
        cleanup. Everything the failure needs is in the panel and on disk;
        a bare assertTrue threw all of it away.
        """
        if self.wait_until(lambda: lock.exists(), 15000):
            return
        self.fail(
            "git never took the index lock at {}\n"
            "  hook marker exists: {}\n"
            "  panel still running: {}\n"
            "  panel status: {}\n"
            "  panel log:\n{}".format(
                lock,
                getattr(self, "hook_marker", None)
                and self.hook_marker.exists(),
                panel.is_running(),
                panel.status_text(),
                panel.log_text(),
            )
        )

    def test_stopping_a_commit_leaves_no_lock_behind(self):
        self.on_branch()
        self.change_config()
        hook = self.install_slow_hook()
        panel = self.panel()
        panel.set_message("tune the gears")

        lock = commit_core.git_dir(self.game_repo) / "index.lock"
        panel.commit()
        # Wait for git to actually take the lock -- it stages the -a
        # changes into index.lock *before* running the hook, and stopping
        # earlier than that would prove nothing about the cleanup.
        self.wait_for_lock(panel, lock)
        panel.stop()
        self.assertTrue(self.wait_until(lambda: not panel.is_running()))

        self.assertIn("stopped", panel.status_text())
        self.assertFalse(lock.exists(), "the killed commit left its index lock")
        self.assertIn("index.lock", panel.log_text())

        # The real proof: git can write again. Without the cleanup this
        # fails with "Unable to create ... index.lock: File exists".
        hook.unlink()
        after = make_runner.run(
            commit_core.commit_command("after the stop"),
            self.game_repo,
            lambda line: None,
        )
        self.assertTrue(after.ok)
        self.assertIn("after the stop", self.git_log())

    def test_nothing_is_committed_by_the_stopped_run(self):
        self.on_branch()
        self.change_config()
        self.install_slow_hook()
        panel = self.panel()
        panel.set_message("tune the gears")
        before = self.git_log()

        lock = commit_core.git_dir(self.game_repo) / "index.lock"
        panel.commit()
        self.wait_for_lock(panel, lock)
        panel.stop()
        self.assertTrue(self.wait_until(lambda: not panel.is_running()))

        self.assertEqual(self.git_log(), before)

    def test_closing_the_window_mid_commit_cleans_up_too(self):
        # `_on_done` never runs on this path -- its signal is queued to an
        # event loop that is going away -- so the cleanup has to happen in
        # stop_and_wait as well.
        self.on_branch()
        self.change_config()
        self.install_slow_hook()
        panel = CommitPanel(self.binding)
        panel.set_message("tune the gears")

        lock = commit_core.git_dir(self.game_repo) / "index.lock"
        panel.commit()
        self.wait_for_lock(panel, lock)

        panel.stop_and_wait()

        self.assertFalse(lock.exists())


class TestGarageWindowCommitIntegration(CommitPanelFixture, unittest.TestCase):
    def _window(self):
        window = GarageWindow(garage_root=self.garage_root)
        self.addCleanup(window.close)
        return window

    def test_the_dialog_is_closed_at_launch_and_opens_from_the_menu(self):
        window = self._window()

        self.assertFalse(window.commit_dialog.isVisible())
        window.show_commit_action.trigger()
        self.assertTrue(window.commit_dialog.isVisible())
        window.commit_dialog.close()

    def test_a_commit_refreshes_the_header(self):
        window = self._window()

        with mock.patch.object(window, "_refresh_header") as refresh:
            window.commit_panel.committed.emit("abc1234 tune the gears")

        refresh.assert_called_once()

    def test_the_commit_panel_follows_a_worktree_switch(self):
        window = self._window()
        window.worktrees_panel.create_worktree("feat/other")
        spike = next(
            w for w in window.worktrees_panel.worktrees() if w.branch == "feat/other"
        )

        window.activate_worktree(spike)

        self.assertEqual(
            window.commit_panel.binding.active_worktree.path, spike.path
        )
        # And on a branch that is not master, it is no longer refused for
        # that reason.
        window.commit_panel.set_message("a message")
        self.assertNotIn("master", window.commit_panel.refusal() or "")


if __name__ == "__main__":
    unittest.main()
