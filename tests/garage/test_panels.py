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

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtWidgets import QApplication

from tools.garage.app import GarageWindow

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


if __name__ == "__main__":
    unittest.main()
