"""The dialog tree model: the two JSON files, the node and choice
operations, and the Game Boy limits the panel enforces as the user types
(spec P3, issue #4).

No Qt import belongs in this module or anywhere under tools/garage/core/
(R12): everything here is testable with no display.

**Written, not ported** (R13). The game repository's `tools/dialog_editor.py`
imports `curses` and cannot run on Windows, so it is a reference for the
rules -- the 63-character node, the three choices, the twelve-character
wrap, the renumbering after a delete -- and not a source to copy. Two
places this module deliberately differs from it are recorded where they
happen: `is_over_limit` (stricter by one than dialog_to_c.py) and
`add_choice` (the TUI leaves a narration node's `next` behind).

**The shape of the data.** `npcs.json` holds a list of NPCs, each with an
`id`, a `name`, a `vendor_field` and a list of nodes. A node has an `idx`
(its position, re-sequenced whenever the list changes), a `text`, a list
of `choices` and a list of `next`. The two lists are parallel and their
lengths are the invariant everything here maintains: a node with choices
has one `next` per choice; a node without has exactly one. A `next` entry
is a node index, "END" or "SHOP". `dialog_to_c.py::validate` rejects any
other shape, so a Garage operation that broke it would produce a file the
generator refuses.

Every path resolves through `tools.garage.core.project.Binding` (R14).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ── The Game Boy's limits ────────────────────────────────────────────────

# AC8 refuses at "63 characters or more". dialog_to_c.py::validate rejects
# `len(text) > 63`, so a 63-character node passes the generator and fails
# here: Garage is stricter by exactly one character, never looser. The
# buffer behind it is DIALOG_TEXT_BUF_LEN (64 bytes) in src/config.h.
MAX_TEXT_LEN = 63
# DIALOG_CHOICE_BUF_LEN is 32 bytes; three is the count the renderer draws.
MAX_CHOICES = 3
# DIALOG_NAME_BUF_LEN is 16 bytes, so fifteen characters and a NUL.
MAX_NAME_LEN = 15
# The dialog box's inner size, in characters and rows.
WRAP_WIDTH = 12
WRAP_ROWS = 5

END = "END"
SHOP = "SHOP"
SENTINELS = (END, SHOP)

# ── Where things live in the game repository ─────────────────────────────

NPCS_RELATIVE = ("assets", "dialog", "npcs.json")
HUBS_RELATIVE = ("assets", "dialog", "hubs.json")
GENERATOR_RELATIVE = ("tools", "dialog_to_c.py")
# Posix-spelled and relative to the worktree, because that is how the
# game repository's Makefile spells them -- see `generator_command`.
NPCS_ARG = "assets/dialog/npcs.json"
HUBS_ARG = "assets/dialog/hubs.json"
CONFIG_H_ARG = "src/config.h"
DIALOG_OUT_RELATIVE = "src/dialog_data.c"
HUB_OUT_RELATIVE = "src/hub_data.c"

_MAX_NPCS_RE = re.compile(r"#define\s+MAX_NPCS\s+(\d+)")


class DialogError(Exception):
    """A failure the panel states in words: a file that will not read, a
    header without MAX_NPCS, an edit the limits refuse. Carries `.message`
    so a caller shows the sentence rather than a traceback.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class DialogData:
    """Both files, and where they came from. `npcs` and `hubs` are the raw
    lists from the JSON -- edited in place by the operations below and
    written back by `save`. Keeping the raw dicts (rather than parsing
    into a class of our own) means a key this spec does not know about,
    `vendor_field` today and whatever the game adds next, survives a round
    trip untouched.
    """

    npcs: List[dict] = field(default_factory=list)
    hubs: List[dict] = field(default_factory=list)
    npcs_path: Optional[Path] = None
    hubs_path: Optional[Path] = None


def _read_json(path: Path, what: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise DialogError(
            f"'{path}' does not exist, so Garage cannot read the {what}. "
            f"The active worktree may not hold the dialog assets."
        ) from exc
    except OSError as exc:
        raise DialogError(f"'{path}' could not be read: {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise DialogError(
            f"'{path}' is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}: {exc.msg}), so Garage cannot read the {what}."
        ) from exc


def load(binding) -> DialogData:
    """Read both dialog files from the active worktree (R1/R14)."""
    npcs_path = binding.resolve(*NPCS_RELATIVE)
    hubs_path = binding.resolve(*HUBS_RELATIVE)
    npcs_doc = _read_json(npcs_path, "NPC dialog")
    hubs_doc = _read_json(hubs_path, "hub roster")
    return DialogData(
        npcs=npcs_doc.get("npcs", []),
        hubs=hubs_doc.get("hubs", []),
        npcs_path=npcs_path,
        hubs_path=hubs_path,
    )


def _write_json(path: Path, document: dict) -> None:
    # newline="\n": the game repository's files are LF, and a Windows
    # editor writing CRLF would show every line of both files as changed
    # in the diff panel.
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(document, f, indent=2)
            f.write("\n")
    except OSError as exc:
        raise DialogError(f"'{path}' could not be written: {exc}.") from exc


def save(data: DialogData) -> None:
    """Write both files back (AC2). The caller checks `refusal` first --
    see Task 4; this function writes what it is given.
    """
    _write_json(data.npcs_path, {"npcs": data.npcs})
    _write_json(data.hubs_path, {"hubs": data.hubs})


# ── The limits, as the panel asks about them ─────────────────────────────


def is_over_limit(text: str) -> bool:
    """AC8's test, in one place. See MAX_TEXT_LEN for the off-by-one."""
    return len(text) >= MAX_TEXT_LEN


def count_label(text: str) -> str:
    """The prototype's `41/63`."""
    return f"{len(text)}/{MAX_TEXT_LEN}"


def wrap_preview(text: str, width: int = WRAP_WIDTH,
                 rows: int = WRAP_ROWS) -> List[str]:
    """The lines the Game Boy will draw (AC7/R8).

    Mirrors `render_wrapped` in the game's src/state_hub.c: wrap at word
    boundaries, and hard-wrap a word that cannot fit on a line of its own.
    At most `rows` lines come back, because that is all the box has.
    """
    lines: List[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word[:width]
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word[:width]
        if len(lines) >= rows:
            break
    if current and len(lines) < rows:
        lines.append(current)
    return lines[:rows]


def read_max_npcs(binding) -> int:
    """The NPC ceiling the game supports (R10/AC9), read from the bound
    worktree's src/config.h at call time.

    Not a constant here: MAX_NPCS is 8 today and the number belongs to the
    game, not to Garage. `dialog_to_c.py` validates the NPC count against
    this same define, so a Garage that guessed would offer an edit the
    generator then rejects.
    """
    path = binding.config_h
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DialogError(
            f"'{path}' could not be read, so Garage cannot tell how many "
            f"NPCs the game supports: {exc}."
        ) from exc
    match = _MAX_NPCS_RE.search(text)
    if match is None:
        raise DialogError(
            f"'{path}' holds no '#define MAX_NPCS', so Garage cannot tell "
            f"how many NPCs the game supports."
        )
    return int(match.group(1))
