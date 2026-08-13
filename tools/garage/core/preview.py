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
