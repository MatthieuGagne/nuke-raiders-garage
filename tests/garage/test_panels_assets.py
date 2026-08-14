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
from unittest import mock

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


class _FakeRuns:
    """Stands in for RunController: records what it was asked to run and
    lets the test decide the outcome. The controller's own threading is
    covered by the compile-bar and commit-panel suites; what matters here
    is which command the panel builds and what it does with the result."""

    def __init__(self, panel):
        self.panel = panel
        self.started = []
        self._running = False

    def start(self, commands, cwd):
        self.started.append((list(commands), cwd))
        self._running = True
        return True

    def is_running(self):
        return self._running

    def stop_and_wait(self):
        self._running = False

    def finish(self, results, lines=()):
        for line in lines:
            self.panel.append_line(line)
        self._running = False
        self.panel._on_run_finished(results)


class _Result:
    def __init__(self, ok=True, exit_code=0):
        self.ok = ok
        self.exit_code = exit_code
        self.cancelled = False


class TestConvert(AssetsPanelTestCase):
    def setUp(self):
        super().setUp()
        self.panel._runs.stop_and_wait()
        self.fake = _FakeRuns(self.panel)
        self.panel._runs = self.fake

    def test_converting_a_clean_sprite_runs_the_planned_command(self):
        """AC6: the command is the one the Makefile's rule implies."""
        card = self.card_for("assets/sprites/player_car.png")

        self.panel.convert(card)

        commands, cwd = self.fake.started[0]
        self.assertEqual(
            list(commands[0].argv),
            ["make", "-W", "assets/sprites/player_car.png", "src/player_sprite.c"],
        )
        self.assertEqual(Path(cwd), self.repo)

    def test_a_failed_asset_runs_nothing_and_says_why(self):
        """AC5."""
        card = self.card_for("assets/sprites/broken.png")

        self.panel.convert(card)

        self.assertEqual(self.fake.started, [])
        self.assertIn("9", self.panel.log_text())

    def test_the_log_shows_the_command_and_the_converter_output(self):
        """AC7."""
        card = self.card_for("assets/sprites/player_car.png")
        self.panel.convert(card)

        self.fake.finish([_Result(ok=True)],
                         lines=["Wrote src/player_sprite.c"])

        log = self.panel.log_text()
        self.assertIn("$ make -W assets/sprites/player_car.png", log)
        self.assertIn("Wrote src/player_sprite.c", log)

    def test_a_converter_error_appears_with_its_own_message(self):
        """AC7: the message the converter produced, not a summary of it."""
        card = self.card_for("assets/sprites/player_car.png")
        self.panel.convert(card)

        self.fake.finish(
            [_Result(ok=False, exit_code=2)],
            lines=["Error: Image dimensions 12x8 must be multiples of 8."],
        )

        log = self.panel.log_text()
        self.assertIn("Image dimensions 12x8 must be multiples of 8.", log)
        self.assertIn("failed", log.lower())

    def test_a_second_run_while_one_is_in_flight_is_refused(self):
        card = self.card_for("assets/sprites/player_car.png")
        self.panel.convert(card)

        self.panel.convert(card)

        self.assertEqual(len(self.fake.started), 1)

    def test_a_uge_runs_both_music_validators(self):
        """AC11 (the validator half; the open half is Task 9)."""
        card = self.card_for("assets/music/song.uge")

        self.panel.convert(card)

        commands, _ = self.fake.started[0]
        self.assertEqual(len(commands), 2)
        self.assertIn("music_song_validate.py", commands[0].label)
        self.assertIn("music_wire_check.py", commands[1].label)


class TestOpen(AssetsPanelTestCase):
    def test_opening_hands_the_file_to_the_windows_default_app(self):
        """AC8."""
        card = self.card_for("assets/sprites/player_car.png")

        with mock.patch.object(assets_core, "_startfile") as startfile:
            self.panel.open(card)

        startfile.assert_called_once_with(str(card.asset.path))

    def test_a_uge_opens_in_the_default_app_too(self):
        """AC11, the open half. Garage names no tracker."""
        card = self.card_for("assets/music/song.uge")

        with mock.patch.object(assets_core, "_startfile") as startfile:
            self.panel.open(card)

        startfile.assert_called_once_with(str(card.asset.path))

    def test_a_failure_to_open_is_reported_in_the_log(self):
        card = self.card_for("assets/sprites/player_car.png")

        with mock.patch.object(assets_core, "_startfile", side_effect=OSError("no app")):
            self.panel.open(card)

        self.assertIn("no application", self.panel.log_text().lower())


class TestChangedOnDisk(AssetsPanelTestCase):
    """AC9: an asset changed on disk is marked as changed, and Garage
    offers to convert it again."""

    def test_a_file_rewritten_after_opening_is_marked_changed(self):
        card = self.card_for("assets/sprites/player_car.png")
        with mock.patch.object(assets_core, "_startfile"):
            self.panel.open(card)

        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()

        self.assertTrue(card.is_changed())
        self.assertIn("CHANGED", card.verdict_label.text())

    def test_the_action_becomes_reconvert(self):
        card = self.card_for("assets/sprites/player_car.png")
        with mock.patch.object(assets_core, "_startfile"):
            self.panel.open(card)
        write_indexed_png(card.asset.path, 24, 8, 4)

        self.panel.check_for_changes()

        self.assertEqual(card.convert_button.text(), "Reconvert")
        self.assertTrue(card.convert_button.isEnabled())

    def test_a_changed_mark_survives_a_refresh(self):
        """`refresh()` throws every card away and builds new ones, and it
        runs each time the dialog opens. Without carrying the marks across,
        editing a sprite, seeing CHANGED, closing the panel and reopening
        it would silently withdraw the offer to convert a file that is
        still unconverted — which is R9 failing quietly."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.assertTrue(card.is_changed())

        self.panel.refresh()

        rebuilt = self.card_for("assets/sprites/player_car.png")
        self.assertTrue(rebuilt.is_changed())
        self.assertEqual(rebuilt.convert_button.text(), "Reconvert")

    def test_a_refresh_does_not_re_baseline_an_unconverted_asset(self):
        """The stamp belongs to the asset, not to a rebuild of the grid.
        If `refresh()` re-stamped, the mark would come back for one tick
        and then vanish on the next poll."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()

        self.panel.refresh()
        self.panel.check_for_changes()

        self.assertTrue(self.card_for("assets/sprites/player_car.png").is_changed())

    def test_an_untouched_asset_stays_ok(self):
        card = self.card_for("assets/sprites/player_car.png")
        with mock.patch.object(assets_core, "_startfile"):
            self.panel.open(card)

        self.panel.check_for_changes()

        self.assertFalse(card.is_changed())

    def test_an_asset_never_opened_is_watched_from_the_first_look(self):
        """The user may edit a file from Explorer; R9 says "changed on
        disk", not "changed after Garage opened it"."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)

        self.panel.check_for_changes()

        self.assertTrue(card.is_changed())


class TestGeneratedFilesAreReadOnly(AssetsPanelTestCase):
    """AC10: Garage offers no way to edit a generated file."""

    def test_no_card_is_a_generated_file(self):
        generated = pipeline.generated_files(pipeline.read_rules(self.binding))
        for card in self.panel.cards():
            self.assertNotIn(card.asset.relative_path, generated)

    def test_the_target_is_shown_as_a_label_not_a_control(self):
        from PySide6.QtWidgets import QAbstractButton

        card = self.card_for("assets/sprites/player_car.png")
        self.assertIn("src/player_sprite.c", card.target_label.text())
        self.assertNotIsInstance(card.target_label, QAbstractButton)
        self.assertIn("read-only", card.target_label.toolTip().lower())

    def test_opening_refuses_a_generated_path(self):
        """The guard behind the absence of a control: even a caller that
        built a card by hand cannot open a generated file."""
        card = self.card_for("assets/sprites/player_car.png")
        card.asset = type(card.asset)(
            path=self.repo / "src" / "player_sprite.c",
            relative_path="src/player_sprite.c",
            kind=card.asset.kind,
            size_bytes=0,
            mtime_ns=0,
        )

        with mock.patch.object(assets_core, "_startfile") as startfile:
            self.panel.open(card)

        startfile.assert_not_called()
        self.assertIn("generated", self.panel.log_text().lower())


if __name__ == "__main__":
    unittest.main()
