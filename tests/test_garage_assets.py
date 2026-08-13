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

from tools.garage.core import assets, pipeline, preview, project

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
        """AC4, and the oversized-palette case: a palette declaring more
        entries than the pixels use decodes cleanly, so the converter
        accepts it and Garage is the one that refuses."""
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

    def test_pixels_that_genuinely_use_five_colours_fail(self):
        """AC4's other half. The test above covers a palette that declares
        more entries than the pixels use, which decodes cleanly; this one
        uses index 4 for real, so the converter itself refuses."""
        write_indexed_png(self.repo / "assets/sprites/car.png", 8, 8, 5,
                          pixels=[4] + [0] * 63)

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        problem = result.problems[0]
        self.assertEqual(problem.code, assets.PROBLEM_COLOURS)
        self.assertIn("5", problem.message)

    def test_an_unsupported_png_format_is_unreadable_not_a_colour_problem(self):
        """A broken *asset* that is not a colour problem takes the other
        branch. Without this the `looks_like_colours` heuristic could
        misroute every read failure into a colour message and no test
        would notice."""
        path = self.repo / "assets/sprites/car.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Greyscale (colour type 0) -- a real PNG that png_to_tiles does not
        # accept, and one with no palette, so no colour count exists.
        ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0)
        raw = b"".join(b"\x00" + bytes([0] * 8) for _ in range(8))
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw))
            + _png_chunk(b"IEND", b"")
        )

        result = assets.verify(self.binding, self._asset("assets/sprites/car.png"))

        self.assertFalse(result.ok)
        self.assertEqual(result.problems[0].code, assets.PROBLEM_UNREADABLE)

    def test_an_editor_source_beside_a_sprite_has_nothing_to_verify(self):
        """A .aseprite is what the artist edits, not what a converter
        reads. It is listed, and it passes, because there is no limit for
        it to exceed."""
        (self.repo / "assets/sprites").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/sprites/car.aseprite").write_bytes(b"\x00\x01")

        result = assets.verify(
            self.binding, self._asset("assets/sprites/car.aseprite")
        )

        self.assertTrue(result.ok)
        self.assertIsNone(result.png)

    def test_an_other_kind_asset_has_nothing_to_verify(self):
        (self.repo / "assets/dialog").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/dialog/npcs.json").write_text("{}", encoding="utf-8")

        result = assets.verify(
            self.binding, self._asset("assets/dialog/npcs.json")
        )

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


# A Makefile fragment in the shape the game repository actually uses: a
# continuation, several targets on one rule, an order-only prerequisite, a
# recipe-less rule declaring side-effect outputs, an aseprite export rule
# whose target is another asset, and a `$(TARGET):` line with no recipe.
SAMPLE_MAKEFILE = """\
SHELL := bash
BUILD_DIR ?= build
TARGET := $(BUILD_DIR)/nuke-raider.gb

.PHONY: all clean memory-check sprites

all: hooks $(TARGET)

memory-check:
\tpython tools/memory_check.py

sprites: src/player_sprite.c

build/track_rotation_manifest.json: \\
    assets/maps/track.tmx assets/maps/track2.tmx \\
    tools/tmx_to_c.py | build
\tpython tools/tmx_to_c.py --emit-rotation-manifest $@ \\
\t    assets/maps/track.tmx assets/maps/track2.tmx

build/track_tile_id_map.json src/track_tileset_meta.h: src/track_tiles.c

src/track_tiles.c: \\
    assets/maps/tileset.png assets/maps/track.tsx \\
    build/track_rotation_manifest.json tools/png_to_tiles.py | build
\tpython tools/png_to_tiles.py --bank 255 \\
\t    --rotation-manifest build/track_rotation_manifest.json \\
\t    assets/maps/tileset.png src/track_tiles.c track_tile_data

src/track_map.c: assets/maps/track.tmx build/track_tile_id_map.json tools/tmx_to_c.py
\tpython tools/tmx_to_c.py --id-map build/track_tile_id_map.json \\
\t    assets/maps/track.tmx src/track_map.c

src/player_sprite.c: assets/sprites/player_car.png tools/png_to_tiles.py
\tpython tools/png_to_tiles.py --bank 255 assets/sprites/player_car.png src/player_sprite.c player_tile_data

$(TARGET): src/player_sprite.c

assets/maps/tileset.png: assets/maps/tileset.aseprite
\taseprite --batch $< --save-as $@

assets/sprites/%.png: assets/sprites/%.aseprite
\taseprite --batch $< --save-as $@

clean:
\trm -rf build/
"""


class TestParseMakefile(unittest.TestCase):
    def setUp(self):
        self.rules = pipeline.parse_makefile(SAMPLE_MAKEFILE)

    def _rule_for(self, target: str):
        matches = [r for r in self.rules if target in r.targets]
        self.assertEqual(len(matches), 1, f"expected one rule for {target}")
        return matches[0]

    def test_it_joins_continued_prerequisite_lines(self):
        rule = self._rule_for("src/track_tiles.c")
        self.assertIn("assets/maps/tileset.png", rule.prerequisites)
        self.assertIn("assets/maps/track.tsx", rule.prerequisites)
        self.assertIn("tools/png_to_tiles.py", rule.prerequisites)

    def test_it_drops_order_only_prerequisites(self):
        rule = self._rule_for("src/track_tiles.c")
        self.assertNotIn("build", rule.prerequisites)
        self.assertNotIn("|", rule.prerequisites)

    def test_it_keeps_every_target_of_a_multi_target_rule(self):
        rule = [r for r in self.rules
                if "build/track_tile_id_map.json" in r.targets][0]
        self.assertIn("src/track_tileset_meta.h", rule.targets)

    def test_it_ignores_variable_assignments(self):
        self.assertFalse(any("SHELL" in t for r in self.rules for t in r.targets))
        self.assertFalse(any("BUILD_DIR" in t for r in self.rules for t in r.targets))

    def test_it_ignores_a_pattern_rule(self):
        self.assertFalse(any("%" in t for r in self.rules for t in r.targets))

    def test_it_ignores_a_target_spelled_with_a_variable(self):
        self.assertFalse(any("$(" in t for r in self.rules for t in r.targets))

    def test_it_joins_continued_recipe_lines(self):
        """The tileset recipe spans three lines; it is one command."""
        rule = self._rule_for("src/track_tiles.c")
        self.assertEqual(len(rule.recipe), 1)
        self.assertIn("--bank 255", rule.recipe[0])
        self.assertIn("--rotation-manifest", rule.recipe[0])
        self.assertIn("track_tile_data", rule.recipe[0])

    def test_a_converter_rule_is_one_whose_recipe_runs_a_repo_tool(self):
        self.assertTrue(self._rule_for("src/player_sprite.c").is_converter)

    def test_an_aseprite_export_rule_is_not_a_converter_rule(self):
        """It writes another asset, not a generated source, and it needs a
        drawing program on PATH. R6 names three converters; this is none
        of them."""
        rule = self._rule_for("assets/maps/tileset.png")
        self.assertFalse(rule.is_converter)

    def test_a_recipe_less_rule_is_not_a_converter_rule(self):
        rule = [r for r in self.rules
                if "build/track_tile_id_map.json" in r.targets][0]
        self.assertFalse(rule.is_converter)

    def test_a_phony_rule_is_not_a_converter_rule(self):
        """`memory-check` runs `python tools/...` like every converter
        rule does, but it is a command, not a file. The game repository
        has ten of these; without the `.PHONY` check they are all
        classified as converters."""
        rule = self._rule_for("memory-check")
        self.assertTrue(rule.phony)
        self.assertFalse(rule.is_converter)


class TestTargetsForAsset(unittest.TestCase):
    def setUp(self):
        self.rules = pipeline.parse_makefile(SAMPLE_MAKEFILE)

    def test_a_sprite_names_the_source_it_generates(self):
        self.assertEqual(
            pipeline.targets_for_asset(self.rules, "assets/sprites/player_car.png"),
            ["src/player_sprite.c"],
        )

    def test_a_map_names_every_target_it_feeds(self):
        """Editing track.tmx regenerates the map *and* the rotation
        manifest -- a converter run that did one and not the other would
        leave the worktree half converted."""
        self.assertEqual(
            pipeline.targets_for_asset(self.rules, "assets/maps/track.tmx"),
            ["build/track_rotation_manifest.json", "src/track_map.c"],
        )

    def test_an_asset_no_rule_reads_names_nothing(self):
        self.assertEqual(
            pipeline.targets_for_asset(self.rules, "assets/reference/x.png"), []
        )

    def test_a_tileset_names_the_tile_source(self):
        self.assertEqual(
            pipeline.targets_for_asset(self.rules, "assets/maps/tileset.png"),
            ["src/track_tiles.c"],
        )


class TestGeneratedFiles(unittest.TestCase):
    """R10: Garage must never edit a generated file. The set is derived
    from the Makefile rather than listed here, so a new converter rule in
    the game repository is covered the day it lands."""

    def setUp(self):
        self.generated = pipeline.generated_files(
            pipeline.parse_makefile(SAMPLE_MAKEFILE)
        )

    def test_a_converter_target_is_generated(self):
        self.assertIn("src/track_map.c", self.generated)
        self.assertIn("src/player_sprite.c", self.generated)

    def test_a_side_effect_target_is_generated(self):
        """`build/track_tile_id_map.json src/track_tileset_meta.h:
        src/track_tiles.c` has no recipe -- it declares outputs the tile
        rule writes on the side. They are generated all the same."""
        self.assertIn("src/track_tileset_meta.h", self.generated)

    def test_an_asset_is_not_generated(self):
        self.assertNotIn("assets/sprites/player_car.png", self.generated)
        self.assertNotIn("assets/maps/tileset.png", self.generated)

    def test_a_phony_target_is_not_a_generated_file(self):
        """This set's whole meaning is "paths a converter writes". A
        maintenance target that happens to run a repo tool is neither a
        path nor written."""
        self.assertNotIn("memory-check", self.generated)
        self.assertNotIn("all", self.generated)

    def test_a_phony_convenience_alias_is_not_a_generated_file(self):
        """`sprites: src/player_sprite.c` has no recipe and its only
        prerequisite IS generated, so it satisfies the side-effect rule
        exactly -- the second pass has to exclude phony targets itself.
        The real Makefile's `dialog_data` is this shape."""
        self.assertNotIn("sprites", self.generated)
        self.assertIn("src/player_sprite.c", self.generated)


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestAgainstTheRealMakefile(unittest.TestCase):
    """The parser is only useful if it reads the file it was written for."""

    def setUp(self):
        self.rules = pipeline.read_rules(project.bind())

    def test_the_specs_three_generated_files_are_all_derived(self):
        """R10 names src/track_map.c, the generated tile sources and
        src/dialog_data.c."""
        generated = pipeline.generated_files(self.rules)
        self.assertIn("src/track_map.c", generated)
        self.assertIn("src/track_tiles.c", generated)
        self.assertIn("src/dialog_data.c", generated)

    def test_the_player_sprite_resolves_to_its_generated_source(self):
        self.assertIn(
            "src/player_sprite.c",
            pipeline.targets_for_asset(
                self.rules, "assets/sprites/player_car.png"
            ),
        )

    def test_no_phony_maintenance_target_is_called_a_generated_file(self):
        """The real Makefile declares ten phony targets whose recipes run
        `python tools/...`. Every one of them looked like a converter rule
        before `.PHONY` was consulted."""
        generated = pipeline.generated_files(self.rules)
        for phony in ("all", "hooks", "memory-check", "bank-check",
                      "sync-docs", "dialog_data", "tile-check"):
            self.assertNotIn(phony, generated)


if __name__ == "__main__":
    unittest.main()
