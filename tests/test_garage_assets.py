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

from tools.garage.core import assets, preview, project

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


# ── PNG fixtures ─────────────────────────────────────────────────────────
# Written by hand rather than by an imaging library: this suite runs under
# `make test`, whose whole point is that it needs nothing installed.


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def write_indexed_png(path: Path, width: int, height: int, palette_size: int,
                      pixels=None) -> Path:
    """An 8-bit indexed PNG (colour type 3) with `palette_size` PLTE
    entries. `pixels` is a flat row-major list of palette indices; None
    means every pixel is index 0."""
    if pixels is None:
        pixels = [0] * (width * height)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    plte = b"".join(bytes(((i * 37) % 256,) * 3) for i in range(palette_size))
    raw = b"".join(
        b"\x00" + bytes(pixels[y * width:(y + 1) * width]) for y in range(height)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"PLTE", plte)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )
    return path


def write_rgb_png(path: Path, width: int, height: int, greys) -> Path:
    """A truecolour PNG (colour type 2). `greys` is a list of grey levels;
    pixel (x, y) takes greys[(y * width + x) % len(greys)], so an image
    with N distinct luminances is one call."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            level = greys[(y * width + x) % len(greys)]
            row += bytes((level, level, level))
        rows.append(bytes(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + _png_chunk(b"IEND", b"")
    )
    return path


# The real converter, copied into a fixture worktree so these tests
# exercise the code Garage will actually load. Resolved through a binding
# (R13); the tests skip when this checkout has no game repository beside
# it, which is the CI case AC12 protects.
def _bound_png_to_tiles():
    try:
        path = project.bind().resolve("tools", "png_to_tiles.py")
    except project.BindingError:
        return None
    return path if path.is_file() else None


REAL_PNG_TO_TILES = _bound_png_to_tiles()
NO_GAME_REPO = REAL_PNG_TO_TILES is None
NO_GAME_REPO_REASON = "no game repository is bound beside this checkout"


def make_repo_with_converters(root: Path) -> Path:
    """A fixture game repository holding the real png_to_tiles.py."""
    repo = make_game_repo(root / "nuke-raider")
    target = repo / "tools" / "png_to_tiles.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(REAL_PNG_TO_TILES.read_bytes())
    return repo


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestReadPng(unittest.TestCase):
    """R2/R3: the pixels, the tile cost and the colour count come from the
    active worktree's own png_to_tiles.py, so AC3 holds by construction."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_repo_with_converters(self.root)
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_reports_the_size_and_the_tile_cost(self):
        png = write_indexed_png(self.repo / "assets/sprites/car.png", 16, 8, 4)

        facts = preview.read_png(self.binding, png)

        self.assertIsNone(facts.error)
        self.assertEqual((facts.width, facts.height), (16, 8))
        self.assertEqual((facts.tiles_x, facts.tiles_y), (2, 1))
        self.assertEqual(facts.tile_count, 2)

    def test_the_pixels_are_game_boy_palette_indices(self):
        png = write_indexed_png(
            self.repo / "assets/sprites/car.png", 8, 8,
            palette_size=4, pixels=[i % 4 for i in range(64)],
        )

        facts = preview.read_png(self.binding, png)

        self.assertEqual(len(facts.pixels), 64)
        self.assertEqual(set(facts.pixels), {0, 1, 2, 3})

    def test_a_palette_of_seven_reports_seven_colours(self):
        """AC4 asks Garage to name the colour count. For an indexed PNG
        the count that means something to the user is how many entries the
        palette holds."""
        png = write_indexed_png(self.repo / "assets/sprites/car.png", 8, 8, 7)

        facts = preview.read_png(self.binding, png)

        self.assertEqual(facts.colour_count, 7)

    def test_an_rgb_png_with_seven_greys_reports_the_converter_message(self):
        png = write_rgb_png(
            self.repo / "assets/sprites/car.png", 8, 8,
            greys=[0, 30, 60, 90, 120, 150, 180],
        )

        facts = preview.read_png(self.binding, png)

        self.assertIsNotNone(facts.error)
        self.assertIn("7 distinct luminance values", facts.error)
        self.assertEqual(facts.colour_count, 7)

    def test_a_missing_converter_is_a_named_failure_not_a_crash(self):
        (self.repo / "tools" / "png_to_tiles.py").unlink()
        png = write_indexed_png(self.repo / "assets/sprites/car.png", 8, 8, 4)

        with self.assertRaises(preview.ConverterUnavailable) as caught:
            preview.read_png(self.binding, png)

        self.assertIn("png_to_tiles.py", str(caught.exception))

    def test_the_tile_count_matches_what_png_to_tiles_writes(self):
        """AC3, proven against the converter's own output rather than
        against a second copy of its arithmetic."""
        png = write_indexed_png(self.repo / "assets/sprites/car.png", 24, 16, 4)
        out = self.repo / "src" / "car.c"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, "tools/png_to_tiles.py", "--bank", "255",
             "assets/sprites/car.png", "src/car.c", "car_tile_data"],
            cwd=str(self.repo), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        written = out.read_text(encoding="utf-8")

        facts = preview.read_png(self.binding, png)

        self.assertIn(f"car_tile_data_count = {facts.tile_count}u;", written)


class TestReadTmx(unittest.TestCase):
    """R3: the size of each map. Plain XML -- no converter needed."""

    def test_it_reports_the_map_size_in_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "track.tmx"
            path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<map version="1.10" orientation="orthogonal" width="64" '
                'height="32" tilewidth="8" tileheight="8"></map>\n',
                encoding="utf-8",
            )

            facts = preview.read_tmx(path)

            self.assertIsNone(facts.error)
            self.assertEqual((facts.width, facts.height), (64, 32))
            self.assertEqual((facts.tile_width, facts.tile_height), (8, 8))

    def test_unparsable_xml_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "broken.tmx"
            path.write_text("<map width=", encoding="utf-8")

            facts = preview.read_tmx(path)

            self.assertIsNotNone(facts.error)
            self.assertIsNone(facts.width)


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestVerify(unittest.TestCase):
    """R4: verify before a converter runs, and say which limit is
    exceeded. R5's refusal is built on `Verification.ok`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_repo_with_converters(self.root)
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def _asset(self, relative: str) -> assets.Asset:
        found = [a for a in assets.discover(self.binding)
                 if a.relative_path == relative]
        self.assertEqual(len(found), 1, f"{relative} not discovered")
        return found[0]

    def test_a_clean_sprite_passes(self):
        write_indexed_png(self.repo / "assets/sprites/car.png", 16, 8, 4)

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertTrue(result.ok)
        self.assertEqual(result.problems, [])
        self.assertEqual(result.png.tile_count, 2)

    def test_five_colours_fails_and_names_the_count(self):
        """AC4."""
        write_indexed_png(self.repo / "assets/sprites/car.png", 8, 8, 5)

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        problem = result.problems[0]
        self.assertEqual(problem.code, assets.PROBLEM_COLOURS)
        self.assertIn("5", problem.message)
        self.assertIn("4", problem.limit)

    def test_an_rgb_png_with_seven_greys_fails_and_names_the_count(self):
        write_rgb_png(self.repo / "assets/sprites/car.png", 8, 8,
                      greys=[0, 30, 60, 90, 120, 150, 180])

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        self.assertEqual(result.problems[0].code, assets.PROBLEM_COLOURS)
        self.assertIn("7", result.problems[0].message)

    def test_a_size_that_is_not_a_multiple_of_eight_fails(self):
        write_indexed_png(self.repo / "assets/sprites/car.png", 12, 8, 4)

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        problem = result.problems[0]
        self.assertEqual(problem.code, assets.PROBLEM_DIMENSIONS)
        self.assertIn("12", problem.message)
        self.assertIn("8", problem.limit)

    def test_a_tileset_over_the_vram_budget_fails_and_names_the_cost(self):
        # 200 tiles: 200 x 1 tiles, past png_to_tiles' 192-tile limit.
        write_indexed_png(self.repo / "assets/tiles/big.png", 1600, 8, 4)

        result = assets.verify(self.binding, self._asset("assets/tiles/big.png"))

        self.assertFalse(result.ok)
        problem = [p for p in result.problems
                   if p.code == assets.PROBLEM_TILE_COST][0]
        self.assertIn("200", problem.message)
        self.assertIn("192", problem.limit)

    def test_a_map_reports_its_size_and_passes(self):
        (self.repo / "assets/maps").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/maps/track.tmx").write_text(
            '<map width="64" height="32" tilewidth="8" tileheight="8"></map>',
            encoding="utf-8",
        )

        result = assets.verify(self.binding, self._asset("assets/maps/track.tmx"))

        self.assertTrue(result.ok)
        self.assertEqual((result.tmx.width, result.tmx.height), (64, 32))

    def test_a_broken_map_fails(self):
        (self.repo / "assets/maps").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/maps/track.tmx").write_text("<map", encoding="utf-8")

        result = assets.verify(self.binding, self._asset("assets/maps/track.tmx"))

        self.assertFalse(result.ok)
        self.assertEqual(result.problems[0].code, assets.PROBLEM_UNREADABLE)

    def test_music_needs_no_pre_flight(self):
        """R11: the validators are the check for a .uge, and they run
        after the user has been in the editor -- there is nothing Garage
        can verify about the binary beforehand."""
        (self.repo / "assets/music").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/music/song.uge").write_bytes(b"\x00\x01")

        result = assets.verify(self.binding, self._asset("assets/music/song.uge"))

        self.assertTrue(result.ok)

    def test_a_missing_converter_is_reported_as_a_problem_not_a_crash(self):
        write_indexed_png(self.repo / "assets/sprites/car.png", 8, 8, 4)
        (self.repo / "tools" / "png_to_tiles.py").unlink()

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        self.assertEqual(result.problems[0].code, assets.PROBLEM_CONVERTER)
        self.assertIn("png_to_tiles.py", result.problems[0].message)

    def test_the_summary_names_every_problem(self):
        write_indexed_png(self.repo / "assets/sprites/car.png", 12, 8, 5)

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        summary = result.summary()
        self.assertIn("5", summary)
        self.assertIn("12", summary)


if __name__ == "__main__":
    unittest.main()
