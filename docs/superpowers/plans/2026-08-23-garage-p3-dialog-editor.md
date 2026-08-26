# Garage P3 — Dialog Tree Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Garage dialog panel so a designer edits the game's NPC dialog trees on Windows with the Game Boy text limits enforced as they type, saves to the active worktree's JSON, and regenerates the C sources.

**Architecture:** A Qt-free `tools/garage/core/dialog_model.py` owns everything worth testing — loading and saving `assets/dialog/npcs.json` / `hubs.json`, node and choice editing, reference renumbering, the 63-character and 3-choice limits, the 12-character wrap preview, the NPC ceiling read from the game repository's `src/config.h`, and the `dialog_to_c.py` invocation as a `make_runner.Command`. A thin `tools/garage/panels/dialog.py` wires Qt widgets to it and streams the generator's output through the existing `RunController`. Every path resolves through `tools.garage.core.project.Binding`; nothing is hardcoded.

**Tech Stack:** Python 3.13, standard-library `unittest`, PySide6 (panel layer only), `git` and the game repository's `tools/dialog_to_c.py` as subprocesses.

**Spec:** MatthieuGagne/nuke-raiders-garage#4 — "feat: Garage P3 — dialog tree editor with live Game Boy text limits". Read it alongside this plan; the requirement (R*) and acceptance (AC*) numbers below are its numbers.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.13, `unittest` only.** `pytest` is not installed in this repository and must not be used. No build step.
- **`tools/garage/core/` imports no Qt** (R12). Not one module, not transitively.
- **No file under `tests/` may import Qt**, directly or transitively (AC13). `make test` must pass with PySide6 absent. Panel coverage lives under `tests/garage/`, which has no `__init__.py`, so default discovery never reaches it — that omission is load-bearing.
- **No path into the game repository may be hardcoded** (R14). Resolve through `tools.garage.core.project.Binding`: `binding.resolve(...)`, `binding.config_h`, `binding.active_worktree.path`.
- **Anything that reads the game repository skips when none is bound.** CI checks this repository out alone; a test that hard-fails on an unbound repository breaks the build.
- **No colour literal, no font family, no `setStyleSheet` in a panel or in `app.py`.** `tests/garage/test_panels.py::TestNoColourLiteralInPanelSource` greps for these and will fail the moment one lands. Colours come from `tools/garage/theme/tokens.py` by name; styling comes from the one stylesheet in `tools/garage/theme/qss.py`, selected by object name or Qt dynamic property.
- **Limits, copied verbatim from the spec and from `src/config.h`:**
  - `MAX_TEXT_LEN = 63` — AC8 refuses to save a node holding **63 characters or more**. (`DIALOG_TEXT_BUF_LEN` is 64 bytes.)
  - `MAX_CHOICES = 3` — AC5, and `DIALOG_CHOICE_BUF_LEN` is 32 bytes.
  - `MAX_NAME_LEN = 15` — `DIALOG_NAME_BUF_LEN` is 16 bytes.
  - `WRAP_WIDTH = 12`, `WRAP_ROWS = 5` — AC7, the Game Boy dialog box's inner size.
  - The NPC ceiling is **read at runtime** from `#define MAX_NPCS` in the bound worktree's `src/config.h` (AC9). It is 8 today; nothing in Garage may assume that.
- **Commit style:** `feat: lowercase sentence (#4)`, `test: …`, `fix: …`, `docs: …`. One commit per task step that says "Commit".
- **Test targets:** `make test` for anything under `tools/garage/core/` and `tests/`; `make test-garage` for anything under `tools/garage/panels/`, `tools/garage/theme/` or `app.py`. Tasks 1–4 need `make test`; tasks 5–7 need both.

## Two places this plan is stricter or different than the game repository's TUI

Both are deliberate. R13 says `dialog_model.py` is **written fresh**, not ported, so the TUI is a reference and not an authority.

1. **The 63-character refusal is off by one against `dialog_to_c.py`.** The generator's `validate()` rejects `len(text) > 63`, so a 63-character node passes it. AC8 says Garage refuses at "63 characters or more". Garage is therefore *stricter* than the generator: it never lets through anything the generator would reject, and it blocks one length the generator would accept. Implement AC8 literally. The count label still reads `n/63`, matching the prototype.

2. **`tools/dialog_editor.py::_toggle_choice` has a bug this plan must not reproduce.** Adding the first choice to a narration node appends to `next` without consuming the node's existing single `next`, producing one choice and two `next` entries — which `dialog_to_c.py::validate` rejects. In `dialog_model.add_choice`, the first choice **takes over** the narration node's existing `next` value, and removing the last choice leaves exactly one `next` entry. There is a test for this in Task 2.

## What `tests/test_dialog_editor.py` covers, for AC12

AC12 asks for "coverage equivalent to the cases `tests/test_dialog_editor.py` holds". That file holds five groups:

| Group there | Equivalent here |
|---|---|
| `TestPosixOnlyImport` — the `curses` guard | **No equivalent, deliberately.** `dialog_model.py` has no platform-conditional import; there is nothing to guard. Task 1 instead adds a guard that `tools/garage/core/` imports no Qt (R12), which is this repository's analogous invariant. |
| `TestUnassignedNpcs` (4 cases) | Task 3, `TestUnassignedNpcs` |
| `TestNextHubId` (3 cases) | Task 3, `TestNextHubId` |
| `TestHubCrud` (8 cases) | Task 3, `TestHubCrud` |
| — | Plus the node model the TUI has but that file never tested: renumbering, choice limits, length limits (Tasks 1, 2, 4). |

## File Structure

| File | Responsibility |
|---|---|
| **Create** `tools/garage/core/dialog_model.py` | Everything Qt-free: constants, load/save, wrap preview, node/choice/`next` editing, renumbering, NPC and hub helpers, the save refusal, and the `dialog_to_c.py` command. One module, because the spec names one and because the pieces are one data model. |
| **Create** `tools/garage/panels/dialog.py` | The Qt panel: NPC list, node cards, live count, preview, edit controls, Save & Generate, the generator log. Thin — it calls `dialog_model` and never reimplements it. |
| **Create** `tests/test_garage_dialog.py` | Core coverage. Reached by `make test`. No Qt import. |
| **Create** `tests/garage/test_panels_dialog.py` | Panel coverage. Reached only by `make test-garage`. |
| **Modify** `tools/garage/app.py` | A `&Dialog…` action under View, and the modeless `QDialog` that holds the panel — the same shape the assets, commit, diff, Doctor and worktrees panels already use. Without this no AC is reachable by a user, so it is in scope even though the spec's Files Impacted list does not name it. It is a file in **this** repository. |
| **Modify** `tools/garage/theme/qss.py` | The `#dialog-*` rules and the docstring entry that lists them. Same justification; same repository. |
| **Modify** `tests/test_garage_core.py` | One new guard: no module under `tools/garage/core/` imports Qt (R12). |
| **Modify** `tests/garage/test_panels.py` | One new case: the window builds the Dialog action and opens the panel. |

Nothing in the game repository is edited. `tools/dialog_editor.py`, `tests/test_dialog_editor.py`, `docs/dev-workflow.md`, `tools/screenshot.py` and `.github/workflows/build.yml` all stay exactly as they are — MatthieuGagne/gmb-nuke-raider#613 changes those, after this ships.

---

## Task 1: The core data model — load, save, wrap, length

**Files:**
- Create: `tools/garage/core/dialog_model.py`
- Create: `tests/test_garage_dialog.py`
- Modify: `tests/test_garage_core.py` (append one guard class)

**Interfaces:**
- Consumes: `tools.garage.core.project.Binding` (`binding.resolve(*parts)`, `binding.config_h`, `binding.active_worktree.path`).
- Produces, for Tasks 2–7:
  - `MAX_TEXT_LEN: int = 63`, `MAX_CHOICES: int = 3`, `MAX_NAME_LEN: int = 15`, `WRAP_WIDTH: int = 12`, `WRAP_ROWS: int = 5`, `END: str = "END"`, `SHOP: str = "SHOP"`
  - `NPCS_RELATIVE: tuple`, `HUBS_RELATIVE: tuple`, `GENERATOR_RELATIVE: tuple`, `DIALOG_OUT_RELATIVE: str`, `HUB_OUT_RELATIVE: str`
  - `class DialogError(Exception)` with a `.message` attribute
  - `@dataclass class DialogData` with fields `npcs: List[dict]`, `hubs: List[dict]`, `npcs_path: Path`, `hubs_path: Path`
  - `load(binding) -> DialogData`
  - `save(data: DialogData) -> None`
  - `wrap_preview(text: str, width: int = WRAP_WIDTH, rows: int = WRAP_ROWS) -> List[str]`
  - `is_over_limit(text: str) -> bool`
  - `count_label(text: str) -> str` returning e.g. `"41/63"`
  - `read_max_npcs(binding) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_garage_dialog.py`:

```python
"""Core coverage for the dialog panel (spec P3, issue #4).

No PySide6 import belongs in this file, directly or transitively: it is
reached by `make test`, which AC13 requires to pass on a machine with no
Qt installed. Panel coverage lives in tests/garage/test_panels_dialog.py.

Fixtures build real git repositories in a temp directory. Nothing here
hardcodes a path into a checkout.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.garage.core import dialog_model, project

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

CONFIG_H = """\
#define MAX_NPCS     8
#define DIALOG_TEXT_BUF_LEN   64u
#define MAX_HUB_NPCS           3u
"""

NPCS = {
    "npcs": [
        {
            "id": 0,
            "name": "STEEVE",
            "vendor_field": "ARMOR",
            "nodes": [
                {"idx": 0, "text": "Roads. Parts.", "choices": [], "next": [1]},
                {"idx": 1, "text": "Da FUQ ?", "choices": ["Races", "Shop"],
                 "next": [2, "SHOP"]},
                {"idx": 2, "text": "Stay sharp.", "choices": [], "next": ["END"]},
            ],
        },
        {
            "id": 1,
            "name": "TRADER",
            "vendor_field": "WEAPON1",
            "nodes": [
                {"idx": 0, "text": "Got caps?", "choices": [], "next": ["END"]},
            ],
        },
    ]
}

HUBS = {
    "hubs": [
        {"id": 0, "name": "RUST TOWN", "npc_ids": [0, 1]},
        {"id": 1, "name": "JANKY CITY", "npc_ids": []},
    ]
}


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it -- see the
    same helper in tests/test_garage_core.py for why `resolve()` matters
    on Windows."""
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, npcs=None, hubs=None, config_h=CONFIG_H) -> Path:
    """A real git repository holding the two dialog files, a config.h and
    a stub generator, with the game repository's origin remote so
    `project.bind` accepts it."""
    (path / "assets" / "dialog").mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(parents=True, exist_ok=True)
    (path / "tools").mkdir(parents=True, exist_ok=True)
    write_json(path / "assets" / "dialog" / "npcs.json",
               NPCS if npcs is None else npcs)
    write_json(path / "assets" / "dialog" / "hubs.json",
               HUBS if hubs is None else hubs)
    (path / "src" / "config.h").write_text(config_h, encoding="utf-8")
    (path / "tools" / "dialog_to_c.py").write_text("# stub\n", encoding="utf-8")
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


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


class DialogModelTestCase(unittest.TestCase):
    """A bound throwaway game repository, rebuilt per test."""

    npcs = None
    hubs = None
    config_h = CONFIG_H

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_game_repo(
            self.root / "nuke-raider",
            npcs=self.npcs, hubs=self.hubs, config_h=self.config_h,
        )
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def reload(self):
        return dialog_model.load(self.binding)


class TestLoad(DialogModelTestCase):
    """R1/R14: both files read from the active worktree, through the
    binding."""

    def test_load_reads_both_files(self):
        data = self.reload()
        self.assertEqual([n["name"] for n in data.npcs], ["STEEVE", "TRADER"])
        self.assertEqual([h["name"] for h in data.hubs],
                         ["RUST TOWN", "JANKY CITY"])

    def test_load_records_the_paths_it_read(self):
        data = self.reload()
        self.assertEqual(
            data.npcs_path,
            self.binding.resolve("assets", "dialog", "npcs.json"),
        )
        self.assertEqual(
            data.hubs_path,
            self.binding.resolve("assets", "dialog", "hubs.json"),
        )

    def test_a_missing_npcs_file_is_a_dialog_error_naming_it(self):
        (self.repo / "assets" / "dialog" / "npcs.json").unlink()
        with self.assertRaises(dialog_model.DialogError) as cm:
            self.reload()
        self.assertIn("npcs.json", cm.exception.message)

    def test_malformed_json_is_a_dialog_error_naming_the_file(self):
        (self.repo / "assets" / "dialog" / "hubs.json").write_text(
            "{not json", encoding="utf-8")
        with self.assertRaises(dialog_model.DialogError) as cm:
            self.reload()
        self.assertIn("hubs.json", cm.exception.message)


class TestSave(DialogModelTestCase):
    """AC2: what Garage edited is what the file holds afterwards."""

    def test_save_writes_edited_text_back(self):
        data = self.reload()
        data.npcs[0]["nodes"][0]["text"] = "New line."
        dialog_model.save(data)

        written = json.loads(
            (self.repo / "assets" / "dialog" / "npcs.json").read_text(
                encoding="utf-8"))
        self.assertEqual(written["npcs"][0]["nodes"][0]["text"], "New line.")

    def test_save_writes_the_hubs_file_too(self):
        data = self.reload()
        data.hubs[1]["name"] = "STEEL CITY"
        dialog_model.save(data)

        written = json.loads(
            (self.repo / "assets" / "dialog" / "hubs.json").read_text(
                encoding="utf-8"))
        self.assertEqual(written["hubs"][1]["name"], "STEEL CITY")

    def test_save_keeps_the_two_space_indent_and_trailing_newline(self):
        # The game repository's files are written by dialog_to_c.py's
        # sibling with indent=2 and a trailing newline. Garage must not
        # rewrite every line of a file it only edited one field of.
        data = self.reload()
        dialog_model.save(data)
        text = (self.repo / "assets" / "dialog" / "npcs.json").read_text(
            encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "npcs": [', text)

    def test_save_writes_lf_line_endings_on_every_platform(self):
        data = self.reload()
        dialog_model.save(data)
        raw = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.assertNotIn(b"\r\n", raw)


class TestWrapPreview(unittest.TestCase):
    """AC7/R8: the Game Boy dialog box wraps at 12 characters."""

    def test_short_text_is_one_line(self):
        self.assertEqual(dialog_model.wrap_preview("Da FUQ ?"), ["Da FUQ ?"])

    def test_no_line_exceeds_twelve_characters(self):
        lines = dialog_model.wrap_preview(
            "Roads. Parts. Sharp. Racer. Grease.")
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(len(line), 12, line)

    def test_wrapping_happens_at_word_boundaries(self):
        self.assertEqual(
            dialog_model.wrap_preview("Stay sharp out there"),
            ["Stay sharp", "out there"],
        )

    def test_a_word_longer_than_the_width_is_hard_wrapped(self):
        self.assertEqual(
            dialog_model.wrap_preview("Supercalifragilistic"),
            ["Supercalifra"],  # the first 12 characters; the rest is cut
        )

    def test_at_most_five_rows_come_back(self):
        lines = dialog_model.wrap_preview(" ".join(["word"] * 40))
        self.assertLessEqual(len(lines), 5)

    def test_empty_text_is_no_lines(self):
        self.assertEqual(dialog_model.wrap_preview(""), [])


class TestLengthLimit(unittest.TestCase):
    """AC6/AC8. Garage refuses at 63 characters or more -- one stricter
    than dialog_to_c.py's `> 63`. See the plan's note on the off-by-one."""

    def test_a_short_node_is_not_over(self):
        self.assertFalse(dialog_model.is_over_limit("A" * 62))

    def test_exactly_sixty_three_is_over(self):
        self.assertTrue(dialog_model.is_over_limit("A" * 63))

    def test_longer_than_sixty_three_is_over(self):
        self.assertTrue(dialog_model.is_over_limit("A" * 80))

    def test_the_count_label_reads_used_over_limit(self):
        self.assertEqual(dialog_model.count_label("A" * 41), "41/63")


class TestReadMaxNpcs(DialogModelTestCase):
    """R10/AC9: the ceiling is the game's, read from its config.h at
    runtime -- never a constant in Garage."""

    def test_the_ceiling_comes_from_the_bound_config_h(self):
        self.assertEqual(dialog_model.read_max_npcs(self.binding), 8)

    def test_a_different_value_in_the_header_is_the_one_reported(self):
        self.binding.config_h.write_text(
            "#define MAX_NPCS     3\n", encoding="utf-8")
        self.assertEqual(dialog_model.read_max_npcs(self.binding), 3)

    def test_a_header_without_the_define_is_a_dialog_error(self):
        self.binding.config_h.write_text("/* nothing */\n", encoding="utf-8")
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.read_max_npcs(self.binding)
        self.assertIn("MAX_NPCS", cm.exception.message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.core.dialog_model'`.

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/dialog_model.py`:

```python
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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from tools.garage.core.make_runner import Command

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: PASS, every case.

- [ ] **Step 5: Add the R12 guard to the core suite**

Append to `tests/test_garage_core.py`:

```python
class TestCoreImportsNoQt(unittest.TestCase):
    """R12: `tools/garage/core/` must contain no Qt import -- not one
    module. A real grep over the source, not a one-time claim: the rule
    only holds while something keeps checking it, and the cost of a break
    is `make test` failing on every machine without PySide6, which is CI
    and is not the machine that would have introduced it.
    """

    def test_no_core_module_imports_qt(self):
        core_dir = (
            Path(__file__).resolve().parents[1] / "tools" / "garage" / "core"
        )
        offenders = []
        for path in sorted(core_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ")
                        or stripped.startswith("from ")):
                    continue
                if "PySide6" in stripped or "shiboken" in stripped:
                    offenders.append(f"{path.name}: {stripped}")
        self.assertEqual(
            offenders, [],
            "tools/garage/core/ must import no Qt (R12); move the widget "
            "code into tools/garage/panels/",
        )
```

If `tests/test_garage_core.py` does not already import `Path`, add `from pathlib import Path` to its imports.

- [ ] **Step 6: Run the whole default suite**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK, with the new cases counted and no failures.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/core/dialog_model.py tests/test_garage_dialog.py tests/test_garage_core.py
git commit -m "feat: the dialog tree model's files, limits and wrap preview (#4)"
```

---

## Task 2: Node, choice and `next` editing, with renumbering

**Files:**
- Modify: `tools/garage/core/dialog_model.py` (append a "node operations" section)
- Modify: `tests/test_garage_dialog.py` (append the test classes below)

**Interfaces:**
- Consumes: everything Task 1 produced, in particular `MAX_CHOICES`, `END`, `SHOP`, `DialogError`.
- Produces, for Tasks 4–7:
  - `new_node(idx: int) -> dict`
  - `add_node(nodes: List[dict]) -> dict` — appends and returns the new node
  - `delete_node(nodes: List[dict], index: int) -> None`
  - `renumber_refs(nodes: List[dict], deleted_idx: int) -> None`
  - `resequence(nodes: List[dict]) -> None`
  - `set_text(node: dict, text: str) -> None`
  - `set_next(node: dict, slot: int, target: Union[int, str]) -> None`
  - `add_choice(node: dict, label: str) -> None`
  - `remove_choice(node: dict, choice_index: int) -> None`
  - `next_targets(nodes: List[dict], node_index: int) -> List[Union[int, str]]` — the choices a `next` combo offers: every other node index, then `END`, then `SHOP`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_garage_dialog.py`, before the `if __name__` block:

```python
def narration(idx, text="hi", nxt="END"):
    return {"idx": idx, "text": text, "choices": [], "next": [nxt]}


def branching(idx, labels, nexts, text="pick"):
    return {"idx": idx, "text": text, "choices": list(labels),
            "next": list(nexts)}


class TestAddNode(unittest.TestCase):
    """R3: add a node."""

    def test_a_new_node_lands_at_the_end_with_the_next_index(self):
        nodes = [narration(0)]
        added = dialog_model.add_node(nodes)
        self.assertEqual(len(nodes), 2)
        self.assertIs(nodes[1], added)
        self.assertEqual(added["idx"], 1)

    def test_a_new_node_is_a_narration_node_ending_the_tree(self):
        nodes = []
        added = dialog_model.add_node(nodes)
        self.assertEqual(added["choices"], [])
        self.assertEqual(added["next"], ["END"])

    def test_a_new_nodes_text_is_within_the_limit(self):
        added = dialog_model.add_node([])
        self.assertFalse(dialog_model.is_over_limit(added["text"]))


class TestDeleteNodeRenumbers(unittest.TestCase):
    """R4/AC3: after a delete, no next pointer and no choice points at a
    wrong node."""

    def test_the_node_is_gone(self):
        nodes = [narration(0, nxt=1), narration(1, nxt=2), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(len(nodes), 2)

    def test_idx_fields_are_resequenced(self):
        nodes = [narration(0, nxt=1), narration(1, nxt=2), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual([n["idx"] for n in nodes], [0, 1])

    def test_a_reference_to_the_deleted_node_becomes_end(self):
        nodes = [narration(0, nxt=1), narration(1)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_a_reference_above_the_deleted_node_is_decremented(self):
        nodes = [narration(0, nxt=2), narration(1), narration(2)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], [1])

    def test_a_reference_below_the_deleted_node_is_untouched(self):
        nodes = [narration(0, nxt=0), narration(1), narration(2)]
        dialog_model.delete_node(nodes, 2)
        self.assertEqual(nodes[0]["next"], [0])

    def test_end_and_shop_survive_a_delete(self):
        nodes = [branching(0, ["a", "b"], ["END", "SHOP"]), narration(1)]
        dialog_model.delete_node(nodes, 1)
        self.assertEqual(nodes[0]["next"], ["END", "SHOP"])

    def test_every_choice_slot_is_renumbered_not_only_the_first(self):
        nodes = [branching(0, ["a", "b", "c"], [1, 2, 3]),
                 narration(1), narration(2), narration(3)]
        dialog_model.delete_node(nodes, 2)
        self.assertEqual(nodes[0]["next"], [1, "END", 2])

    def test_deleting_the_only_node_leaves_a_stub_rather_than_nothing(self):
        # An NPC with no nodes is a slot dialog_to_c.py cannot generate a
        # tree for; the TUI keeps a one-node stub for the same reason.
        nodes = [narration(0)]
        dialog_model.delete_node(nodes, 0)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["idx"], 0)
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_deleting_out_of_range_is_a_dialog_error(self):
        nodes = [narration(0)]
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.delete_node(nodes, 7)


class TestSetNext(unittest.TestCase):
    """R5/AC4: point a node at another node, or at the end of the tree."""

    def test_setting_a_node_index(self):
        node = narration(0)
        dialog_model.set_next(node, 0, 2)
        self.assertEqual(node["next"], [2])

    def test_setting_end(self):
        node = narration(0, nxt=3)
        dialog_model.set_next(node, 0, "END")
        self.assertEqual(node["next"], ["END"])

    def test_setting_shop(self):
        node = narration(0)
        dialog_model.set_next(node, 0, "SHOP")
        self.assertEqual(node["next"], ["SHOP"])

    def test_setting_one_choice_slot_leaves_the_others_alone(self):
        node = branching(0, ["a", "b"], [1, 2])
        dialog_model.set_next(node, 1, "END")
        self.assertEqual(node["next"], [1, "END"])

    def test_a_slot_that_does_not_exist_is_a_dialog_error(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.set_next(node, 2, "END")

    def test_a_target_that_is_neither_an_index_nor_a_sentinel_is_refused(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.set_next(node, 0, "ELSEWHERE")


class TestNextTargets(unittest.TestCase):
    """What the panel's next combo offers."""

    def test_every_other_node_then_the_sentinels(self):
        nodes = [narration(0), narration(1), narration(2)]
        self.assertEqual(
            dialog_model.next_targets(nodes, 1), [0, 2, "END", "SHOP"])

    def test_a_node_is_never_offered_itself(self):
        nodes = [narration(0)]
        self.assertEqual(dialog_model.next_targets(nodes, 0), ["END", "SHOP"])


class TestChoices(unittest.TestCase):
    """R6/AC5: between zero and three choices, and the parallel `next`
    list stays parallel."""

    def test_the_first_choice_takes_over_the_narration_next(self):
        # The TUI appends here and leaves the narration `next` behind,
        # which produces one choice and two nexts -- a shape
        # dialog_to_c.py::validate rejects. Written fresh (R13), so this
        # is the corrected behaviour.
        node = narration(0, nxt=4)
        dialog_model.add_choice(node, "The races")
        self.assertEqual(node["choices"], ["The races"])
        self.assertEqual(node["next"], [4])

    def test_a_further_choice_appends_an_end_slot(self):
        node = narration(0, nxt=4)
        dialog_model.add_choice(node, "a")
        dialog_model.add_choice(node, "b")
        self.assertEqual(node["choices"], ["a", "b"])
        self.assertEqual(node["next"], [4, "END"])

    def test_a_fourth_choice_is_refused_and_the_node_is_unchanged(self):
        node = branching(0, ["a", "b", "c"], [1, 2, 3])
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.add_choice(node, "d")
        self.assertIn("3", cm.exception.message)
        self.assertEqual(node["choices"], ["a", "b", "c"])
        self.assertEqual(node["next"], [1, 2, 3])

    def test_an_empty_label_is_refused(self):
        node = narration(0)
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.add_choice(node, "   ")

    def test_removing_a_choice_removes_its_next_slot(self):
        node = branching(0, ["a", "b", "c"], [1, 2, 3])
        dialog_model.remove_choice(node, 1)
        self.assertEqual(node["choices"], ["a", "c"])
        self.assertEqual(node["next"], [1, 3])

    def test_removing_the_last_choice_leaves_one_next_slot(self):
        node = branching(0, ["a"], [5])
        dialog_model.remove_choice(node, 0)
        self.assertEqual(node["choices"], [])
        self.assertEqual(node["next"], [5])

    def test_removing_a_choice_that_is_not_there_is_a_dialog_error(self):
        node = branching(0, ["a"], [5])
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.remove_choice(node, 3)


class TestSetText(unittest.TestCase):
    """R3: editing a node's text. The limit is not enforced here -- AC6
    wants the count to move as the user types, which means an over-long
    value must be storable and shown; AC8's refusal happens at save."""

    def test_the_text_is_stored(self):
        node = narration(0)
        dialog_model.set_text(node, "Watch the east corner.")
        self.assertEqual(node["text"], "Watch the east corner.")

    def test_an_over_long_value_is_stored_so_the_count_can_report_it(self):
        node = narration(0)
        dialog_model.set_text(node, "A" * 80)
        self.assertEqual(len(node["text"]), 80)
        self.assertTrue(dialog_model.is_over_limit(node["text"]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.dialog_model' has no attribute 'add_node'` and the like.

- [ ] **Step 3: Write the implementation**

Append to `tools/garage/core/dialog_model.py`:

```python
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
```

Add `Union` to the module's `typing` import if Step 3 of Task 1 did not already.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: PASS, every case.

- [ ] **Step 5: Commit**

```bash
git add tools/garage/core/dialog_model.py tests/test_garage_dialog.py
git commit -m "feat: node, choice and next editing with reference renumbering (#4)"
```

---

## Task 3: NPC and hub helpers, and the NPC ceiling

**Files:**
- Modify: `tools/garage/core/dialog_model.py` (append an "NPCs and hubs" section)
- Modify: `tests/test_garage_dialog.py` (append the test classes below)

This task is where AC12's equivalence is discharged: the four `unassigned_npcs` cases, the three `next_hub_id` cases and the eight hub-CRUD cases of `tests/test_dialog_editor.py` all have a counterpart below.

**Interfaces:**
- Consumes: `MAX_NAME_LEN`, `DialogError`, `new_node`, `read_max_npcs` from Tasks 1–2.
- Produces, for Tasks 4–7:
  - `add_npc(npcs: List[dict], name: str, max_npcs: int) -> dict`
  - `rename_npc(npcs: List[dict], index: int, new_name: str) -> str` — returns the stored name
  - `next_npc_id(npcs: List[dict]) -> int`
  - `unassigned_npcs(npcs: List[dict], hub_npc_ids: List[int]) -> List[dict]`
  - `next_hub_id(hubs: List[dict]) -> int`
  - `hub_add_npc(hubs, hub_idx: int, npc_id: int) -> Tuple[List[dict], str]`
  - `hub_remove_npc(hubs, hub_idx: int, roster_idx: int) -> Tuple[List[dict], str]`
  - `hub_rename(hubs, hub_idx: int, new_name: str) -> Tuple[List[dict], str]`
  - `hub_delete(hubs, hub_idx: int) -> Tuple[List[dict], str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_garage_dialog.py`:

```python
class TestAddNpc(unittest.TestCase):
    """R10/AC9: Garage refuses to add an NPC beyond the maximum the game
    supports. The ceiling is passed in, because it belongs to the game's
    config.h -- see TestReadMaxNpcs."""

    def _npcs(self, count):
        return [{"id": i, "name": f"NPC{i}", "vendor_field": "ARMOR",
                 "nodes": [narration(0)]} for i in range(count)]

    def test_an_npc_below_the_ceiling_is_added(self):
        npcs = self._npcs(2)
        added = dialog_model.add_npc(npcs, "scout", max_npcs=4)
        self.assertEqual(len(npcs), 3)
        self.assertIs(npcs[2], added)

    def test_a_new_npc_gets_the_next_id_and_an_upper_case_name(self):
        npcs = self._npcs(2)
        added = dialog_model.add_npc(npcs, "scout", max_npcs=4)
        self.assertEqual(added["id"], 2)
        self.assertEqual(added["name"], "SCOUT")

    def test_a_new_npc_starts_with_one_node(self):
        added = dialog_model.add_npc([], "scout", max_npcs=4)
        self.assertEqual(len(added["nodes"]), 1)
        self.assertEqual(added["nodes"][0]["next"], ["END"])

    def test_adding_at_the_ceiling_is_refused_and_names_the_limit(self):
        npcs = self._npcs(4)
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.add_npc(npcs, "scout", max_npcs=4)
        self.assertIn("4", cm.exception.message)
        self.assertEqual(len(npcs), 4)

    def test_a_name_longer_than_fifteen_is_refused(self):
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.add_npc([], "A" * 16, max_npcs=4)

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.add_npc([], "  ", max_npcs=4)


class TestRenameNpc(unittest.TestCase):
    """R3: rename an NPC."""

    def _npcs(self):
        return [{"id": 0, "name": "STEEVE", "vendor_field": "ARMOR",
                 "nodes": [narration(0)]}]

    def test_the_name_is_stored_upper_case(self):
        npcs = self._npcs()
        stored = dialog_model.rename_npc(npcs, 0, "grease monkey")
        self.assertEqual(stored, "GREASE MONKEY")
        self.assertEqual(npcs[0]["name"], "GREASE MONKEY")

    def test_a_name_longer_than_fifteen_is_refused_not_truncated(self):
        # The TUI truncates a hub name and refuses an NPC name; Garage
        # refuses here, because a silently shortened name is an edit the
        # user did not make.
        npcs = self._npcs()
        with self.assertRaises(dialog_model.DialogError) as cm:
            dialog_model.rename_npc(npcs, 0, "A" * 16)
        self.assertIn("15", cm.exception.message)
        self.assertEqual(npcs[0]["name"], "STEEVE")

    def test_an_empty_name_is_refused(self):
        npcs = self._npcs()
        with self.assertRaises(dialog_model.DialogError):
            dialog_model.rename_npc(npcs, 0, "")


class TestUnassignedNpcs(unittest.TestCase):
    """Equivalent to tests/test_dialog_editor.py::TestUnassignedNpcs
    (AC12)."""

    def _npcs(self):
        return [
            {"id": 0, "name": "MECHANIC", "nodes": []},
            {"id": 1, "name": "TRADER", "nodes": []},
            {"id": 2, "name": "SCOUT", "nodes": []},
        ]

    def test_all_assigned_returns_empty(self):
        self.assertEqual(dialog_model.unassigned_npcs(self._npcs(), [0, 1, 2]), [])

    def test_none_assigned_returns_all(self):
        result = dialog_model.unassigned_npcs(self._npcs(), [])
        self.assertEqual([n["id"] for n in result], [0, 1, 2])

    def test_partial_assignment(self):
        result = dialog_model.unassigned_npcs(self._npcs(), [1])
        self.assertEqual([n["id"] for n in result], [0, 2])

    def test_returns_npc_dicts_not_ids(self):
        result = dialog_model.unassigned_npcs(self._npcs(), [0, 2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "TRADER")


class TestNextHubId(unittest.TestCase):
    """Equivalent to tests/test_dialog_editor.py::TestNextHubId (AC12)."""

    def test_empty_hubs_returns_zero(self):
        self.assertEqual(dialog_model.next_hub_id([]), 0)

    def test_single_hub(self):
        self.assertEqual(dialog_model.next_hub_id([{"id": 0}]), 1)

    def test_gap_in_ids(self):
        self.assertEqual(dialog_model.next_hub_id([{"id": 0}, {"id": 3}]), 4)


class TestHubCrud(unittest.TestCase):
    """Equivalent to tests/test_dialog_editor.py::TestHubCrud (AC12)."""

    def _hubs(self):
        return [
            {"id": 0, "name": "RUST TOWN", "npc_ids": [0, 1]},
            {"id": 1, "name": "JANKY CITY", "npc_ids": []},
        ]

    def test_add_npc_appends_to_roster(self):
        hubs, msg = dialog_model.hub_add_npc(self._hubs(), hub_idx=1, npc_id=2)
        self.assertIn(2, hubs[1]["npc_ids"])
        self.assertIn("added", msg.lower())

    def test_add_npc_already_present_returns_error(self):
        hubs, msg = dialog_model.hub_add_npc(self._hubs(), hub_idx=0, npc_id=1)
        self.assertIn("already", msg.lower())
        self.assertEqual(hubs[0]["npc_ids"].count(1), 1)

    def test_remove_npc_by_roster_index(self):
        hubs, msg = dialog_model.hub_remove_npc(self._hubs(), hub_idx=0,
                                                roster_idx=0)
        self.assertNotIn(0, hubs[0]["npc_ids"])
        self.assertIn("removed", msg.lower())

    def test_remove_npc_out_of_range_returns_error(self):
        hubs, msg = dialog_model.hub_remove_npc(self._hubs(), hub_idx=1,
                                                roster_idx=0)
        self.assertIn("empty", msg.lower())

    def test_rename_hub(self):
        hubs, msg = dialog_model.hub_rename(self._hubs(), hub_idx=0,
                                            new_name="steel city")
        self.assertEqual(hubs[0]["name"], "STEEL CITY")
        self.assertIn("renamed", msg.lower())

    def test_rename_hub_truncates_to_15(self):
        hubs, _ = dialog_model.hub_rename(self._hubs(), hub_idx=0,
                                          new_name="A" * 20)
        self.assertEqual(len(hubs[0]["name"]), 15)

    def test_delete_hub_removes_from_list(self):
        hubs, msg = dialog_model.hub_delete(self._hubs(), hub_idx=0)
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0]["name"], "JANKY CITY")
        self.assertIn("deleted", msg.lower())

    def test_delete_last_hub_leaves_empty_list(self):
        hubs, _ = dialog_model.hub_delete(
            [{"id": 0, "name": "SOLO", "npc_ids": []}], hub_idx=0)
        self.assertEqual(hubs, [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: FAIL — `AttributeError: … has no attribute 'add_npc'` and the like.

- [ ] **Step 3: Write the implementation**

Append to `tools/garage/core/dialog_model.py`:

```python
# ── NPCs and hubs ────────────────────────────────────────────────────────

# The vendor field a new NPC starts with. `dialog_to_c.py` maps this
# string to a LOADOUT_FIELD_* macro and has no entry for an absent one, so
# a new NPC needs a valid value from the moment it exists.
DEFAULT_VENDOR_FIELD = "ARMOR"


def _clean_name(raw: str, what: str) -> str:
    name = raw.strip().upper()
    if not name:
        raise DialogError(f"A {what} needs a name.")
    if len(name) > MAX_NAME_LEN:
        raise DialogError(
            f"'{name}' is {len(name)} characters; a {what} name holds at "
            f"most {MAX_NAME_LEN}."
        )
    return name


def next_npc_id(npcs: List[dict]) -> int:
    if not npcs:
        return 0
    return max(n["id"] for n in npcs) + 1


def add_npc(npcs: List[dict], name: str, max_npcs: int) -> dict:
    """Add an NPC, refusing past the game's ceiling (R10/AC9).

    `max_npcs` is passed in rather than read here: it comes from the bound
    worktree's config.h (see `read_max_npcs`), and this function stays
    testable without one.
    """
    if len(npcs) >= max_npcs:
        raise DialogError(
            f"The game supports {max_npcs} NPCs (MAX_NPCS in src/config.h) "
            f"and there are already {len(npcs)}. Raise MAX_NPCS in the game "
            f"repository before adding another."
        )
    npc = {
        "id": next_npc_id(npcs),
        "name": _clean_name(name, "NPC"),
        "vendor_field": DEFAULT_VENDOR_FIELD,
        "nodes": [new_node(0)],
    }
    npcs.append(npc)
    return npc


def rename_npc(npcs: List[dict], index: int, new_name: str) -> str:
    """Rename an NPC (R3), returning the name as stored.

    A too-long name is refused rather than truncated: the hub helpers
    below truncate because the TUI's tests pin that behaviour and AC12
    asks for equivalence, but nothing pins this one, and silently storing
    a different name than the user typed is an edit they did not make.
    """
    if index < 0 or index >= len(npcs):
        raise DialogError(f"There is no NPC {index} to rename.")
    name = _clean_name(new_name, "NPC")
    npcs[index]["name"] = name
    return name


def unassigned_npcs(npcs: List[dict], hub_npc_ids: List[int]) -> List[dict]:
    """The NPC dicts whose id is not in `hub_npc_ids`."""
    assigned = set(hub_npc_ids)
    return [n for n in npcs if n["id"] not in assigned]


def next_hub_id(hubs: List[dict]) -> int:
    """One above the highest hub id, or 0 when there are none."""
    if not hubs:
        return 0
    return max(h["id"] for h in hubs) + 1


def hub_add_npc(hubs: List[dict], hub_idx: int, npc_id: int):
    """Add `npc_id` to a hub's roster. Returns (hubs, status)."""
    hub = hubs[hub_idx]
    if npc_id in hub["npc_ids"]:
        return hubs, "NPC already in hub"
    hub["npc_ids"].append(npc_id)
    return hubs, f"Added NPC {npc_id} to {hub['name']}"


def hub_remove_npc(hubs: List[dict], hub_idx: int, roster_idx: int):
    """Remove the NPC at `roster_idx`. Returns (hubs, status)."""
    hub = hubs[hub_idx]
    if not hub["npc_ids"]:
        return hubs, "Hub roster is empty"
    if roster_idx < 0 or roster_idx >= len(hub["npc_ids"]):
        return hubs, f"Roster index {roster_idx} out of range"
    npc_id = hub["npc_ids"].pop(roster_idx)
    return hubs, f"Removed NPC {npc_id} from {hub['name']}"


def hub_rename(hubs: List[dict], hub_idx: int, new_name: str):
    """Rename a hub, upper-cased and truncated to MAX_NAME_LEN. Returns
    (hubs, status). Truncation rather than refusal is the behaviour
    `tests/test_dialog_editor.py::TestHubCrud` pins, and AC12 asks for
    equivalent coverage -- see `rename_npc` for why the NPC name differs.
    """
    name = new_name.upper()[:MAX_NAME_LEN]
    old = hubs[hub_idx]["name"]
    hubs[hub_idx]["name"] = name
    return hubs, f"Renamed '{old}' → '{name}'"


def hub_delete(hubs: List[dict], hub_idx: int):
    """Delete a hub. Returns (new list, status)."""
    name = hubs[hub_idx]["name"]
    hubs = [h for i, h in enumerate(hubs) if i != hub_idx]
    return hubs, f"Deleted hub '{name}'"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/garage/core/dialog_model.py tests/test_garage_dialog.py
git commit -m "feat: NPC and hub helpers, with the NPC ceiling read from the game (#4)" 
```

---

## Task 4: The save refusal and the generator command

**Files:**
- Modify: `tools/garage/core/dialog_model.py` (append a "refusing a save" and a "running the generator" section)
- Modify: `tests/test_garage_dialog.py`

**Interfaces:**
- Consumes: `DialogData`, `is_over_limit`, `MAX_TEXT_LEN`, `MAX_CHOICES`, the path constants, and `tools.garage.core.make_runner.Command`.
- Produces, for Tasks 5–7:
  - `@dataclass(frozen=True) class Problem` with `npc_id: int`, `npc_name: str`, `node_idx: int`, `message: str`
  - `problems(data: DialogData) -> List[Problem]`
  - `refusal(data: DialogData) -> Optional[str]` — `None` when the save may proceed
  - `generator_command(binding) -> Command`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_garage_dialog.py`:

```python
def npc(npc_id, name, nodes):
    return {"id": npc_id, "name": name, "vendor_field": "ARMOR",
            "nodes": nodes}


def data_of(*npcs):
    return dialog_model.DialogData(npcs=list(npcs), hubs=[])


class TestProblems(unittest.TestCase):
    """AC8: Garage refuses to save when a node holds 63 characters or
    more, and names that node."""

    def test_a_tree_within_the_limits_has_no_problems(self):
        self.assertEqual(
            dialog_model.problems(data_of(npc(0, "STEEVE", [narration(0)]))),
            [],
        )

    def test_an_over_long_node_is_a_problem(self):
        found = dialog_model.problems(
            data_of(npc(0, "STEEVE", [narration(0, text="A" * 70)])))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].node_idx, 0)
        self.assertEqual(found[0].npc_name, "STEEVE")

    def test_exactly_sixty_three_characters_is_a_problem(self):
        found = dialog_model.problems(
            data_of(npc(0, "STEEVE", [narration(0, text="A" * 63)])))
        self.assertEqual(len(found), 1)

    def test_sixty_two_characters_is_not(self):
        self.assertEqual(
            dialog_model.problems(
                data_of(npc(0, "STEEVE", [narration(0, text="A" * 62)]))),
            [],
        )

    def test_every_over_long_node_is_reported_not_only_the_first(self):
        found = dialog_model.problems(
            data_of(npc(0, "STEEVE",
                        [narration(0, text="A" * 70), narration(1),
                         narration(2, text="B" * 70)])))
        self.assertEqual([p.node_idx for p in found], [0, 2])

    def test_problems_are_found_across_npcs(self):
        found = dialog_model.problems(
            data_of(npc(0, "STEEVE", [narration(0)]),
                    npc(1, "TRADER", [narration(0, text="A" * 70)])))
        self.assertEqual([p.npc_name for p in found], ["TRADER"])

    def test_a_node_with_four_choices_is_a_problem(self):
        found = dialog_model.problems(
            data_of(npc(0, "STEEVE",
                        [branching(0, ["a", "b", "c", "d"],
                                   [1, 1, 1, 1])])))
        self.assertEqual(len(found), 1)
        self.assertIn("choice", found[0].message.lower())


class TestRefusal(unittest.TestCase):
    """The sentence the panel shows, and the gate on Save."""

    def test_a_clean_tree_has_no_refusal(self):
        self.assertIsNone(
            dialog_model.refusal(data_of(npc(0, "STEEVE", [narration(0)]))))

    def test_the_refusal_names_the_npc_and_the_node(self):
        message = dialog_model.refusal(
            data_of(npc(0, "STEEVE", [narration(0), narration(1, text="A" * 70)])))
        self.assertIsNotNone(message)
        self.assertIn("STEEVE", message)
        self.assertIn("[1]", message)

    def test_the_refusal_counts_every_offending_node(self):
        message = dialog_model.refusal(
            data_of(npc(0, "STEEVE",
                        [narration(0, text="A" * 70),
                         narration(1, text="B" * 70)])))
        self.assertIn("[0]", message)
        self.assertIn("[1]", message)


class TestGeneratorCommand(DialogModelTestCase):
    """R11/AC11: the same call the Makefile makes, so the sources it
    writes are the sources a terminal would produce."""

    def test_the_command_runs_the_bound_worktrees_generator(self):
        command = dialog_model.generator_command(self.binding)
        self.assertIn(
            str(self.binding.resolve("tools", "dialog_to_c.py")),
            command.argv,
        )

    def test_it_runs_the_interpreter_garage_runs_under(self):
        command = dialog_model.generator_command(self.binding)
        self.assertEqual(command.argv[0], sys.executable)

    def test_it_passes_both_json_files_and_both_outputs(self):
        argv = dialog_model.generator_command(self.binding).argv
        self.assertIn("assets/dialog/npcs.json", argv)
        self.assertIn("src/dialog_data.c", argv)
        self.assertIn("--hubs-json", argv)
        self.assertIn("assets/dialog/hubs.json", argv)
        self.assertIn("--hub-out", argv)
        self.assertIn("src/hub_data.c", argv)

    def test_it_passes_config_h_so_max_npcs_is_validated(self):
        argv = dialog_model.generator_command(self.binding).argv
        self.assertIn("--config-h", argv)
        self.assertIn("src/config.h", argv)

    def test_the_label_reads_like_the_makefile_recipe(self):
        command = dialog_model.generator_command(self.binding)
        self.assertTrue(command.label.startswith("python tools/dialog_to_c.py"))

    def test_no_path_in_the_command_points_outside_the_active_worktree(self):
        # R14: every absolute path in the command is under the bound
        # worktree. The relative ones are resolved by the cwd the panel
        # runs it in, which is that same worktree.
        worktree = self.binding.active_worktree.path
        for argument in dialog_model.generator_command(self.binding).argv[1:]:
            if Path(argument).is_absolute() and argument != sys.executable:
                self.assertTrue(
                    str(Path(argument)).startswith(str(worktree)),
                    f"{argument} is outside {worktree}",
                )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: FAIL — `AttributeError: … has no attribute 'problems'`.

- [ ] **Step 3: Write the implementation**

Append to `tools/garage/core/dialog_model.py`:

```python
# ── Refusing a save (R9/AC8) ─────────────────────────────────────────────


@dataclass(frozen=True)
class Problem:
    """One node the limits refuse, named the way the panel shows it."""

    npc_id: int
    npc_name: str
    node_idx: int
    message: str


def problems(data: DialogData) -> List[Problem]:
    """Every node the limits refuse, across every NPC.

    All of them, not the first: a designer who fixed one node and pressed
    Save again only to be told about the next would be walked through the
    tree one refusal at a time.
    """
    found: List[Problem] = []
    for npc_entry in data.npcs:
        for node in npc_entry.get("nodes", []):
            text = node.get("text", "")
            if is_over_limit(text):
                found.append(
                    Problem(
                        npc_id=npc_entry.get("id", -1),
                        npc_name=npc_entry.get("name", "?"),
                        node_idx=node.get("idx", -1),
                        message=(
                            f"holds {len(text)} characters; the limit is "
                            f"{MAX_TEXT_LEN}"
                        ),
                    )
                )
            choices = node.get("choices", [])
            if len(choices) > MAX_CHOICES:
                found.append(
                    Problem(
                        npc_id=npc_entry.get("id", -1),
                        npc_name=npc_entry.get("name", "?"),
                        node_idx=node.get("idx", -1),
                        message=(
                            f"has {len(choices)} choices; the limit is "
                            f"{MAX_CHOICES}"
                        ),
                    )
                )
    return found


def refusal(data: DialogData) -> Optional[str]:
    """The sentence the panel shows instead of saving, or None when the
    save may go ahead (R9/AC8). Every offending node is named.
    """
    found = problems(data)
    if not found:
        return None
    named = "; ".join(
        f"{p.npc_name} node [{p.node_idx}] {p.message}" for p in found
    )
    return f"Save blocked — {named}."


# ── Running the generator (R11/AC11) ─────────────────────────────────────


def generator_command(binding) -> Command:
    """The `dialog_to_c.py` call to make after a save.

    Argument for argument the game repository's own Makefile recipe:

        python tools/dialog_to_c.py assets/dialog/npcs.json src/dialog_data.c \\
            --hubs-json assets/dialog/hubs.json \\
            --hub-out src/hub_data.c \\
            --config-h src/config.h

    AC11 asks for sources identical to the ones a terminal produces, so
    the safest thing Garage can do is make the identical call. The file
    arguments stay worktree-relative and the run's cwd is the active
    worktree (the panel passes it), which is also what keeps the
    generator's own "Written: src/dialog_data.c" lines readable in the
    log.

    `--config-h` is passed, so `dialog_to_c.py` validates the NPC count
    against MAX_NPCS exactly and patches MAX_HUB_NPCS when the rosters
    need it -- the same two side effects `make dialog_data` has.

    `sys.executable`, not "python": Garage runs the interpreter it is
    running under, not whatever a PATH lookup finds.

    The generator writes the hub lookup tables into src/hub_data.c, which
    bank 0 code reads, and not into the banked src/dialog_data.c. That
    split is load-bearing (gmb-nuke-raider#139, commit e333c56). Garage
    calls the generator and never chooses where it writes.
    """
    generator = binding.resolve(*GENERATOR_RELATIVE)
    argv = (
        sys.executable,
        "-u",
        str(generator),
        NPCS_ARG,
        DIALOG_OUT_RELATIVE,
        "--hubs-json", HUBS_ARG,
        "--hub-out", HUB_OUT_RELATIVE,
        "--config-h", CONFIG_H_ARG,
    )
    label = (
        f"python tools/{GENERATOR_RELATIVE[-1]} {NPCS_ARG} "
        f"{DIALOG_OUT_RELATIVE} --hubs-json {HUBS_ARG} "
        f"--hub-out {HUB_OUT_RELATIVE} --config-h {CONFIG_H_ARG}"
    )
    return Command(argv=argv, label=label, target=DIALOG_OUT_RELATIVE)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_dialog -v`
Expected: PASS.

- [ ] **Step 5: Run the full default suite and confirm it is Qt-free**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK. The new `TestCoreImportsNoQt` from Task 1 covers R12 for `dialog_model.py` — confirm it is in the run and passing.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/dialog_model.py tests/test_garage_dialog.py
git commit -m "feat: the save refusal and the dialog_to_c.py invocation (#4)"
```

---

## Task 5: The panel, read-only — NPC list, node cards, live count, preview

**Files:**
- Create: `tools/garage/panels/dialog.py`
- Create: `tests/garage/test_panels_dialog.py`
- Modify: `tools/garage/theme/qss.py`

This task builds the panel that *shows* a tree. Editing, saving and generating are Task 6, so a reviewer can reject the layout without rejecting the write path.

**Interfaces:**
- Consumes: everything `dialog_model` produces; `tools.garage.core.project.Binding` / `BindingError`; `tools.garage.theme.tokens.TOKENS` (by name only).
- Produces, for Tasks 6–7:
  - `class NodeCard(QWidget)` with attributes `node: dict`, `id_label: QLabel`, `text_field: QLineEdit`, `count_label: QLabel`, `preview_label: QLabel`, and methods `refresh_text_state() -> None`, `refresh_links() -> None`, `link_texts() -> List[str]`, `is_over() -> bool`
  - `class DialogPanel(QWidget)` with `__init__(binding, binding_error, parent=None)`, the attributes `binding`, `data: Optional[DialogData]`, `max_npcs: Optional[int]`, `npc_list: QListWidget`, `log_view: QPlainTextEdit`, and the methods `refresh() -> None`, `rebuild_cards() -> None`, `npc_names() -> List[str]`, `select_npc(index: int) -> None`, `selected_npc_index() -> int`, `selected_npc() -> Optional[dict]`, `selected_nodes() -> List[dict]`, `node_cards() -> List[NodeCard]`, `status_text() -> str`, `append_line(text: str) -> None`, `log_text() -> str`, `is_running() -> bool`, `stop_and_wait() -> None`
  - Object names for the stylesheet: `dialog-panel`, `dialog-status`, `dialog-npc-list`, `dialog-npc-row`, `dialog-node-card`, `dialog-node-id`, `dialog-node-text`, `dialog-node-count`, `dialog-node-preview`, `dialog-link-chip`, `dialog-refusal`, `dialog-log`
  - The dynamic property `over="true"|"false"` on `#dialog-node-card` and `#dialog-node-count`

- [ ] **Step 1: Write the failing tests**

Create `tests/garage/test_panels_dialog.py`:

```python
"""Panel coverage for the dialog panel (spec P3, issue #4).

Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` -- tests/garage/ has no
__init__.py, so default discovery never descends into it (AC13). Run via
`make test-garage` (AC14).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from tools.garage import theme
from tools.garage.core import dialog_model, project
from tools.garage.panels.dialog import DialogPanel

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

_app = QApplication.instance() or QApplication([])

CONFIG_H = """\
#define MAX_NPCS     2
#define MAX_HUB_NPCS           3u
"""

NPCS = {
    "npcs": [
        {
            "id": 0,
            "name": "STEEVE",
            "vendor_field": "ARMOR",
            "nodes": [
                {"idx": 0, "text": "Roads. Parts. Sharp. Racer.",
                 "choices": [], "next": [1]},
                {"idx": 1, "text": "Da FUQ ?", "choices": ["Races", "Shop"],
                 "next": [2, "SHOP"]},
                {"idx": 2, "text": "Stay sharp.", "choices": [],
                 "next": ["END"]},
            ],
        },
        {
            "id": 1,
            "name": "TRADER",
            "vendor_field": "WEAPON1",
            "nodes": [
                {"idx": 0, "text": "Got caps?", "choices": [], "next": ["END"]},
            ],
        },
    ]
}

HUBS = {"hubs": [{"id": 0, "name": "RUST TOWN", "npc_ids": [0, 1]}]}


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _real_generator():
    """The game repository's own dialog_to_c.py, when one is bound. The
    fixture copies it in so AC11 is checked against the real generator
    rather than a stub; every test that needs it skips when no game
    repository is bound, which is the CI case."""
    try:
        path = project.bind().resolve("tools", "dialog_to_c.py")
    except project.BindingError:
        return None
    return path if path.is_file() else None


REAL_GENERATOR = _real_generator()
NO_GAME_REPO = REAL_GENERATOR is None
NO_GAME_REPO_REASON = "no game repository is bound beside this checkout"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def make_fixture_worktree(root: Path, npcs=None, config_h=CONFIG_H) -> Path:
    repo = root / "nuke-raider"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    write_json(repo / "assets" / "dialog" / "npcs.json",
               NPCS if npcs is None else npcs)
    write_json(repo / "assets" / "dialog" / "hubs.json", HUBS)
    (repo / "src" / "config.h").write_text(config_h, encoding="utf-8")
    if REAL_GENERATOR is not None:
        (repo / "tools" / "dialog_to_c.py").write_bytes(
            REAL_GENERATOR.read_bytes())
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
class DialogPanelTestCase(unittest.TestCase):
    npcs = None
    config_h = CONFIG_H

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_fixture_worktree(
            self.root, npcs=self.npcs, config_h=self.config_h)
        self.binding = bind_over(self.root, self.repo)
        self.panel = DialogPanel(self.binding, None)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def saved_npcs(self):
        return json.loads(
            (self.repo / "assets" / "dialog" / "npcs.json").read_text(
                encoding="utf-8"))


class TestNpcList(DialogPanelTestCase):
    """AC1: the panel lists the NPCs in npcs.json."""

    def test_every_npc_is_listed(self):
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER"])

    def test_the_first_npc_is_selected_on_open(self):
        self.assertEqual(self.panel.selected_npc_index(), 0)


class TestNodeCards(DialogPanelTestCase):
    """AC1: the nodes of the selected NPC."""

    def test_a_card_per_node_of_the_selected_npc(self):
        self.assertEqual(len(self.panel.node_cards()), 3)

    def test_selecting_another_npc_shows_its_nodes(self):
        self.panel.select_npc(1)
        cards = self.panel.node_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].text_field.text(), "Got caps?")

    def test_a_card_shows_the_node_index(self):
        self.assertEqual(
            [c.id_label.text() for c in self.panel.node_cards()],
            ["[0]", "[1]", "[2]"],
        )

    def test_a_card_shows_the_node_text(self):
        self.assertEqual(
            self.panel.node_cards()[2].text_field.text(), "Stay sharp.")


class TestCharacterCount(DialogPanelTestCase):
    """AC6/R7: the count is shown against 63 and moves as the user
    types."""

    def test_the_count_is_shown_against_the_limit(self):
        card = self.panel.node_cards()[1]
        self.assertEqual(card.count_label.text(), "8/63")

    def test_typing_updates_the_count_without_a_save(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("Da FUQ ?!!")
        self.assertEqual(card.count_label.text(), "10/63")

    def test_an_over_long_value_marks_the_card_over(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("A" * 70)
        self.assertTrue(card.is_over())
        self.assertEqual(card.property("over"), "true")

    def test_shortening_it_again_clears_the_mark(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("A" * 70)
        card.text_field.setText("short")
        self.assertFalse(card.is_over())
        self.assertEqual(card.property("over"), "false")


class TestPreview(DialogPanelTestCase):
    """AC7/R8: the preview wraps at 12 characters."""

    def test_the_preview_is_the_wrapped_text(self):
        card = self.panel.node_cards()[0]
        self.assertEqual(
            card.preview_label.text(),
            "\n".join(dialog_model.wrap_preview("Roads. Parts. Sharp. Racer.")),
        )

    def test_no_preview_line_is_longer_than_twelve_characters(self):
        card = self.panel.node_cards()[0]
        for line in card.preview_label.text().splitlines():
            self.assertLessEqual(len(line), 12, line)

    def test_the_preview_follows_the_text_as_it_is_typed(self):
        card = self.panel.node_cards()[2]
        card.text_field.setText("Watch the east corner")
        self.assertEqual(
            card.preview_label.text(),
            "\n".join(dialog_model.wrap_preview("Watch the east corner")),
        )


class TestLinkChips(DialogPanelTestCase):
    """The prototype's `next → [1]` and `[Races] → [2]` chips."""

    def test_a_narration_node_shows_its_next(self):
        self.assertEqual(
            self.panel.node_cards()[0].link_texts(), ["next → [1]"])

    def test_a_choice_node_shows_one_chip_per_choice(self):
        self.assertEqual(
            self.panel.node_cards()[1].link_texts(),
            ["[Races] → [2]", "[Shop] → SHOP"],
        )

    def test_a_node_ending_the_tree_says_so(self):
        self.assertEqual(
            self.panel.node_cards()[2].link_texts(), ["next → END"])


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestUnreadableFiles(unittest.TestCase):
    """A worktree with no dialog assets must state that, not crash."""

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_fixture_worktree(self.root)
        (self.repo / "assets" / "dialog" / "npcs.json").unlink()
        self.binding = bind_over(self.root, self.repo)
        self.panel = DialogPanel(self.binding, None)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def test_the_status_names_the_missing_file(self):
        self.assertIn("npcs.json", self.panel.status_text())

    def test_no_cards_are_shown(self):
        self.assertEqual(self.panel.node_cards(), [])


class TestNoBinding(unittest.TestCase):
    """No game repository bound: the panel states it and offers nothing.
    Not skipped -- this is the CI case, and it must be covered there."""

    def setUp(self):
        theme.apply(_app)
        self.error = project.BindingError("game_repo", "nothing is bound")
        self.panel = DialogPanel(None, self.error)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_status_carries_the_binding_failure(self):
        self.assertIn("nothing is bound", self.panel.status_text())

    def test_no_npcs_and_no_cards(self):
        self.assertEqual(self.panel.npc_names(), [])
        self.assertEqual(self.panel.node_cards(), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.panels.dialog'`.

- [ ] **Step 3: Write the panel**

Create `tools/garage/panels/dialog.py`:

```python
"""The dialog panel: edit an NPC's dialog tree with the Game Boy's text
limits enforced as you type (spec P3, issue #4).

Layout follows the prototype's Dialog screen (`garage/index.html`): a
narrow NPC list on the left, a column of node cards on the right, and
under them the refusal line, the Save & Generate button and the
generator's output.

Thin by rule. Every rule this panel enforces -- the 63-character node, the
three choices, the twelve-character wrap, the renumbering after a delete,
the NPC ceiling, the refusal -- lives in `tools.garage.core.dialog_model`
and is tested with no display (R12). What is here is widgets, signals and
the order things happen in.

R18/AC18 of P1 still applies: no colour literal, no font family and no
`setStyleSheet` call in this file. Appearance comes from the one
stylesheet, selected by the object names below and by the `over` dynamic
property.

Threading: the generator is a subprocess, so it runs through
`tools.garage.panels.runner.RunController` -- the same worker the compile
bar, the commit panel and the asset panel use.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import dialog_model
from tools.garage.core.project import Binding, BindingError
from tools.garage.panels.runner import RunController

# How many lines of the generator's output stay visible.
LOG_VISIBLE_LINES = 6


class NodeCard(QWidget):
    """One node: its index, its text, the live character count, the wrap
    preview, and where it goes next.

    The card holds the node dict itself, not a copy: an edit here is an
    edit to the tree the panel will save, which is what makes AC2 a
    property of the data rather than of a copy-back step someone has to
    remember.
    """

    def __init__(self, node: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("dialog-node-card")
        self.node = node

        layout = QVBoxLayout(self)

        head = QHBoxLayout()
        self.id_label = QLabel(f"[{node['idx']}]")
        self.id_label.setObjectName("dialog-node-id")
        head.addWidget(self.id_label)

        self.text_field = QLineEdit(node.get("text", ""))
        self.text_field.setObjectName("dialog-node-text")
        head.addWidget(self.text_field, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("dialog-node-count")
        head.addWidget(self.count_label)
        layout.addLayout(head)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("dialog-node-preview")
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignLeft)

        self.links_row = QHBoxLayout()
        self.links_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.links_row)
        self._link_labels: List[QLabel] = []

        # AC6: the count and the preview follow the field, keystroke by
        # keystroke -- and the node dict follows it too, so nothing has to
        # be harvested out of the widgets at save time.
        self.text_field.textChanged.connect(self._on_text_changed)
        self.refresh_text_state()
        self.refresh_links()

    # -- text, count, preview ---------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        dialog_model.set_text(self.node, text)
        self.refresh_text_state()

    def refresh_text_state(self) -> None:
        text = self.node.get("text", "")
        self.count_label.setText(dialog_model.count_label(text))
        self.preview_label.setText("\n".join(dialog_model.wrap_preview(text)))
        self._set_over_property(dialog_model.is_over_limit(text))

    def is_over(self) -> bool:
        return dialog_model.is_over_limit(self.node.get("text", ""))

    def _set_over_property(self, over: bool) -> None:
        value = "true" if over else "false"
        for widget in (self, self.count_label):
            widget.setProperty("over", value)
            # A dynamic property a stylesheet selects on does not re-apply
            # itself; the widget has to be repolished for the new value to
            # take effect.
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)

    # -- where the node goes ----------------------------------------------

    def link_texts(self) -> List[str]:
        return [label.text() for label in self._link_labels]

    def refresh_links(self) -> None:
        for label in self._link_labels:
            self.links_row.removeWidget(label)
            label.setParent(None)
            label.deleteLater()
        self._link_labels = []
        for text in self._link_strings():
            label = QLabel(text)
            label.setObjectName("dialog-link-chip")
            self.links_row.addWidget(label)
            self._link_labels.append(label)

    def _link_strings(self) -> List[str]:
        choices = self.node.get("choices", [])
        nexts = self.node.get("next", [])
        if not choices:
            target = nexts[0] if nexts else dialog_model.END
            return [f"next → {_target_text(target)}"]
        strings = []
        for position, choice in enumerate(choices):
            target = nexts[position] if position < len(nexts) else dialog_model.END
            strings.append(f"[{choice}] → {_target_text(target)}")
        return strings


def _target_text(target) -> str:
    """`END` and `SHOP` read as themselves; a node index reads as `[2]`,
    the way the prototype's chips and the node headers spell one."""
    if target in dialog_model.SENTINELS:
        return str(target)
    return f"[{target}]"


class DialogPanel(QWidget):
    """R1's two files, R2's NPC list and node list, R7's live count and
    R8's wrap preview. Editing, saving and generating are wired in on top
    of this in the same class -- see the edit controls below.
    """

    saved = Signal()

    def __init__(self, binding: Optional[Binding],
                 binding_error: Optional[BindingError], parent=None):
        super().__init__(parent)
        self.setObjectName("dialog-panel")
        self.binding = binding
        self.binding_error = binding_error
        self.data: Optional[dialog_model.DialogData] = None
        self.max_npcs: Optional[int] = None
        self._cards: List[NodeCard] = []

        layout = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setObjectName("dialog-status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        body = QHBoxLayout()

        self.npc_list = QListWidget()
        self.npc_list.setObjectName("dialog-npc-list")
        self.npc_list.currentRowChanged.connect(self._on_npc_changed)
        body.addWidget(self.npc_list)

        self.nodes_holder = QWidget()
        self.nodes_layout = QVBoxLayout(self.nodes_holder)
        self.nodes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.nodes_holder)
        body.addWidget(scroll, 1)

        layout.addLayout(body, 1)

        self.refusal_label = QLabel()
        self.refusal_label.setObjectName("dialog-refusal")
        self.refusal_label.setWordWrap(True)
        self.refusal_label.hide()
        layout.addWidget(self.refusal_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("dialog-log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES
        )
        layout.addWidget(self.log_view)

        self._runs = RunController(self)
        self._runs.line.connect(self.append_line)
        self._runs.command_started.connect(self._append_command)
        self._runs.finished.connect(self._on_run_finished)

        self.refresh()

    # -- reading the tree --------------------------------------------------

    def refresh(self) -> None:
        """Re-read both files and rebuild the list and the cards.

        Called on every open, like the asset panel: the worktree's files
        can change under a closed dialog -- a branch switch, a pull, a
        hand edit -- and a panel showing what was there last time would
        save that stale tree back over them.
        """
        self._clear_cards()
        self.npc_list.clear()
        self.data = None
        self.max_npcs = None

        if self.binding is None:
            message = (
                self.binding_error.message if self.binding_error is not None
                else "No game repository is bound, so there is no dialog to "
                     "edit."
            )
            self.status_label.setText(message)
            return

        try:
            self.data = dialog_model.load(self.binding)
            self.max_npcs = dialog_model.read_max_npcs(self.binding)
        except dialog_model.DialogError as exc:
            self.data = None
            self.status_label.setText(exc.message)
            return

        for npc in self.data.npcs:
            self.npc_list.addItem(
                f"{npc['name']}  {len(npc.get('nodes', []))}")
        self._refresh_status()
        if self.data.npcs:
            self.npc_list.setCurrentRow(0)

    def _refresh_status(self) -> None:
        if self.data is None:
            return
        self.status_label.setText(
            f"{self.data.npcs_path.name} · {len(self.data.npcs)} of "
            f"{self.max_npcs} NPCs"
        )

    def status_text(self) -> str:
        return self.status_label.text()

    def npc_names(self) -> List[str]:
        if self.data is None:
            return []
        return [npc["name"] for npc in self.data.npcs]

    def selected_npc_index(self) -> int:
        return self.npc_list.currentRow()

    def select_npc(self, index: int) -> None:
        self.npc_list.setCurrentRow(index)

    def selected_npc(self) -> Optional[dict]:
        if self.data is None:
            return None
        index = self.selected_npc_index()
        if index < 0 or index >= len(self.data.npcs):
            return None
        return self.data.npcs[index]

    def selected_nodes(self) -> List[dict]:
        npc = self.selected_npc()
        return npc["nodes"] if npc is not None else []

    def node_cards(self) -> List[NodeCard]:
        return list(self._cards)

    def _on_npc_changed(self, _row: int) -> None:
        self.rebuild_cards()

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.nodes_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []

    def rebuild_cards(self) -> None:
        self._clear_cards()
        for node in self.selected_nodes():
            card = NodeCard(node, parent=self.nodes_holder)
            self.nodes_layout.addWidget(card)
            self._cards.append(card)

    # -- the generator's output -------------------------------------------

    def append_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def _append_command(self, label: str, _target: str) -> None:
        self.append_line(f"$ {label}")

    def _on_run_finished(self, results) -> None:
        # Task 6 fills this in; the connection exists here so the panel is
        # never wired half-way.
        pass

    def is_running(self) -> bool:
        return self._runs.is_running()

    def stop_and_wait(self) -> None:
        self._runs.stop_and_wait()
```

- [ ] **Step 4: Add the stylesheet rules**

In `tools/garage/theme/qss.py`, append this entry to the module docstring's list of selectors (after the asset panel's entry):

```
- `#dialog-panel`, `#dialog-status`, `#dialog-npc-list`,
  `#dialog-node-card`, `#dialog-node-id`, `#dialog-node-text`,
  `#dialog-node-count`, `#dialog-node-preview`, `#dialog-link-chip`,
  `#dialog-refusal`, `#dialog-log` -- the dialog panel
  (`tools/garage/panels/dialog.py`). `[over="true"]` on a card and on its
  count is the over-the-limit treatment the prototype's `.node.over`
  declares; the count also spells the numbers out (`70/63`), so colour is
  never the only signal. `#dialog-node-preview` is the Game Boy dialog
  box, painted in the four `gb-*` shades.
```

And append these rules to the end of `build_stylesheet`'s returned string, before the closing `"""`:

```python
/* ============================================================
   Dialog panel (tools/garage/panels/dialog.py). The prototype's
   Dialog screen: an NPC list, a column of node cards, each with
   a live character count and a Game Boy wrap preview.
   ============================================================ */
#dialog-status {{ color: {t["text-2"]}; }}
#dialog-npc-list {{
    background: {t["surface"]};
    border: 1px solid {t["line"]};
    border-radius: 4px;
    max-width: 190px;
}}
#dialog-node-card {{
    background: {t["surface"]};
    border: 1px solid {t["line"]};
    border-radius: 5px;
}}
#dialog-node-card[over="true"] {{
    border-color: {t["fail"]};
    background: {t["fail-soft"]};
}}
#dialog-node-id {{
    font-family: {FONT_MONO};
    font-size: 10px;
    color: {t["text-3"]};
}}
#dialog-node-count {{
    font-family: {FONT_MONO};
    font-size: 10px;
    color: {t["text-3"]};
}}
#dialog-node-count[over="true"] {{ color: {t["fail"]}; font-weight: 700; }}
#dialog-node-preview {{
    font-family: {FONT_MONO};
    font-size: 11px;
    background: {t["gb-0"]};
    color: {t["gb-3"]};
    border: 2px solid {t["gb-2"]};
    border-radius: 2px;
    padding: 6px 7px;
}}
#dialog-link-chip {{
    font-family: {FONT_MONO};
    font-size: 10px;
    color: {t["text-2"]};
    background: {t["surface-2"]};
    border: 1px solid {t["line"]};
    border-radius: 3px;
    padding: 2px 7px;
}}
#dialog-refusal {{ color: {t["fail"]}; font-weight: 600; }}
#dialog-log {{ font-family: {FONT_MONO}; font-size: 11px; }}
```

- [ ] **Step 5: Run the panel tests to verify they pass**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`
Expected: PASS. The whole file skips when no game repository is bound except `TestNoBinding`, which must pass either way.

- [ ] **Step 6: Run the whole panel suite**

Run: `python -m unittest discover -s tests/garage -p 'test_*.py'`
Expected: OK — in particular `TestNoColourLiteralInPanelSource`, which now greps the new panel file. This target is long and prints nothing while it runs; give it a generous timeout and do not kill it for being quiet.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/panels/dialog.py tests/garage/test_panels_dialog.py tools/garage/theme/qss.py
git commit -m "feat: the dialog panel's tree view, live count and wrap preview (#4)"
```

---

## Task 6: Editing, saving and generating in the panel

**Files:**
- Modify: `tools/garage/panels/dialog.py`
- Modify: `tests/garage/test_panels_dialog.py`
- Modify: `tools/garage/theme/qss.py` (one more object name)

**Interfaces:**
- Consumes: Task 5's `DialogPanel` and `NodeCard`; `dialog_model.add_node` / `delete_node` / `set_next` / `add_choice` / `remove_choice` / `rename_npc` / `add_npc` / `refusal` / `generator_command`; `RunController`.
- Produces, for Task 7:
  - `DialogPanel.add_node() -> None`
  - `DialogPanel.delete_node(card: NodeCard) -> None`
  - `DialogPanel.set_next(card: NodeCard, slot: int, target) -> None`
  - `DialogPanel.add_choice(card: NodeCard, label: str) -> None`
  - `DialogPanel.remove_choice(card: NodeCard, choice_index: int) -> None`
  - `DialogPanel.rename_selected_npc(name: str) -> None`
  - `DialogPanel.add_npc(name: str) -> None`
  - `DialogPanel.save() -> bool` — False when refused
  - `DialogPanel.refusal_text() -> str`
  - `DialogPanel.saved` signal, emitted after a successful write
  - `DialogPanel.save_button: QPushButton`, `DialogPanel.add_node_button`, `DialogPanel.add_npc_button`, `DialogPanel.rename_npc_button`, `DialogPanel.npc_name_field: QLineEdit`
  - Object names `dialog-save`, `dialog-add-node`, `dialog-add-npc`, `dialog-rename-npc`, `dialog-npc-name`

- [ ] **Step 1: Write the failing tests**

Append to `tests/garage/test_panels_dialog.py`:

```python
class TestEditingText(DialogPanelTestCase):
    """AC2: text edited in Garage appears in the JSON after a save."""

    def test_saving_writes_the_edited_text(self):
        card = self.panel.node_cards()[0]
        card.text_field.setText("Fresh line.")

        self.assertTrue(self.panel.save())

        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["text"], "Fresh line.")

    def test_saving_emits_saved(self):
        seen = []
        self.panel.saved.connect(lambda: seen.append(True))
        self.panel.save()
        self.assertEqual(seen, [True])


class TestAddAndDeleteNode(DialogPanelTestCase):
    """R3/AC3: add a node, delete a node, and leave no reference wrong."""

    def test_adding_a_node_shows_a_new_card(self):
        self.panel.add_node()
        self.assertEqual(len(self.panel.node_cards()), 4)
        self.assertEqual(self.panel.node_cards()[3].id_label.text(), "[3]")

    def test_an_added_node_is_saved(self):
        self.panel.add_node()
        self.panel.save()
        self.assertEqual(len(self.saved_npcs()["npcs"][0]["nodes"]), 4)

    def test_deleting_a_node_removes_its_card(self):
        self.panel.delete_node(self.panel.node_cards()[1])
        self.assertEqual(
            [c.id_label.text() for c in self.panel.node_cards()],
            ["[0]", "[1]"],
        )

    def test_a_deleted_nodes_referrers_are_renumbered_in_the_saved_json(self):
        # Node [0] points at [1]; deleting [1] must leave [0] at END, and
        # the old [2] must have become [1].
        self.panel.delete_node(self.panel.node_cards()[1])
        self.panel.save()

        nodes = self.saved_npcs()["npcs"][0]["nodes"]
        self.assertEqual([n["idx"] for n in nodes], [0, 1])
        self.assertEqual(nodes[0]["next"], ["END"])

    def test_deleting_updates_the_npc_lists_node_count(self):
        self.panel.delete_node(self.panel.node_cards()[1])
        self.assertIn("2", self.panel.npc_list.item(0).text())


class TestSetNext(DialogPanelTestCase):
    """R5/AC4: a next pointer set in Garage appears in the saved JSON."""

    def test_setting_a_narration_next_to_a_node(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, 2)
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["next"], [2])

    def test_setting_a_narration_next_to_end(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, "END")
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][0]["next"], ["END"])

    def test_setting_one_choice_slot_leaves_the_other_alone(self):
        self.panel.set_next(self.panel.node_cards()[1], 0, "END")
        self.panel.save()
        self.assertEqual(
            self.saved_npcs()["npcs"][0]["nodes"][1]["next"], ["END", "SHOP"])

    def test_the_chip_redraws_after_the_change(self):
        self.panel.set_next(self.panel.node_cards()[0], 0, "END")
        self.assertEqual(
            self.panel.node_cards()[0].link_texts(), ["next → END"])


class TestChoices(DialogPanelTestCase):
    """R6/AC5: between zero and three choices, and no fourth."""

    def test_adding_a_choice_shows_a_chip_for_it(self):
        card = self.panel.node_cards()[0]
        self.panel.add_choice(card, "Yes")
        self.assertEqual(card.link_texts(), ["[Yes] → [1]"])

    def test_a_choice_is_saved(self):
        self.panel.add_choice(self.panel.node_cards()[0], "Yes")
        self.panel.save()
        node = self.saved_npcs()["npcs"][0]["nodes"][0]
        self.assertEqual(node["choices"], ["Yes"])
        self.assertEqual(node["next"], [1])

    def test_a_fourth_choice_is_refused_and_said_in_the_log(self):
        card = self.panel.node_cards()[1]
        self.panel.add_choice(card, "Third")
        self.panel.add_choice(card, "Fourth")
        self.assertEqual(len(card.node["choices"]), 3)
        self.assertIn("3", self.panel.log_text())

    def test_removing_a_choice_removes_its_chip(self):
        card = self.panel.node_cards()[1]
        self.panel.remove_choice(card, 0)
        self.assertEqual(card.link_texts(), ["[Shop] → SHOP"])


class TestRenameNpc(DialogPanelTestCase):
    """R3: rename an NPC."""

    def test_the_list_shows_the_new_name(self):
        self.panel.rename_selected_npc("grease")
        self.assertEqual(self.panel.npc_names(), ["GREASE", "TRADER"])

    def test_the_new_name_is_saved(self):
        self.panel.rename_selected_npc("grease")
        self.panel.save()
        self.assertEqual(self.saved_npcs()["npcs"][0]["name"], "GREASE")


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestNpcCeiling(DialogPanelTestCase):
    """AC9: Garage refuses to add an NPC beyond the maximum the game
    supports. The fixture's config.h says MAX_NPCS 2, and the fixture has
    two NPCs."""

    def test_adding_a_third_npc_is_refused(self):
        self.panel.add_npc("SCOUT")
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER"])

    def test_the_refusal_names_the_limit(self):
        self.panel.add_npc("SCOUT")
        self.assertIn("2", self.panel.log_text())

    def test_a_raised_ceiling_lets_the_npc_in(self):
        self.binding.config_h.write_text(
            "#define MAX_NPCS     3\n", encoding="utf-8")
        self.panel.refresh()
        self.panel.add_npc("SCOUT")
        self.assertEqual(self.panel.npc_names(), ["STEEVE", "TRADER", "SCOUT"])


class TestSaveRefusal(DialogPanelTestCase):
    """AC8: Garage refuses to save when a node holds 63 characters or
    more, and names that node."""

    def test_an_over_long_node_blocks_the_save(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save())

    def test_the_file_is_untouched_by_a_refused_save(self):
        before = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.panel.save()
        after = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.assertEqual(before, after)

    def test_the_refusal_names_the_npc_and_the_node(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.panel.save()
        self.assertIn("STEEVE", self.panel.refusal_text())
        self.assertIn("[1]", self.panel.refusal_text())

    def test_exactly_sixty_three_characters_is_refused(self):
        self.panel.node_cards()[1].text_field.setText("A" * 63)
        self.assertFalse(self.panel.save())

    def test_sixty_two_characters_saves(self):
        self.panel.node_cards()[1].text_field.setText("A" * 62)
        self.assertTrue(self.panel.save())

    def test_the_save_button_is_disabled_while_a_node_is_over(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_it_is_enabled_again_once_the_node_fits(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("A" * 70)
        card.text_field.setText("fits")
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_the_refusal_clears_once_the_node_fits(self):
        card = self.panel.node_cards()[1]
        card.text_field.setText("A" * 70)
        card.text_field.setText("fits")
        self.assertEqual(self.panel.refusal_text(), "")


@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
class TestGeneratorRuns(DialogPanelTestCase):
    """AC10/AC11: dialog_to_c.py runs after a save, its output appears in
    the window, and what it writes is what a terminal writes.

    The fixture holds the game repository's real dialog_to_c.py, and the
    run is a real subprocess -- a stub would prove the wiring and nothing
    about AC11.
    """

    npcs = NPCS

    def _save_and_wait(self):
        self.assertTrue(self.panel.save())
        deadline = 30.0
        step = 0.05
        waited = 0.0
        while self.panel.is_running() and waited < deadline:
            QApplication.processEvents()
            time.sleep(step)
            waited += step
        QApplication.processEvents()
        self.assertFalse(self.panel.is_running(), "the generator never ended")

    def test_the_generator_writes_the_dialog_source(self):
        self._save_and_wait()
        self.assertTrue((self.repo / "src" / "dialog_data.c").is_file())

    def test_the_generator_writes_the_hub_source(self):
        self._save_and_wait()
        self.assertTrue((self.repo / "src" / "hub_data.c").is_file())

    def test_its_output_appears_in_the_window(self):
        self._save_and_wait()
        self.assertIn("dialog_data.c", self.panel.log_text())

    def test_the_command_is_echoed_before_it_runs(self):
        self._save_and_wait()
        self.assertIn("$ python tools/dialog_to_c.py", self.panel.log_text())

    def test_the_sources_match_what_a_terminal_produces(self):
        """AC11, checked rather than asserted: the same generator, run the
        way the Makefile runs it, must produce byte-identical output."""
        self._save_and_wait()
        from_garage = (self.repo / "src" / "dialog_data.c").read_bytes()
        hub_from_garage = (self.repo / "src" / "hub_data.c").read_bytes()

        (self.repo / "src" / "dialog_data.c").unlink()
        (self.repo / "src" / "hub_data.c").unlink()
        subprocess.run(
            [sys.executable, "tools/dialog_to_c.py",
             "assets/dialog/npcs.json", "src/dialog_data.c",
             "--hubs-json", "assets/dialog/hubs.json",
             "--hub-out", "src/hub_data.c",
             "--config-h", "src/config.h"],
            cwd=str(self.repo), check=True, capture_output=True, text=True,
        )

        self.assertEqual(from_garage,
                         (self.repo / "src" / "dialog_data.c").read_bytes())
        self.assertEqual(hub_from_garage,
                         (self.repo / "src" / "hub_data.c").read_bytes())

    def test_a_refused_save_runs_no_generator(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        self.assertFalse(self.panel.save())
        self.assertFalse(self.panel.is_running())
        self.assertFalse((self.repo / "src" / "dialog_data.c").exists())
```

Add `import time` to the file's imports, and `from PySide6.QtWidgets import QApplication` is already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`
Expected: FAIL — `AttributeError: 'DialogPanel' object has no attribute 'save'`.

- [ ] **Step 3: Add the edit controls, the save and the run**

In `tools/garage/panels/dialog.py`, add these widgets to `__init__`, immediately after the `body` layout is added to `layout` and before the refusal label:

```python
        controls = QHBoxLayout()
        self.add_node_button = QPushButton("Add node")
        self.add_node_button.setObjectName("dialog-add-node")
        self.add_node_button.clicked.connect(lambda: self.add_node())
        controls.addWidget(self.add_node_button)

        self.npc_name_field = QLineEdit()
        self.npc_name_field.setObjectName("dialog-npc-name")
        self.npc_name_field.setPlaceholderText("NPC name")
        controls.addWidget(self.npc_name_field)

        self.rename_npc_button = QPushButton("Rename NPC")
        self.rename_npc_button.setObjectName("dialog-rename-npc")
        self.rename_npc_button.clicked.connect(
            lambda: self.rename_selected_npc(self.npc_name_field.text()))
        controls.addWidget(self.rename_npc_button)

        self.add_npc_button = QPushButton("Add NPC")
        self.add_npc_button.setObjectName("dialog-add-npc")
        self.add_npc_button.clicked.connect(
            lambda: self.add_npc(self.npc_name_field.text()))
        controls.addWidget(self.add_npc_button)

        controls.addStretch(1)

        self.save_button = QPushButton("Save & Generate")
        self.save_button.setObjectName("dialog-save")
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(lambda: self.save())
        controls.addWidget(self.save_button)

        layout.addLayout(controls)
```

Then append these methods to `DialogPanel` and replace the stub `_on_run_finished`:

```python
    # -- editing (R3, R5, R6, R10) ----------------------------------------

    def _report(self, message: str) -> None:
        """A refused edit is said in the log, where the generator's output
        already goes. One place for everything Garage has to tell the user
        about this tree, rather than a second status line to notice.
        """
        self.append_line(message)

    def add_node(self) -> None:
        nodes = self.selected_nodes()
        if self.selected_npc() is None:
            return
        dialog_model.add_node(nodes)
        self.rebuild_cards()
        self._refresh_npc_row()
        self._refresh_refusal()

    def delete_node(self, card: "NodeCard") -> None:
        nodes = self.selected_nodes()
        try:
            index = nodes.index(card.node)
        except ValueError:
            return
        try:
            dialog_model.delete_node(nodes, index)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        # Every card is rebuilt, not only the deleted one: renumbering
        # rewrites `next` on nodes that were not touched by the user, and
        # a chip left showing the old target is a wrong answer to AC3.
        self.rebuild_cards()
        self._refresh_npc_row()
        self._refresh_refusal()

    def set_next(self, card: "NodeCard", slot: int, target) -> None:
        try:
            dialog_model.set_next(card.node, slot, target)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()

    def add_choice(self, card: "NodeCard", label: str) -> None:
        try:
            dialog_model.add_choice(card.node, label)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()
        self._refresh_refusal()

    def remove_choice(self, card: "NodeCard", choice_index: int) -> None:
        try:
            dialog_model.remove_choice(card.node, choice_index)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()
        self._refresh_refusal()

    def rename_selected_npc(self, name: str) -> None:
        if self.data is None:
            return
        index = self.selected_npc_index()
        try:
            dialog_model.rename_npc(self.data.npcs, index, name)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self._refresh_npc_row()

    def add_npc(self, name: str) -> None:
        if self.data is None or self.max_npcs is None:
            return
        try:
            dialog_model.add_npc(self.data.npcs, name, self.max_npcs)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self.npc_list.addItem(f"{self.data.npcs[-1]['name']}  1")
        self._refresh_status()
        self.npc_list.setCurrentRow(len(self.data.npcs) - 1)

    def _refresh_npc_row(self) -> None:
        """Re-label the selected NPC's row: its name and its node count
        are both shown there and both can have just changed."""
        if self.data is None:
            return
        index = self.selected_npc_index()
        npc = self.selected_npc()
        if npc is None:
            return
        item = self.npc_list.item(index)
        if item is not None:
            item.setText(f"{npc['name']}  {len(npc.get('nodes', []))}")

    # -- the refusal, live (AC8) -------------------------------------------

    def refusal_text(self) -> str:
        return self.refusal_label.text()

    def _refresh_refusal(self) -> None:
        """Recompute AC8's refusal and gate the Save button on it.

        Called on every keystroke (through the card, below) rather than
        only at save: the prototype's Dialog screen shows "save blocked"
        while the node is too long, and a button that looks live until it
        is pressed is a worse answer to the same requirement.
        """
        if self.data is None:
            self.refusal_label.hide()
            self.save_button.setEnabled(False)
            return
        message = dialog_model.refusal(self.data)
        if message is None:
            self.refusal_label.setText("")
            self.refusal_label.hide()
            self.save_button.setEnabled(not self.is_running())
            return
        self.refusal_label.setText(message)
        self.refusal_label.show()
        self.save_button.setEnabled(False)

    # -- saving and generating (R9, R11) ----------------------------------

    def save(self) -> bool:
        """Write both files and run the generator (AC2, AC10). Returns
        False when the limits refused the save.

        The refusal is recomputed here rather than trusted from the last
        keystroke: `save()` is callable from a test, from the button and
        from a future caller, and R9 must hold for all three.
        """
        if self.data is None:
            return False
        self._refresh_refusal()
        if dialog_model.refusal(self.data) is not None:
            return False
        if self.is_running():
            self._report(
                "The generator is still running; nothing was saved.")
            return False
        try:
            dialog_model.save(self.data)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return False
        self.saved.emit()
        self._start_generator()
        return True

    def _start_generator(self) -> None:
        """R11: run dialog_to_c.py against the active worktree and stream
        what it prints.

        cwd is the active worktree, because the command's file arguments
        are worktree-relative -- the same spelling the game repository's
        Makefile uses, which is what AC11's byte-identical output rests
        on.
        """
        try:
            command = dialog_model.generator_command(self.binding)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self.save_button.setEnabled(False)
        if not self._runs.start([command], self.binding.active_worktree.path):
            self.save_button.setEnabled(True)

    def _on_run_finished(self, results) -> None:
        for result in results:
            if not result.ok:
                self.append_line(
                    f"{result.command.label} failed (exit "
                    f"{result.exit_code})."
                )
        self._refresh_refusal()
```

Wire the live refusal to the card: in `NodeCard.__init__`, the panel is not known, so connect from the panel instead. In `DialogPanel.rebuild_cards`, after appending each card, add:

```python
            card.text_field.textChanged.connect(
                lambda _text: self._refresh_refusal())
```

and call `self._refresh_refusal()` at the end of `rebuild_cards`.

Add `QPushButton` and `QLineEdit` to the `PySide6.QtWidgets` import list if they are not already there.

- [ ] **Step 4: Add the two new object names to the stylesheet**

In `tools/garage/theme/qss.py`, extend the dialog panel's docstring entry with `#dialog-save`, `#dialog-add-node`, `#dialog-add-npc`, `#dialog-rename-npc`, `#dialog-npc-name`. The `[role="primary"]` button rule the compile bar already declares styles the Save button; no new colour rule is needed.

- [ ] **Step 5: Run the panel tests to verify they pass**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`
Expected: PASS.

- [ ] **Step 6: Run both suites**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Then: `python -m unittest discover -s tests/garage -p 'test_*.py'`
Expected: OK for both.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/panels/dialog.py tests/garage/test_panels_dialog.py tools/garage/theme/qss.py
git commit -m "feat: edit, save and regenerate the dialog tree from the panel (#4)"
```

---

## Task 7: Wire the panel into the window, and the acceptance pass

**Files:**
- Modify: `tools/garage/app.py`
- Modify: `tests/garage/test_panels.py`

**Interfaces:**
- Consumes: `tools.garage.panels.dialog.DialogPanel`.
- Produces: `GarageWindow.dialog_panel`, `GarageWindow.dialog_dialog`, `GarageWindow.show_dialog_action`, `GarageWindow.open_dialog_editor()`.

Note the naming: the action and dialog are called `dialog_editor` where "dialog" alone would collide with Qt's `QDialog` in the reader's head — `open_dialog_editor`, not `open_dialog`.

- [ ] **Step 1: Write the failing test**

Append to `tests/garage/test_panels.py` (in the section that covers the window's menu and dialogs):

```python
class TestDialogEditorInTheWindow(unittest.TestCase):
    """AC1/AC10 reachable by a user: the Dialog panel has a View action,
    opens in a dialog of its own, and points at the active worktree.
    """

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_game_repo(self.root / "nuke-raider")
        self.garage_root = write_settings(self.root, self.repo)
        self.window = GarageWindow(self.garage_root)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self._tmp.cleanup()

    def test_the_view_menu_offers_the_dialog_editor(self):
        self.assertIsNotNone(self.window.show_dialog_action)

    def test_it_is_closed_at_launch(self):
        self.assertFalse(self.window.dialog_dialog.isVisible())

    def test_triggering_the_action_opens_it(self):
        self.window.show_dialog_action.trigger()
        self.assertTrue(self.window.dialog_dialog.isVisible())

    def test_the_title_names_the_active_worktree(self):
        self.assertIn(
            self.window.binding.active_worktree.path.name,
            self.window.dialog_dialog.windowTitle(),
        )
```

Use whatever fixture helpers `tests/garage/test_panels.py` already defines for a bound window — `make_game_repo` / `write_settings` above are placeholders for that file's existing helpers; read the top of the file and use its real ones rather than adding duplicates. The game repository fixture must hold `assets/dialog/npcs.json` and `assets/dialog/hubs.json`; if the file's existing helper does not write them, extend it to (a worktree with no dialog assets is the `TestUnreadableFiles` case from Task 5, already covered).

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest discover -s tests/garage -p 'test_panels.py' -v -k DialogEditor`
Expected: FAIL — `AttributeError: 'GarageWindow' object has no attribute 'show_dialog_action'`.

- [ ] **Step 3: Wire it into `app.py`**

Add the import beside the other panels:

```python
from tools.garage.panels.dialog import DialogPanel
```

Add a builder beside `_build_assets`:

```python
    def _build_dialog_editor(self) -> None:
        """P3's dialog panel, in a dialog like the assets panel. Rebuilt
        with the body, because what it edits is `assets/dialog/` of the
        *active* worktree — a panel left pointing at the previous one
        would save a tree back over a checkout Garage no longer means.
        """
        self.dialog_panel = DialogPanel(self.binding, self.binding_error)
        self.dialog_panel.setObjectName("garage-dialog-panel")
        self.dialog_dialog = QDialog(self)
        self.dialog_dialog.setObjectName("garage-dialog-dialog")
        self.dialog_dialog.setWindowTitle(self._dialog_editor_title())
        layout = QVBoxLayout(self.dialog_dialog)
        layout.addWidget(self.dialog_panel)
        self.dialog_dialog.resize(980, 760)

    def _dialog_editor_title(self) -> str:
        if self.binding is None:
            return "Dialog"
        return f"Dialog — {self.binding.active_worktree.path.name}"

    def open_dialog_editor(self) -> None:
        self.dialog_panel.refresh()
        self.dialog_dialog.show()
        self.dialog_dialog.raise_()
        self.dialog_dialog.activateWindow()
```

Call it in `_build_ui`, next to `self._build_assets()`:

```python
        self._build_assets()
        self._build_dialog_editor()
```

Add the action in `_build_menu`, after the Assets action:

```python
        self.show_dialog_action = QAction("&Dialog…", self)
        self.show_dialog_action.setObjectName("garage-action-show-dialog")
        self.show_dialog_action.triggered.connect(self.open_dialog_editor)
        view_menu.addAction(self.show_dialog_action)
```

Find `activate_worktree`'s refusal check — the one that refuses a worktree switch while a compile or a converter run is in flight — and add the dialog panel's run to it, in the same shape the assets panel's run is already handled: a generator writing `src/dialog_data.c` in the tree Garage is about to stop pointing at is the same situation. Read the existing branch and follow it exactly.

Also add `self.dialog_panel.stop_and_wait()` wherever the window already calls `stop_and_wait()` on the assets panel (the close handler and the worktree rebuild), for the same reason: a QThread still running when Qt tears its parent down is a crash.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest discover -s tests/garage -p 'test_panels.py' -v -k DialogEditor`
Expected: PASS.

- [ ] **Step 5: Run both suites in full**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK.
Run: `python -m unittest discover -s tests/garage -p 'test_*.py'`
Expected: OK. Long and silent; do not kill it for being quiet.

- [ ] **Step 6: Prove AC13 — the default suite passes with PySide6 absent**

The CI workflow (`.github/workflows/test.yml`) runs `make test` on Windows and Linux with nothing installed, which is the real proof. Locally, confirm the two structural facts that make it true:

```bash
python - <<'PY'
import pathlib, re
root = pathlib.Path("tests")
bad = [p for p in root.glob("*.py") if "PySide6" in p.read_text(encoding="utf-8")]
print("tests/ files mentioning PySide6:", bad)
print("tests/garage/__init__.py exists:", (root / "garage" / "__init__.py").exists())
PY
```

Expected: an empty list, and `False`. If either is wrong, `make test` will break on a machine without Qt.

- [ ] **Step 7: Hand-verify against the real game repository**

Green tests have hidden runtime defects here before. Run the application against the real bound checkout and walk the acceptance criteria:

```bash
python -m tools.garage
```

Then, with the game repository's own worktree bound and **clean** (commit or stash first, so the generated sources can be inspected and reverted):

1. View ▸ Dialog… — the NPC list shows the eight NPCs from `assets/dialog/npcs.json`, and STEEVE's seven nodes appear (AC1).
2. Type into a node — the count moves with each keystroke and the preview rewraps at 12 characters (AC6, AC7).
3. Type 63 characters — the card turns over, the refusal names the NPC and the node, and Save & Generate is disabled (AC8).
4. Shorten it, press Save & Generate — the generator's `Written: src/dialog_data.c` and `Written: src/hub_data.c` lines appear in the log (AC10), and `git diff` in the game repository shows the edit in `assets/dialog/npcs.json` (AC2).
5. `git diff src/dialog_data.c src/hub_data.c`, then run the terminal command by hand and diff again — the two must be identical (AC11):

```bash
cd ../nuke-raider && python tools/dialog_to_c.py assets/dialog/npcs.json src/dialog_data.c --hubs-json assets/dialog/hubs.json --hub-out src/hub_data.c --config-h src/config.h && git diff --stat
```

6. Add an NPC — refused, naming MAX_NPCS 8 (AC9).
7. Delete a node other NPCs' nodes point at, save, and read the JSON: no `next` points at a node that is gone (AC3).
8. Revert the game repository: `cd ../nuke-raider && git checkout -- assets/dialog src` — Garage must leave that checkout as it found it once the verification is done.

Record anything that differs from the plan; a difference here is a defect, not a note.

- [ ] **Step 8: Commit**

```bash
git add tools/garage/app.py tests/garage/test_panels.py
git commit -m "feat: open the dialog editor from the Garage window (#4)"
```

---

## Self-Review

**Spec coverage.**

| Spec item | Task |
|---|---|
| R1 read both files from the active worktree | 1 (`load`) |
| R2 list NPCs, show the selected NPC's nodes | 5 |
| R3 edit text, add node, delete node, rename NPC | 2, 3, 6 |
| R4 renumber every reference on delete | 2 (`renumber_refs`, `delete_node`) |
| R5 set `next` to a node or to the end | 2 (`set_next`, `next_targets`), 6 |
| R6 add/remove choices, zero to three | 2 (`add_choice`, `remove_choice`), 6 |
| R7 live character count against 63 | 1 (`count_label`), 5 |
| R8 wrap preview at 12 | 1 (`wrap_preview`), 5 |
| R9 refuse to save at 63+, naming the node | 4 (`refusal`), 6 |
| R10 refuse an NPC beyond the game's maximum | 1 (`read_max_npcs`), 3 (`add_npc`), 6 |
| R11 run `dialog_to_c.py` after a save, show its output | 4 (`generator_command`), 6 |
| R12 no Qt in `core/`; renumbering, choice and length limits testable headless | 1 (guard test), 2, 3, 4 |
| R13 written fresh, coverage equivalent to `tests/test_dialog_editor.py` | 3 (the equivalence table above) |
| R14 every path through `project.py` | 1, 4 (and the Task 4 test that asserts it) |
| AC1 | 5 (`TestNpcList`, `TestNodeCards`) |
| AC2 | 6 (`TestEditingText`) |
| AC3 | 2, 6 (`TestAddAndDeleteNode`) |
| AC4 | 6 (`TestSetNext`) |
| AC5 | 2, 6 (`TestChoices`) |
| AC6 | 5 (`TestCharacterCount`) |
| AC7 | 5 (`TestPreview`) |
| AC8 | 4, 6 (`TestSaveRefusal`) |
| AC9 | 6 (`TestNpcCeiling`) |
| AC10 | 6 (`TestGeneratorRuns`) |
| AC11 | 6 (`test_the_sources_match_what_a_terminal_produces`), 7 step 7 |
| AC12 | 3 (equivalence table) |
| AC13 | 7 step 6, and CI |
| AC14 | 7 step 5 |

**Out of scope, confirmed untouched.** No task edits the dialog JSON format, `dialog_to_c.py`, `tools/dialog_editor.py`, `tests/test_dialog_editor.py`, `docs/dev-workflow.md`, `tools/screenshot.py` or `.github/workflows/build.yml`. No task previews dialog inside the running game. Nothing in the game repository is modified except by the generator Garage calls, which is the product function the spec asks for.

**Two things a reviewer should look at deliberately.**

1. The 63-character off-by-one against `dialog_to_c.py` (AC8 taken literally; Garage strictly stricter). If the intent was "over 63", one constant comparison changes and four tests move with it.
2. `add_choice` correcting the TUI's `next` bug. R13 makes this a fresh implementation, so the correction is in scope, but it is a behavioural difference from the tool being retired and worth naming in the PR.
