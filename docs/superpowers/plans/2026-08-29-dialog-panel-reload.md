# Dialog Panel Reload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Reload from disk" action to the dialog panel that re-reads `npcs.json`/`hubs.json`, rebuilds the NPC list and node cards, and clears the clobber refusal #43 added — without weakening that refusal.

**Architecture:** The rebuild logic already exists as `DialogPanel.refresh()` (called today only from `__init__`); the only new panel-level surface is a `QPushButton` wired to a thin `reload()` method that calls `refresh()` and logs a line. No new core function is needed — `dialog_model.load()` already re-stamps against whatever is on disk. The one core change is a docstring correction: `clobber_refusal()` currently says reload is "Out of Scope (#43)", which stops being true.

**Tech Stack:** Python 3.13, PySide6 (Qt widgets), stdlib `unittest`.

**Spec:** GitHub issue #45 (`gh issue view 45` in this repo) — "reload the dialog panel after an editor round trip." Related: #43 (added the clobber refusal and the "Open in VS Code" button this issue fixes the recovery gap for).

## Global Constraints

- No panel file may call `setStyleSheet` or construct a `QColor`/Qt colour constant directly — a new button gets an `objectName` only, styled by the existing `QPushButton` type selector in `tools/garage/theme/qss.py`. Enforced by `tests/garage/test_panels.py::test_no_direct_setstylesheet_call` and the neighbouring colour-literal guards, which sweep every file in `PANEL_SOURCE_FILES`.
- `tools/garage/core/` imports no Qt; `tests/` (plain `unittest discover`) must stay Qt-free and pass with PySide6 absent. This plan's only core edit is a docstring, so this constraint is satisfied by construction — verify no Qt import creeps into `dialog_model.py`.
- `tests/garage/` has no `__init__.py` — new panel tests belong in the existing `tests/garage/test_panels_dialog.py`, discovered only by `make test-garage`, never by `make test`.
- Files written by `dialog_model._write_json` use `newline="\n"`; test fixtures that hand-edit a JSON file on disk to force a stamp mismatch follow the existing pattern (`path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")`) so the size — not just the mtime — changes, avoiding a race on filesystem mtime resolution (see `TestClobberRefusal`'s docstring in `tests/test_garage_dialog.py`).

---

## File Structure

- **Modify** `tools/garage/panels/dialog.py`: add `self.reload_button` (a plain `QPushButton`, objectName `"dialog-reload"`) next to `open_editor_button` in the controls row; add a `reload()` method that calls the existing `refresh()` and logs a line; extend `_refresh_refusal()` to gate `reload_button`'s enabled state on `self.binding is not None` (not on `self.data`, so Reload stays usable to recover from a parse failure that leaves `self.data` as `None`).
- **Modify** `tools/garage/core/dialog_model.py`: update `clobber_refusal()`'s docstring — the closing sentence naming reload as "a separate spec (#43, Out of Scope)" is now wrong; point it at the Reload button (#45) instead. No behavioural change.
- **Modify** `tools/garage/theme/qss.py`: add `#dialog-reload` to the dialog panel's "plain widgets styled only by their type selector" list in the module docstring (lines ~63-71), alongside `#dialog-save`, `#dialog-open-editor`, etc.
- **Modify** `tests/garage/test_panels_dialog.py`: add test coverage for the new button — object name, no-binding disablement, clearing the clobber refusal, rebuilding the NPC list from changed content, and staying usable after a parse failure.

---

### Task 1: Reload button — wiring, gating, and the disk re-read

**Files:**
- Modify: `tools/garage/panels/dialog.py:355-364` (controls row), `tools/garage/panels/dialog.py:391-428` (`refresh()` — add `reload()` right after it), `tools/garage/panels/dialog.py:612-644` (`_refresh_refusal()` — add gating)
- Modify: `tools/garage/core/dialog_model.py:174-201` (`clobber_refusal()` docstring only)
- Modify: `tools/garage/theme/qss.py:63-71` (docstring registry)
- Test: `tests/garage/test_panels_dialog.py` (new `TestReloadButton`, `TestReloadWithNoBinding`, `TestReloadAfterAParseFailure` classes)

**Interfaces:**
- Consumes: `DialogPanel.refresh() -> None` (existing, `tools/garage/panels/dialog.py:391`) — re-reads both files via `dialog_model.load(self.binding)`, rebuilds `npc_list` and (via the `currentRowChanged` signal) the node cards, and calls `self._refresh_refusal()`. `DialogPanel._report(message: str) -> None` (existing, line 511) — appends a line to the log view.
- Produces: `DialogPanel.reload_button` (a `QPushButton`, objectName `"dialog-reload"`) and `DialogPanel.reload() -> None`, for any later task or test that wants to trigger a reload the same way the button does.

- [ ] **Step 1: Write the failing panel tests**

Add to `tests/garage/test_panels_dialog.py`, directly after the existing `TestOpenInEditorStyling` class (currently the file's last class, ending at line 951) and before the `if __name__ == "__main__":` block:

```python
class TestReloadButton(DialogPanelTestCase):
    """#45: Reload re-reads both files, rebuilds the panel, and clears
    the clobber refusal #43 added -- without weakening it."""

    def test_the_button_carries_its_object_name(self):
        self.assertEqual(
            self.panel.reload_button.objectName(), "dialog-reload")

    def test_reload_clears_the_outside_edit_refusal(self):
        path = self.repo / "assets" / "dialog" / "npcs.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n",
                        encoding="utf-8")
        self.assertFalse(self.panel.save())
        self.assertIn("npcs.json", self.panel.log_text())

        self.panel.reload_button.click()

        self.assertTrue(self.panel.save())

    def test_reload_rebuilds_the_list_from_the_new_content(self):
        path = self.repo / "assets" / "dialog" / "npcs.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["npcs"][0]["name"] = "RENAMED"
        write_json(path, changed)

        self.panel.reload_button.click()

        self.assertIn("RENAMED", self.panel.npc_list.item(0).text())

    def test_reload_rebuilds_the_node_cards_too(self):
        path = self.repo / "assets" / "dialog" / "npcs.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["npcs"][0]["nodes"][0]["text"] = "Reloaded text."
        write_json(path, changed)

        self.panel.reload_button.click()

        self.assertEqual(
            self.panel.node_cards()[0].node["text"], "Reloaded text.")


class TestReloadWithNoBinding(unittest.TestCase):
    """R7: no game repository bound -- there is nothing to reload."""

    def setUp(self):
        theme.apply(_app)
        self.error = project.BindingError("game_repo", "nothing is bound")
        self.panel = DialogPanel(None, self.error)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_button_is_disabled(self):
        self.assertFalse(self.panel.reload_button.isEnabled())


class TestReloadAfterAParseFailure(DialogPanelTestCase):
    """Reload is the recovery path for a bad file, not only for a
    clobber refusal -- it must stay enabled when `self.data` is None
    for that reason, unlike `open_editor_button`."""

    def test_reload_stays_enabled_after_a_parse_failure(self):
        path = self.repo / "assets" / "dialog" / "npcs.json"
        path.write_text("{not json", encoding="utf-8")
        self.panel.refresh()
        self.assertIsNone(self.panel.data)

        self.assertTrue(self.panel.reload_button.isEnabled())

    def test_reload_recovers_once_the_file_is_fixed(self):
        path = self.repo / "assets" / "dialog" / "npcs.json"
        good = path.read_text(encoding="utf-8")
        path.write_text("{not json", encoding="utf-8")
        self.panel.refresh()
        self.assertIsNone(self.panel.data)

        path.write_text(good, encoding="utf-8")
        self.panel.reload_button.click()

        self.assertIsNotNone(self.panel.data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.garage.test_panels_dialog.TestReloadButton tests.garage.test_panels_dialog.TestReloadWithNoBinding tests.garage.test_panels_dialog.TestReloadAfterAParseFailure -v`

Expected: every test errors with `AttributeError: 'DialogPanel' object has no attribute 'reload_button'` (or `'reload'`) — the button and method do not exist yet.

- [ ] **Step 3: Add the button and wire it**

In `tools/garage/panels/dialog.py`, in `__init__`, insert a new button between `open_editor_button` (ending line 358) and `save_button` (starting line 360):

```python
        self.open_editor_button = QPushButton(f"Open in {editor.EDITOR_NAME}")
        self.open_editor_button.setObjectName("dialog-open-editor")
        self.open_editor_button.clicked.connect(lambda: self.open_in_editor())
        controls.addWidget(self.open_editor_button)

        self.reload_button = QPushButton("Reload from disk")
        self.reload_button.setObjectName("dialog-reload")
        self.reload_button.clicked.connect(lambda: self.reload())
        controls.addWidget(self.reload_button)

        self.save_button = QPushButton("Save & Generate")
```

- [ ] **Step 4: Add the `reload()` method**

In `tools/garage/panels/dialog.py`, immediately after `refresh()` (which ends at line 428 with `self._refresh_refusal()`) and before `_refresh_status()`:

```python
    def reload(self) -> None:
        """#45: re-read both files and clear the clobber refusal (R8) --
        the recovery #43 left as "reopen the panel by hand". Just
        `refresh()` plus a log line: `refresh()` already does everything
        a reload needs, since it re-reads the tree and re-stamps it the
        same way opening the panel does.
        """
        self.refresh()
        self._report("Reloaded the dialog files from disk.")
```

- [ ] **Step 5: Gate the button's enabled state**

In `tools/garage/panels/dialog.py`, in `_refresh_refusal()` (starting line 612), add the gate as the first line of the body — before the `open_editor_button` line — so it is set on every path, including both early returns:

```python
    def _refresh_refusal(self) -> Optional[str]:
        """Recompute AC8's refusal, gate the Save and Open buttons on it,
        ...
        """
        # Reload's job is recovering from whatever is wrong with the
        # tree -- a clobber refusal or a file that would not even parse
        # -- so unlike Save and Open it is gated on the binding alone,
        # not on `self.data`.
        self.reload_button.setEnabled(self.binding is not None)
        self.open_editor_button.setEnabled(self.data is not None)
```

(The rest of the method is unchanged.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m unittest tests.garage.test_panels_dialog.TestReloadButton tests.garage.test_panels_dialog.TestReloadWithNoBinding tests.garage.test_panels_dialog.TestReloadAfterAParseFailure -v`

Expected: all 7 tests PASS.

- [ ] **Step 7: Run the full Qt suite to confirm nothing regressed**

Run: `python -m unittest discover -s tests/garage -p 'test_*.py'`

Expected: all tests pass (353 baseline + 7 new = 360; the doubled `make test-garage` timing note in this repo's `CLAUDE.md` applies — give it a generous timeout and do not treat a quiet run as a hung one).

- [ ] **Step 8: Update the two docstrings**

In `tools/garage/core/dialog_model.py`, `clobber_refusal()`'s docstring (lines 174-201), replace the closing sentence:

```python
    The refusal names the file, and does not re-read the tree: reloading
    is a separate spec (#43, Out of Scope).
    """
```

with:

```python
    The refusal names the file and does not re-read the tree itself --
    that is the dialog panel's Reload button (#45), which calls `load`
    again and replaces this `DialogData` outright.
    """
```

In `tools/garage/theme/qss.py`, in the module docstring's dialog-panel paragraph (lines 63-71), add `#dialog-reload` to the "plain widgets" list:

```python
- `#dialog-status`, `#dialog-npc-list`, `#dialog-node-card`,
  `#dialog-node-id`, `#dialog-node-text`, `#dialog-node-count`,
  `#dialog-node-preview`, `#dialog-link-chip`, `#dialog-refusal`,
  `#dialog-log` -- the dialog panel (`tools/garage/panels/dialog.py`); its
  other object names (`#dialog-panel`, `#dialog-save`, `#dialog-open-editor`,
  `#dialog-reload`, `#dialog-add-node`, `#dialog-add-npc`, `#dialog-rename-npc`,
  `#dialog-npc-name`, `#dialog-delete-node`, `#dialog-next-combo`,
  `#dialog-choice-label`, `#dialog-add-choice`, `#dialog-remove-choice`)
  are plain widgets styled only by their type selector -- the same as
```

(Only the list of names in that sentence changes — the rest of the paragraph is unchanged.)

- [ ] **Step 9: Run the plain-`unittest` core suite**

Run: `python -m unittest discover -s tests -p 'test_*.py'`

Expected: all tests pass (547 baseline — no count change, since Step 8 only touched docstrings and no test targets `clobber_refusal`'s exact wording).

- [ ] **Step 10: Run the style guards explicitly**

Run: `python -m unittest tests.garage.test_panels.TestNoDirectStyleSheetCalls -v` (adjust the class name to whatever `test_no_direct_setstylesheet_call` actually lives under, per `tests/garage/test_panels.py`)

Expected: PASS — the new button is a plain `QPushButton` with only `setObjectName`, no `setStyleSheet` or `QColor` literal.

- [ ] **Step 11: Commit**

```bash
git add tools/garage/panels/dialog.py tools/garage/core/dialog_model.py tools/garage/theme/qss.py tests/garage/test_panels_dialog.py
git commit -m "feat(garage): reload the dialog panel after an editor round trip

Adds a Reload button next to Open in VS Code and Save that re-reads
npcs.json/hubs.json, rebuilds the NPC list and node cards, and clears
the clobber refusal #43 added -- the in-panel recovery #43 deliberately
left out of scope.

Fixes #45"
```

---

## Self-Review

**1. Spec coverage.** Issue #45 asks for exactly one thing: "add a Reload action to the dialog panel — re-read both files from disk, rebuild the NPC list and node cards, and clear the refusal — without weakening the refusal itself." Task 1 covers all four clauses: the button exists and is wired (Step 3-4); `reload()` re-reads both files and rebuilds the list/cards by delegating to the existing `refresh()` → `dialog_model.load()` (Step 4, verified against real rebuilds in Step 1's `test_reload_rebuilds_the_list_from_the_new_content` / `test_reload_rebuilds_the_node_cards_too`); the refusal clears because `dialog_model.load()` re-stamps against the current disk state, verified end-to-end by `test_reload_clears_the_outside_edit_refusal` (refusal blocks Save, Reload runs, Save now succeeds); the refusal itself is untouched — `clobber_refusal()` and `dialog_model.save()` are not modified at all, only `clobber_refusal`'s docstring, which Step 9's full core-suite run confirms doesn't change any test's outcome. No gap found.

**2. Placeholder scan.** No "TBD"/"implement later"/"add appropriate handling" language; every step shows the literal code to write, not a description of it. No `pytest` reference (this repo doesn't have it installed, per this repo's `CLAUDE.md`) — commands use `python -m unittest`.

**3. Type consistency.** `reload_button` is a `QPushButton`, named consistently in every step. `reload()` returns `None` everywhere it's referenced. `refresh()`'s signature and behaviour (`-> None`, re-reads via `dialog_model.load`, rebuilds `npc_list`, triggers card rebuild through `currentRowChanged`) is used as-is, matching `tools/garage/panels/dialog.py:391-428` verbatim — no invented method names. `_report(message: str) -> None` matches `tools/garage/panels/dialog.py:511`. `node_cards()[i].node` matches the `NodeCard` attribute used identically in `rebuild_cards()` (`tools/garage/panels/dialog.py:481`) and read back in existing tests (e.g. `test_an_over_long_node_stops_the_editor_and_the_write` reaches `.text_field` the same way `test_reload_rebuilds_the_node_cards_too` reaches `.node`).
