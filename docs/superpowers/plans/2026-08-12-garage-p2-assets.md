# Garage P2 — Asset Browser, Preview and Converter Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Garage's asset panel — find an asset under the active worktree's `assets/`, see it in the four-shade Game Boy palette with the tile grid, learn its tile cost, open it in the Windows default application, and run the game repository's own converter against it, with problems reported before the converter runs.

**Architecture:** Three Qt-free core modules and one Qt panel. `core/assets.py` walks `assets/` of the active worktree, classifies each file into sprites/tiles/maps/music, and verifies an image before a converter is offered. `core/preview.py` gets the pixels, the colour count and the tile cost by loading the **active worktree's own** `tools/png_to_tiles.py` as a module and calling its `load_png_pixels` — so the numbers Garage shows are the converter's numbers by construction, not a second implementation that can drift. `core/pipeline.py` parses the game repository's `Makefile` to learn which target each asset feeds and what generated file that target writes, and runs `make -W <asset> <targets…>` in the active worktree — the same command a terminal would run, which is what makes AC6 true rather than argued. `panels/assets.py` is the Qt layer: a filterable card grid, a converter log fed by the existing `RunController` worker thread, and an Open button that hands the file to the Windows shell.

**Tech Stack:** Python 3.13, standard library only in `tools/garage/core/` (`zlib`, `struct`, `importlib.util`, `xml.etree.ElementTree`, `subprocess`, `os.startfile`), PySide6 for `tools/garage/panels/`, `unittest` for both suites.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/3 (Garage P2 — asset browser, preview and converter runs). Depends on the P1 child spec, issue #2, delivered on `main` at `b7a5e1b`.

---

## Global Constraints

These apply to every task below. They are not repeated per task.

- **No Qt import anywhere under `tools/garage/core/`** (R12). `core/assets.py`, `core/preview.py` and `core/pipeline.py` import stdlib only. Verification and converter calls must run with no display.
- **No hardcoded path** (R13). Every path resolves through `tools/garage/core/project.py` — `binding.resolve("assets")`, `binding.resolve("tools", "png_to_tiles.py")`, `binding.active_worktree.path`. A literal like `C:/Code/nuke-raider` in product code *or in a test* is a defect: P1 shipped one and it turned three CI skips into three CI failures.
- **No colour literal and no font literal outside `tools/garage/theme/`** (P1 R18/AC18). The four Game Boy shades are added to `tools/garage/theme/tokens.py` in Task 7 and read by name.
- **Garage changes no file that the game repository tracks as a checked-in change.** Running a converter writes generated files *at runtime, in a checkout Garage does not own* — that is this panel's product function and is allowed. Editing a game-repository file from this repository's tree is not.
- **The default test target must pass with PySide6 absent** (AC12). `tests/test_garage_assets.py` must not import PySide6, directly or transitively. Panel tests live in `tests/garage/test_panels_assets.py`, which default discovery never reaches (`tests/garage/` has no `__init__.py`).
- **Tests that need a real game repository skip, never fail, when none is bound** (the AC12 rule again). Follow `tests/test_garage_core.py`'s `NO_GAME_REPO` / `NO_GAME_REPO_REASON` pattern.
- **Generated files are read-only in Garage** (R10). No code path in this plan opens, writes, or offers an edit action for a converter's output.
- **The four converter names, verbatim from R6/R11:** `png_to_tiles.py` (sprites and tiles), `tmx_to_c.py` (maps), `music_song_validate.py` and `music_wire_check.py` (`.uge`). Garage never names an editor (R8) — no `aseprite`, no `tiled`, no `hUGETracker` string in product code.
- **Limits, copied from the game repository's converters:** 4 colours (`png_to_tiles.load_png_pixels`), image dimensions a multiple of 8 (`png_to_tiles.encode_2bpp`), 192 tiles VRAM budget (`png_to_tiles.png_to_c`).
- **Commit after each task**, with the exact `git commit` command each task's last step gives.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/garage/core/assets.py` (create) | Walk `assets/`, classify by kind, hold the `Asset` record, stamp a file for change detection, open a file in the Windows default application, and run pre-flight verification. |
| `tools/garage/core/preview.py` (create) | Load the active worktree's `png_to_tiles.py`, decode a PNG to Game Boy palette indices, report width/height/tile cost/colour count; read a `.tmx`'s map size. Returns numbers and indices only — never a colour. |
| `tools/garage/core/pipeline.py` (create) | Parse the game repository's `Makefile` into rules; answer "which targets does this asset feed", "which files are generated", "what command converts this asset"; build the two music-validator commands. |
| `tools/garage/panels/assets.py` (create) | The Qt panel: kind filter chips, the card grid, thumbnails, verdict chips, Open/Convert buttons, the converter log, the changed-on-disk poll. |
| `tools/garage/theme/tokens.py` (modify) | Add the four Game Boy shades as tokens. |
| `tools/garage/theme/qss.py` (modify) | Add the asset panel's selectors to the stylesheet. |
| `tools/garage/app.py` (modify) | Build the assets dialog, add the `View ▸ Assets…` action, rebuild it with the body on a worktree switch, and stop its thread on close. |
| `tests/test_garage_assets.py` (create) | Core coverage: discovery, kinds, preview facts, verification, Makefile parsing, converter commands, generated-file set, open-in-default-app, change stamps. No PySide6. |
| `tests/garage/test_panels_assets.py` (create) | Panel coverage: grouping in the UI, thumbnail construction, the refusal to convert, the log, the changed badge, the absence of any edit affordance for a generated file. |

---

## Task 1: Asset discovery and kinds

**Files:**
- Create: `tools/garage/core/assets.py`
- Test: `tests/test_garage_assets.py`

**Interfaces:**
- Consumes: `tools.garage.core.project.Binding` (P1) — `binding.resolve(*parts) -> Path`, `binding.active_worktree.path`.
- Produces:
  - `KIND_SPRITES = "sprites"`, `KIND_TILES = "tiles"`, `KIND_MAPS = "maps"`, `KIND_MUSIC = "music"`, `KIND_OTHER = "other"`, `KIND_ORDER: Tuple[str, ...]`
  - `KIND_LABELS: Dict[str, str]`
  - `@dataclass(frozen=True) Asset(path: Path, relative_path: str, kind: str, size_bytes: int, mtime_ns: int)` with `@property name -> str`
  - `classify(relative_path: str) -> str`
  - `discover(binding) -> List[Asset]` (sorted by kind order, then relative path)
  - `group_by_kind(assets) -> Dict[str, List[Asset]]`
  - `ASSETS_DIRNAME = "assets"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_garage_assets.py` with this content. It is the whole file for now; later tasks append to it.

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.core.assets'`

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/assets.py`:

```python
"""Asset discovery, kind detection, pre-flight verification and the two
file operations the panel needs (open, and "did it change?").

No Qt import belongs in this module or anywhere under tools/garage/core/
(R12): everything here is testable with no display.

R1 names four kinds -- sprites, tiles, maps and music -- and AC1 asks for
*every* file under assets/ in its correct group. Those two together mean a
fifth group: `assets/dialog/*.json`, `assets/reference/**` and the Tiled
project files are real files under assets/ that are none of the four, and
dropping them would make the panel a filtered view that quietly disagrees
with the directory it claims to list. They are listed as KIND_OTHER, with
no converter and no preview -- which is the truth about them.

Every path resolves through `tools.garage.core.project.Binding` (R13).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

ASSETS_DIRNAME = "assets"

KIND_SPRITES = "sprites"
KIND_TILES = "tiles"
KIND_MAPS = "maps"
KIND_MUSIC = "music"
KIND_OTHER = "other"

# The order the panel shows the groups in, and the order `discover` sorts
# by. R1's four kinds first, in the order R1 names them.
KIND_ORDER: Tuple[str, ...] = (
    KIND_SPRITES,
    KIND_TILES,
    KIND_MAPS,
    KIND_MUSIC,
    KIND_OTHER,
)

KIND_LABELS: Dict[str, str] = {
    KIND_SPRITES: "Sprites",
    KIND_TILES: "Tiles",
    KIND_MAPS: "Maps",
    KIND_MUSIC: "Music",
    KIND_OTHER: "Other",
}

# Suffixes that decide a kind on their own, wherever the file sits.
MAP_SUFFIXES = (".tmx",)
MUSIC_SUFFIXES = (".uge", ".mid")
IMAGE_SUFFIXES = (".png",)

# Directories under assets/ whose contents are of one kind.
_SPRITE_DIR = "sprites"
_TILE_DIR = "tiles"
_MAP_DIR = "maps"


@dataclass(frozen=True)
class Asset:
    """One file under assets/. `relative_path` is posix-spelled and
    relative to the worktree root -- it is what the Makefile spells its
    prerequisites with (see core/pipeline.py), so the two never need a
    conversion between them.
    """

    path: Path
    relative_path: str
    kind: str
    size_bytes: int
    mtime_ns: int

    @property
    def name(self) -> str:
        return self.path.name


def classify(relative_path: str) -> str:
    """The kind of `relative_path` (posix, relative to the worktree).

    Suffix decides first, then directory: a `.tmx` is a map wherever it
    lives, and a `.png` beside the maps is a tileset rather than a map.
    Anything left is KIND_OTHER -- see the module docstring.
    """
    parts = relative_path.split("/")
    suffix = ("." + parts[-1].rsplit(".", 1)[1].lower()) if "." in parts[-1] else ""

    if suffix in MUSIC_SUFFIXES:
        return KIND_MUSIC
    if suffix in MAP_SUFFIXES:
        return KIND_MAPS

    # parts[0] is "assets"; parts[1] is the directory under it.
    directory = parts[1] if len(parts) > 2 else ""
    if directory == _TILE_DIR:
        return KIND_TILES
    if directory == _MAP_DIR and suffix in IMAGE_SUFFIXES:
        # The tilesets live beside the maps they belong to; the prototype's
        # Assets screen shows tileset.png under Tiles, not under Maps.
        return KIND_TILES
    if directory == _SPRITE_DIR:
        return KIND_SPRITES
    return KIND_OTHER


def assets_dir(binding) -> Path:
    """`assets/` of the active worktree (R13 -- resolved, never joined by
    a caller)."""
    return binding.resolve(ASSETS_DIRNAME)


def discover(binding) -> List[Asset]:
    """Every file under `assets/` of the active worktree, sorted by kind
    order then by path (AC1).

    A worktree with no assets/ directory yields nothing rather than
    raising: it is a state the panel reports in words.
    """
    root = assets_dir(binding)
    if not root.is_dir():
        return []

    worktree = binding.active_worktree.path
    found: List[Asset] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(worktree).as_posix()
        stat = path.stat()
        found.append(
            Asset(
                path=path,
                relative_path=relative,
                kind=classify(relative),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )
    found.sort(key=lambda a: (KIND_ORDER.index(a.kind), a.relative_path))
    return found


def group_by_kind(found: List[Asset]) -> Dict[str, List[Asset]]:
    """`found` bucketed by kind. Every kind in KIND_ORDER is a key, even
    when empty, so a caller iterating the result never has to know which
    kinds happened to be present.
    """
    groups: Dict[str, List[Asset]] = {kind: [] for kind in KIND_ORDER}
    for asset in found:
        groups[asset.kind].append(asset)
    return groups
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS — 13 tests.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS, no regression in P1's 214 tests.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/assets.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 1: asset discovery and kinds"
```

---

## Task 2: Preview facts from the converter's own decoder

**Files:**
- Create: `tools/garage/core/preview.py`
- Modify: `tests/test_garage_assets.py` (append)

**Interfaces:**
- Consumes: `project.Binding.resolve`; the active worktree's `tools/png_to_tiles.py`, whose public function is `load_png_pixels(data: bytes) -> (List[int], int, int)` — a flat row-major list of Game Boy palette indices 0–3, the width and the height — and which raises `ValueError` on an unsupported format or more than four colours.
- Produces:
  - `TILE_SIZE = 8`, `MAX_COLOURS = 4`, `MAX_TILES = 192`
  - `class ConverterUnavailable(Exception)` with `.path` and `.message`
  - `load_png_tools(binding)` -> module
  - `@dataclass(frozen=True) PngFacts(width, height, tiles_x, tiles_y, tile_count, colour_count, pixels, error)`
  - `read_png(binding, path) -> PngFacts`
  - `@dataclass(frozen=True) TmxFacts(width, height, tile_width, tile_height, error)`
  - `read_tmx(path) -> TmxFacts`
  - `plte_entry_count(data: bytes) -> Optional[int]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_assets.py`, above the `if __name__` block, and add `from tools.garage.core import preview` to the imports at the top:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: FAIL — `ImportError: cannot import name 'preview'`

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/preview.py`:

```python
"""Game Boy palette preview data and asset cost (R2, R3).

No Qt import belongs here (R12). This module returns *numbers and palette
indices*: 0-3 per pixel, a tile count, a colour count, a map size. It
names no colour at all -- the four shades live in
`tools/garage/theme/tokens.py`, because that package is the only place in
this application where a colour may be spelled out (P1 R18/AC18), and the
panel is what turns an index into one.

**Where the numbers come from.** The pixels and the colour rejection are
the active worktree's own `tools/png_to_tiles.py`, loaded as a module and
called (`load_png_pixels`). Not a second PNG decoder written here: AC3
asks the tile cost Garage shows to match the tile count png_to_tiles
produces, and AC4 asks the colour failure to be the one the converter
would give. Two implementations of that would agree on the day they were
written and drift afterwards -- and R6 forbids copying converter logic
into this repository, which a second 2bpp-aware decoder would be.

Loading is by path through the binding (R13), so it is the converter of
the *active worktree* -- a worktree whose converter differs is previewed
by its own converter, which is the only answer that can be right.

R6's "as a subprocess" governs *running* a converter, which writes files;
that is `core/pipeline.py`. This module only reads, which is why it can
afford to call the function directly and hand back exactly what it
returned.
"""
from __future__ import annotations

import importlib.util
import struct
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The Game Boy tile is 8x8 -- the grid R2 asks to be drawn over a preview,
# and the unit the tile cost counts in.
TILE_SIZE = 8

# The limits the game repository's converters enforce. Named here because
# Garage reports them *before* the converter runs (R4); each one cites
# where it is enforced, so a change there has one place to land here.
MAX_COLOURS = 4       # png_to_tiles.load_png_pixels
MAX_TILES = 192       # png_to_tiles.png_to_c -- the VRAM budget

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_TO_TILES_RELATIVE = ("tools", "png_to_tiles.py")


class ConverterUnavailable(Exception):
    """The active worktree does not hold a converter Garage needs. Carries
    the path it looked for, so the panel can say which file is missing from
    which worktree rather than reporting an import error.
    """

    def __init__(self, path: Path, message: str):
        self.path = path
        self.message = message
        super().__init__(message)


_MODULE_CACHE: Dict[Tuple[str, int], object] = {}


def load_png_tools(binding):
    """The active worktree's `tools/png_to_tiles.py`, as a module.

    Cached on (path, mtime): re-executing a module for every asset in a
    grid is wasted work, and keying on the mtime means an edited converter
    is picked up without restarting Garage.

    The module is deliberately *not* registered in `sys.modules`: it is the
    game repository's file, not an import of this package, and a name in
    `sys.modules` is a name a future import here could collide with.
    """
    path = binding.resolve(*PNG_TO_TILES_RELATIVE)
    if not path.is_file():
        raise ConverterUnavailable(
            path,
            f"'{path}' does not exist. Garage previews an image with the "
            f"active worktree's own converter, so it cannot show a preview "
            f"or a tile cost until that file is there.",
        )
    key = (str(path), path.stat().st_mtime_ns)
    cached = _MODULE_CACHE.get(key)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location("garage_png_to_tiles", path)
    if spec is None or spec.loader is None:
        raise ConverterUnavailable(
            path, f"'{path}' could not be loaded as a Python module."
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # a broken converter is a report, not a crash
        raise ConverterUnavailable(
            path, f"'{path}' could not be loaded: {exc}"
        ) from exc
    _MODULE_CACHE[key] = module
    return module


@dataclass(frozen=True)
class PngFacts:
    """What Garage knows about an image before any converter runs.

    `error` is the converter's own message when it refused the file --
    reported verbatim, so the user reads the sentence they would have read
    from the terminal. `pixels` is empty in that case; `colour_count` is
    still filled whenever it can be determined, because AC4 asks Garage to
    name the count even when the decode failed.
    """

    width: Optional[int]
    height: Optional[int]
    tiles_x: Optional[int]
    tiles_y: Optional[int]
    tile_count: Optional[int]
    colour_count: Optional[int]
    pixels: List[int] = field(default_factory=list)
    error: Optional[str] = None


def plte_entry_count(data: bytes) -> Optional[int]:
    """How many colours the PNG's palette declares, or None when it has no
    palette (a truecolour image).

    This walks chunk headers -- length, type, skip -- which is the PNG
    container, not the tile encoding. It is the one thing the converter
    cannot tell us: `load_png_pixels` raises before it reports anything
    when a palette is oversized, and "your palette holds 7 colours, the
    Game Boy allows 4" is the sentence AC4 asks for.
    """
    if not data.startswith(PNG_SIGNATURE):
        return None
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(data):
        (length,) = struct.unpack(">I", data[position:position + 4])
        ctype = data[position + 4:position + 8]
        if ctype == b"PLTE":
            return length // 3
        if ctype == b"IEND":
            return None
        position += 12 + length
    return None


def _colour_count_from_message(message: str) -> Optional[int]:
    """The count png_to_tiles names in its truecolour refusal ("PNG has 7
    distinct luminance values (max 4)"). Read out so the panel can show a
    number beside the sentence; None when the message names none.
    """
    for word in message.replace("(", " ").split():
        if word.isdigit():
            return int(word)
    return None


def read_png(binding, path: Path) -> PngFacts:
    """Everything the panel needs about one image (R2, R3).

    Raises ConverterUnavailable when the active worktree holds no
    png_to_tiles.py -- that is a broken worktree, not a broken asset, and
    the two must not be reported the same way. A file the converter
    *rejects* comes back as a PngFacts carrying its message.
    """
    module = load_png_tools(binding)
    data = Path(path).read_bytes()
    palette_size = plte_entry_count(data)

    try:
        pixels, width, height = module.load_png_pixels(data)
    except ValueError as exc:
        message = str(exc)
        return PngFacts(
            width=None, height=None, tiles_x=None, tiles_y=None,
            tile_count=None,
            colour_count=palette_size or _colour_count_from_message(message),
            pixels=[], error=message,
        )
    except Exception as exc:  # a truncated or corrupt file
        return PngFacts(
            width=None, height=None, tiles_x=None, tiles_y=None,
            tile_count=None, colour_count=palette_size, pixels=[],
            error=f"{type(exc).__name__}: {exc}",
        )

    tiles_x = width // TILE_SIZE
    tiles_y = height // TILE_SIZE
    return PngFacts(
        width=width,
        height=height,
        tiles_x=tiles_x,
        tiles_y=tiles_y,
        # png_to_tiles.png_to_c counts exactly this (`n_tiles`). A tileset
        # built with a rotation manifest costs more -- the rotated variants
        # it generates are counted at conversion time and cannot be known
        # in advance -- see core/pipeline.py's ROTATION_NOTE.
        tile_count=tiles_x * tiles_y,
        colour_count=palette_size if palette_size is not None else len(set(pixels)),
        pixels=list(pixels),
    )


@dataclass(frozen=True)
class TmxFacts:
    """The size of a map, in tiles (R3)."""

    width: Optional[int]
    height: Optional[int]
    tile_width: Optional[int]
    tile_height: Optional[int]
    error: Optional[str] = None


def read_tmx(path: Path) -> TmxFacts:
    """The `<map>` element's declared size. Plain XML: Tiled's format
    carries the size as attributes, so no converter is needed and none is
    loaded -- reading a map's size must work in a worktree whose
    tmx_to_c.py is missing.
    """
    try:
        root = ElementTree.parse(str(path)).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        return TmxFacts(None, None, None, None, error=f"{path.name}: {exc}")

    def attribute(name: str) -> Optional[int]:
        raw = root.get(name)
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            return None

    return TmxFacts(
        width=attribute("width"),
        height=attribute("height"),
        tile_width=attribute("tilewidth"),
        tile_height=attribute("tileheight"),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS. On a machine with the game repository beside this one, `TestReadPng` runs; without it, those 6 tests skip and `TestReadTmx` still runs.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/preview.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 2: preview facts from the worktree's own converter"
```

---

## Task 3: Pre-flight verification

**Files:**
- Modify: `tools/garage/core/assets.py` (append)
- Modify: `tests/test_garage_assets.py` (append)

**Interfaces:**
- Consumes: `preview.read_png`, `preview.read_tmx`, `preview.PngFacts`, `preview.TmxFacts`, `preview.ConverterUnavailable`, `preview.MAX_COLOURS`, `preview.MAX_TILES`, `preview.TILE_SIZE`; `Asset` and the `KIND_*` constants from Task 1.
- Produces:
  - `@dataclass(frozen=True) Problem(code: str, message: str, limit: str)`
  - `PROBLEM_COLOURS = "colours"`, `PROBLEM_DIMENSIONS = "dimensions"`, `PROBLEM_TILE_COST = "tile-cost"`, `PROBLEM_UNREADABLE = "unreadable"`, `PROBLEM_CONVERTER = "converter"`
  - `@dataclass Verification(asset, problems, png, tmx)` with `.ok` and `.summary()`
  - `verify(binding, asset) -> Verification`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_assets.py`:

```python
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
        # Greyscale (colour type 0) — a real PNG that png_to_tiles does not
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets.TestVerify -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.assets' has no attribute 'verify'`

- [ ] **Step 3: Write the implementation**

First extend the module docstring's summary line — Task 1 left it describing only what Task 1 delivered:

```python
"""Asset discovery, kind detection and pre-flight verification.
```

Then append to `tools/garage/core/assets.py` (and add `from tools.garage.core import preview` to its imports):

```python
# ── Verification (R4) ────────────────────────────────────────────────────
# Today an asset problem appears as a converter error, or later as a
# compile error -- both far from the change that caused them. R4 moves the
# report to the moment the user selects the asset, which is only useful if
# it states *which* limit is exceeded and by how much. Every Problem
# therefore carries both the measured value and the limit.

PROBLEM_COLOURS = "colours"
PROBLEM_DIMENSIONS = "dimensions"
PROBLEM_TILE_COST = "tile-cost"
PROBLEM_UNREADABLE = "unreadable"
PROBLEM_CONVERTER = "converter"


@dataclass(frozen=True)
class Problem:
    """One reason a converter must not run yet. `message` states what is
    wrong including the measured value; `limit` states the limit exceeded.
    Both are shown -- "5 colours" alone does not say what is allowed.
    """

    code: str
    message: str
    limit: str


@dataclass
class Verification:
    asset: "Asset"
    problems: List[Problem]
    png: "preview.PngFacts | None" = None
    tmx: "preview.TmxFacts | None" = None

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        """One line naming every problem, for a tooltip or a log."""
        if not self.problems:
            return "Verified — no problem found."
        return "  ".join(f"{p.message} (limit: {p.limit})" for p in self.problems)


def _verify_image(binding, asset: "Asset") -> Verification:
    try:
        facts = preview.read_png(binding, asset.path)
    except preview.ConverterUnavailable as exc:
        return Verification(
            asset,
            [Problem(PROBLEM_CONVERTER, exc.message, "a converter in the worktree")],
        )

    problems: List[Problem] = []

    # The colour rejection is the converter's own sentence, so the user
    # reads what a terminal would have printed (AC4). The count is stated
    # separately because png_to_tiles' indexed-PNG message names the
    # offending index rather than the count.
    if facts.error is not None:
        count = facts.colour_count
        looks_like_colours = count is not None and count > preview.MAX_COLOURS
        problems.append(
            Problem(
                PROBLEM_COLOURS if looks_like_colours else PROBLEM_UNREADABLE,
                (
                    f"{asset.name} has {count} colours — {facts.error}"
                    if looks_like_colours
                    else f"{asset.name} could not be read — {facts.error}"
                ),
                (
                    f"{preview.MAX_COLOURS} colours"
                    if looks_like_colours
                    else "a PNG png_to_tiles.py accepts"
                ),
            )
        )
        return Verification(asset, problems, png=facts)

    if facts.colour_count is not None and facts.colour_count > preview.MAX_COLOURS:
        # An indexed PNG whose palette is oversized but whose pixels stay
        # inside 0-3 decodes cleanly. png_to_tiles accepts it; the palette
        # is still wrong, and the user will hit it the moment they use a
        # fifth entry.
        problems.append(
            Problem(
                PROBLEM_COLOURS,
                f"{asset.name} has a palette of {facts.colour_count} colours",
                f"{preview.MAX_COLOURS} colours",
            )
        )

    if facts.width % preview.TILE_SIZE or facts.height % preview.TILE_SIZE:
        problems.append(
            Problem(
                PROBLEM_DIMENSIONS,
                f"{asset.name} is {facts.width}×{facts.height} pixels, which is "
                f"not a whole number of tiles",
                f"a multiple of {preview.TILE_SIZE} pixels on each side",
            )
        )

    if facts.tile_count is not None and facts.tile_count > preview.MAX_TILES:
        problems.append(
            Problem(
                PROBLEM_TILE_COST,
                f"{asset.name} costs {facts.tile_count} tiles",
                f"{preview.MAX_TILES} tiles of VRAM",
            )
        )

    return Verification(asset, problems, png=facts)


def _verify_map(asset: "Asset") -> Verification:
    facts = preview.read_tmx(asset.path)
    if facts.error is not None:
        return Verification(
            asset,
            # The limit names the *format*, not the program that writes it.
            # R8 keeps every editor's name out of Garage, and a message the
            # card shows in a tooltip is exactly where one would creep back
            # in. It is also more useful this way: the user knows which
            # program made the file, and what they need is what is wrong
            # with it.
            [Problem(PROBLEM_UNREADABLE, facts.error, "a well-formed .tmx file")],
            tmx=facts,
        )
    return Verification(asset, [], tmx=facts)


def verify(binding, asset: "Asset") -> Verification:
    """Pre-flight an asset (R4). `Verification.ok` is what R5's refusal
    reads; nothing here runs a converter or writes a file.

    Music has no pre-flight: a `.uge` is a binary Garage cannot inspect,
    and R11 names the two validators as its check -- they run after the
    user comes back from the editor, which is where their answer means
    something.
    """
    if asset.kind in (KIND_SPRITES, KIND_TILES):
        if asset.path.suffix.lower() in IMAGE_SUFFIXES:
            return _verify_image(binding, asset)
        # A .aseprite or .xcf source: the file the artist edits, not the
        # file a converter reads. Nothing to verify and nothing to refuse.
        return Verification(asset, [])
    if asset.kind == KIND_MAPS:
        return _verify_map(asset)
    return Verification(asset, [])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/assets.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 3: pre-flight verification"
```

---

## Task 4: Makefile rule parsing and the generated-file set

**Files:**
- Create: `tools/garage/core/pipeline.py`
- Modify: `tests/test_garage_assets.py` (append)

**Interfaces:**
- Consumes: `project.Binding.resolve`, `project.Binding.active_worktree.path`.
- Produces:
  - `MAKEFILE_NAME = "Makefile"`
  - `@dataclass(frozen=True) Rule(targets: Tuple[str, ...], prerequisites: Tuple[str, ...], recipe: Tuple[str, ...])` with `.is_converter` and `.converter_names()`
  - `CONVERTER_MARKER = "python tools/"`
  - `parse_makefile(text: str) -> List[Rule]`
  - `read_rules(binding) -> List[Rule]` (raises `PipelineError` when no Makefile)
  - `class PipelineError(Exception)` with `.message`
  - `targets_for_asset(rules, relative_path) -> List[str]`
  - `generated_files(rules) -> Set[str]`
  - `ROTATION_NOTE: str`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_assets.py` (and add `from tools.garage.core import pipeline` at the top):

```python
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

    def test_a_phony_rule_is_not_a_converter_rule(self):
        """`memory-check` runs `python tools/...` like every converter
        rule does, but it is a command, not a file. The game repository
        has ten of these; without the `.PHONY` check they are all
        classified as converters."""
        rule = self._rule_for("memory-check")
        self.assertTrue(rule.phony)
        self.assertFalse(rule.is_converter)

    def test_a_recipe_less_rule_is_not_a_converter_rule(self):
        rule = [r for r in self.rules
                if "build/track_tile_id_map.json" in r.targets][0]
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
        exactly — the second pass has to exclude phony targets itself.
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

    def test_no_phony_maintenance_target_is_called_a_generated_file(self):
        """The real Makefile declares ten phony targets whose recipes run
        `python tools/...`. Every one of them looked like a converter rule
        before `.PHONY` was consulted."""
        generated = pipeline.generated_files(self.rules)
        for phony in ("all", "hooks", "memory-check", "bank-check",
                      "sync-docs", "dialog_data", "tile-check"):
            self.assertNotIn(phony, generated)

    def test_the_player_sprite_resolves_to_its_generated_source(self):
        self.assertIn(
            "src/player_sprite.c",
            pipeline.targets_for_asset(
                self.rules, "assets/sprites/player_car.png"
            ),
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: FAIL — `ImportError: cannot import name 'pipeline'`

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/pipeline.py`:

```python
"""Which converter an asset feeds, and the command that runs it (R6, R10).

No Qt import belongs here (R12); nothing here writes a file of its own.

**Why this reads the game repository's Makefile.** R6 forbids copying
converter logic into this repository, and AC6 asks a run from Garage to
produce the same output file as the same converter run from a terminal.
The invocations are not uniform -- `png_to_tiles.py` takes `--bank 255`,
an output path and an array name; the track tileset also takes a rotation
manifest, a `.tsx`, an id-map output and a meta-header output; a `.tmx`
feeds several targets at once. Spelling those out here would be exactly
the copy R6 forbids, and would drift the first time the game repository
changed one. The Makefile already holds every one of them, so Garage reads
it and then asks `make` to do the work -- the terminal command, run from a
window.

**Why `make -W <asset> <targets>` and not `make -B`.** `make <target>`
alone does nothing when the asset is older than its output, and "I pressed
Convert and nothing ran" is not an outcome. `-B` would force *every*
prerequisite, including `assets/maps/tileset.png: assets/maps/tileset.
aseprite`, which needs a drawing program on PATH -- so a user who edited
the PNG directly would be told to install Aseprite. `-W <asset>` says
"treat this one file as new", which forces exactly the chain the user
asked for and leaves everything else alone.

**Music is the exception R11 states.** No Makefile rule reads a `.uge`:
the export to `src/music_data.c` happens inside the tracker. So the two
validators are named here, and only here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Set, Tuple

MAKEFILE_NAME = "Makefile"

# What marks a recipe line as running one of the game repository's own
# converters. Every converter rule in that Makefile is spelled this way
# ("python tools/png_to_tiles.py ...", "python tools/tmx_to_c.py ..."),
# and it is what separates them from the aseprite export rules and from
# the compile/link recipes.
CONVERTER_MARKER = "python tools/"

# The converters R6 names, for the panel to say which one a card would
# run. Read out of the recipe rather than assumed from the asset's kind:
# the Makefile is what decides, and a rule that changed tool would
# otherwise be reported wrongly.
KNOWN_CONVERTERS = (
    "png_to_tiles.py",
    "tmx_to_c.py",
    "overmap_to_c.py",
    "dialog_to_c.py",
    "tmx_to_array_c.py",
)

# Said beside a tileset built with a rotation manifest. Garage's tile cost
# is the base tile count (width/8 x height/8, which is png_to_tiles'
# `n_tiles`); that converter then generates a rotated variant per entry in
# the manifest and checks the *total* against 192. The total cannot be
# known without running it, so the panel says which number it is showing
# rather than implying the budget is safe.
ROTATION_NOTE = (
    "base tiles only — this tileset also generates rotated variants at "
    "conversion time, which count against the same 192-tile VRAM budget."
)

# The two music validators R11 names, and what each is run against.
MUSIC_SONG_VALIDATE = ("tools", "music_song_validate.py")
MUSIC_WIRE_CHECK = ("tools", "music_wire_check.py")
# music_song_validate.py validates the hUGETracker *C export*, not the
# .uge -- the .uge is the tracker's project file and nothing outside the
# tracker reads it. This is the file the export lands in.
MUSIC_EXPORT_RELATIVE = "src/music_data.c"

MAKE_EXECUTABLE = "make"

# A variable assignment, not a rule. `export ` is allowed in front of it
# because the game repository's Makefile has one (`export PYTHONUTF8 := 1`)
# and without it "export" and "PYTHONUTF8" parse as two targets.
_ASSIGNMENT = re.compile(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*(:?=|\+=|\?=|::=)")


class PipelineError(Exception):
    """The active worktree cannot answer a question about converters --
    no Makefile, or none Garage can read. Carries a message that names the
    path and what the failure prevents.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Rule:
    """One Makefile rule: what it writes, what it reads, how it does it.

    `recipe` lines have their leading tab stripped and their continuations
    joined, so one entry is one command.
    """

    targets: Tuple[str, ...]
    prerequisites: Tuple[str, ...]
    recipe: Tuple[str, ...]
    phony: bool = False

    @property
    def is_converter(self) -> bool:
        """True when this rule runs one of the game repository's own tools
        to write a generated source. Two kinds of rule are excluded.

        A rule whose target is another asset (the aseprite exports)
        produces an input, not an output, and needs a drawing program
        Garage must not require.

        A `.PHONY` rule is a command, not a file. The game repository has
        ten of them whose recipes run `python tools/...` -- `memory-check`,
        `bank-check`, `hooks`, `sync-docs`, `all` and the rest -- and
        without this they are classified as converter rules and their names
        end up in `generated_files()`, a set whose whole meaning is "paths
        a converter writes". Make already declares the answer, so this asks
        it rather than guessing from the shape of the name.
        """
        if self.phony or not self.recipe:
            return False
        if not any(CONVERTER_MARKER in line for line in self.recipe):
            return False
        return not any(t.startswith("assets/") for t in self.targets)

    def converter_names(self) -> Tuple[str, ...]:
        """The converter scripts this rule's recipe invokes, in order."""
        found = []
        for line in self.recipe:
            for name in KNOWN_CONVERTERS:
                if name in line and name not in found:
                    found.append(name)
        return tuple(found)


def _join_continuations(text: str) -> List[str]:
    """Fold `\\`-continued lines into one, keeping a leading tab on the
    result when the first line had one (that tab is what makes a line a
    recipe).
    """
    joined: List[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if buffer:
            buffer += " " + line.strip()
        else:
            buffer = line
        if buffer.endswith("\\"):
            buffer = buffer[:-1].rstrip()
            continue
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _is_rule_line(line: str) -> bool:
    if not line or line.startswith("\t") or line.lstrip().startswith("#"):
        return False
    if _ASSIGNMENT.match(line.strip()):
        return False
    return ":" in line


def _split_targets_and_prerequisites(line: str) -> Tuple[List[str], List[str]]:
    head, _, tail = line.partition(":")
    # Order-only prerequisites (after `|`) are ordering constraints, not
    # inputs: `| build` only says the build directory must exist first.
    tail = tail.split("|", 1)[0]
    return head.split(), tail.split()


def _usable(name: str) -> bool:
    """A target Garage can name on a make command line: a literal path.
    A pattern (`%`) and a variable (`$(TARGET)`) are neither.
    """
    return "%" not in name and "$" not in name


def _phony_targets(lines: List[str]) -> Set[str]:
    """Every name `.PHONY` declares.

    Collected in its own pass because Make lets `.PHONY` appear anywhere,
    including after the rules it names -- reading it as we go would
    classify a rule correctly or not depending on line order.
    """
    phony: Set[str] = set()
    for line in lines:
        if line.startswith("\t"):
            continue
        head, separator, tail = line.partition(":")
        if separator and head.strip() == ".PHONY":
            phony.update(tail.split())
    return phony


def parse_makefile(text: str) -> List[Rule]:
    """Every rule in `text` whose targets are literal paths.

    Deliberately not a Make implementation: no variable expansion, no
    conditionals, no includes. It answers one question -- which literal
    target lists this asset as a prerequisite -- and everything it cannot
    answer literally it drops, so a rule Garage misreads becomes a rule
    Garage does not offer rather than a wrong command run in the user's
    worktree.
    """
    lines = _join_continuations(text)
    phony_names = _phony_targets(lines)

    rules: List[Rule] = []
    targets: List[str] = []
    prerequisites: List[str] = []
    recipe: List[str] = []
    have_rule = False

    def flush() -> None:
        nonlocal have_rule, targets, prerequisites, recipe
        if have_rule and targets:
            rules.append(
                Rule(
                    targets=tuple(targets),
                    prerequisites=tuple(prerequisites),
                    recipe=tuple(recipe),
                    phony=any(t in phony_names for t in targets),
                )
            )
        have_rule, targets, prerequisites, recipe = False, [], [], []

    for line in lines:
        if line.startswith("\t"):
            if have_rule:
                recipe.append(line[1:].strip())
            continue
        if not line.strip():
            continue
        if not _is_rule_line(line):
            flush()
            continue
        flush()
        parsed_targets, parsed_prerequisites = _split_targets_and_prerequisites(line)
        parsed_targets = [t for t in parsed_targets if _usable(t)]
        if not parsed_targets or parsed_targets == [".PHONY"]:
            continue
        have_rule = True
        targets = parsed_targets
        prerequisites = [p for p in parsed_prerequisites if _usable(p)]
    flush()
    return rules


def makefile_path(binding) -> Path:
    """The active worktree's Makefile (R13)."""
    return binding.resolve(MAKEFILE_NAME)


def read_rules(binding) -> List[Rule]:
    """Parse the active worktree's Makefile."""
    path = makefile_path(binding)
    if not path.is_file():
        raise PipelineError(
            f"'{path}' does not exist. Garage reads the game repository's "
            f"own Makefile to learn which converter each asset feeds, so it "
            f"cannot offer a conversion until that file is there."
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PipelineError(f"'{path}' could not be read: {exc}") from exc
    return parse_makefile(text)


def targets_for_asset(rules: Sequence[Rule], relative_path: str) -> List[str]:
    """Every generated file that reads `relative_path`, sorted.

    All of them, not the first: `assets/maps/track.tmx` feeds the map
    source *and* the rotation manifest, and converting one without the
    other leaves the worktree half converted.
    """
    found: List[str] = []
    for rule in rules:
        if not rule.is_converter:
            continue
        if relative_path in rule.prerequisites:
            found.extend(t for t in rule.targets if t not in found)
    return sorted(found)


def generated_files(rules: Sequence[Rule]) -> Set[str]:
    """Every file a converter rule writes (R10).

    Derived from the Makefile, not listed here: the spec names three
    (`src/track_map.c`, the generated tile sources, `src/dialog_data.c`),
    and a list would go stale the first time the game repository added a
    fourth. Includes the recipe-less rules that declare a converter's
    side-effect outputs (`build/track_tile_id_map.json
    src/track_tileset_meta.h: src/track_tiles.c`), which are generated by
    the rule that writes their prerequisite.

    The second pass excludes `.PHONY` rules for the same reason the first
    one does, and it has to say so itself: `dialog_data: src/dialog_data.c
    src/hub_data.c` is a phony rule with no recipe whose prerequisites are
    both generated, so it satisfies the side-effect test exactly. Reading
    `is_converter` in the first pass is not enough -- this loop never
    consults it.
    """
    generated: Set[str] = set()
    for rule in rules:
        if rule.is_converter:
            generated.update(rule.targets)
    for rule in rules:
        if rule.phony or rule.recipe or not rule.prerequisites:
            continue
        if all(p in generated for p in rule.prerequisites):
            generated.update(rule.targets)
    return generated
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/pipeline.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 4: Makefile rule parsing and the generated-file set"
```

---

## Task 5: Converter commands, the refusal, and the music validators

**Files:**
- Modify: `tools/garage/core/pipeline.py` (append)
- Modify: `tests/test_garage_assets.py` (append)

**Interfaces:**
- Consumes: `Rule`, `targets_for_asset`, `read_rules`, `PipelineError` (Task 4); `assets.Asset`, `assets.Verification`, `assets.KIND_MUSIC`, `assets.verify` (Tasks 1 and 3); `make_runner.Command` and `make_runner.run_sequence` (P1).
- Produces:
  - `@dataclass(frozen=True) Plan(commands: Tuple[Command, ...], targets: Tuple[str, ...], converters: Tuple[str, ...], refusal: Optional[str], rotation: bool)` with `.can_run`
  - `plan_for(binding, asset, verification, rules=None) -> Plan`
  - `music_commands(binding) -> List[Command]`
  - `REFUSAL_PREFIX = "Verification failed"`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_assets.py`:

```python
@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestPlanFor(unittest.TestCase):
    """R5/R6/R11: what Garage would run for an asset, and when it refuses
    to run anything at all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_repo_with_converters(self.root)
        (self.repo / "Makefile").write_text(SAMPLE_MAKEFILE, encoding="utf-8")
        self.binding = bind_over(self.root, self.repo)
        self.rules = pipeline.parse_makefile(SAMPLE_MAKEFILE)

    def tearDown(self):
        self._tmp.cleanup()

    def _asset(self, relative: str) -> assets.Asset:
        return [a for a in assets.discover(self.binding)
                if a.relative_path == relative][0]

    def _plan(self, relative: str) -> pipeline.Plan:
        asset = self._asset(relative)
        return pipeline.plan_for(
            self.binding, asset, assets.verify(self.binding, asset), self.rules
        )

    def test_a_clean_sprite_gets_the_make_command_for_its_target(self):
        """AC6: the same command a terminal runs."""
        write_indexed_png(self.repo / "assets/sprites/player_car.png", 16, 8, 4)

        plan = self._plan("assets/sprites/player_car.png")

        self.assertTrue(plan.can_run)
        self.assertEqual(len(plan.commands), 1)
        self.assertEqual(
            list(plan.commands[0].argv),
            ["make", "-W", "assets/sprites/player_car.png", "src/player_sprite.c"],
        )
        self.assertEqual(plan.converters, ("png_to_tiles.py",))

    def test_a_failed_verification_refuses_and_produces_no_command(self):
        """AC5."""
        write_indexed_png(self.repo / "assets/sprites/player_car.png", 8, 8, 9)

        plan = self._plan("assets/sprites/player_car.png")

        self.assertFalse(plan.can_run)
        self.assertEqual(plan.commands, ())
        self.assertIn("9", plan.refusal)

    def test_a_map_gets_every_target_in_one_make_call(self):
        (self.repo / "assets/maps").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/maps/track.tmx").write_text(
            '<map width="64" height="32" tilewidth="8" tileheight="8"></map>',
            encoding="utf-8",
        )

        plan = self._plan("assets/maps/track.tmx")

        self.assertEqual(
            list(plan.commands[0].argv),
            ["make", "-W", "assets/maps/track.tmx",
             "build/track_rotation_manifest.json", "src/track_map.c"],
        )
        self.assertEqual(plan.converters, ("tmx_to_c.py",))

    def test_an_asset_no_rule_reads_refuses_and_says_so(self):
        (self.repo / "assets/reference").mkdir(parents=True, exist_ok=True)
        write_indexed_png(self.repo / "assets/reference/shot.png", 8, 8, 4)

        plan = self._plan("assets/reference/shot.png")

        self.assertFalse(plan.can_run)
        self.assertIn("Makefile", plan.refusal)

    def test_a_uge_gets_the_two_music_validators(self):
        """R11/AC11."""
        (self.repo / "assets/music").mkdir(parents=True, exist_ok=True)
        (self.repo / "assets/music/song.uge").write_bytes(b"\x00")

        plan = self._plan("assets/music/song.uge")

        self.assertTrue(plan.can_run)
        self.assertEqual(len(plan.commands), 2)
        self.assertIn("music_song_validate.py", plan.commands[0].argv[2])
        self.assertEqual(plan.commands[0].argv[3], "src/music_data.c")
        self.assertIn("music_wire_check.py", plan.commands[1].argv[2])
        self.assertEqual(
            plan.converters, ("music_song_validate.py", "music_wire_check.py")
        )

    def test_the_music_commands_run_the_worktrees_own_copies(self):
        """R13: no path here is hardcoded -- these must point into the
        fixture worktree, not into any checkout on this machine."""
        commands = pipeline.music_commands(self.binding)

        for command in commands:
            self.assertTrue(
                Path(command.argv[2]).is_relative_to(self.repo),
                f"{command.argv[2]} is outside the active worktree",
            )


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestConverterRunProducesTheSameFile(unittest.TestCase):
    """AC6, end to end: run the plan's command with make_runner and
    compare the file it wrote against the one a terminal invocation of the
    converter writes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_repo_with_converters(self.root)
        (self.repo / "Makefile").write_text(
            "src/player_sprite.c: assets/sprites/player_car.png tools/png_to_tiles.py\n"
            "\tpython tools/png_to_tiles.py --bank 255 "
            "assets/sprites/player_car.png src/player_sprite.c player_tile_data\n",
            encoding="utf-8",
        )
        (self.repo / "src").mkdir(exist_ok=True)
        write_indexed_png(self.repo / "assets/sprites/player_car.png", 16, 8, 4)
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_make_from_garage_writes_what_the_terminal_writes(self):
        from tools.garage.core import make_runner

        asset = [a for a in assets.discover(self.binding)
                 if a.relative_path == "assets/sprites/player_car.png"][0]
        plan = pipeline.plan_for(
            self.binding, asset, assets.verify(self.binding, asset)
        )
        lines = []
        results = make_runner.run_sequence(
            list(plan.commands), self.repo, lines.append
        )
        if results and results[0].exit_code == make_runner.EXIT_NOT_STARTED:
            self.skipTest("make is not on PATH on this machine")
        self.assertTrue(all(r.ok for r in results), "\n".join(lines))
        from_garage = (self.repo / "src/player_sprite.c").read_bytes()

        (self.repo / "src/player_sprite.c").unlink()
        subprocess.run(
            [sys.executable, "tools/png_to_tiles.py", "--bank", "255",
             "assets/sprites/player_car.png", "src/player_sprite.c",
             "player_tile_data"],
            cwd=str(self.repo), check=True, capture_output=True, text=True,
        )
        from_terminal = (self.repo / "src/player_sprite.c").read_bytes()

        self.assertEqual(from_garage, from_terminal)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets.TestPlanFor -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.pipeline' has no attribute 'plan_for'`

- [ ] **Step 3: Write the implementation**

First extend `tools/garage/core/pipeline.py`'s imports — Task 4 left them at what Task 4 used:

```python
import sys                                                    # add
from typing import List, Optional, Sequence, Set, Tuple       # add Optional

from tools.garage.core import assets as assets_core           # add
from tools.garage.core.make_runner import Command             # add
```

(`assets.py` imports `preview`, and neither imports `pipeline`, so this is not a cycle.)

Then append:

```python
# ── What Garage would run, and when it refuses (R5, R6, R11) ─────────────

REFUSAL_PREFIX = "Verification failed"


@dataclass(frozen=True)
class Plan:
    """The commands for one asset, or the reason there are none.

    `refusal` and `commands` are exclusive: R5 says a failed verification
    means no converter runs, and the way to make that structural rather
    than remembered is for the refusing branch to produce an empty command
    list. A panel that runs `plan.commands` cannot run a refused asset.
    """

    commands: Tuple[Command, ...] = ()
    targets: Tuple[str, ...] = ()
    converters: Tuple[str, ...] = ()
    refusal: Optional[str] = None
    # True when a rule for this asset passes `--rotation-manifest`, which
    # is what makes Garage's tile cost a *base* count -- see ROTATION_NOTE.
    rotation: bool = False

    @property
    def can_run(self) -> bool:
        return bool(self.commands) and self.refusal is None


def music_commands(binding) -> List[Command]:
    """R11's two validators, run against the active worktree's own copies.

    `music_song_validate.py` reads the hUGETracker C export -- the .uge is
    the tracker's project file, and nothing outside the tracker parses it.
    `music_wire_check.py` reads the whole worktree and checks that the
    export is wired into music_data.h, music.c and bank-manifest.json.
    Between them they answer the only question Garage can ask about a song
    after the user has been in the editor: is what came out of it usable.

    `sys.executable`, not "python": Garage must run the interpreter it is
    running under, not whatever a PATH lookup finds.
    """
    worktree = binding.active_worktree.path
    song = binding.resolve(*MUSIC_SONG_VALIDATE)
    wire = binding.resolve(*MUSIC_WIRE_CHECK)
    return [
        Command(
            argv=(sys.executable, "-u", str(song), MUSIC_EXPORT_RELATIVE),
            label=f"python tools/{MUSIC_SONG_VALIDATE[-1]} {MUSIC_EXPORT_RELATIVE}",
            target=MUSIC_EXPORT_RELATIVE,
        ),
        Command(
            argv=(sys.executable, "-u", str(wire), str(worktree)),
            label=f"python tools/{MUSIC_WIRE_CHECK[-1]} .",
            target=MUSIC_EXPORT_RELATIVE,
        ),
    ]


def _converters_for_targets(rules: Sequence[Rule], targets: Sequence[str]) -> Tuple[str, ...]:
    found: List[str] = []
    for rule in rules:
        if not rule.is_converter or not any(t in targets for t in rule.targets):
            continue
        for name in rule.converter_names():
            if name not in found:
                found.append(name)
    return tuple(found)


def plan_for(binding, asset, verification, rules: Sequence[Rule] = None) -> Plan:
    """What Garage would run for `asset`, or why it will not.

    R5 first: a failed verification produces a refusal and no command, so
    the panel cannot run a converter on an asset that failed. The refusal
    is the verification's own summary, which names the value and the limit
    (R4).
    """
    if not verification.ok:
        return Plan(refusal=f"{REFUSAL_PREFIX} — {verification.summary()}")

    if asset.kind == assets_core.KIND_MUSIC:
        commands = music_commands(binding)
        return Plan(
            commands=tuple(commands),
            targets=(MUSIC_EXPORT_RELATIVE,),
            converters=(MUSIC_SONG_VALIDATE[-1], MUSIC_WIRE_CHECK[-1]),
        )

    if rules is None:
        try:
            rules = read_rules(binding)
        except PipelineError as exc:
            return Plan(refusal=exc.message)

    targets = targets_for_asset(rules, asset.relative_path)
    if not targets:
        return Plan(
            refusal=(
                f"No rule in the game repository's Makefile reads "
                f"{asset.relative_path}, so there is no converter to run for "
                f"it. It is a source or a reference file rather than an "
                f"input to the build."
            )
        )

    # `-W <asset>`: force the chain this asset feeds and nothing else. See
    # the module docstring for why not `-B`.
    argv = (MAKE_EXECUTABLE, "-W", asset.relative_path, *targets)
    rotation = any(
        rule.is_converter
        and any(t in targets for t in rule.targets)
        and any("--rotation-manifest" in line for line in rule.recipe)
        for rule in rules
    )
    return Plan(
        commands=(Command(argv=argv, label=" ".join(argv), target=targets[0]),),
        targets=tuple(targets),
        converters=_converters_for_targets(rules, targets),
        rotation=rotation,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS. `TestConverterRunProducesTheSameFile` skips when `make` is absent from PATH.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/pipeline.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 5: converter commands, the refusal and the music validators"
```

---

## Task 6: Opening in the default application, and change detection

**Files:**
- Modify: `tools/garage/core/assets.py` (append)
- Modify: `tests/test_garage_assets.py` (append)

**Interfaces:**
- Consumes: `Asset` (Task 1).
- Produces:
  - `class OpenError(Exception)` with `.path` and `.message`
  - `open_in_default_app(path: Path) -> None`
  - `@dataclass(frozen=True) Stamp(exists: bool, size_bytes: int, mtime_ns: int)`
  - `stamp(path) -> Stamp`
  - `has_changed(before: Stamp, after: Stamp) -> bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_assets.py` (and add `from unittest import mock` at the top):

```python
class TestOpenInDefaultApp(unittest.TestCase):
    """R8/AC8: the Windows file association, and no editor named."""

    def test_it_calls_the_windows_shell_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.png"
            path.write_bytes(b"x")
            with mock.patch.object(assets, "_startfile") as startfile:
                assets.open_in_default_app(path)
            startfile.assert_called_once_with(str(path))

    def test_a_missing_file_is_a_named_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "gone.png"
            with self.assertRaises(assets.OpenError) as caught:
                assets.open_in_default_app(path)
            self.assertIn("gone.png", str(caught.exception))

    def test_no_file_association_is_a_named_failure_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.weird"
            path.write_bytes(b"x")
            with mock.patch.object(assets, "_startfile", side_effect=OSError("no app")):
                with self.assertRaises(assets.OpenError) as caught:
                    assets.open_in_default_app(path)
            self.assertIn("no application", str(caught.exception).lower())

    def test_no_editor_is_named_in_any_string_the_code_uses(self):
        """R8: Garage carries no path to an editor and no setting for one.

        Docstrings are excluded on purpose: explaining *why* an Aseprite
        export rule is not a converter is exactly the comment that belongs
        in `core/pipeline.py`. What R8 forbids is a string the code can
        pass to a subprocess or store as a setting, which is every string
        constant that is not a docstring.
        """
        import ast

        from tools.garage.core import pipeline as pipeline_module

        for module in (assets, pipeline_module):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
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
                            editor, lowered,
                            f"{module.__name__} names {editor} in code",
                        )


class TestChangeDetection(unittest.TestCase):
    """R9/AC9: an asset changed on disk after the user opened it."""

    def test_an_untouched_file_reports_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.png"
            path.write_bytes(b"x")
            before = assets.stamp(path)
            self.assertFalse(assets.has_changed(before, assets.stamp(path)))

    def test_a_rewritten_file_reports_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.png"
            path.write_bytes(b"x")
            before = assets.stamp(path)
            path.write_bytes(b"xy")
            self.assertTrue(assets.has_changed(before, assets.stamp(path)))

    def test_a_same_size_rewrite_reports_a_change(self):
        """An editor that saves the same byte count must not slip past --
        the mtime is what catches it."""
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.png"
            path.write_bytes(b"x")
            before = assets.stamp(path)
            path.write_bytes(b"y")
            after = assets.Stamp(
                exists=True, size_bytes=1, mtime_ns=before.mtime_ns + 1_000_000
            )
            self.assertTrue(assets.has_changed(before, after))

    def test_a_deleted_file_reports_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp_root(tmp) / "car.png"
            path.write_bytes(b"x")
            before = assets.stamp(path)
            path.unlink()
            self.assertTrue(assets.has_changed(before, assets.stamp(path)))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_assets.TestOpenInDefaultApp -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.assets' has no attribute '_startfile'`

- [ ] **Step 3: Write the implementation**

First extend the module docstring's summary line one last time, to the module's finished scope:

```python
"""Asset discovery, kind detection, pre-flight verification and the two
file operations the panel needs (open, and "did it change?").
```

Then append to `tools/garage/core/assets.py` (and add `import os`, `import subprocess`, `import sys` to its imports):

```python
# ── Opening an asset, and noticing it changed (R8, R9) ───────────────────


class OpenError(Exception):
    """The file could not be handed to an application. Carries the path,
    so the panel says which file rather than showing a traceback.
    """

    def __init__(self, path: Path, message: str):
        self.path = path
        self.message = message
        super().__init__(message)


def _startfile(target: str) -> None:
    """The Windows shell "open" verb -- the file association itself.

    Wrapped in a function of our own for two reasons: `os.startfile` does
    not exist off Windows, so referring to it at module scope would make
    this module unimportable there (and the default suite runs on Linux in
    CI); and a named seam is what the test replaces, rather than patching
    a standard-library attribute that may not be present.
    """
    if hasattr(os, "startfile"):
        os.startfile(target)  # noqa: S606 -- the shell association is the point
        return
    # Not Windows. Garage ships on Windows (P1 R1), but the module must
    # still work where the suite runs.
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, target])


def open_in_default_app(path: Path) -> None:
    """Hand `path` to whatever application the user has associated with
    its file type (R8).

    Garage names no editor and holds no setting for one: which program
    opens a `.png`, a `.tmx` or a `.uge` is the user's decision, recorded
    where they already record it. That also means Garage cannot know
    whether an application actually appeared -- a failure to *start* one is
    reported; what the user then does in it is R9's problem.
    """
    path = Path(path)
    if not path.is_file():
        raise OpenError(path, f"'{path}' does not exist, so there is nothing to open.")
    try:
        _startfile(str(path))
    except OSError as exc:
        raise OpenError(
            path,
            f"Windows started no application for '{path.name}': {exc}. That "
            f"file type has no application associated with it — set one from "
            f"Explorer (Open with ▸ Choose another app).",
        ) from exc


@dataclass(frozen=True)
class Stamp:
    """What a file looked like at one moment. Size *and* mtime: an editor
    that rewrites a file to the same byte count is the ordinary case for a
    sprite, and size alone would miss every one of them.
    """

    exists: bool
    size_bytes: int
    mtime_ns: int


def stamp(path: Path) -> Stamp:
    try:
        stat = Path(path).stat()
    except OSError:
        return Stamp(exists=False, size_bytes=0, mtime_ns=0)
    return Stamp(exists=True, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)


def has_changed(before: Stamp, after: Stamp) -> bool:
    """Did the file change between the two stamps? A deletion counts: the
    asset the user opened is not the asset on disk any more, which is
    exactly what R9 asks Garage to notice.
    """
    return before != after
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_assets -v`
Expected: PASS.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/assets.py tests/test_garage_assets.py
git commit -m "Add Garage P2 iteration 6: opening in the default application, and change detection"
```

---

## Task 7: The Game Boy shades, and the panel's card grid

**Files:**
- Modify: `tools/garage/theme/tokens.py`
- Modify: `tools/garage/theme/qss.py`
- Create: `tools/garage/panels/assets.py`
- Create: `tests/garage/test_panels_assets.py`

**Interfaces:**
- Consumes: `assets.discover`, `assets.group_by_kind`, `assets.verify`, `assets.KIND_ORDER`, `assets.KIND_LABELS`, `assets.Asset`, `assets.Verification`; `preview.PngFacts`, `preview.TILE_SIZE`, `preview.ConverterUnavailable`; `pipeline.read_rules`, `pipeline.plan_for`, `pipeline.PipelineError`, `pipeline.ROTATION_NOTE`; `project.Binding`, `project.BindingError`; `theme.tokens.TOKENS`.
- Produces:
  - `GB_TOKEN_KEYS: Tuple[str, ...]` and `gb_shades() -> List[QColor]` in `panels/assets.py`
  - `thumbnail_image(facts: preview.PngFacts, scale: int = THUMBNAIL_SCALE, grid: bool = True) -> QImage`
  - `_previewable(facts: preview.PngFacts) -> bool`
  - `cost_text(asset, verification, rotation) -> str`
  - `class AssetCard(QWidget)` with `.asset`, `.verification`, `.plan`, `.open_button`, `.convert_button`, `.verdict_label`, `.cost_label`, `.target_label`, `.set_changed(bool)`, `.is_changed()`
  - `class AssetsPanel(QWidget)` with `.cards()`, `.visible_cards()`, `.set_kind_filter(kind)`, `.refresh()`, `KIND_FILTER_ALL = "all"`

- [ ] **Step 1: Write the failing test**

Create `tests/garage/test_panels_assets.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.garage.test_panels_assets -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.panels.assets'`

- [ ] **Step 3: Add the Game Boy shades to the theme**

In `tools/garage/theme/tokens.py`, add these four entries to the `TOKENS` dict, after `"fail-soft"`:

```python
    # The four Game Boy shades, from the prototype's `:root` block
    # (`--gb0` … `--gb3` in garage/index.html). R2 asks the asset preview
    # to use them; they are here rather than in the panel because this
    # package is the only place in the application where a colour may be
    # spelled out (R18/AC18), and core/preview.py deals in palette
    # indices 0-3 precisely so that it never has to name one.
    "gb-0": "#E8EDD8",
    "gb-1": "#A8B67C",
    "gb-2": "#5A7043",
    "gb-3": "#23301E",
```

In `tools/garage/theme/qss.py`, add this to the docstring's selector list (after the diff-view entry):

```
- `#assets-panel`, `#assets-status`, `#assets-filter`, `#assets-card`,
  `#assets-name`, `#assets-kind`, `#assets-verdict`, `#assets-cost`,
  `#assets-target`, `#assets-log` -- the asset panel
  (`tools/garage/panels/assets.py`). `[verdict="pass"|"fail"|"changed"]`
  carries the OK/problem/CHANGED vocabulary the prototype's `.acard`
  declares; the chip also spells the word out, so colour is never the
  only signal.
```

and add these rules inside `build_stylesheet()`, alongside the existing panel blocks (using the same `t[...]` lookup style the file already uses — never a hex literal):

```python
        f"""
        #assets-card {{
            background: {t["surface"]};
            border: 1px solid {t["line"]};
            border-radius: 5px;
        }}
        #assets-card[verdict="fail"] {{ border-color: {t["fail"]}; }}
        #assets-card[verdict="changed"] {{ border-color: {t["warn"]}; }}
        #assets-name {{ font-family: {FONT_MONO}; font-size: 11px; }}
        #assets-cost, #assets-target {{
            font-family: {FONT_MONO};
            font-size: 10px;
            color: {t["text-3"]};
        }}
        #assets-kind {{ color: {t["text-2"]}; font-size: 10px; }}
        #assets-verdict {{ font-size: 10px; font-weight: 600; }}
        #assets-verdict[verdict="pass"] {{ color: {t["pass"]}; }}
        #assets-verdict[verdict="fail"] {{ color: {t["fail"]}; }}
        #assets-verdict[verdict="changed"] {{ color: {t["warn"]}; }}
        #assets-log {{ font-family: {FONT_MONO}; font-size: 11px; }}
        #assets-status {{ color: {t["text-2"]}; }}
        """,
```

- [ ] **Step 4: Write the panel**

Create `tools/garage/panels/assets.py`:

```python
"""The asset panel: find an asset, see it, learn what it costs, open it,
convert it (spec P2, issue #3).

Layout follows the prototype's Assets screen (`garage/index.html`): a row
of kind chips, a grid of cards — thumbnail, name, kind tag, verdict chip,
cost, actions — and a log underneath for what a converter printed.

R18/AC18: no colour literal here. The four Game Boy shades are read from
`tools.garage.theme.tokens` by name; every other colour is the
stylesheet's, selected through the object names and the `verdict` dynamic
property this module sets.

Threading: a converter run blocks on a subprocess pipe, so it goes through
`tools.garage.panels.runner.RunController` — the same worker the compile
bar and the commit panel use. Everything that touches a widget below runs
on the UI thread.

R10 is held twice. Structurally, the panel lists files under `assets/`
and nothing else, and a card's only reference to a generated file is a
text label naming where the converter writes — no control offers to open
one. `open()` also refuses a path in the generated set outright, so the
rule holds for any caller rather than only for a user clicking a button
that was never drawn.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import assets as assets_core
from tools.garage.core import pipeline, preview
from tools.garage.core.project import Binding, BindingError
from tools.garage.panels.runner import RunController
from tools.garage.theme.tokens import TOKENS

# The four shades, darkest index last, in the order png_to_tiles' palette
# indices run (0 = lightest, 3 = darkest).
GB_TOKEN_KEYS = ("gb-0", "gb-1", "gb-2", "gb-3")

# How many screen pixels one image pixel takes in a card thumbnail, and
# the card's width. The prototype's grid is 168px columns with a 96px
# thumbnail strip.
THUMBNAIL_SCALE = 4
THUMBNAIL_MAX_WIDTH = 152
CARD_WIDTH = 168
GRID_COLUMNS = 4
LOG_VISIBLE_LINES = 8

# The most pixels `thumbnail_image` will walk. 192 tiles is 12,288 pixels,
# so this leaves room for a legal image of any shape while still bounding
# one whose dimensions defeat the tile count -- see `_previewable`.
MAX_PREVIEW_PIXELS = 16384


def gb_shades() -> List[QColor]:
    """The four Game Boy shades as colours, read from the theme by name."""
    return [QColor(TOKENS[key]) for key in GB_TOKEN_KEYS]


def thumbnail_image(facts: preview.PngFacts, scale: int = THUMBNAIL_SCALE,
                    grid: bool = True) -> QImage:
    """An image of `facts.pixels` in the four Game Boy shades, with the
    8-pixel tile grid drawn over it (R2/AC2).

    The grid is drawn in the darkest shade rather than in a colour of its
    own: it must read as a rule over the art, and adding a fifth colour to
    a four-shade preview would be a lie about the palette.
    """
    shades = gb_shades()
    width = (facts.width or 0) * scale
    height = (facts.height or 0) * scale
    image = QImage(max(width, 1), max(height, 1), QImage.Format.Format_RGB32)
    image.fill(shades[0])
    if not facts.pixels or not facts.width:
        return image

    for y in range(facts.height):
        for x in range(facts.width):
            # `& 3` is defence, not conversion: png_to_tiles' own decoder
            # already guarantees 0-3 (it raises on a higher index, and
            # clamps when it quantises luminance). A converter that ever
            # returned something else would be an IndexError here, and a
            # preview is not where that should surface.
            colour = shades[facts.pixels[y * facts.width + x] & 3]
            for dy in range(scale):
                for dx in range(scale):
                    image.setPixelColor(x * scale + dx, y * scale + dy, colour)

    if grid:
        line = shades[3]
        step = preview.TILE_SIZE * scale
        for x in range(0, width, step):
            for y in range(height):
                image.setPixelColor(x, y, line)
        for y in range(0, height, step):
            for x in range(width):
                image.setPixelColor(x, y, line)
    return image


def _previewable(facts: preview.PngFacts) -> bool:
    """Is this image worth drawing a thumbnail of?

    `thumbnail_image` sets every pixel from Python, so its cost is the
    pixel count times the scale squared. An asset inside the tile budget
    is at most 192 tiles — 12,288 pixels, a few hundred thousand calls,
    imperceptible. An asset *over* the budget has no bound at all: the
    reference screenshots in this project are 2454×122, which is 4.8
    million calls and a window frozen for seconds — to preview art the
    converter is going to refuse anyway. Such a card already carries a
    fail chip naming its tile cost, which is the useful half.

    The pixel bound is not redundant with the tile bound. `tile_count` is
    `(width // 8) * (height // 8)`, which floors to zero the moment either
    side is under 8 -- so a 100000x7 strip costs "0 tiles" and would sail
    through a tile-only check straight into the freeze this function
    exists to prevent.
    """
    if not facts.pixels:
        return False
    if (facts.tile_count or 0) > preview.MAX_TILES:
        return False
    return len(facts.pixels) <= MAX_PREVIEW_PIXELS


def cost_text(asset: assets_core.Asset, verification: assets_core.Verification,
              rotation: bool = False) -> str:
    """The cost line under a card: tiles for an image, size for a map,
    bytes for anything else (R3).
    """
    if verification.png is not None and verification.png.tile_count is not None:
        count = verification.png.tile_count
        text = (
            f"{verification.png.width}×{verification.png.height} · "
            f"{count} tile{'' if count == 1 else 's'}"
        )
        return f"{text} · {pipeline.ROTATION_NOTE}" if rotation else text
    if verification.tmx is not None and verification.tmx.width is not None:
        return f"{verification.tmx.width} × {verification.tmx.height} tiles"
    return f"{asset.size_bytes:,} bytes"


class AssetCard(QWidget):
    """One asset: what it looks like, what it costs, what is wrong with
    it, and the two things the user can do to it.

    `convert_button` is disabled — with the refusal as its tooltip — when
    verification failed (R5/AC5). The plan it would run carries no command
    in that case either, so the refusal holds even if a caller reaches
    past the button.
    """

    open_requested = Signal(object)     # AssetCard
    convert_requested = Signal(object)  # AssetCard

    def __init__(self, asset, verification, plan, image: Optional[QImage],
                 parent=None):
        super().__init__(parent)
        self.setObjectName("assets-card")
        # Without this, every rule in the stylesheet's `#assets-card` block
        # is dead: a plain QWidget does not paint a background or a border
        # from a style sheet, so the card's fail and CHANGED borders would
        # simply never appear. `tools/garage/panels/tuner.py` carries the
        # same call for the same reason; `doctor.py` solves it by deriving
        # from QFrame instead.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_WIDTH)
        self.asset = asset
        self.verification = verification
        self.plan = plan
        self._changed = False

        layout = QVBoxLayout(self)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            if pixmap.width() > THUMBNAIL_MAX_WIDTH:
                pixmap = pixmap.scaledToWidth(
                    THUMBNAIL_MAX_WIDTH, Qt.TransformationMode.FastTransformation
                )
            self.thumbnail_label.setPixmap(pixmap)
        else:
            # A map, a song, a source file: no preview exists, and an empty
            # frame that looks like a failed one would be worse than words.
            self.thumbnail_label.setText("no preview")
        layout.addWidget(self.thumbnail_label)

        self.name_label = QLabel(asset.name)
        self.name_label.setObjectName("assets-name")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        row = QHBoxLayout()
        self.kind_label = QLabel(assets_core.KIND_LABELS[asset.kind])
        self.kind_label.setObjectName("assets-kind")
        row.addWidget(self.kind_label)
        row.addStretch(1)
        self.verdict_label = QLabel()
        self.verdict_label.setObjectName("assets-verdict")
        row.addWidget(self.verdict_label)
        layout.addLayout(row)

        self.cost_label = QLabel(cost_text(asset, verification, plan.rotation))
        self.cost_label.setObjectName("assets-cost")
        self.cost_label.setWordWrap(True)
        layout.addWidget(self.cost_label)

        # R10: where the converter writes. A label, never a button — a
        # generated file is read-only in Garage, and the way to make that
        # true is to offer no control that could open one.
        self.target_label = QLabel(
            "→ " + ", ".join(plan.targets) if plan.targets else "no converter"
        )
        self.target_label.setObjectName("assets-target")
        self.target_label.setWordWrap(True)
        self.target_label.setToolTip(
            "Generated — read-only in Garage. Edit the asset, not this file."
            if plan.targets
            else (plan.refusal or "")
        )
        layout.addWidget(self.target_label)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("assets-open")
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self))
        actions.addWidget(self.open_button)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("assets-convert")
        self.convert_button.clicked.connect(
            lambda: self.convert_requested.emit(self)
        )
        actions.addWidget(self.convert_button)
        layout.addLayout(actions)

        self._apply_verdict()

    def _apply_verdict(self) -> None:
        if not self.verification.ok:
            problem = self.verification.problems[0]
            self.verdict_label.setText(problem.message.upper()[:40])
            self.verdict_label.setToolTip(self.verification.summary())
            self.convert_button.setEnabled(False)
            self.convert_button.setToolTip(self.plan.refusal or "")
            self._set_verdict_property("fail")
            return
        if self._changed:
            self.verdict_label.setText("CHANGED")
            self.convert_button.setText("Reconvert")
            self._set_verdict_property("changed")
        else:
            self.verdict_label.setText("OK")
            self.convert_button.setText("Convert")
            self._set_verdict_property("pass")
        self.convert_button.setEnabled(self.plan.can_run)
        self.convert_button.setToolTip(
            "" if self.plan.can_run else (self.plan.refusal or "")
        )

    def _set_verdict_property(self, value: str) -> None:
        for widget in (self, self.verdict_label):
            widget.setProperty("verdict", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def is_changed(self) -> bool:
        return self._changed

    def set_changed(self, changed: bool) -> None:
        """R9: the asset changed on disk since Garage last looked. The
        card says so and its action becomes Reconvert, which is the offer
        AC9 asks for."""
        if changed == self._changed:
            return
        self._changed = changed
        self._apply_verdict()


class AssetsPanel(QWidget):
    """R1's list, R2's previews, R3's costs, R4's verdicts."""

    KIND_FILTER_ALL = "all"

    def __init__(self, binding: Optional[Binding],
                 binding_error: Optional[BindingError], parent=None):
        super().__init__(parent)
        self.setObjectName("assets-panel")
        self.binding = binding
        self.binding_error = binding_error
        self._cards: List[AssetCard] = []
        self._filter = self.KIND_FILTER_ALL

        layout = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setObjectName("assets-status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.filter_row = QHBoxLayout()
        self._filter_buttons: Dict[str, QPushButton] = {}
        for key, label in [(self.KIND_FILTER_ALL, "All")] + [
            (k, assets_core.KIND_LABELS[k]) for k in assets_core.KIND_ORDER
        ]:
            button = QPushButton(label)
            button.setObjectName("assets-filter")
            button.setCheckable(True)
            button.setChecked(key == self.KIND_FILTER_ALL)
            button.clicked.connect(
                lambda _checked=False, k=key: self.set_kind_filter(k)
            )
            self._filter_buttons[key] = button
            self.filter_row.addWidget(button)
        self.filter_row.addStretch(1)
        layout.addLayout(self.filter_row)

        self.grid_holder = QWidget()
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_holder)
        layout.addWidget(scroll, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("assets-log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES
        )
        layout.addWidget(self.log_view)

        self._runs = RunController(self)
        self._runs.line.connect(self.append_line)
        self._runs.finished.connect(self._on_run_finished)
        self._running_card: Optional[AssetCard] = None

        self.refresh()

    # -- building the grid -------------------------------------------------

    def cards(self) -> List[AssetCard]:
        return list(self._cards)

    def visible_cards(self) -> List[AssetCard]:
        return [c for c in self._cards
                if self._filter in (self.KIND_FILTER_ALL, c.asset.kind)]

    def refresh(self) -> None:
        """Re-read assets/ and rebuild every card."""
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        if self.binding is None:
            self.status_label.setText(
                self.binding_error.message if self.binding_error
                else "No game repository is bound, so there are no assets to show."
            )
            return

        try:
            rules = pipeline.read_rules(self.binding)
        except pipeline.PipelineError as exc:
            rules = []
            self.append_line(exc.message)

        found = assets_core.discover(self.binding)
        if not found:
            self.status_label.setText(
                f"{assets_core.assets_dir(self.binding)} holds no files."
            )
            return

        problems = 0
        for asset in found:
            verification = assets_core.verify(self.binding, asset)
            plan = pipeline.plan_for(self.binding, asset, verification, rules)
            image = None
            if verification.png is not None and _previewable(verification.png):
                image = thumbnail_image(verification.png)
            card = AssetCard(asset, verification, plan, image, parent=self.grid_holder)
            card.open_requested.connect(self._open)
            card.convert_requested.connect(self._convert)
            self._cards.append(card)
            if not verification.ok:
                problems += 1

        self.status_label.setText(
            f"{assets_core.assets_dir(self.binding)} · {len(found)} files · "
            f"{problems} need attention"
        )
        self._relayout()

    def _relayout(self) -> None:
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for card in self._cards:
            card.setVisible(False)
        for index, card in enumerate(self.visible_cards()):
            self.grid_layout.addWidget(
                card, index // GRID_COLUMNS, index % GRID_COLUMNS
            )
            card.setVisible(True)

    def set_kind_filter(self, kind: str) -> None:
        self._filter = kind
        for key, button in self._filter_buttons.items():
            button.setChecked(key == kind)
        self._relayout()

    # -- the log -----------------------------------------------------------

    def append_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def is_running(self) -> bool:
        return self._runs.is_running()

    def stop_and_wait(self) -> None:
        """For the window closing: a QThread still running when Qt tears
        its parent down is a crash."""
        self._runs.stop_and_wait()

    # -- the two actions (filled in by Task 8 and Task 9) ------------------

    def _open(self, card: AssetCard) -> None:
        raise NotImplementedError

    def _convert(self, card: AssetCard) -> None:
        raise NotImplementedError

    def _on_run_finished(self, results) -> None:
        raise NotImplementedError
```

- [ ] **Step 5: Run the panel test to verify it passes**

Run: `python -m unittest tests.garage.test_panels_assets -v`
Expected: PASS. `TestVerdict.test_a_clean_sprite_reads_ok` exercises `plan_refusal`, so a typo there fails here rather than at runtime.

- [ ] **Step 6: Run both targets**

Run: `make test` then `make test-garage`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/theme/tokens.py tools/garage/theme/qss.py tools/garage/panels/assets.py tests/garage/test_panels_assets.py
git commit -m "Add Garage P2 iteration 7: the Game Boy shades and the asset card grid"
```

---

## Task 8: Running the converter, and showing what it printed

**Files:**
- Modify: `tools/garage/panels/assets.py` (replace `_convert` and `_on_run_finished`)
- Modify: `tests/garage/test_panels_assets.py` (append)

**Interfaces:**
- Consumes: `AssetCard`, `AssetsPanel`, `RunController` (Task 7); `pipeline.Plan`; `make_runner.RunResult`.
- Produces: a working `AssetsPanel._convert(card)`, `AssetsPanel._on_run_finished(results)`, and `AssetsPanel.convert(card)` as the public entry point the tests call.

- [ ] **Step 1: Write the failing test**

Append to `tests/garage/test_panels_assets.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.garage.test_panels_assets.TestConvert -v`
Expected: FAIL — `AttributeError: 'AssetsPanel' object has no attribute 'convert'`

- [ ] **Step 3: Write the implementation**

In `tools/garage/panels/assets.py`, replace the `_convert` and `_on_run_finished` stubs with:

```python
    def convert(self, card: AssetCard) -> None:
        """Run the converter for `card`'s asset (R6/R7).

        R5's refusal is here as well as on the button: the button is
        disabled when verification failed, and this is the guard behind
        it. A refused asset writes its reason to the log rather than
        failing silently — the user pressed something, and something must
        answer.
        """
        if not card.plan.can_run:
            self.append_line(
                card.plan.refusal
                or f"{card.asset.name} cannot be converted."
            )
            return
        if self._runs.is_running():
            # Two converter runs at once would interleave two tools'
            # output in one log and race over the same generated file.
            self.append_line(
                f"A converter is already running; {card.asset.name} was not "
                f"started."
            )
            return

        self._running_card = card
        for command in card.plan.commands:
            # The prototype's log echoes each command as a shell line, so
            # the output underneath is attributable to the call that
            # produced it.
            self.append_line(f"$ {command.label}")
        if not self._runs.start(
            list(card.plan.commands), self.binding.active_worktree.path
        ):
            self._running_card = None
            return
        self._set_busy(True)

    def _convert(self, card: AssetCard) -> None:
        self.convert(card)

    def _set_busy(self, busy: bool) -> None:
        for card in self._cards:
            card.convert_button.setEnabled(not busy and card.plan.can_run)
            card.open_button.setEnabled(not busy)

    def _on_run_finished(self, results) -> None:
        card, self._running_card = self._running_card, None
        self._set_busy(False)
        if card is None:
            return
        if results and all(r.ok for r in results):
            self.append_line(
                f"{card.asset.name} converted — wrote "
                f"{', '.join(card.plan.targets)}"
            )
            # The asset and its outputs now agree, so whatever change
            # brought the user here is answered (R9).
            self._stamps[card.asset.relative_path] = assets_core.stamp(
                card.asset.path
            )
            # The offer is answered, so it is withdrawn -- from the panel's
            # own memory as well as from the card, or the next refresh
            # would put the mark back (see `refresh`).
            self._changed_paths.discard(card.asset.relative_path)
            card.set_changed(False)
        else:
            codes = ", ".join(str(r.exit_code) for r in results) or "no result"
            self.append_line(
                f"{card.asset.name} — the converter failed (exit {codes}). "
                f"The message above is the converter's own."
            )
        self.run_finished.emit(results)
```

Add `run_finished = Signal(object)` to the class's signal declarations (add it as the first line of the class body, after the docstring and `KIND_FILTER_ALL`), and initialise both of these in `__init__` before `self.refresh()`:

```python
        # What each listed asset looked like when Garage last stamped it,
        # and which ones are known to have changed since. Both live on the
        # panel rather than on the cards, because `refresh()` destroys and
        # rebuilds every card. Task 9 is what fills them; a successful
        # conversion below is what clears a mark.
        self._stamps: Dict[str, assets_core.Stamp] = {}
        self._changed_paths: set = set()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.garage.test_panels_assets -v`
Expected: PASS.

- [ ] **Step 5: Run both targets**

Run: `make test` then `make test-garage`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/panels/assets.py tests/garage/test_panels_assets.py
git commit -m "Add Garage P2 iteration 8: converter runs and their output in the window"
```

---

## Task 9: Opening an asset, and noticing it changed

**Files:**
- Modify: `tools/garage/panels/assets.py` (replace `_open`, add the poll)
- Modify: `tests/garage/test_panels_assets.py` (append)

**Interfaces:**
- Consumes: `assets_core.open_in_default_app`, `assets_core.OpenError`, `assets_core.stamp`, `assets_core.has_changed` (Task 6); `AssetCard.set_changed` (Task 7).
- Produces: `AssetsPanel.open(card)`, `AssetsPanel.check_for_changes()`, `POLL_INTERVAL_MS`.

- [ ] **Step 1: Write the failing test**

Append to `tests/garage/test_panels_assets.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.garage.test_panels_assets.TestOpen -v`
Expected: FAIL — `NotImplementedError` from `_open`, and `AttributeError: 'AssetsPanel' object has no attribute 'open'`.

- [ ] **Step 3: Write the implementation**

In `tools/garage/panels/assets.py`, add `from PySide6.QtCore import QTimer` to the Qt imports, add this constant beside the others:

```python
# How often the panel re-stamps every asset it lists (milliseconds). R9
# asks Garage to notice a file changed after the user opened it, and the
# editor is another process that reports nothing when it saves. A poll is
# the only signal available; two seconds is short enough that returning
# from the editor shows the mark immediately and long enough that a
# directory of a hundred files costs nothing measurable.
POLL_INTERVAL_MS = 2000
```

replace the `_open` stub with:

```python
    def open(self, card: AssetCard) -> None:
        """Hand the asset to the Windows default application (R8/AC8).

        R10's guard lives here rather than only in the absence of a
        button: a generated file is read-only in Garage, and the refusal
        must hold for any caller.
        """
        relative = card.asset.relative_path
        if relative in self._generated:
            self.append_line(
                f"{relative} is generated by a converter — it is read-only in "
                f"Garage. A hand edit to it is overwritten on the next "
                f"compile; edit the asset it is generated from instead."
            )
            return
        try:
            assets_core.open_in_default_app(card.asset.path)
        except assets_core.OpenError as exc:
            self.append_line(exc.message)
            return
        self.append_line(
            f"Opened {card.asset.name} in the application Windows associates "
            f"with that file type."
        )
        # From here on the file is watched, so a save on the way back is
        # noticed (R9). It is watched before this too -- see refresh() --
        # because a user may edit from Explorer; opening only re-baselines.
        self._stamps[relative] = assets_core.stamp(card.asset.path)

    def _open(self, card: AssetCard) -> None:
        self.open(card)

    def check_for_changes(self) -> None:
        """Re-stamp every listed asset and mark the ones that moved
        (R9/AC9). Called by the poll timer, and directly by tests."""
        for card in self._cards:
            relative = card.asset.relative_path
            before = self._stamps.get(relative)
            after = assets_core.stamp(card.asset.path)
            if before is None:
                self._stamps[relative] = after
                continue
            if assets_core.has_changed(before, after):
                # Remembered on the panel, not only on the card: the card is
                # thrown away and rebuilt by every `refresh()`.
                self._changed_paths.add(relative)
                card.set_changed(True)
```

In `refresh()`, after the card loop and before `self.status_label.setText(...)`, add:

```python
        # Every listed asset is stamped as it is built, so a change made
        # from anywhere -- the editor Garage started, or Explorer -- is
        # noticed by the next poll (R9).
        #
        # `setdefault`, not a fresh dict: a refresh must not act as an
        # acknowledgement. `refresh()` runs every time the dialog opens, and
        # re-baselining here would mean editing a sprite, seeing CHANGED,
        # closing the panel and reopening it silently withdrew the offer to
        # convert a file that is still unconverted. The baseline belongs to
        # the asset, not to this rebuild of the grid.
        for card in self._cards:
            self._stamps.setdefault(
                card.asset.relative_path, assets_core.stamp(card.asset.path)
            )
        # A rebuilt card is a new widget with default state, so the marks
        # the panel already knows about are re-applied to it.
        for card in self._cards:
            if card.asset.relative_path in self._changed_paths:
                card.set_changed(True)
        # R10's read-only set, derived from the Makefile rather than
        # listed: a converter rule added to the game repository is covered
        # the day it lands.
        self._generated = pipeline.generated_files(rules)
```

In `__init__`, after `self._stamps` is initialised and before `self.refresh()`, add:

```python
        self._generated: set = set()
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self.check_for_changes)
        self._poll.start()
```

and in `stop_and_wait`, stop the timer first:

```python
    def stop_and_wait(self) -> None:
        """For the window closing: a QThread still running when Qt tears
        its parent down is a crash, and a timer that fires into a
        half-destroyed panel is the same failure with a different stack.
        """
        self._poll.stop()
        self._runs.stop_and_wait()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.garage.test_panels_assets -v`
Expected: PASS.

- [ ] **Step 5: Run both targets**

Run: `make test` then `make test-garage`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/panels/assets.py tests/garage/test_panels_assets.py
git commit -m "Add Garage P2 iteration 9: opening an asset, and noticing it changed"
```

---

## Task 10: Wiring the panel into the window

**Files:**
- Modify: `tools/garage/app.py`
- Modify: `tests/garage/test_panels_assets.py` (append)

**Interfaces:**
- Consumes: `AssetsPanel` (Tasks 7–9); `GarageWindow._build_ui`, `GarageWindow._build_menu`, `GarageWindow.closeEvent`, `GarageWindow.activate_worktree` (P1).
- Produces: `GarageWindow.assets_panel`, `GarageWindow.assets_dialog`, `GarageWindow.show_assets_action`, `GarageWindow.open_assets()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/garage/test_panels_assets.py`:

```python
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
        self.assertEqual(len(self.window.assets_panel.cards()), 4)

    def test_the_dialog_names_the_worktree_it_lists(self):
        """With several checkouts open (P1 R3), "Assets" alone does not
        say whose."""
        self.assertIn(self.repo.name, self.window.assets_dialog.windowTitle())

    def test_closing_the_window_stops_the_panels_timer_and_thread(self):
        self.window.open_assets()

        self.window.close()

        self.assertFalse(self.window.assets_panel._poll.isActive())
        self.assertFalse(self.window.assets_panel.is_running())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.garage.test_panels_assets.TestWindowWiring -v`
Expected: FAIL — `AttributeError: 'GarageWindow' object has no attribute 'show_assets_action'`

- [ ] **Step 3: Write the implementation**

In `tools/garage/app.py`:

Add the import beside the other panel imports:

```python
from tools.garage.panels.assets import AssetsPanel
```

Add this method after `_build_commit`:

```python
    def _build_assets(self) -> None:
        """P2's asset panel, in a dialog like the diff, the Doctor and the
        commit panel. Rebuilt with the body, because what it lists is
        `assets/` of the *active* worktree — a panel left pointing at the
        previous one would offer to convert files in a tree Garage no
        longer means.
        """
        self.assets_panel = AssetsPanel(self.binding, self.binding_error)
        self.assets_panel.setObjectName("garage-assets-panel")
        self.assets_dialog = QDialog(self)
        self.assets_dialog.setObjectName("garage-assets-dialog")
        self.assets_dialog.setWindowTitle(self._assets_dialog_title())
        layout = QVBoxLayout(self.assets_dialog)
        layout.addWidget(self.assets_panel)
        self.assets_dialog.resize(920, 720)

    def _assets_dialog_title(self) -> str:
        if self.binding is None:
            return "Assets"
        return f"Assets — {self.binding.active_worktree.path.name}"

    def open_assets(self) -> None:
        self.assets_panel.refresh()
        self.assets_dialog.show()
        self.assets_dialog.raise_()
        self.assets_dialog.activateWindow()
```

In `_build_ui`, call it beside `_build_commit`:

```python
        self._build_commit()
        self._build_assets()
```

In `activate_worktree`, add the assets dialog to the list of dialogs closed with the old worktree:

```python
        for dialog in (
            self.diff_dialog,
            self.doctor_dialog,
            self.commit_dialog,
            self.assets_dialog,
        ):
```

and stop its worker before the dialog goes, immediately above that loop:

```python
        # The asset panel owns a poll timer and may own a converter thread;
        # both must end before the widget that hosts them is deleted.
        self.assets_panel.stop_and_wait()
```

In `_build_menu`, add the action after the commit one:

```python
        self.show_assets_action = QAction("&Assets…", self)
        self.show_assets_action.setObjectName("garage-action-show-assets")
        self.show_assets_action.triggered.connect(self.open_assets)
        view_menu.addAction(self.show_assets_action)
```

In `closeEvent`, add the panel's teardown beside the others:

```python
        self.commit_panel.stop_and_wait()
        self.assets_panel.stop_and_wait()
```

Finally, add a line to the module docstring, in the same style as the iterations above it:

```
Iteration P2 adds the asset panel (issue #3): assets/ of the active
worktree, previewed in the Game Boy palette, verified before a converter
is offered, and converted by the game repository's own Makefile rule.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.garage.test_panels_assets -v`
Expected: PASS.

- [ ] **Step 5: Run both targets, and the default target with no game repository**

Run: `make test`
Expected: PASS.

Run: `make test-garage`
Expected: PASS (AC13).

Then prove AC12 the only way it can honestly be proven — a fresh checkout with no game repository beside it, and a virtualenv with no PySide6. Running the default target in the working tree does not prove it: this machine has both, so every game-repository test *runs* instead of skipping, and the panel modules are importable. P1 shipped a hardcoded `src/config.h` path that only this check would have caught.

```powershell
$probe = "$env:TEMP\garage-ac12"
Remove-Item -Recurse -Force $probe -ErrorAction SilentlyContinue
git clone . $probe
python -m venv "$probe\.venv"
Push-Location $probe
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p 'test_*.py'
Pop-Location
```

Expected: PASS, with the game-repository-dependent tests reported as skipped and no `ModuleNotFoundError: PySide6`. Note the count: a class that *errors* on import rather than skipping is the failure this check exists to find.

- [ ] **Step 6: Launch Garage and click through it**

Run: `garage.bat`

Check, by hand, against the acceptance criteria this suite cannot reach:
- `View ▸ Assets…` opens the panel, and every file under `assets/` is there in its group (AC1).
- A sprite thumbnail reads as the art, in four shades, with the tile grid over it (AC2).
- `player_car.png` shows a tile cost; compare it against `src/player_sprite.c`'s `player_tile_data_count` (AC3).
- Convert a sprite and watch `make` run in the log; the file it writes matches a terminal run (AC6, AC7).
- Open a `.png` — the application the machine associates with PNGs starts (AC8). Save a change in it and watch the card turn CHANGED within two seconds, with a Reconvert button (AC9).
- Open the `.uge` and press Reconvert on return: both music validators run and report (AC11).

- [ ] **Step 7: Commit**

```bash
git add tools/garage/app.py tests/garage/test_panels_assets.py
git commit -m "Add Garage P2 iteration 10: the asset panel in the window"
```

---

## Spec coverage

| Requirement | Where |
|---|---|
| R1 list under `assets/`, grouped | Task 1 (`discover`, `classify`, `group_by_kind`), Task 7 (grid + filter chips) |
| R2 four-shade preview with the 8-pixel grid | Task 2 (`read_png` pixels), Task 7 (`thumbnail_image`, `gb_shades`) |
| R3 tile cost and map size | Task 2 (`PngFacts.tile_count`, `TmxFacts`), Task 7 (`cost_text`) |
| R4 verify before converting, naming the limit | Task 3 (`verify`, `Problem.limit`) |
| R5 refuse to convert a failed asset | Task 5 (`Plan.refusal` with no commands), Task 7 (disabled button), Task 8 (the guard behind it) |
| R6 the right converter, as a subprocess, from the worktree's own copy | Tasks 4–5 (Makefile rules → `make -W`), Task 8 (`RunController`) |
| R7 converter output and errors in the window | Task 8 (`append_line`, the log) |
| R8 the Windows default application, no editor named | Task 6 (`open_in_default_app`, the no-editor-named test), Task 9 |
| R9 changed on disk, offer to convert again | Task 6 (`Stamp`, `has_changed`), Task 9 (poll, CHANGED, Reconvert) |
| R10 generated files read-only | Task 4 (`generated_files`), Task 7 (label not button), Task 9 (the open guard) |
| R11 music: open, then both validators | Task 5 (`music_commands`), Tasks 8–9 |
| R12 no Qt in `core/` | Global constraint; enforced by `tests/test_garage_assets.py` running under `make test` |
| R13 every path through `project.py` | Global constraint; `assets_dir`, `makefile_path`, `load_png_tools`, `music_commands` all resolve through the binding |

## Judgment calls made while planning, worth a second look before Task 1

1. **The panel runs `make`, not the converter directly.** R6 says "run the correct converter… as a subprocess". `make -W <asset> <targets>` runs `python tools/png_to_tiles.py …` as a subprocess, from the worktree's own copy, with the exact flags the game repository specifies — which is the only way AC6 ("the same output file as the same converter run from a terminal") can be true without copying `--bank 255` and every array name into this repository, which R6 forbids. The cost is that Garage needs `make` and Git's `usr\bin` on PATH; P1's Doctor already checks both.
2. **`core/preview.py` imports the worktree's `png_to_tiles.py` in-process** rather than shelling out. R6's subprocess rule governs *running* a converter, which writes files; previewing only reads. The alternative — a second PNG decoder in this repository — is both slower to write and guaranteed to drift from AC3 and AC4.
3. **A fifth group, `other`.** R1 names four kinds; AC1 asks for every file under `assets/`. `assets/dialog/*.json`, `assets/reference/**` and the `.tsx` files are none of the four. They are listed, with no converter and no preview.
4. **Tile cost for the track tileset is base tiles only.** `png_to_tiles.py` generates rotated variants at conversion time and checks the total against 192; that total cannot be known in advance. The card says which number it is showing (`pipeline.ROTATION_NOTE`) rather than implying the budget is safe.
