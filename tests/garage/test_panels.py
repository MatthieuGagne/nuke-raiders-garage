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

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from tools.garage.app import GarageWindow, format_header
from tools.garage.core import config_io, diff as diff_core, project
from tools.garage.core.schema import Schema
from tools.garage.panels.diff_view import DiffPanel
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

    def test_racer_hp_row_shows_its_derived_dependent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            config_path = binding.config_h
            self.assertNotEqual(config_path, Path("C:/Code/nuke-raider/src/config.h"))

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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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

            self.assertEqual(row.spin.value(), 9)  # value currently on disk
            self.assertEqual(row.head_value, 2)  # committed value
            self.assertTrue(row.differs_from_head())
            self.assertIn("2", row.head_label.text())
            self.assertFalse(row.head_label.isHidden())
            self.assertFalse(row.revert_button.isHidden())

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

    def test_per_row_revert_writes_head_value_at_once(self):
        # A row that has been hand-edited (or written by a previous
        # session) differs from HEAD from launch. Revert restores it and
        # writes it -- there is no "pending" state to clear first.
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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            binding, schema = make_panel_binding(tmp_path)
            panel = TunerPanel(binding, schema=schema)

            with mock.patch(
                "tools.garage.panels.tuner.config_io.write"
            ) as write_spy:
                panel.revert_all()

            write_spy.assert_not_called()

    def test_revert_all_button_wired_to_revert_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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


# -- R19/AC19/AC2: diff panel, header dirty mark and master warning --------


class TestDiffPanel(unittest.TestCase):
    def test_clean_worktree_shows_clean_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding, _schema = make_panel_binding(tmp_path)

            panel = DiffPanel(binding)

            self.assertIn("clean", panel.status_text().lower())
            self.assertEqual(panel.file_paths(), [])
            self.assertEqual(panel.untracked_files(), [])

    def test_modified_file_shows_hunks_and_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            binding, _schema = make_panel_binding(tmp_path)

            panel = DiffPanel(binding)
            self.assertEqual(panel.untracked_files(), [])

            (binding.game_repo / "new.txt").write_text("hi\n", encoding="utf-8")
            panel.refresh()

            self.assertEqual(panel.untracked_files(), ["new.txt"])


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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=1, added_lines=5, removed_lines=5
            )

            text = format_header(binding, None, summary)

            self.assertIn("1 file +5 −5 · 1 untracked", text)

    def test_untracked_absent_omits_the_untracked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=5, removed_lines=5
            )

            text = format_header(binding, None, summary)

            self.assertNotIn("untracked", text)

    def test_master_appends_commit_blocked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding = self._binding_on(tmp_path, "master")
            summary = diff_core.ChangeSummary(
                changed_file_count=0, untracked_count=0, added_lines=0, removed_lines=0
            )

            text = format_header(binding, None, summary)

            self.assertIn("commit blocked on master", text)

    def test_off_master_omits_commit_blocked_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binding = self._binding_on(tmp_path, "feat")
            summary = diff_core.ChangeSummary(
                changed_file_count=1, untracked_count=0, added_lines=1, removed_lines=1
            )

            text = format_header(binding, None, summary)

            self.assertNotIn("commit blocked", text.lower())

    def test_dirty_master_still_shows_mark_and_commit_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)

            self.assertIsInstance(window.diff_panel, DiffPanel)
            self.assertFalse(window.diff_dialog.isVisible())

    def test_menu_action_opens_diff_dialog_and_it_can_be_closed_and_reopened(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            self.assertIs(window.centralWidget(), window.tuner_panel.parentWidget())
            self.assertTrue(window.tuner_panel.isEnabled())

            window.show_diff_action.trigger()
            self.assertTrue(window.diff_dialog.isVisible())

    def test_ac20_header_reads_no_changes_and_untracked_for_untracked_only_tree(self):
        # AC20 against a real bound repository: two untracked files, no
        # tracked change at all. The "●" mark stands for a tracked file
        # differing from HEAD, so it must not appear here; "no changes"
        # names the tracked state, "2 untracked" the rest.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider")

            window = GarageWindow(garage_root=garage_root)

            self.assertIn("commit blocked", window.header_label.text().lower())

    def test_tuner_write_refreshes_header_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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
            tmp_path = Path(tmp)
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


if __name__ == "__main__":
    unittest.main()
