"""Asset discovery, kind detection and pre-flight verification.

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

from tools.garage.core import preview

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
            [Problem(PROBLEM_UNREADABLE, facts.error, "a map Tiled can read")],
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
