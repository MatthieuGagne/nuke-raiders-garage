"""Core coverage for the asset panel (spec P2, issue #3).

No PySide6 import belongs in this file, directly or transitively: it is
reached by `make test`, which AC12 requires to pass on a machine with no
Qt installed. Panel coverage lives in tests/garage/test_panels_assets.py.

Fixtures build real directories and real PNG bytes in a temp directory.
Nothing here hardcodes a path into a checkout: a path spelled out in a
test is a path that exists on one machine, and P1 shipped one that turned
three CI skips into three CI failures.
"""
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.garage.core import assets, project

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it -- see the
    same helper in tests/test_garage_core.py for why `resolve()` matters
    on Windows."""
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, files: dict = None) -> Path:
    """A real git repository at `path` holding `files` (relative posix
    path -> text), with the game repository's origin remote so
    `project.bind` accepts it."""
    path.mkdir(parents=True, exist_ok=True)
    for rel, text in (files or {}).items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def bind_over(tmp_path: Path, game_repo: Path) -> project.Binding:
    """A Binding whose game repository is `game_repo`, recorded in a
    garage.local.json under a throwaway garage root."""
    garage_root = tmp_path / "nuke-raider-garage"
    garage_root.mkdir(exist_ok=True)
    project.save_settings(
        garage_root,
        {
            "game_repo": game_repo.as_posix(),
            "worktree_root": (tmp_path / "worktrees").as_posix(),
            "active": None,
        },
    )
    return project.bind(garage_root)


class TestClassify(unittest.TestCase):
    """R1: sprites, tiles, maps and music. AC1 says *every* file under
    assets/ lands in a group, so anything that is none of the four gets
    KIND_OTHER rather than being dropped."""

    def test_a_png_under_sprites_is_a_sprite(self):
        self.assertEqual(
            assets.classify("assets/sprites/player_car.png"), assets.KIND_SPRITES
        )

    def test_an_aseprite_source_under_sprites_is_still_a_sprite(self):
        self.assertEqual(
            assets.classify("assets/sprites/player_car.aseprite"),
            assets.KIND_SPRITES,
        )

    def test_a_png_under_maps_is_a_tileset(self):
        """The tilesets live beside the maps they belong to; the
        prototype's Assets screen shows tileset.png under Tiles."""
        self.assertEqual(
            assets.classify("assets/maps/tileset.png"), assets.KIND_TILES
        )

    def test_a_file_under_tiles_is_a_tileset(self):
        self.assertEqual(
            assets.classify("assets/tiles/extra.png"), assets.KIND_TILES
        )

    def test_a_tmx_is_a_map(self):
        self.assertEqual(assets.classify("assets/maps/track.tmx"), assets.KIND_MAPS)

    def test_a_uge_is_music(self):
        self.assertEqual(
            assets.classify("assets/music/BeepBox-Song.uge"), assets.KIND_MUSIC
        )

    def test_a_mid_is_music(self):
        self.assertEqual(
            assets.classify("assets/music/BeepBox-Song.mid"), assets.KIND_MUSIC
        )

    def test_dialog_json_is_other_not_dropped(self):
        self.assertEqual(
            assets.classify("assets/dialog/npcs.json"), assets.KIND_OTHER
        )

    def test_a_reference_image_is_other(self):
        self.assertEqual(
            assets.classify("assets/reference/micro-machines/v01_race01.png"),
            assets.KIND_OTHER,
        )


class TestDiscover(unittest.TestCase):
    def test_it_lists_every_file_under_assets_of_the_active_worktree(self):
        """AC1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(
                root / "nuke-raider",
                {
                    "assets/sprites/player_car.png": "x",
                    "assets/sprites/notes.txt": "x",
                    "assets/maps/track.tmx": "x",
                    "assets/maps/tileset.png": "x",
                    "assets/music/song.uge": "x",
                    "assets/dialog/npcs.json": "{}",
                    "src/main.c": "int main(void){return 0;}",
                },
            )
            binding = bind_over(root, repo)

            found = assets.discover(binding)

            self.assertEqual(
                sorted(a.relative_path for a in found),
                [
                    "assets/dialog/npcs.json",
                    "assets/maps/tileset.png",
                    "assets/maps/track.tmx",
                    "assets/music/song.uge",
                    "assets/sprites/notes.txt",
                    "assets/sprites/player_car.png",
                ],
            )

    def test_it_lists_nothing_and_does_not_raise_without_an_assets_dir(self):
        """A worktree checked out without assets/ is a state Garage must
        report, not crash on."""
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(root / "nuke-raider", {"src/main.c": "x"})
            binding = bind_over(root, repo)

            self.assertEqual(assets.discover(binding), [])

    def test_each_asset_carries_its_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(
                root / "nuke-raider", {"assets/sprites/a.png": "abcde"}
            )
            binding = bind_over(root, repo)

            asset = assets.discover(binding)[0]

            self.assertEqual(asset.size_bytes, 5)
            self.assertGreater(asset.mtime_ns, 0)
            self.assertEqual(asset.name, "a.png")

    def test_group_by_kind_returns_every_kind_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(
                root / "nuke-raider",
                {"assets/sprites/a.png": "x", "assets/music/b.uge": "x"},
            )
            binding = bind_over(root, repo)

            groups = assets.group_by_kind(assets.discover(binding))

            self.assertEqual(list(groups), list(assets.KIND_ORDER))
            self.assertEqual(
                [a.name for a in groups[assets.KIND_SPRITES]], ["a.png"]
            )
            self.assertEqual([a.name for a in groups[assets.KIND_MAPS]], [])


if __name__ == "__main__":
    unittest.main()
