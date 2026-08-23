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
from typing import List, Optional, Union

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


# ── Node operations (R3, R4, R5, R6) ─────────────────────────────────────

# What a node added from the panel says before the user types. Short,
# inside every limit, and obviously a placeholder.
NEW_NODE_TEXT = "..."


def new_node(idx: int) -> dict:
    """A narration node that ends the tree."""
    return {"idx": idx, "text": NEW_NODE_TEXT, "choices": [], "next": [END]}


def add_node(nodes: List[dict]) -> dict:
    """Append a node and return it (R3)."""
    node = new_node(len(nodes))
    nodes.append(node)
    return node


def resequence(nodes: List[dict]) -> None:
    """Make every node's `idx` its position again. A node's index *is* its
    position -- `dialog_to_c.py` names its generated strings after it and
    validates every `next` against `len(nodes)` -- so the two can never be
    allowed to drift.
    """
    for position, node in enumerate(nodes):
        node["idx"] = position


def renumber_refs(nodes: List[dict], deleted_idx: int) -> None:
    """Fix every reference after the node at `deleted_idx` has been
    removed (R4/AC3).

    A reference *to* the deleted node has nowhere to go, so it becomes
    END -- the tree ends rather than jumping somewhere arbitrary. A
    reference *above* it shifts down by one, because every node above the
    hole did. A reference below it, and both sentinels, are untouched.

    Applied to every slot of every node, not only to the first: a
    three-choice node has three references and the second one is exactly
    as able to point at the deleted node as the first.
    """
    for node in nodes:
        renumbered: List[Union[int, str]] = []
        for target in node["next"]:
            if target in SENTINELS:
                renumbered.append(target)
            elif target == deleted_idx:
                renumbered.append(END)
            elif isinstance(target, int) and target > deleted_idx:
                renumbered.append(target - 1)
            else:
                renumbered.append(target)
        node["next"] = renumbered


def delete_node(nodes: List[dict], index: int) -> None:
    """Remove the node at `index` and leave every reference correct
    (R3/R4).

    An NPC never ends up with no nodes at all: `dialog_to_c.py` generates
    a node table per NPC and the game indexes into it, so an empty list is
    a slot the game cannot enter. Deleting the last node therefore leaves
    a one-node stub, which is what the TUI does for the same reason.
    """
    if index < 0 or index >= len(nodes):
        raise DialogError(
            f"There is no node {index} to delete; this NPC has "
            f"{len(nodes)} node(s)."
        )
    del nodes[index]
    resequence(nodes)
    renumber_refs(nodes, index)
    if not nodes:
        nodes.append(new_node(0))


def set_text(node: dict, text: str) -> None:
    """Store a node's text (R3).

    The length limit is deliberately not enforced here. AC6 asks for the
    count to move as the user types, and a value the model refused to hold
    could not be counted -- so an over-long node is storable, shown as
    over, and refused at save (AC8, `refusal` in Task 4).
    """
    node["text"] = text


def set_next(node: dict, slot: int, target: Union[int, str]) -> None:
    """Point one of a node's `next` slots at a node, at END or at SHOP
    (R5/AC4).
    """
    nexts = node["next"]
    if slot < 0 or slot >= len(nexts):
        raise DialogError(
            f"This node has {len(nexts)} next slot(s), so there is no slot "
            f"{slot} to set."
        )
    if isinstance(target, bool) or not (
        isinstance(target, int) or target in SENTINELS
    ):
        raise DialogError(
            f"'{target}' is not a node index, {END} or {SHOP}, so it cannot "
            f"be a next target."
        )
    nexts[slot] = target


def next_targets(nodes: List[dict], node_index: int) -> List[Union[int, str]]:
    """What a node's next slot may be set to: every *other* node, then the
    two sentinels. A node pointing at itself is a loop the player cannot
    leave, so it is not offered.
    """
    targets: List[Union[int, str]] = [
        i for i in range(len(nodes)) if i != node_index
    ]
    targets.extend(SENTINELS)
    return targets


def add_choice(node: dict, label: str) -> None:
    """Add a choice to a node (R6/AC5).

    The first choice **takes over** the narration node's existing `next`
    rather than adding a slot beside it: a node has one `next` per choice,
    and a narration node's single `next` is the slot the first choice
    inherits. `tools/dialog_editor.py::_toggle_choice` appends instead,
    which leaves one choice with two nexts -- a shape
    `dialog_to_c.py::validate` rejects. This module is written fresh
    (R13), so it does the correct thing rather than the compatible one.
    """
    label = label.strip()
    if not label:
        raise DialogError("A choice needs a label.")
    choices = node["choices"]
    if len(choices) >= MAX_CHOICES:
        raise DialogError(
            f"A node holds at most {MAX_CHOICES} choices, and this one "
            f"already has {len(choices)}."
        )
    if not choices:
        # The single narration `next` becomes choice 0's next; the list
        # already has exactly the one slot this choice needs.
        choices.append(label)
        return
    choices.append(label)
    node["next"].append(END)


def remove_choice(node: dict, choice_index: int) -> None:
    """Remove a choice and its `next` slot (R6).

    Removing the last choice leaves the node's `next` list at exactly one
    entry -- the slot that choice used -- because a narration node has one
    next and an empty list is a shape the generator rejects.
    """
    choices = node["choices"]
    if choice_index < 0 or choice_index >= len(choices):
        raise DialogError(
            f"This node has {len(choices)} choice(s), so there is no choice "
            f"{choice_index} to remove."
        )
    del choices[choice_index]
    nexts = node["next"]
    if len(choices) == 0:
        # Keep the removed choice's target as the narration node's next:
        # deleting a choice should not silently change where the node
        # goes when it had only one way out to begin with.
        keep = nexts[choice_index] if choice_index < len(nexts) else END
        node["next"] = [keep]
        return
    if choice_index < len(nexts):
        del nexts[choice_index]
