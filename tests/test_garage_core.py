"""Coverage for tools/garage/core/project.py.

No Qt import anywhere in this file. Must pass with PySide6 absent.

Fixtures build real git repositories in a temp directory with `git init`,
`git remote add` and `git worktree add` -- git output is not mocked as
strings for the happy-path cases.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the repository root importable regardless of the test runner's cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import project  # noqa: E402


GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"
WRONG_REMOTE_URL = "https://github.com/someone/unrelated-repo.git"


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def make_game_repo(path: Path, remote_url=GAME_REPO_REMOTE_URL) -> Path:
    """Create a real git repository at `path` with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    if remote_url:
        _run_git(["remote", "add", "origin", remote_url], path)
    return path


class TestFindDefaultGameRepo(unittest.TestCase):
    def test_detect_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            found = project.find_default_game_repo(garage_root)

            self.assertEqual(found.resolve(), game_repo.resolve())

    def test_wrong_remote_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", remote_url=WRONG_REMOTE_URL)

            with self.assertRaises(project.BindingError) as ctx:
                project.find_default_game_repo(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")
            self.assertIn("remote", ctx.exception.message.lower())

    def test_missing_sibling_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # No sibling "nuke-raider" directory created.

            with self.assertRaises(project.BindingError) as ctx:
                project.find_default_game_repo(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")


class TestBind(unittest.TestCase):
    def test_first_run_writes_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            settings_path = garage_root / "garage.local.json"
            self.assertFalse(settings_path.exists())

            binding = project.bind(garage_root)

            self.assertTrue(settings_path.exists())
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn("game_repo", data)
            self.assertIn("worktree_root", data)
            self.assertIn("active", data)
            self.assertEqual(Path(data["game_repo"]).resolve(), game_repo.resolve())
            self.assertEqual(
                Path(data["worktree_root"]).resolve(),
                (game_repo.parent / "worktrees").resolve(),
            )
            self.assertIsNone(data["active"])

            self.assertEqual(binding.game_repo.resolve(), game_repo.resolve())
            self.assertEqual(binding.active_source, "main-fallback")
            self.assertEqual(binding.active_worktree.branch, "master")

    def test_missing_recorded_path_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            # game_repo sibling deliberately absent; recorded path points
            # at a directory that does not exist.
            bad_path = tmp_path / "does-not-exist"
            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": bad_path.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(project.BindingError) as ctx:
                project.bind(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")
            self.assertIn("game_repo", ctx.exception.message)

    def test_recorded_path_with_wrong_checkout_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            wrong_repo = make_game_repo(tmp_path / "other-repo", remote_url=WRONG_REMOTE_URL)

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": wrong_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(project.BindingError) as ctx:
                project.bind(garage_root)
            self.assertEqual(ctx.exception.key, "game_repo")

    def test_stale_active_falls_back_to_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        # Points at a worktree that was never created.
                        "active": str(tmp_path / "worktrees" / "ghost"),
                    }
                ),
                encoding="utf-8",
            )

            binding = project.bind(garage_root)

            self.assertEqual(binding.active_source, "main-fallback")
            self.assertEqual(binding.active_worktree.path.resolve(), game_repo.resolve())

    def test_recorded_active_worktree_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            wt_path = tmp_path / "worktrees" / "feat"
            _run_git(["worktree", "add", "-b", "feat", str(wt_path)], game_repo)

            settings_path = garage_root / "garage.local.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "game_repo": game_repo.as_posix(),
                        "worktree_root": (tmp_path / "worktrees").as_posix(),
                        "active": wt_path.as_posix(),
                    }
                ),
                encoding="utf-8",
            )

            binding = project.bind(garage_root)

            self.assertEqual(binding.active_source, "recorded")
            self.assertEqual(binding.active_worktree.path.resolve(), wt_path.resolve())
            self.assertEqual(binding.active_worktree.branch, "feat")


class TestListWorktrees(unittest.TestCase):
    def test_parses_main_and_linked_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            wt_path = tmp_path / "worktrees" / "feat"
            _run_git(["worktree", "add", "-b", "feat", str(wt_path)], game_repo)

            worktrees = project.list_worktrees(game_repo)

            self.assertEqual(len(worktrees), 2)
            self.assertEqual(worktrees[0].path.resolve(), game_repo.resolve())
            self.assertEqual(worktrees[0].branch, "master")
            self.assertFalse(worktrees[0].detached)
            self.assertTrue(worktrees[0].head)

            self.assertEqual(worktrees[1].path.resolve(), wt_path.resolve())
            self.assertEqual(worktrees[1].branch, "feat")
            self.assertFalse(worktrees[1].detached)

    def test_detached_head_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_repo = make_game_repo(tmp_path / "nuke-raider")
            head_sha = _run_git(["rev-parse", "HEAD"], game_repo).stdout.strip()
            wt_path = tmp_path / "worktrees" / "detached"
            _run_git(["worktree", "add", "--detach", str(wt_path), head_sha], game_repo)

            worktrees = project.list_worktrees(game_repo)

            detached_entries = [w for w in worktrees if w.path.resolve() == wt_path.resolve()]
            self.assertEqual(len(detached_entries), 1)
            entry = detached_entries[0]
            self.assertTrue(entry.detached)
            self.assertIsNone(entry.branch)
            self.assertEqual(entry.head, head_sha)


class TestBindingPathHelpers(unittest.TestCase):
    def test_config_h_and_build_dir_resolve_inside_active_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            game_repo = make_game_repo(tmp_path / "nuke-raider")

            binding = project.bind(garage_root)

            self.assertEqual(
                binding.config_h.resolve(),
                (game_repo / "src" / "config.h").resolve(),
            )
            self.assertEqual(
                binding.build_dir.resolve(),
                (game_repo / "build").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
