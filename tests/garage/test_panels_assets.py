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

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tools.garage import theme
from tools.garage.core import assets as assets_core
from tools.garage.core import make_runner, pipeline, project
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

# One recipe, two outputs -- the shape issue #13 turns on. Make reads
# `a b:` as two rules sharing this recipe, so the card must name both
# files and the command must ask for one.
src/track_map.c src/track_meta.h: assets/maps/track.tmx tools/tmx_to_c.py
\tpython tools/tmx_to_c.py assets/maps/track.tmx src/track_map.c --meta-out src/track_meta.h

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


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestMissingMakefile(unittest.TestCase):
    """FIX 4: a worktree with no Makefile must not misdiagnose every card
    as though no rule reads that card's asset -- the real cause is that
    there is no Makefile to read at all, and every card's refusal should
    say so."""

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = self.root / "nuke-raider"
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "tools" / "png_to_tiles.py").write_bytes(
            REAL_PNG_TO_TILES.read_bytes()
        )
        write_indexed_png(self.repo / "assets/sprites/player_car.png", 16, 8, 4)
        # Deliberately no Makefile.
        _run_git(["init", "-b", "master"], self.repo)
        _run_git(["config", "user.email", "test@example.com"], self.repo)
        _run_git(["config", "user.name", "Test"], self.repo)
        _run_git(["add", "."], self.repo)
        _run_git(["commit", "-m", "init"], self.repo)
        _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], self.repo)
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_refusal_names_the_missing_makefile_not_a_missing_rule(self):
        panel = AssetsPanel(self.binding, None)
        self.addCleanup(panel.stop_and_wait)

        matches = [c for c in panel.cards()
                   if c.asset.relative_path == "assets/sprites/player_car.png"]
        self.assertEqual(len(matches), 1)
        card = matches[0]

        self.assertIn("does not exist", card.plan.refusal)
        self.assertNotIn(
            "No rule in the game repository's Makefile reads",
            card.plan.refusal,
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


class TestMultiTargetRule(AssetsPanelTestCase):
    """Issue #13: one recipe writing two files. The card names both, the
    command asks for one -- naming both ran the converter twice, because
    `a b:` is two rules sharing a recipe rather than one rule with two
    outputs."""

    def setUp(self):
        super().setUp()
        self.card = self.card_for("assets/maps/track.tmx")

    def test_the_card_names_every_file_the_conversion_writes(self):
        self.assertEqual(
            self.card.target_label.text(), "→ src/track_map.c, src/track_meta.h"
        )

    def test_the_command_asks_for_one_target_per_rule(self):
        self.assertEqual(
            list(self.card.plan.commands[0].argv),
            ["make", "-W", "assets/maps/track.tmx", "src/track_map.c"],
        )


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
    is which command the panel builds and what it does with the result.

    `start` echoes every command through the panel's own
    `_append_command` -- the same handler the real controller's
    `command_started` signal drives -- so a test using this fake still
    exercises the production echo path rather than a copy of it. It
    echoes them all at once because this fake never runs anything and so
    has no notion of one command failing before the next starts; the
    real controller's sequential, stops-on-first-failure echoing is
    covered separately, with the real controller, in
    `TestConvertEchoesOnlyCommandsThatRan`.
    """

    def __init__(self, panel):
        self.panel = panel
        self.started = []
        self._running = False

    def start(self, commands, cwd):
        self.started.append((list(commands), cwd))
        self._running = True
        for command in commands:
            self.panel._append_command(command.label, command.target)
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

    def test_convert_refuses_a_card_whose_verification_went_stale(self):
        """FIX 1: the acceptance flow is edit an asset, see CHANGED, press
        Reconvert -- and the seconds between are exactly when a file can go
        from clean to broken. A card built (or last redrawn) while the
        file was clean must not let a converter run against that stale
        verification once the file no longer passes it. This fails against
        the code before FIX 1: `convert()` used to trust `card.plan`
        outright, which was still the OK plan from before this edit."""
        card = self.card_for("assets/sprites/player_car.png")
        self.assertTrue(card.verification.ok)

        write_indexed_png(card.asset.path, 8, 8, 9)  # now fails: 9 colours
        self.panel.check_for_changes()
        self.panel.convert(card)

        self.assertEqual(self.fake.started, [])
        self.assertIn("9", self.panel.log_text())
        self.assertFalse(card.verification.ok)
        self.assertFalse(card.convert_button.isEnabled())

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


class TestBusyDuringARun(AssetsPanelTestCase):
    """Issue #9, defect 1: while a converter runs, no card offers an
    action -- and nothing that redraws a card in the meantime may put one
    back. `_set_busy(True)` is what disables the buttons; a poll tick, a
    refused second Convert and a grid rebuild all redraw cards, and each
    one used to undo it."""

    def setUp(self):
        super().setUp()
        self.panel._runs.stop_and_wait()
        self.fake = _FakeRuns(self.panel)
        self.panel._runs = self.fake

    def test_a_poll_during_a_run_leaves_every_convert_button_disabled(self):
        """The defect itself: `check_for_changes` re-verifies a card that
        moved on disk, and re-verifying used to re-enable its Convert
        button -- a button that looks live for up to two seconds and
        answers by refusing."""
        running = self.card_for("assets/sprites/player_car.png")
        other = self.card_for("assets/maps/tileset.png")
        self.panel.convert(running)
        self.assertFalse(other.convert_button.isEnabled())

        write_indexed_png(other.asset.path, 32, 8, 4)
        self.panel.check_for_changes()

        # The poll really did re-verify it -- otherwise this test would
        # pass against a panel that simply never polls.
        self.assertTrue(other.is_changed())
        self.assertFalse(other.convert_button.isEnabled())
        self.assertFalse(other.open_button.isEnabled())

    def test_a_refused_second_convert_leaves_the_button_disabled(self):
        """The same defect through the other door: `convert()` re-verifies
        and redraws the card *before* it discovers a run is already in
        flight."""
        card = self.card_for("assets/sprites/player_car.png")
        self.panel.convert(card)

        self.panel.convert(card)

        self.assertIn("already running", self.panel.log_text())
        self.assertFalse(card.convert_button.isEnabled())

    def test_a_grid_rebuilt_during_a_run_offers_no_action(self):
        """`refresh()` builds fresh widgets that know nothing of the run.
        Closing the Assets dialog only hides it -- the panel and any
        converter thread it started keep running underneath -- and
        reopening it calls `refresh()` unconditionally, so this rebuild can
        land squarely in the middle of a run."""
        card = self.card_for("assets/sprites/player_car.png")
        self.panel.convert(card)

        self.panel.refresh()

        rebuilt = self.card_for("assets/sprites/player_car.png")
        self.assertFalse(rebuilt.convert_button.isEnabled())
        self.assertFalse(rebuilt.open_button.isEnabled())

    def test_a_disabled_convert_button_carries_the_busy_tooltip(self):
        """Task 1 gave the disabled Convert button its own tooltip, naming
        the run rather than leaving the button silent or repeating the
        refusal a failed verification would show. Pin the text so a future
        edit does not quietly swap it back to one of those."""
        card = self.card_for("assets/sprites/player_car.png")
        other = self.card_for("assets/maps/tileset.png")

        self.panel.convert(card)

        self.assertEqual(
            other.convert_button.toolTip(),
            "A converter is running. This is offered again when it finishes.",
        )

    def test_a_failed_cards_refusal_tooltip_survives_a_run(self):
        """`_apply_verdict`'s failed-verification branch returns before it
        ever looks at `_busy` (R5) -- a card whose verification failed
        keeps its own refusal tooltip through a run in flight rather than
        having it overwritten by the busy one."""
        broken = self.card_for("assets/sprites/broken.png")
        refusal = broken.convert_button.toolTip()
        card = self.card_for("assets/sprites/player_car.png")

        self.panel.convert(card)

        self.assertEqual(broken.convert_button.toolTip(), refusal)
        self.assertIn("9", broken.convert_button.toolTip())

    def test_the_actions_come_back_when_the_run_finishes(self):
        """The disable must be exactly as long as the run: a card left
        dead after a successful conversion would be worse than the
        defect."""
        card = self.card_for("assets/sprites/player_car.png")
        other = self.card_for("assets/maps/tileset.png")
        self.panel.convert(card)

        self.fake.finish([_Result(ok=True)])

        self.assertTrue(other.convert_button.isEnabled())
        self.assertTrue(other.open_button.isEnabled())
        self.assertTrue(card.open_button.isEnabled())
        self.assertTrue(card.convert_button.isEnabled())


class TestARunThatOutlivesItsCard(AssetsPanelTestCase):
    """Issue #11, defect 1: `refresh()` destroys every card and builds new
    ones, and `open_assets()` in app.py calls it unconditionally -- so a
    run started before the dialog was closed reports its result to a widget
    that no longer exists. `_running_card` has to be re-pointed at the
    rebuilt card, or the result is lost and, once Qt has processed the
    deferred delete, the completion handler raises.

    The reachable path: press Reconvert on a CHANGED card, close the Assets
    dialog, reopen it via View > Assets... before the run finishes.
    """

    def setUp(self):
        super().setUp()
        self.panel._runs.stop_and_wait()
        self.fake = _FakeRuns(self.panel)
        self.panel._runs = self.fake

    def _mark_and_convert(self):
        """A CHANGED card with a run in flight -- the state the defect
        needs. CHANGED matters: `set_changed(False)` early-returns on an
        unmarked card, so an OK card loses the result quietly instead of
        raising."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.assertTrue(card.is_changed())
        self.panel.convert(card)
        return card

    def test_the_result_lands_on_the_rebuilt_card(self):
        """Without the remap the mark is cleared on a discarded widget, so
        the rebuilt card keeps a CHANGED it has no way to lose."""
        self._mark_and_convert()

        self.panel.refresh()
        self.fake.finish([_Result(ok=True)])

        rebuilt = self.card_for("assets/sprites/player_car.png")
        self.assertFalse(rebuilt.is_changed())
        self.assertIn("converted", self.panel.log_text())
        # And the panel's own memory agrees, so the next rebuild does not
        # put the mark back: `refresh()` re-applies marks from
        # `_changed_paths`, not from the widgets.
        self.panel.refresh()
        self.assertFalse(
            self.card_for("assets/sprites/player_car.png").is_changed()
        )

    def test_a_finished_run_does_not_call_into_a_deleted_widget(self):
        """`refresh()` calls `deleteLater()`, which a live event loop acts
        on. Once it has, any Qt call on the old card raises `RuntimeError:
        Internal C++ object ... already deleted` out of a signal handler,
        and `run_finished` never fires. `sendPostedEvents` is what a real
        event loop does here; the test does it by hand because it runs
        without one."""
        self._mark_and_convert()
        self.panel.refresh()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.fake.finish([_Result(ok=True)])

        self.assertIn("converted", self.panel.log_text())
        self.assertFalse(
            self.card_for("assets/sprites/player_car.png").is_changed()
        )


class TestConvertEchoesOnlyCommandsThatRan(AssetsPanelTestCase):
    """FIX 6: the log must attribute a `$ ...` line only to a command that
    actually started -- not to every command in a plan, echoed up front,
    including ones a failed earlier command means never ran. Runs the
    real `RunController` (this class does not replace `self.panel._runs`
    the way `TestConvert` does), because the bug this guards against is in
    the timing of two real, sequential subprocesses.
    """

    @staticmethod
    def _wait_until(predicate, timeout_ms=15000):
        waited = 0
        while waited < timeout_ms and not predicate():
            QTest.qWait(20)
            waited += 20
        return predicate()

    def test_a_failing_first_command_stops_the_sequence_and_echoes_only_it(self):
        card = self.card_for("assets/music/song.uge")
        commands = [
            make_runner.Command(
                argv=(sys.executable, "-c", "raise SystemExit(2)"),
                label="first",
                target="first",
            ),
            make_runner.Command(
                argv=(sys.executable, "-c", "print('second ran')"),
                label="second",
                target="second",
            ),
        ]

        self.panel._running_card = card
        self.assertTrue(self.panel._runs.start(commands, self.repo))
        self.assertTrue(self._wait_until(lambda: not self.panel.is_running()))

        log = self.panel.log_text()
        self.assertIn("$ first", log)
        self.assertNotIn("$ second", log)
        self.assertNotIn("second ran", log)


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

        The ordering is the whole test. The edit lands and `refresh()` runs
        with no poll in between — the exact race `setdefault` protects: a
        user who edits a sprite and reopens the panel before the two-second
        timer has fired. If `refresh()` re-baselined, that edit would be
        absorbed into the new baseline, the next poll would compare the
        changed file against itself, and Garage would never offer to
        convert it.

        Do not call `check_for_changes()` before the `refresh()` here. Once
        an asset is marked, the mark is monotonic — only a successful
        conversion clears it — so `refresh()`'s re-apply loop would keep
        the card CHANGED on its own and the assertion would hold whether
        the stamps were preserved or rebuilt. The test would pass against
        the bug it exists to catch.
        """
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)

        self.panel.refresh()
        self.panel.check_for_changes()

        self.assertTrue(self.card_for("assets/sprites/player_car.png").is_changed())

    def test_a_change_that_breaks_verification_updates_the_verdict(self):
        """FIX 1b: `check_for_changes` must not leave a stale OK verdict
        (or stale cost/target text) on a card whose file now fails
        verification -- it re-verifies and re-plans the card in place,
        rather than only re-stamping it."""
        card = self.card_for("assets/sprites/player_car.png")
        self.assertTrue(card.verification.ok)
        self.assertEqual(card.verdict_label.text(), "OK")

        write_indexed_png(card.asset.path, 8, 8, 9)  # now fails: 9 colours
        self.panel.check_for_changes()

        self.assertFalse(card.verification.ok)
        self.assertFalse(card.convert_button.isEnabled())
        self.assertIn("9", card.verdict_label.text())
        self.assertNotEqual(card.verdict_label.text(), "OK")

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


class TestVerificationBaseline(AssetsPanelTestCase):
    """Issue #9, defect 2: the CHANGED mark is sticky by design -- only a
    conversion clears it -- so a marked asset stays changed against the
    baseline that drives the mark. Re-verifying off that same baseline
    meant decoding the PNG and re-parsing the game repository's Makefile
    on every two-second tick, per marked card, forever. The re-verify
    needs a baseline of its own."""

    def test_a_marked_asset_is_not_re_verified_on_every_tick(self):
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.assertTrue(card.is_changed())

        with mock.patch.object(
            assets_core, "verify", wraps=assets_core.verify
        ) as verify:
            self.panel.check_for_changes()
            self.panel.check_for_changes()

        # Still marked -- the mark outlives the tick, which is the whole
        # point of `_stamps` not moving -- but the work is done once.
        self.assertTrue(card.is_changed())
        self.assertEqual(verify.call_count, 0)

    def test_a_second_edit_of_a_marked_asset_is_verified_again(self):
        """The trap in the other direction, and the reason the fix is a
        second baseline rather than "skip if already marked": that
        shortcut would keep the verification from the *first* edit, so a
        card would go on showing OK about a file the second edit broke."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.assertTrue(card.is_changed())
        self.assertTrue(card.verification.ok)

        write_indexed_png(card.asset.path, 8, 8, 9)  # nine colours
        self.panel.check_for_changes()

        self.assertFalse(card.verification.ok)
        self.assertIn("9", card.verdict_label.text())
        self.assertFalse(card.convert_button.isEnabled())

    def test_a_re_plan_uses_the_rules_the_panel_already_parsed(self):
        """`plan_for` with no rules re-reads and re-parses the game
        repository's Makefile. The panel parsed it in `refresh()`; the
        poll must not do it again."""
        card = self.card_for("assets/sprites/player_car.png")
        write_indexed_png(card.asset.path, 24, 8, 4)

        with mock.patch.object(
            pipeline, "read_rules", wraps=pipeline.read_rules
        ) as read_rules:
            self.panel.check_for_changes()

        self.assertTrue(card.is_changed())
        self.assertEqual(read_rules.call_count, 0)
        # And the cached rules were the real ones: an empty rule list
        # would have produced a refusal with no target at all.
        self.assertEqual(card.plan.targets, ("src/player_sprite.c",))


class TestAnEditDuringARun(AssetsPanelTestCase):
    """Issue #11, defect 2: a save that lands while the converter is
    running is answered by nothing, and used to be forgotten anyway.

    `_on_run_finished` re-baselined `_stamps` to the asset's stamp at
    *completion* time and discarded the mark, so the edit was absorbed into
    the new baseline: never converted, and the card said OK. The poll timer
    is not stopped during a run, so the tick that marks the card CHANGED
    lands inside the same window."""

    def setUp(self):
        super().setUp()
        self.panel._runs.stop_and_wait()
        self.fake = _FakeRuns(self.panel)
        self.panel._runs = self.fake
        self.card = self.card_for("assets/sprites/player_car.png")

    def test_an_edit_made_while_the_converter_ran_keeps_the_mark(self):
        self.panel.convert(self.card)

        write_indexed_png(self.card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.fake.finish([_Result(ok=True)])

        self.assertTrue(self.card.is_changed())
        self.assertEqual(self.card.convert_button.text(), "Reconvert")

    def test_that_edit_is_still_unanswered_after_the_next_rebuild(self):
        """The baseline is what makes the mark stick. Clearing the widget's
        mark while leaving `_stamps` behind, or the reverse, both read as
        "answered" one rebuild later."""
        self.panel.convert(self.card)

        write_indexed_png(self.card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.fake.finish([_Result(ok=True)])
        self.panel.refresh()

        self.assertTrue(
            self.card_for("assets/sprites/player_car.png").is_changed()
        )

    def test_an_edit_the_poll_has_not_seen_yet_still_keeps_the_mark(self):
        """The same loss without a poll tick to help: the two-second timer
        need not have fired between the save and the converter finishing,
        and the run's own completion is the last chance to notice."""
        self.panel.convert(self.card)

        write_indexed_png(self.card.asset.path, 24, 8, 4)
        self.fake.finish([_Result(ok=True)])

        self.assertTrue(self.card.is_changed())

    def test_the_log_says_why_the_card_still_reads_changed(self):
        """A success line followed by a card that still says CHANGED is a
        contradiction unless the panel accounts for it."""
        self.panel.convert(self.card)

        write_indexed_png(self.card.asset.path, 24, 8, 4)
        self.fake.finish([_Result(ok=True)])

        log = self.panel.log_text()
        self.assertIn("changed while the converter ran", log)
        self.assertIn("player_car.png", log)

    def test_an_untouched_asset_still_has_its_mark_cleared(self):
        """The case the guard must not break: a conversion that answers the
        edit it was started for withdraws the offer, which is what makes
        the mark mean anything."""
        write_indexed_png(self.card.asset.path, 24, 8, 4)
        self.panel.check_for_changes()
        self.assertTrue(self.card.is_changed())

        self.panel.convert(self.card)
        self.fake.finish([_Result(ok=True)])

        self.assertFalse(self.card.is_changed())
        self.panel.refresh()
        self.assertFalse(
            self.card_for("assets/sprites/player_car.png").is_changed()
        )


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


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestWindowWiring(unittest.TestCase):
    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_fixture_worktree(self.root)
        self.garage_root = self.root / "nuke-raider-garage"
        bind_over(self.root, self.repo)
        from tools.garage.app import GarageWindow

        self.window = GarageWindow(self.garage_root)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self._tmp.cleanup()

    def test_the_view_menu_offers_the_assets_panel(self):
        self.assertEqual(self.window.show_assets_action.text(), "&Assets…")

    def test_opening_shows_the_dialog_with_the_worktrees_assets(self):
        self.window.open_assets()

        self.assertTrue(self.window.assets_dialog.isVisible())
        # `make_fixture_worktree` lists one asset of each of the four kinds
        # plus `broken.png`, a second sprite kept for the failing-verdict
        # tests (AC4/AC5) -- five files total, as `TestGrid` already
        # establishes above.
        self.assertEqual(len(self.window.assets_panel.cards()), 5)

    def test_the_dialog_names_the_worktree_it_lists(self):
        """With several checkouts open (P1 R3), "Assets" alone does not
        say whose."""
        self.assertIn(self.repo.name, self.window.assets_dialog.windowTitle())

    def test_closing_the_window_stops_the_panels_timer_and_thread(self):
        self.window.open_assets()

        self.window.close()

        self.assertFalse(self.window.assets_panel._poll.isActive())
        self.assertFalse(self.window.assets_panel.is_running())


if __name__ == "__main__":
    unittest.main()
