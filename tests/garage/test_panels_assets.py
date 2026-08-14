"""Panel coverage for the asset panel (spec P2, issue #3).

Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` -- tests/garage/ has no
__init__.py, so default discovery never descends into it (AC12). Run via
`make test-garage` (AC13).
"""
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from tools.garage import theme
from tools.garage.core import assets as assets_core
from tools.garage.core import pipeline, project
from tools.garage.panels.assets import AssetsPanel, cost_text, thumbnail_image

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

_app = QApplication.instance() or QApplication([])


def tmp_root(tmp: str) -> Path:
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def write_indexed_png(path: Path, width: int, height: int, palette_size: int,
                      pixels=None) -> Path:
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


MAKEFILE = """\
src/player_sprite.c: assets/sprites/player_car.png tools/png_to_tiles.py
\tpython tools/png_to_tiles.py --bank 255 assets/sprites/player_car.png src/player_sprite.c player_tile_data

src/track_map.c: assets/maps/track.tmx tools/tmx_to_c.py
\tpython tools/tmx_to_c.py assets/maps/track.tmx src/track_map.c

src/track_tiles.c: assets/maps/tileset.png tools/png_to_tiles.py
\tpython tools/png_to_tiles.py --bank 255 --rotation-manifest build/m.json assets/maps/tileset.png src/track_tiles.c track_tile_data
"""


def _bound_png_to_tiles():
    try:
        path = project.bind().resolve("tools", "png_to_tiles.py")
    except project.BindingError:
        return None
    return path if path.is_file() else None


REAL_PNG_TO_TILES = _bound_png_to_tiles()
NO_GAME_REPO = REAL_PNG_TO_TILES is None
NO_GAME_REPO_REASON = "no game repository is bound beside this checkout"


def make_fixture_worktree(root: Path) -> Path:
    """A game repository with the real converter, a Makefile, and one
    asset of each kind that matters."""
    repo = root / "nuke-raider"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools" / "png_to_tiles.py").write_bytes(REAL_PNG_TO_TILES.read_bytes())
    (repo / "tools" / "tmx_to_c.py").write_text("# stub\n", encoding="utf-8")
    (repo / "tools" / "music_song_validate.py").write_text("# stub\n", encoding="utf-8")
    (repo / "tools" / "music_wire_check.py").write_text("# stub\n", encoding="utf-8")
    (repo / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    write_indexed_png(repo / "assets/sprites/player_car.png", 16, 8, 4)
    write_indexed_png(repo / "assets/sprites/broken.png", 8, 8, 9)
    write_indexed_png(repo / "assets/maps/tileset.png", 24, 8, 4)
    (repo / "assets/maps").mkdir(parents=True, exist_ok=True)
    (repo / "assets/maps/track.tmx").write_text(
        '<map width="64" height="32" tilewidth="8" tileheight="8"></map>',
        encoding="utf-8",
    )
    (repo / "assets/music").mkdir(parents=True, exist_ok=True)
    (repo / "assets/music/song.uge").write_bytes(b"\x00")
    _run_git(["init", "-b", "master"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "init"], repo)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], repo)
    return repo


def bind_over(root: Path, repo: Path) -> project.Binding:
    garage_root = root / "nuke-raider-garage"
    garage_root.mkdir(exist_ok=True)
    project.save_settings(
        garage_root,
        {
            "game_repo": repo.as_posix(),
            "worktree_root": (root / "worktrees").as_posix(),
            "active": None,
        },
    )
    return project.bind(garage_root)


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class AssetsPanelTestCase(unittest.TestCase):
    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_fixture_worktree(self.root)
        self.binding = bind_over(self.root, self.repo)
        self.panel = AssetsPanel(self.binding, None)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def card_for(self, relative: str):
        matches = [c for c in self.panel.cards()
                   if c.asset.relative_path == relative]
        self.assertEqual(len(matches), 1, f"no card for {relative}")
        return matches[0]


class TestGrid(AssetsPanelTestCase):
    def test_every_asset_gets_a_card(self):
        """AC1."""
        self.assertEqual(
            sorted(c.asset.relative_path for c in self.panel.cards()),
            [
                "assets/maps/tileset.png",
                "assets/maps/track.tmx",
                "assets/music/song.uge",
                "assets/sprites/broken.png",
                "assets/sprites/player_car.png",
            ],
        )

    def test_the_kind_filter_shows_one_group(self):
        self.panel.set_kind_filter(assets_core.KIND_MAPS)
        self.assertEqual(
            [c.asset.name for c in self.panel.visible_cards()], ["track.tmx"]
        )

    def test_the_all_filter_shows_every_group(self):
        self.panel.set_kind_filter(assets_core.KIND_MAPS)
        self.panel.set_kind_filter(AssetsPanel.KIND_FILTER_ALL)
        self.assertEqual(len(self.panel.visible_cards()), 5)

    def test_a_png_beside_the_maps_is_filed_under_tiles(self):
        self.panel.set_kind_filter(assets_core.KIND_TILES)
        self.assertEqual(
            [c.asset.name for c in self.panel.visible_cards()], ["tileset.png"]
        )


class TestNoEditorIsNamed(unittest.TestCase):
    """R8, for the panel.

    The default suite runs this same sweep over `tools/garage/core/`, and
    it has already caught one violation there. This is the half that suite
    cannot reach — it imports Qt — and it is the likelier place for an
    editor name to appear: a button label, a tooltip, a status line. The
    panel says "the application Windows associates with that file type",
    never a program's name.
    """

    def test_no_editor_is_named_in_any_string_the_panel_uses(self):
        import ast

        from tools.garage.panels import assets as panel_module

        tree = ast.parse(
            Path(panel_module.__file__).read_text(encoding="utf-8")
        )
        docstrings = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if (
                isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                  ast.AsyncFunctionDef))
                and isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                lowered = node.value.lower()
                for editor in ("aseprite", "tiled", "hugetracker"):
                    self.assertNotIn(
                        editor, lowered, f"the panel names {editor} in code"
                    )


class TestThumbnail(unittest.TestCase):
    """AC2: four shades and the 8-pixel tile grid."""

    def test_it_uses_the_four_game_boy_shades(self):
        from tools.garage.core import preview
        from tools.garage.panels.assets import gb_shades

        facts = preview.PngFacts(
            width=8, height=8, tiles_x=1, tiles_y=1, tile_count=1,
            colour_count=4, pixels=[i % 4 for i in range(64)],
        )

        image = thumbnail_image(facts, scale=1, grid=False)

        found = {image.pixelColor(x, y).name()
                 for y in range(8) for x in range(8)}
        self.assertEqual(found, {c.name() for c in gb_shades()})

    def test_it_draws_a_line_every_eight_pixels(self):
        from tools.garage.core import preview
        from tools.garage.panels.assets import gb_shades

        facts = preview.PngFacts(
            width=16, height=16, tiles_x=2, tiles_y=2, tile_count=4,
            colour_count=1, pixels=[0] * 256,
        )

        image = thumbnail_image(facts, scale=1, grid=True)

        background = gb_shades()[0].name()
        # The tile boundary at x = 8 carries the grid; a pixel inside a
        # tile does not.
        self.assertNotEqual(image.pixelColor(8, 4).name(), background)
        self.assertEqual(image.pixelColor(4, 4).name(), background)


class TestPreviewable(unittest.TestCase):
    """A card for an oversized image must not freeze the window drawing a
    preview of art the converter will refuse."""

    def test_an_image_inside_the_budget_is_previewed(self):
        from tools.garage.core import preview
        from tools.garage.panels.assets import _previewable

        self.assertTrue(_previewable(preview.PngFacts(
            width=8, height=8, tiles_x=1, tiles_y=1, tile_count=1,
            colour_count=4, pixels=[0] * 64,
        )))

    def test_an_image_over_the_tile_budget_is_not_previewed(self):
        from tools.garage.core import preview
        from tools.garage.panels.assets import _previewable

        self.assertFalse(_previewable(preview.PngFacts(
            width=2454, height=122, tiles_x=306, tiles_y=15,
            tile_count=4590, colour_count=4, pixels=[0],
        )))

    def test_an_image_that_did_not_decode_is_not_previewed(self):
        from tools.garage.core import preview
        from tools.garage.panels.assets import _previewable

        self.assertFalse(_previewable(preview.PngFacts(
            width=None, height=None, tiles_x=None, tiles_y=None,
            tile_count=None, colour_count=9, pixels=[], error="too many",
        )))

    def test_a_strip_too_short_to_count_a_tile_is_not_previewed(self):
        """`tile_count` is `(w // 8) * (h // 8)`, so a strip under 8 pixels
        tall costs "0 tiles" however wide it is. A tile-only bound would
        wave 700,000 pixels straight into the freeze this guard exists to
        prevent."""
        from tools.garage.core import preview
        from tools.garage.panels.assets import _previewable

        self.assertFalse(_previewable(preview.PngFacts(
            width=100000, height=7, tiles_x=12500, tiles_y=0, tile_count=0,
            colour_count=4, pixels=[0] * 700000,
        )))


class TestCostText(AssetsPanelTestCase):
    def test_a_sprite_states_its_tile_cost(self):
        """AC3."""
        card = self.card_for("assets/sprites/player_car.png")
        self.assertIn("2 tiles", card.cost_label.text())

    def test_a_map_states_its_size(self):
        """R3."""
        card = self.card_for("assets/maps/track.tmx")
        self.assertIn("64 × 32", card.cost_label.text())

    def test_a_tileset_built_with_rotations_says_its_cost_is_base_only(self):
        """The converter generates a rotated variant per manifest entry at
        conversion time and counts them against the same 192-tile budget,
        so the number Garage can know in advance is not the whole cost.
        The card has to say which number it is showing rather than imply
        the budget is safe."""
        card = self.card_for("assets/maps/tileset.png")
        self.assertTrue(card.plan.rotation)
        self.assertIn("base tiles only", card.cost_label.text())

    def test_a_sprite_without_rotations_carries_no_such_note(self):
        card = self.card_for("assets/sprites/player_car.png")
        self.assertFalse(card.plan.rotation)
        self.assertNotIn("base tiles only", card.cost_label.text())


class TestVerdict(AssetsPanelTestCase):
    def test_a_clean_sprite_reads_ok(self):
        card = self.card_for("assets/sprites/player_car.png")
        self.assertEqual(card.verdict_label.text(), "OK")
        self.assertTrue(card.convert_button.isEnabled())

    def test_a_nine_colour_sprite_names_the_count_and_refuses(self):
        """AC4 and AC5."""
        card = self.card_for("assets/sprites/broken.png")
        self.assertIn("9", card.verdict_label.text())
        self.assertFalse(card.convert_button.isEnabled())
        self.assertIn("9", card.convert_button.toolTip())

    def test_the_card_can_actually_paint_its_verdict_border(self):
        """A plain QWidget paints neither background nor border from a
        style sheet, so without this attribute the whole `#assets-card`
        block — including the fail and CHANGED borders — is dead CSS that
        renders as nothing. The suite cannot see colour, but it can see
        whether the card is capable of showing one."""
        from PySide6.QtCore import Qt as QtNamespace

        card = self.card_for("assets/sprites/broken.png")
        self.assertTrue(
            card.testAttribute(QtNamespace.WidgetAttribute.WA_StyledBackground)
        )
        self.assertEqual(card.property("verdict"), "fail")


if __name__ == "__main__":
    unittest.main()
