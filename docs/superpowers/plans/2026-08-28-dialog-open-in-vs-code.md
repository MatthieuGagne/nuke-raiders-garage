# Open the Dialog Files in VS Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the dialog panel a button that saves the tree and then opens the bound worktree's `assets/dialog/` in VS Code, so a bulk edit or a look at `hubs.json` does not mean finding the checkout by hand.

**Architecture:** A new Qt-free `tools/garage/core/editor.py` owns the launch: it resolves `code` on `PATH`, spawns it fire-and-forget behind two named seams (`_find_editor`, `_spawn`), and raises a named `EditorError` when there is no `code`. `tools/garage/core/dialog_model.py` gains a directory resolver and, separately, the load-time `Stamp` that makes a clobbering save refuse. `tools/garage/panels/dialog.py` gains one button that calls the panel's existing `save()` and then the core launcher, reporting any refusal in the log the panel already uses for refused edits.

**Tech Stack:** Python 3.13, standard-library `unittest`, PySide6 (panel layer only), `shutil.which` and `subprocess.Popen`.

**Spec:** MatthieuGagne/nuke-raiders-garage#43 — "feat: open the dialog files in VS Code from the dialog panel". Read it alongside this plan; every R and AC number below is its number.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.13, `unittest` only.** `pytest` is not installed in this repository and must not be used. No build step.
- **`tools/garage/core/` imports no Qt** (R9). `tests/test_garage_core.py::TestCoreImportsNoQt` rglobs `tools/garage/core/*.py` and fails on any `import`/`from` line naming PySide6 or shiboken. A new core module is auto-enrolled.
- **No file under `tests/` may import Qt** (R11). `make test` must pass with PySide6 absent. Panel coverage lives under `tests/garage/`, which has no `__init__.py`, so default discovery never descends into it. That omission is load-bearing.
- **No path into the game repository may be hardcoded** (R2). Resolve through `tools.garage.core.project.Binding`: `binding.resolve(...)`, `binding.active_worktree.path`, `binding.config_h`.
- **Anything that reads the game repository skips when none is bound.** CI checks this repository out alone. `bind()` raises `BindingError`; it never returns `None`. The panel takes `Optional[Binding]` plus a `binding_error`, and the unbound path is *not* skipped in panel tests — it is the CI case (R7).
- **No colour literal, no font family, no `setStyleSheet` in a panel** (R10). `tests/garage/test_panels.py::TestNoColourLiteralInPanelSource` globs `tools/garage/panels/*.py`, so a new widget is auto-enrolled. Styling comes from object names and string-valued dynamic properties, selected in `tools/garage/theme/qss.py`.
- **Naming VS Code is legal in exactly one core module.** `tests/test_garage_assets.py::TestOpenInDefaultApp::test_no_editor_is_named_in_any_string_the_code_uses` is an AST tripwire over `core/assets.py`, `core/pipeline.py` and `core/preview.py` for the strings `aseprite`, `tiled`, `hugetracker`. It is not touched by this work; Task 1 adds the matching tripwire for VS Code, which exempts `core/editor.py` and nothing else. That is what "the exception is scoped to this button" (R3) means mechanically.
- **Commit style:** `feat: lowercase sentence (#43)`, `test: …`, `fix: …`, `docs: …`. One commit per step that says "Commit".
- **Test targets:** `make test` for anything under `tools/garage/core/` and `tests/`; `make test-garage` for anything under `tools/garage/panels/`, `tools/garage/theme/` or `app.py`. Tasks 1–2 need `make test`; Task 3 needs both. `make test-garage` is long and prints nothing until it finishes — give it a generous timeout and do not kill it for being quiet.

## Four design decisions this plan makes, and why

**1. A new `core/editor.py`, not a function beside `open_in_default_app`.**

The spec offers both (`Files Impacted`). A separate module is chosen because the module docstring of `core/assets.py` argues at length that Garage names no editor, and that argument stays true of everything in that file. Putting the one deliberate exception in its own module keeps the exception visible, keeps the tripwire's exemption list one name long, and gives the new behaviour a place to be documented next to its own reasoning rather than as a contradiction inside someone else's.

**2. Two seams, not one.**

R9 asks for "a named seam the suite replaces rather than starting a real editor". One seam is not enough here: `_spawn` covers "do not really launch", but the *not-found* path (R4/AC2) needs the resolution itself to be replaceable, because a developer machine has `code` on `PATH` and the test must be able to say it does not. So `_find_editor()` and `_spawn(argv)` are both module-level functions, replaced with `mock.patch.object`, exactly the shape `_startfile` already has.

**3. The button reuses the panel's `save()` whole, generator included.**

R6 says the button saves "through the panel's existing save path". That path is `DialogPanel.save()`, which writes both files, emits `saved`, and starts `dialog_to_c.py`. The generator therefore runs too. That is the honest reading of R6 and the useful one: the state the editor opens is a saved tree whose generated sources match it. It also means every existing refusal — the limits (AC4), a run already in progress, and the new clobber refusal (R8) — gates the editor for free, with `save()` returning `False` and nothing else to write.

**4. The clobber refusal is raised by `dialog_model.save`, not checked by the panel.**

R8's failure mode is silent data loss, so the check belongs where every caller passes: `save()` itself raises `DialogError` before it writes a byte. The panel already has `except dialog_model.DialogError: self._report(exc.message); return False` in `save()`, so the message reaches the user through the same log line refused edits use, with no new mechanism and no new widget. The stamps are refreshed after a successful write, so a second save is not refused by the first one's own output.

## What this plan does *not* build

- No reload-on-return. R8 refuses the clobbering save; it does not re-read the tree. The user reopens the panel, which already re-reads both files on every `refresh()`.
- No setting for the editor command, no second editor, no fallback. A machine without `code` gets R4's message.
- No button on any other panel. `AssetPanel` is untouched.
- No change to the dialog data format, the generator, the text limits, or any file the game repository tracks.

## File Structure

| File | Responsibility |
|---|---|
| **Create** `tools/garage/core/editor.py` | The whole launch: `EDITOR_NAME`, `EDITOR_COMMAND`, `EditorError`, the `_find_editor` and `_spawn` seams, and `open_directory(path)`. The one module in the tree allowed to name an editor. |
| **Modify** `tools/garage/core/dialog_model.py` | `DIALOG_DIR_RELATIVE` and `dialog_dir(binding)`; the two load stamps on `DialogData`; `clobber_refusal(data)`; the refusal and the re-stamp inside `save`. |
| **Modify** `tools/garage/panels/dialog.py` | The "Open in VS Code" button, its enablement, and `open_in_editor()`. |
| **Modify** `tools/garage/theme/qss.py` | One bullet in `build_stylesheet`'s docstring index. No new rule — the button takes the base `QPushButton` styling. |
| **Create** `tests/test_garage_editor.py` | Core coverage for the launch, the not-found path and the tripwire. Reached by `make test`. No Qt import. |
| **Modify** `tests/test_garage_dialog.py` | Coverage for `dialog_dir` and the stamp refusal. |
| **Modify** `tests/garage/test_panels_dialog.py` | Panel coverage: the button, its disabled state, and every refusal that stops it. |
| **Modify** `CLAUDE.md` | The two advertised test counts. |

---

## Task 1: The editor launch

**Files:**
- Create: `tools/garage/core/editor.py`
- Test: `tests/test_garage_editor.py`

**Interfaces:**
- Consumes: nothing from this repository. `shutil.which`, `subprocess.Popen`, `pathlib.Path`.
- Produces: `EDITOR_NAME: str` (`"VS Code"`), `EDITOR_COMMAND: str` (`"code"`), `EditorError(Exception)` with `.message: str`, `_find_editor() -> Optional[str]`, `_spawn(argv: List[str]) -> None`, `open_directory(path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_garage_editor.py`:

```python
"""Coverage for tools/garage/core/editor.py — MatthieuGagne/nuke-raiders-garage#43.

No Qt import anywhere in this file, and no editor is ever started: both
sides of the launch go through the module's two named seams (R9), which
these tests replace.

`make test` discovers this file, and that target installs no PySide6.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import editor  # noqa: E402


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it -- see the
    same helper in tests/test_garage_core.py for why `resolve()` matters
    on Windows."""
    return Path(tmp).resolve()


class TestOpenDirectory(unittest.TestCase):
    """R3/AC1: the directory is handed to the `code` PATH resolves."""

    def test_it_spawns_the_resolved_editor_with_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp) / "dialog"
            target.mkdir()
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(editor, "_spawn") as spawn:
                    editor.open_directory(target)
            spawn.assert_called_once_with(["C:/vs/code.CMD", str(target)])

    def test_the_editor_is_resolved_by_name_on_path(self):
        """R3, and the Notes: `code`, never an absolute path to Code.exe."""
        with mock.patch("shutil.which", return_value="C:/vs/code.CMD") as which:
            self.assertEqual(editor._find_editor(), "C:/vs/code.CMD")
        which.assert_called_once_with("code")

    def test_a_missing_directory_is_a_named_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp) / "gone"
            with self.assertRaises(editor.EditorError) as caught:
                editor.open_directory(target)
            self.assertIn("gone", caught.exception.message)


class TestEditorNotFound(unittest.TestCase):
    """R4/AC2: no `code` on PATH is a message naming VS Code and PATH."""

    def test_nothing_is_spawned(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor", return_value=None):
                with mock.patch.object(editor, "_spawn") as spawn:
                    with self.assertRaises(editor.EditorError):
                        editor.open_directory(target)
            spawn.assert_not_called()

    def test_the_message_names_vs_code_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor", return_value=None):
                with self.assertRaises(editor.EditorError) as caught:
                    editor.open_directory(target)
            message = caught.exception.message
            self.assertIn("VS Code", message)
            self.assertIn("PATH", message)

    def test_a_spawn_failure_is_a_named_failure_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(editor, "_spawn",
                                       side_effect=OSError("denied")):
                    with self.assertRaises(editor.EditorError) as caught:
                        editor.open_directory(target)
            self.assertIn("denied", caught.exception.message)


class TestFireAndForget(unittest.TestCase):
    """R5: Garage starts the editor and never waits on it."""

    def test_the_seam_uses_popen_and_does_not_wait(self):
        with mock.patch.object(subprocess, "Popen") as popen:
            editor._spawn(["C:/vs/code.CMD", "C:/repo/assets/dialog"])
        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            ["C:/vs/code.CMD", "C:/repo/assets/dialog"],
        )
        started = popen.return_value
        started.wait.assert_not_called()
        started.communicate.assert_not_called()

    def test_open_directory_never_calls_run(self):
        """`subprocess.run` blocks until the editor is closed, which is
        the whole failure R5 forbids. Asserted rather than reasoned
        about."""
        with tempfile.TemporaryDirectory() as tmp:
            target = tmp_root(tmp)
            with mock.patch.object(editor, "_find_editor",
                                   return_value="C:/vs/code.CMD"):
                with mock.patch.object(subprocess, "Popen"):
                    with mock.patch.object(subprocess, "run") as run:
                        editor.open_directory(target)
        run.assert_not_called()


class TestTheExceptionIsScoped(unittest.TestCase):
    """R3: `core/editor.py` is the only module allowed to name an editor.

    The sibling tripwire in tests/test_garage_assets.py guards
    assets/pipeline/preview against three other editors' names; this one
    guards every core module against VS Code's, exempting the one module
    the spec makes an exception for. Same shape and same limits: it walks
    the AST for literal string constants outside docstrings, so a name
    assembled at runtime would slip past it.
    """

    def test_no_other_core_module_names_vs_code(self):
        import ast

        core_dir = REPO_ROOT / "tools" / "garage" / "core"
        for path in sorted(core_dir.rglob("*.py")):
            if path.name == "editor.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
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
                    for name in ("vs code", "vscode", "visual studio code",
                                 "code.exe"):
                        self.assertNotIn(
                            name, lowered,
                            f"{path.name} names {name} in code; only "
                            f"core/editor.py may (#43 R3)",
                        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_editor -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.core.editor'`.

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/editor.py`:

```python
"""Opening a directory of the game repository in VS Code (issue #43).

No Qt import belongs in this module or anywhere under tools/garage/core/
(R9): everything here is testable with no display and, through the two
seams below, with no editor.

**This module names an editor, and it is the only one that may.**
`core/assets.py::open_in_default_app` records the opposite rule -- which
program opens a `.png` or a `.uge` is the user's choice, recorded in
Windows -- and that rule is untouched. It holds for a *file* and breaks
for a *directory*: a directory has one association, Explorer, and Explorer
is not an editor. Naming the editor is the only way to hand a folder to
one, so #43 R3 makes this button the stated exception and
`tests/test_garage_editor.py::TestTheExceptionIsScoped` keeps the
exception one module wide.

**The name, not a path.** `code` is resolved on PATH rather than spelled
as an absolute path to the executable: the install location varies (user,
system, portable) and `code` is what an install puts on PATH and what
survives an upgrade. On Windows PATH holds `code.CMD`; `shutil.which`
finds it through PATHEXT and `subprocess.Popen` runs it without a shell.

**Two seams, not one** (R9). `_spawn` is "do not really launch";
`_find_editor` is "pretend PATH has no code", which the not-found test
(R4/AC2) needs on a developer machine where it does.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

# What the user is told, and what Garage looks for. Two constants because
# they are two different things: the product's name, and the command an
# install puts on PATH.
EDITOR_NAME = "VS Code"
EDITOR_COMMAND = "code"


class EditorError(Exception):
    """The editor could not be started. Carries `.message` so the panel
    shows a sentence rather than a traceback (R4).
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _find_editor() -> Optional[str]:
    """Where PATH says `code` is, or None. A seam (R9)."""
    return shutil.which(EDITOR_COMMAND)


def _spawn(argv: List[str]) -> None:
    """Start `argv` and return immediately (R5). A seam (R9).

    `Popen`, never `run`: Garage must not block until the editor is
    closed, and it never learns what the user does in it.

    CREATE_NO_WINDOW keeps the `code.CMD` shim from flashing a console
    window on Windows; the flag does not exist elsewhere, and 0 is the
    no-op value `Popen` accepts on every platform.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(argv, creationflags=creationflags)


def open_directory(path: Path) -> None:
    """Open `path` as a folder in the editor (R3).

    Raises `EditorError` when the directory is not there, when PATH holds
    no `code`, or when the launch itself fails. There is no fallback and
    no second editor: a machine without it gets the message, not another
    program (R4).
    """
    path = Path(path)
    if not path.is_dir():
        raise EditorError(
            f"'{path}' is not a directory, so there is nothing to open in "
            f"{EDITOR_NAME}."
        )
    executable = _find_editor()
    if executable is None:
        raise EditorError(
            f"{EDITOR_NAME} was not found on PATH: no '{EDITOR_COMMAND}' "
            f"command resolves there. Install {EDITOR_NAME}, or add its "
            f"bin directory to PATH — Garage opens no other editor."
        )
    try:
        _spawn([executable, str(path)])
    except OSError as exc:
        raise EditorError(
            f"{EDITOR_NAME} did not start from '{executable}': {exc}."
        ) from exc
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_editor -v`

Expected: PASS, 9 tests.

- [ ] **Step 5: Run the whole default suite**

Run: `python -m unittest discover -s tests -p 'test_*.py'`

Expected: OK. `TestCoreImportsNoQt` now walks the new module and must stay green.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/editor.py tests/test_garage_editor.py
git commit -m "feat: open a directory in VS Code from a Qt-free core module (#43)"
```

---

## Task 2: The dialog directory, and the save that refuses to clobber

Two changes to the same module, in one task because they share its fixture and neither is reviewable without the other's file: `dialog_dir` is what the button opens (R2), and the stamp refusal is what stops the round trip losing the editor's work (R8).

**Files:**
- Modify: `tools/garage/core/dialog_model.py`
- Test: `tests/test_garage_dialog.py`

**Interfaces:**
- Consumes: `project.Binding.resolve(*parts) -> Path`; `assets.Stamp(exists, size_bytes, mtime_ns)`, `assets.stamp(path) -> Stamp`, `assets.has_changed(before, after) -> bool` from `tools/garage/core/assets.py`.
- Produces: `DIALOG_DIR_RELATIVE: Tuple[str, str]`, `dialog_dir(binding) -> Path`, `DialogData.npcs_stamp` / `.hubs_stamp: Optional[assets.Stamp]`, `clobber_refusal(data) -> Optional[str]`, and a `save(data)` that raises `DialogError` instead of overwriting.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_garage_dialog.py`, immediately before the closing `if __name__ == "__main__":` block:

```python
class TestDialogDir(DialogModelTestCase):
    """R2: the directory the button opens is resolved through the
    binding, never joined by a caller."""

    def test_it_is_the_bound_worktrees_assets_dialog(self):
        self.assertEqual(
            dialog_model.dialog_dir(self.binding),
            self.binding.resolve("assets", "dialog"),
        )

    def test_it_holds_both_dialog_files(self):
        directory = dialog_model.dialog_dir(self.binding)
        names = sorted(p.name for p in directory.iterdir())
        self.assertEqual(names, ["hubs.json", "npcs.json"])


class TestLoadStamps(DialogModelTestCase):
    """R8: what the files looked like when Garage read them."""

    def test_load_records_a_stamp_for_each_file(self):
        data = self.reload()
        self.assertTrue(data.npcs_stamp.exists)
        self.assertTrue(data.hubs_stamp.exists)

    def test_an_untouched_pair_is_not_a_refusal(self):
        data = self.reload()
        self.assertIsNone(dialog_model.clobber_refusal(data))


class TestClobberRefusal(DialogModelTestCase):
    """R8/AC6: a file changed outside Garage is not overwritten.

    Every fixture edit below changes the file's *size*, so the refusal
    never rests on mtime resolution -- a same-size rewrite within one
    filesystem tick is what `assets.Stamp` carries an mtime for, and is
    covered in tests/test_garage_assets.py rather than raced here.
    """

    def test_a_changed_npcs_file_refuses_and_names_it(self):
        data = self.reload()
        path = self.repo / "assets" / "dialog" / "npcs.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")

        message = dialog_model.clobber_refusal(data)
        self.assertIsNotNone(message)
        self.assertIn("npcs.json", message)

    def test_a_changed_hubs_file_refuses_and_names_it(self):
        data = self.reload()
        path = self.repo / "assets" / "dialog" / "hubs.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")

        message = dialog_model.clobber_refusal(data)
        self.assertIsNotNone(message)
        self.assertIn("hubs.json", message)

    def test_save_refuses_rather_than_overwriting(self):
        data = self.reload()
        path = self.repo / "assets" / "dialog" / "npcs.json"
        outside = path.read_text(encoding="utf-8") + "\n\n"
        path.write_text(outside, encoding="utf-8")
        data.npcs[0]["nodes"][0]["text"] = "Garage wins?"

        with self.assertRaises(dialog_model.DialogError) as caught:
            dialog_model.save(data)

        self.assertIn("npcs.json", caught.exception.message)
        self.assertEqual(path.read_text(encoding="utf-8"), outside)

    def test_a_refused_save_writes_neither_file(self):
        data = self.reload()
        hubs = self.repo / "assets" / "dialog" / "hubs.json"
        npcs = self.repo / "assets" / "dialog" / "npcs.json"
        hubs.write_text(hubs.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")
        before = npcs.read_bytes()
        data.npcs[0]["nodes"][0]["text"] = "Garage wins?"

        with self.assertRaises(dialog_model.DialogError):
            dialog_model.save(data)

        self.assertEqual(npcs.read_bytes(), before)

    def test_two_saves_in_a_row_are_allowed(self):
        """The stamps follow Garage's own write; without that, the second
        save would refuse against the first one's output."""
        data = self.reload()
        data.npcs[0]["nodes"][0]["text"] = "First."
        dialog_model.save(data)
        data.npcs[0]["nodes"][0]["text"] = "Second."
        dialog_model.save(data)

        written = json.loads(
            (self.repo / "assets" / "dialog" / "npcs.json").read_text(
                encoding="utf-8"))
        self.assertEqual(written["npcs"][0]["nodes"][0]["text"], "Second.")

    def test_data_built_without_stamps_still_saves(self):
        """A `DialogData` a caller assembled by hand has no baseline, so
        there is nothing to compare and nothing to refuse -- it must not
        be treated as "changed"."""
        data = self.reload()
        data.npcs_stamp = None
        data.hubs_stamp = None
        dialog_model.save(data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_dialog -v`

Expected: FAIL — `AttributeError: module 'tools.garage.core.dialog_model' has no attribute 'dialog_dir'`.

- [ ] **Step 3: Add the directory constant and resolver**

In `tools/garage/core/dialog_model.py`, replace the two path constants:

```python
NPCS_RELATIVE = ("assets", "dialog", "npcs.json")
HUBS_RELATIVE = ("assets", "dialog", "hubs.json")
```

with:

```python
# The directory both files live in. Named once and joined onto, rather
# than spelled twice: #43's button opens the directory itself, and a
# second spelling is a second thing to keep in step.
DIALOG_DIR_RELATIVE = ("assets", "dialog")
NPCS_RELATIVE = DIALOG_DIR_RELATIVE + ("npcs.json",)
HUBS_RELATIVE = DIALOG_DIR_RELATIVE + ("hubs.json",)
```

Add the import beside the existing one (`from tools.garage.core.make_runner import Command`):

```python
from tools.garage.core import assets
```

Add the resolver just above `class DialogError`:

```python
def dialog_dir(binding) -> Path:
    """`assets/dialog/` of the active worktree (R2 -- resolved through
    the binding, never joined by a caller).

    Both dialog files live here, and it is what #43's button hands to the
    editor: a folder rather than a file, so `hubs.json` -- which the panel
    does not surface at all -- is reachable too.
    """
    return binding.resolve(*DIALOG_DIR_RELATIVE)
```

- [ ] **Step 4: Add the stamps to `DialogData`**

In the `DialogData` dataclass, replace the two path fields with the four fields below:

```python
    npcs_path: Optional[Path] = None
    hubs_path: Optional[Path] = None
    # What each file looked like when `load` read it (R8). None means "no
    # baseline was taken" -- a DialogData a caller assembled by hand --
    # and never "unchanged": `clobber_refusal` skips a None rather than
    # inventing a comparison it cannot make.
    npcs_stamp: Optional["assets.Stamp"] = None
    hubs_stamp: Optional["assets.Stamp"] = None
```

- [ ] **Step 5: Stamp on load**

In `load`, replace the `return DialogData(...)` with:

```python
    return DialogData(
        npcs=npcs_doc.get("npcs", []),
        hubs=hubs_doc.get("hubs", []),
        npcs_path=npcs_path,
        hubs_path=hubs_path,
        # Stamped after the read, not before: the file Garage is holding
        # is the one it just parsed.
        npcs_stamp=assets.stamp(npcs_path),
        hubs_stamp=assets.stamp(hubs_path),
    )
```

- [ ] **Step 6: Add the refusal, and make `save` raise it**

Add above `save`:

```python
def clobber_refusal(data: DialogData) -> Optional[str]:
    """The sentence to show instead of saving, when a file changed on
    disk after Garage read it (R8), or None when the save may go ahead.

    Garage invites the user to edit these files in an external editor
    (#43), so "open, edit outside, come back, press Save" is an ordinary
    sequence rather than a race -- and without this check it silently
    discards the editor's work. Same class of defect, and same mechanism,
    as the asset panel's mid-run edit (#11): `assets.Stamp` compares size
    *and* mtime, so a rewrite of the same byte count is still a change.

    The refusal names the file, and does not re-read the tree: reloading
    is a separate spec (#43, Out of Scope).
    """
    for path, before in (
        (data.npcs_path, data.npcs_stamp),
        (data.hubs_path, data.hubs_stamp),
    ):
        if before is None or path is None:
            continue
        if assets.has_changed(before, assets.stamp(path)):
            return (
                f"Save blocked — '{path.name}' changed on disk after Garage "
                f"read it, and saving now would overwrite that edit. Reopen "
                f"the dialog panel to load the file as it stands; the edits "
                f"made here since are lost."
            )
    return None
```

Then replace `save` with:

```python
def save(data: DialogData) -> None:
    """Write both files back (AC2). The caller checks `refusal` first --
    see Task 4; this function writes what it is given.

    It does check one thing itself: `clobber_refusal` (R8). That refusal
    is about the file rather than the tree, every caller must obey it,
    and the cost of missing it is somebody's lost work -- so it is raised
    here, before a byte is written, rather than trusted to each caller.
    """
    blocked = clobber_refusal(data)
    if blocked is not None:
        raise DialogError(blocked)
    _write_json(data.npcs_path, {"npcs": data.npcs})
    _write_json(data.hubs_path, {"hubs": data.hubs})
    # Re-baselined against Garage's own write, or the next save would be
    # refused by this one's output. Only for a file that had a baseline:
    # `None` means the caller never wanted one.
    if data.npcs_stamp is not None:
        data.npcs_stamp = assets.stamp(data.npcs_path)
    if data.hubs_stamp is not None:
        data.hubs_stamp = assets.stamp(data.hubs_path)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_dialog -v`

Expected: PASS.

- [ ] **Step 8: Run the whole default suite**

Run: `python -m unittest discover -s tests -p 'test_*.py'`

Expected: OK. `dialog_model` now imports `core/assets.py`, which imports `core/preview.py`; neither imports Qt, so `TestCoreImportsNoQt` stays green.

- [ ] **Step 9: Commit**

```bash
git add tools/garage/core/dialog_model.py tests/test_garage_dialog.py
git commit -m "feat: refuse a dialog save that would overwrite an outside edit (#43)"
```

---

## Task 3: The button

**Files:**
- Modify: `tools/garage/panels/dialog.py`
- Modify: `tools/garage/theme/qss.py` (docstring index only)
- Modify: `CLAUDE.md` (the advertised test counts)
- Test: `tests/garage/test_panels_dialog.py`

**Interfaces:**
- Consumes: `editor.open_directory(path)`, `editor.EditorError.message`, `editor.EDITOR_NAME`; `dialog_model.dialog_dir(binding)`; the panel's own `save() -> bool`, `_report(message)`, `_refresh_refusal()`.
- Produces: `DialogPanel.open_editor_button: QPushButton` (object name `dialog-open-editor`), `DialogPanel.open_in_editor() -> bool`.

- [ ] **Step 1: Write the failing tests**

At the top of `tests/garage/test_panels_dialog.py`, add `mock` to the imports and extend the core import line:

```python
from unittest import mock
```

```python
from tools.garage.core import dialog_model, editor, project
```

Then append, immediately before the closing `if __name__ == "__main__":` block:

```python
class TestOpenInEditorButton(DialogPanelTestCase):
    """#43 R1/R6/AC1/AC3: the button saves, then opens assets/dialog/."""

    def test_the_button_is_enabled_with_a_tree_loaded(self):
        self.assertTrue(self.panel.open_editor_button.isEnabled())

    def test_pressing_it_opens_the_bound_worktrees_dialog_directory(self):
        with mock.patch.object(editor, "open_directory") as opened:
            self.panel.open_editor_button.click()
        opened.assert_called_once_with(
            self.binding.resolve("assets", "dialog"))

    def test_the_directory_it_opens_holds_both_files(self):
        with mock.patch.object(editor, "open_directory") as opened:
            self.panel.open_editor_button.click()
        directory = opened.call_args.args[0]
        self.assertEqual(
            sorted(p.name for p in directory.iterdir()),
            ["hubs.json", "npcs.json"],
        )

    def test_an_unsaved_edit_is_on_disk_before_the_editor_opens(self):
        """AC3, and the ordering R6 asks for: the assertion is made from
        inside the launch, so a save that happened afterwards would fail
        it."""
        card = self.panel.node_cards()[0]
        card.text_field.setText("Edited in Garage.")
        seen = {}

        def record(path):
            seen["text"] = json.loads(
                (path / "npcs.json").read_text(encoding="utf-8")
            )["npcs"][0]["nodes"][0]["text"]

        with mock.patch.object(editor, "open_directory", side_effect=record):
            self.panel.open_editor_button.click()

        self.assertEqual(seen["text"], "Edited in Garage.")

    def test_it_says_what_it_opened(self):
        with mock.patch.object(editor, "open_directory"):
            self.panel.open_editor_button.click()
        self.assertIn(editor.EDITOR_NAME, self.panel.log_text())


class TestOpenInEditorRefusals(DialogPanelTestCase):
    """AC2/AC4/AC6: nothing is opened, and nothing is written, on a
    refusal."""

    def test_an_over_long_node_stops_the_editor_and_the_write(self):
        before = (self.repo / "assets" / "dialog" / "npcs.json").read_bytes()
        self.panel.node_cards()[1].text_field.setText("A" * 70)

        with mock.patch.object(editor, "open_directory") as opened:
            self.panel.open_editor_button.click()

        opened.assert_not_called()
        self.assertEqual(
            (self.repo / "assets" / "dialog" / "npcs.json").read_bytes(),
            before,
        )

    def test_the_same_refusal_the_save_button_would_show_is_shown(self):
        self.panel.node_cards()[1].text_field.setText("A" * 70)
        with mock.patch.object(editor, "open_directory"):
            self.panel.open_editor_button.click()
        self.assertIn("STEEVE", self.panel.refusal_text())
        self.assertIn("[1]", self.panel.refusal_text())

    def test_an_absent_code_on_path_is_stated_in_the_panel(self):
        """AC2, driven through the real core module: only the two seams
        are replaced, so the message the panel shows is the one
        `editor.open_directory` really raises."""
        with mock.patch.object(editor, "_find_editor", return_value=None):
            with mock.patch.object(editor, "_spawn") as spawn:
                self.panel.open_editor_button.click()
        spawn.assert_not_called()
        log = self.panel.log_text()
        self.assertIn("VS Code", log)
        self.assertIn("PATH", log)

    def test_an_outside_edit_stops_the_button_and_names_the_file(self):
        """AC6 through the button: the clobber refusal gates the editor
        the same way the limits do."""
        path = self.repo / "assets" / "dialog" / "npcs.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")
        outside = path.read_bytes()
        self.panel.node_cards()[0].text_field.setText("Garage wins?")

        with mock.patch.object(editor, "open_directory") as opened:
            self.panel.open_editor_button.click()

        opened.assert_not_called()
        self.assertEqual(path.read_bytes(), outside)
        self.assertIn("npcs.json", self.panel.log_text())

    def test_the_save_button_refuses_the_outside_edit_too(self):
        path = self.repo / "assets" / "dialog" / "hubs.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")
        self.assertFalse(self.panel.save())
        self.assertIn("hubs.json", self.panel.log_text())


class TestOpenInEditorWithNoBinding(unittest.TestCase):
    """AC5/R7: no game repository bound. Not skipped -- this is the CI
    case."""

    def setUp(self):
        theme.apply(_app)
        self.error = project.BindingError("game_repo", "nothing is bound")
        self.panel = DialogPanel(None, self.error)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_button_is_disabled(self):
        self.assertFalse(self.panel.open_editor_button.isEnabled())

    def test_the_panel_says_a_repository_must_be_bound(self):
        self.assertIn("nothing is bound", self.panel.status_text())

    def test_calling_it_directly_opens_nothing_and_says_why(self):
        with mock.patch.object(editor, "open_directory") as opened:
            self.assertFalse(self.panel.open_in_editor())
        opened.assert_not_called()
        self.assertIn("bound", self.panel.log_text())


class TestOpenInEditorStyling(DialogPanelTestCase):
    """R10: the button is named for the stylesheet, and styles nothing
    itself. The blanket guards live in tests/garage/test_panels.py; this
    pins the object name they select on."""

    def test_the_button_carries_its_object_name(self):
        self.assertEqual(
            self.panel.open_editor_button.objectName(), "dialog-open-editor")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`

Expected: FAIL — `AttributeError: 'DialogPanel' object has no attribute 'open_editor_button'`.

- [ ] **Step 3: Add the button and its slot**

In `tools/garage/panels/dialog.py`, extend the core import:

```python
from tools.garage.core import dialog_model, editor
```

In `DialogPanel.__init__`, insert the button in the `controls` row immediately before the Save button:

```python
        self.open_editor_button = QPushButton("Open in VS Code")
        self.open_editor_button.setObjectName("dialog-open-editor")
        self.open_editor_button.clicked.connect(lambda: self.open_in_editor())
        controls.addWidget(self.open_editor_button)

        self.save_button = QPushButton("Save & Generate")
```

Add the method after `_start_generator`:

```python
    def open_in_editor(self) -> bool:
        """Save the tree, then open `assets/dialog/` in VS Code (#43
        R1/R6). Returns False when nothing was opened.

        Saving first is the point rather than a convenience: the panel's
        in-memory tree and the file are the same content in two places,
        and opening the file while they disagree shows the user stale
        JSON to edit against. `save()` is called whole -- generator
        included -- so every refusal it already enforces (the limits, a
        run in progress, an outside edit) stops the editor too, with
        nothing written and nothing opened.

        Every rule about *how* an editor is found and started lives in
        `tools.garage.core.editor` and is tested with no display and no
        editor; what is here is the order things happen in.
        """
        if self.binding is None or self.data is None:
            self._report(
                "No game repository is bound, so there is no dialog "
                "directory to open."
            )
            return False
        if not self.save():
            return False
        directory = dialog_model.dialog_dir(self.binding)
        try:
            editor.open_directory(directory)
        except editor.EditorError as exc:
            self._report(exc.message)
            return False
        self._report(f"Opened '{directory}' in {editor.EDITOR_NAME}.")
        return True
```

- [ ] **Step 4: Gate the button on a loaded tree**

In `_refresh_refusal`, add these lines at the very top of the method body, above the `if self.data is None:` branch:

```python
        # R7: with no tree loaded -- no binding, or a file that would not
        # read -- there is nothing to save and nothing to open. Set before
        # the branches below, so both early returns leave it right.
        #
        # Not gated on the refusal, unlike Save: AC4 asks that pressing it
        # while a node is over the limit *shows* that refusal, which a
        # disabled button cannot do.
        self.open_editor_button.setEnabled(self.data is not None)
```

and change the docstring's first sentence to say it gates both buttons:

```python
        """Recompute AC8's refusal, gate the Save and Open buttons on it,
        and return the message (or None) so a caller that already needs
        it -- `save`, below -- is not asking `dialog_model.refusal` a
        second time for the same answer.
```

- [ ] **Step 5: Run the panel tests to verify they pass**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_dialog.py' -v`

Expected: PASS.

- [ ] **Step 6: Name the button in the stylesheet's index**

In `tools/garage/theme/qss.py`, in `build_stylesheet`'s docstring, add `#dialog-open-editor` to the list of dialog object names that are "plain widgets styled by the base rules" (the `#dialog-panel`, `#dialog-save`, … sentence). No QSS rule is added: the button takes the base `QPushButton` styling, which is what R10 asks for — a name the stylesheet owns, not a literal in the panel.

- [ ] **Step 7: Run both suites**

Run:

```
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s tests/garage -p 'test_*.py'
```

Expected: OK from both. The second is long and silent; do not kill it for being quiet.

- [ ] **Step 8: Update the advertised test counts**

`CLAUDE.md`'s table advertises 528 and 339. Take the two "Ran N tests" numbers printed by Step 7 and write those, exactly, into the table's `Tests` column. Do not estimate them.

- [ ] **Step 9: Commit**

```bash
git add tools/garage/panels/dialog.py tools/garage/theme/qss.py tests/garage/test_panels_dialog.py CLAUDE.md
git commit -m "feat: open the dialog directory in VS Code from the dialog panel (#43)"
```

---

## Hand verification

Three acceptance criteria cannot be reached by either suite: they need a real VS Code, a real PATH and the running application. AC1 says "Hand-verified in the running application" outright. Run these against the real binding before opening the pull request, and record the results in the PR body.

Run the app from the repository root with `garage.bat` (or `python -m tools.garage`), open the Dialog panel, and:

| AC | How to check | What must be true |
|---|---|---|
| AC1 | Press **Open in VS Code** | VS Code opens on the bound worktree's `assets/dialog/`, with `npcs.json` and `hubs.json` both in its explorer |
| AC2 | Start Garage from a shell whose PATH has had the VS Code `bin` directory removed, then press the button | Nothing opens; the panel's log states VS Code was not found on PATH |
| AC5 | Move `garage.local.json` aside so nothing is bound, start Garage, open Dialog | The button is greyed out and the status line says a repository must be bound. Restore the file afterwards |

Two notes on driving this by hand, from what the previous verification cost:

- The mouse is not required. Build the panel with the real `Binding` under a plain `QApplication` and call `panel.open_in_editor()` — everything downstream of the click is then production code. Say plainly in the write-up that the click itself was not exercised by hand if you take that route.
- `isVisible()` reads False for a widget whose top-level was never `show()`n. Assert on `open_editor_button.isEnabled()`, which is real either way, rather than on visibility.

Revert anything the verification changed — including `garage.local.json`'s `active` key — before opening the pull request.

## Self-review

**Spec coverage.** R1 → Task 3. R2 → Task 2 (`dialog_dir`). R3 → Task 1 (`_find_editor`, and `TestTheExceptionIsScoped`). R4 → Task 1 (`TestEditorNotFound`) and Task 3 (`test_an_absent_code_on_path_is_stated_in_the_panel`). R5 → Task 1 (`TestFireAndForget`). R6 → Task 3 (`open_in_editor` calls `save()` first; `TestOpenInEditorRefusals`). R7 → Task 3 (`TestOpenInEditorWithNoBinding`). R8 → Task 2 (`clobber_refusal`, `save`). R9 → Task 1 (both seams) plus the global `TestCoreImportsNoQt` constraint. R10 → Task 3 Steps 3/6 plus the global `TestNoColourLiteralInPanelSource` constraint. R11 → the split between Tasks 1–2 (`make test`) and Task 3 (`make test-garage`).

AC1 → hand verification. AC2 → Task 1 and Task 3. AC3 → Task 3 (`test_an_unsaved_edit_is_on_disk_before_the_editor_opens`). AC4 → Task 3 (`TestOpenInEditorRefusals`). AC5 → Task 3 (`TestOpenInEditorWithNoBinding`) and hand verification for the running app. AC6 → Task 2 and Task 3 (`test_an_outside_edit_stops_the_button_and_names_the_file`). AC7 → Tasks 1–2, both under `make test`, no Qt import, no editor started. AC8 → Task 3, which drives `open_editor_button.click()` rather than the method in every test but the direct-call one.

**Names.** `open_directory` mirrors `assets.open_in_default_app`'s shape; `EditorError` mirrors `OpenError` (both carry `.message`, which is what the panels read). `clobber_refusal` mirrors `dialog_model.refusal` — same signature shape, same `Optional[str]` return, same "Save blocked — …" opening, so the two read as one family in the log. `_find_editor`/`_spawn` mirror `_startfile`'s seam convention.

**Known soft spot.** `save()` re-stamping after its own write is what keeps two saves in a row legal; if a future caller ever writes those files without going through `dialog_model.save`, the next save refuses. That is the safe direction to fail, and `test_two_saves_in_a_row_are_allowed` pins the behaviour that matters.
