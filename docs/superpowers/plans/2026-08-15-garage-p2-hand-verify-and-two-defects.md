# Garage P2 — Hand-Verification and the Two Parked Defects — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two defects the P2 merge gate parked in `tools/garage/panels/assets.py`, then walk the eight acceptance criteria that only a running window and a real Windows file association can prove.

**Architecture:** Two contained changes to one file, each with panel tests, followed by a human pass over the real application. Defect 1 makes the card the single owner of its Convert button's enabled state, so a poll tick that re-verifies a card mid-run can no longer undo the disable the run applied. Defect 2 splits one baseline into two — `_stamps` answers "changed since Garage last watched it?" and drives the sticky CHANGED mark; a new `_verified` dict answers "changed since Garage last decoded it?" and gates the re-verify — and caches the parsed Makefile rules on the panel so a re-plan stops re-reading the game repository's Makefile. Nothing under `tools/garage/core/` changes; no new module appears.

**Tech Stack:** Python 3.13, PySide6 (panel + panel tests), `unittest`. The hand-verification runs `garage.bat` against the real game repository at `C:\Code\nuke-raider`.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/9 (Garage P2 — hand-verify the asset panel, and close two defects the merge gate parked). Implements the remainder of https://github.com/MatthieuGagne/nuke-raiders-garage/issues/3, whose code landed on `main` at `e4615ec`; that spec's plan is `docs/superpowers/plans/2026-08-12-garage-p2-assets.md`.

---

## Global Constraints

These apply to every task below. They are not repeated per task.

- **No Qt import anywhere under `tools/garage/core/`** (R12). Neither task changes a file there; if you find yourself editing `core/assets.py` or `core/pipeline.py`, stop — the fix is in the panel.
- **No hardcoded filesystem path** in product code *or* in a test (R13). Everything resolves through `tools/garage/core/project.py`. `DEFAULT_EMULICIOUS_JAR` is the tree's only absolute path and predates this work; do not add a second.
- **No colour literal and no font literal outside `tools/garage/theme/`** (P1 R18/AC18).
- **Garage never changes a file the game repository tracks as a checked-in change.** Running a converter writes generated files at runtime in a checkout Garage does not own — that is the product working. Task 3 deliberately edits two game-repository files by hand to force a failure, and reverts each with `git checkout --` in the same step. Nothing in this repository's tree may reference a game-repository file.
- **The default test target must pass with PySide6 absent** (AC12). Both new test classes go in `tests/garage/test_panels_assets.py`, which default discovery never reaches (`tests/garage/` has no `__init__.py`). Do not add a PySide6 import to anything under `tests/` directly.
- **Tests that need a real game repository skip, never fail, when none is bound.** Both new classes inherit `AssetsPanelTestCase`, which is already guarded by the module's `@unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)` on its fixture path — follow the existing classes, add no new skip logic.
- **Both suites and the lint must be green at the end of every task:** `make test` (289 tests at `e4615ec`, growing only if you add core tests — you should not), `make test-garage` (203 at `e4615ec`, +7 by the end of Task 2), `python tools/garage_lint.py`.
- **Commit after each task**, with the exact `git commit` command each task's last step gives. Do not push.

---

## Setup

- [ ] **Branch off `main` before Task 1.**

```bash
git -C C:/Code/nuke-raider-garage switch -c fix/garage-p2-defects
```

The tree is clean at `e4615ec`. If you prefer an isolated workspace, create it with the `superpowers:using-git-worktrees` skill instead — but note Task 3 must run `garage.bat` from a checkout whose `garage.local.json` binds `C:/Code/nuke-raider`, and that file is gitignored, so a fresh worktree needs one written by hand before the hand-verification can run.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/garage/panels/assets.py` | The Qt panel. `AssetCard` owns one card's widgets and the state that decides what its buttons offer; `AssetsPanel` owns the grid, the baselines, the cached Makefile rules, the converter run and the poll. | Modify — `AssetCard.__init__`, `AssetCard._apply_verdict`, new `AssetCard.set_busy`, `AssetsPanel.__init__`, `AssetsPanel.refresh`, `AssetsPanel.check_for_changes`, `AssetsPanel._set_busy`. |
| `tests/garage/test_panels_assets.py` | Panel coverage, run by `make test-garage`. | Modify — two new classes, `TestBusyDuringARun` (4 tests) and `TestVerificationBaseline` (3 tests). |

No file is created and no file is deleted. `tools/garage/core/assets.py`, `tools/garage/core/pipeline.py` and `tests/test_garage_assets.py` are untouched.

---

## Task 1: A run in flight owns every Convert button

**The defect (issue #9, defect 1).** `AssetCard.apply_verification` ends in `_apply_verdict`, whose last act is `convert_button.setEnabled(self.plan.can_run)`. It knows nothing about a run in flight, and `AssetsPanel._set_busy(True)` is what disabled every Convert button when the run started. A poll tick that re-verifies a card mid-run therefore puts that card's button back. It cannot cause a second run — `convert()` checks `self._runs.is_running()` and refuses — so the visible effect is a button that looks live for up to two seconds and answers by writing "A converter is already running" instead of starting.

**The fix.** Two mechanisms disagree because two places decide the same thing. Move the busy state onto the card, beside `_changed`, and let `_apply_verdict` — the one method that decides whether Convert is enabled — read it. Every route into that method then agrees by construction: the card being built, a poll re-verifying it, `convert()` re-verifying it, and `set_busy` itself.

**Files:**
- Modify: `tools/garage/panels/assets.py:177-331` (`AssetCard.__init__`, `_apply_verdict`, new `set_busy`), `:424-503` (`AssetsPanel.refresh`), `:670-673` (`AssetsPanel._set_busy`)
- Test: `tests/garage/test_panels_assets.py` (new class after `TestConvert`, which ends at line 563)

**Interfaces:**
- Consumes: `_FakeRuns(panel)` and `_Result(ok, exit_code)`, already defined at `tests/garage/test_panels_assets.py:421-468`; `AssetsPanelTestCase.card_for(relative) -> AssetCard`; `write_indexed_png(path, width, height, palette_size, pixels=None) -> Path`.
- Produces:
  - `AssetCard.set_busy(busy: bool) -> None` — a converter is running somewhere in the panel; this card offers neither action while it is.
  - `AssetCard._busy: bool` — read by `_apply_verdict`. Task 2 does not touch it.
  - `AssetsPanel._set_busy(busy: bool) -> None` — unchanged signature, new body: it forwards to each card instead of setting buttons itself.

- [ ] **Step 1: Write the failing tests**

Insert this class into `tests/garage/test_panels_assets.py` immediately after `TestConvert` (that is, before `class TestConvertEchoesOnlyCommandsThatRan`):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_assets.py' -k TestBusyDuringARun -v`

Expected: 3 failures, 1 pass. The three failures are `test_a_poll_during_a_run_leaves_every_convert_button_disabled`, `test_a_refused_second_convert_leaves_the_button_disabled` and `test_a_grid_rebuilt_during_a_run_offers_no_action`, each `AssertionError: True is not false` on a `convert_button.isEnabled()` line. `test_the_actions_come_back_when_the_run_finishes` passes already — it pins the behaviour the fix must not break, and if it ever fails you have disabled something permanently.

If a failure reads `AssertionError: False is not true` on `other.is_changed()` instead, the poll did not see your write: check that `write_indexed_png` targeted `other.asset.path` and not the running card's.

- [ ] **Step 3: Give the card the busy state**

In `tools/garage/panels/assets.py`, in `AssetCard.__init__`, after `self._changed = False`:

```python
        self._changed = False
        self._busy = False
```

Replace the last four lines of `AssetCard._apply_verdict` (currently `self.convert_button.setEnabled(self.plan.can_run)` and the `setToolTip` call that follows it) with:

```python
        # `and not self._busy`: this method is the single place that
        # decides whether Convert is offered, and it is reached from four
        # directions -- the card being built, a poll re-verifying it,
        # `convert()` re-verifying it, and `set_busy` below. Reading the
        # busy state here is what stops any of the first three from
        # re-enabling a button a run in flight disabled (issue #9,
        # defect 1). Before this, `_set_busy` and `_apply_verdict` both
        # wrote that button's enabled state and disagreed about it.
        self.convert_button.setEnabled(self.plan.can_run and not self._busy)
        if self._busy:
            tooltip = (
                "A converter is running. This is offered again when it "
                "finishes."
            )
        else:
            tooltip = "" if self.plan.can_run else (self.plan.refusal or "")
        self.convert_button.setToolTip(tooltip)
```

Add this method to `AssetCard`, immediately after `set_changed`:

```python
    def set_busy(self, busy: bool) -> None:
        """A converter is running somewhere in the panel (or has just
        stopped). While one is, this card offers neither action: two runs
        at once would interleave two tools' output in one log and race
        over the same generated file, and Open is withheld with it so the
        user is not editing an asset a converter is mid-way through
        reading.

        The state is remembered rather than applied straight to the
        buttons, because a card recomputes its own Convert button every
        time it is re-verified -- see `_apply_verdict`.
        """
        if busy == self._busy:
            return
        self._busy = busy
        self.open_button.setEnabled(not busy)
        self._apply_verdict()
```

- [ ] **Step 4: Make the panel push the state into the cards**

In `AssetsPanel`, replace `_set_busy` entirely:

```python
    def _set_busy(self, busy: bool) -> None:
        """Every card learns that a run started or finished.

        Pushed into the cards rather than applied to their buttons from
        here: a card that is re-verified while a run is in flight redraws
        its own Convert button, and this loop cannot reach forward in time
        to stop it (issue #9, defect 1). `AssetCard.set_busy` is where the
        two facts -- "a run is in flight" and "this asset's plan can run"
        -- are combined, in one place.
        """
        for card in self._cards:
            card.set_busy(busy)
```

In `AssetsPanel.refresh`, immediately after the loop that re-applies the changed marks (`for card in self._cards: if card.asset.relative_path in self._changed_paths: card.set_changed(True)`) and before the `self._generated = ...` assignment, add:

```python
        # A rebuilt card is a fresh widget that knows nothing of a run in
        # flight. Closing the Assets dialog only hides it -- the panel, its
        # poll and any converter thread it started keep running underneath
        # -- and `open_assets()` in app.py calls `refresh()` unconditionally
        # every time the dialog is reopened, so this rebuild can land
        # squarely in the middle of a run the user started before closing
        # it.
        self._set_busy(self._runs.is_running())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_assets.py' -k TestBusyDuringARun -v`
Expected: `Ran 4 tests ... OK`

- [ ] **Step 6: Run both suites and the lint**

Run:
```bash
make test-garage
make test
python tools/garage_lint.py
```
Expected: `make test-garage` reports `Ran 207 tests ... OK` (203 + 4); `make test` reports 289 tests with 0 failures and 0 errors (its skip count depends on whether a game repository is bound); the lint prints its report and exits 0.

If `make test-garage` reports a failure in `TestConvert.test_a_second_run_while_one_is_in_flight_is_refused` or in `TestGeneratedFilesAreReadOnly`, you have disabled a button that should still be live — re-read `_apply_verdict`'s early `return` in the failed-verification branch, which must keep setting the refusal as its tooltip rather than the busy sentence.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/panels/assets.py tests/garage/test_panels_assets.py
git commit -m "fix: hold Convert disabled for the whole of a converter run

A poll tick that re-verified a card mid-run re-enabled its Convert
button, because _apply_verdict and _set_busy both wrote that button's
enabled state and only one of them knew a run was in flight. The card
now owns the busy state and _apply_verdict reads it, so every route
that redraws a card agrees. Closes defect 1 of issue #9."
```

---

## Task 2: Two baselines, and the Makefile parsed once

**The defect (issue #9, defect 2).** `check_for_changes` deliberately does not re-stamp an asset it has marked CHANGED — the mark has to outlive the tick, and the baseline belongs to the asset rather than to the poll. That is correct and load-bearing. But it means `has_changed` stays true on every subsequent tick, and since the merge-gate fix wave each of those ticks runs a full `verify` (a PNG decode) plus a `plan_for` called without `rules` (a fresh read and parse of the game repository's ~250-line Makefile). Per changed card. Until it is converted. On the GUI thread, every two seconds.

**The fix.** There are two questions and they need two baselines. "Has this changed since Garage last *watched* it?" decides the CHANGED mark, and its baseline (`_stamps`) must not move until a conversion answers it. "Has this changed since Garage last *verified* it?" decides whether a re-verify is needed, and its baseline (`_verified`, new) moves on every verify. Caching the parsed rules on the panel and passing them to `plan_for` removes the Makefile re-read as well.

**Do not** fix this by skipping the re-verify whenever the path is already marked. An asset edited twice would keep the verification from the first edit, which reintroduces the staleness the merge-gate fix wave closed — `TestVerificationBaseline.test_a_second_edit_of_a_marked_asset_is_verified_again` below is the test that catches that shortcut.

**Files:**
- Modify: `tools/garage/panels/assets.py:404-406` (`AssetsPanel.__init__`'s baselines), `:424-503` (`refresh`), `:575-607` (`check_for_changes`)
- Test: `tests/garage/test_panels_assets.py` (new class after `TestChangedOnDisk`, which ends at line 739)

**Interfaces:**
- Consumes: `assets_core.Stamp(exists, size_bytes, mtime_ns)`, `assets_core.stamp(path) -> Stamp`, `assets_core.has_changed(before, after) -> bool`, `pipeline.Rule`, `pipeline.read_rules(binding) -> List[Rule]`, `pipeline.plan_for(binding, asset, verification, rules=None) -> Plan` — all unchanged, all already imported by the panel. Note `plan_for`'s fourth argument: `None` means "read the rules yourself", and `[]` means "a Makefile with no rules at all". They are not the same and the difference is load-bearing (see `refresh`'s existing comment).
- Produces:
  - `AssetsPanel._verified: Dict[str, assets_core.Stamp]` — what each listed asset looked like when Garage last verified it. Task 1's `set_busy` does not interact with it.
  - `AssetsPanel._rules: Optional[List[pipeline.Rule]]` — the active worktree's rules, parsed once per `refresh`. `None` means they could not be read.

- [ ] **Step 1: Write the failing tests**

Insert this class into `tests/garage/test_panels_assets.py` immediately after `TestChangedOnDisk` (that is, before `class TestGeneratedFilesAreReadOnly`):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_assets.py' -k TestVerificationBaseline -v`

Expected: 2 failures, 1 pass.
- `test_a_marked_asset_is_not_re_verified_on_every_tick` — `AssertionError: 2 != 0`, one `verify` per tick.
- `test_a_re_plan_uses_the_rules_the_panel_already_parsed` — `AssertionError: 1 != 0`, `plan_for` re-read the Makefile.
- `test_a_second_edit_of_a_marked_asset_is_verified_again` passes already. It is the guard that constrains the fix, not a driver of it — keep it, and if it fails after Step 3 you took the shortcut the class docstring warns against.

- [ ] **Step 3: Add the second baseline and the rules cache**

In `AssetsPanel.__init__`, replace the `_stamps` / `_changed_paths` block (currently preceded by the comment beginning "What each listed asset looked like when Garage last stamped it") with:

```python
        # What each listed asset looked like when Garage last stamped it,
        # and which ones are known to have changed since. Both live on the
        # panel rather than on the cards, because `refresh()` destroys and
        # rebuilds every card. A successful conversion below is what clears
        # a mark.
        self._stamps: Dict[str, assets_core.Stamp] = {}
        self._changed_paths: set = set()
        # A second, independent baseline: what each asset looked like when
        # Garage last *verified* it. The two answer different questions and
        # move at different times. `_stamps` answers "has this changed since
        # Garage last watched it?", which drives the CHANGED mark, and it
        # must not move until a conversion answers the offer. `_verified`
        # answers "has this changed since Garage last decoded it?", which
        # decides whether `check_for_changes` needs to re-verify, and it
        # moves on every verify. One dict cannot do both: a marked asset
        # stays changed against `_stamps` until it is converted, so a single
        # baseline meant re-decoding the PNG and re-parsing the game
        # repository's Makefile on every tick, per marked card, forever
        # (issue #9, defect 2).
        self._verified: Dict[str, assets_core.Stamp] = {}
        # The active worktree's parsed Makefile rules, read once per
        # `refresh()` and handed to `plan_for` rather than letting it read
        # the file itself. `None` means they could not be read, which
        # `plan_for` treats as "read them yourself" -- that branch is what
        # reproduces the PipelineError as each card's refusal, so `None` and
        # `[]` are not interchangeable here.
        self._rules: Optional[List[pipeline.Rule]] = None
```

- [ ] **Step 4: Fill both from `refresh`**

In `AssetsPanel.refresh`, immediately after `self._cards = []`:

```python
        self._cards = []
        # Both describe the cards this method is about to build, so both
        # are rebuilt from scratch: an entry for a file that has since
        # vanished should not survive. `_stamps` and `_changed_paths` are
        # deliberately *not* reset -- see the `setdefault` below.
        self._verified = {}
        self._rules = None
```

Then, in the `try` / `except pipeline.PipelineError` block that assigns `rules`, add one line after the block (keeping the existing comment about `None` versus `[]` where it is):

```python
        self._rules = rules
```

Then, in the `for asset in found:` loop, add the stamp as its first statement:

```python
        for asset in found:
            # Stamped *before* verifying, not after: if the file changes
            # while this loop runs, the older stamp is what makes the next
            # poll re-verify it, instead of trusting a verification of a
            # file that has already moved on.
            self._verified[asset.relative_path] = assets_core.stamp(asset.path)
            verification = assets_core.verify(self.binding, asset)
```

The rest of that loop is unchanged.

- [ ] **Step 5: Gate the re-verify on the second baseline**

Replace the body of `AssetsPanel.check_for_changes` (keep the method's existing docstring and append the new paragraph below to it):

```python
        A card whose file changed is re-verified and re-planned here, not
        only re-stamped: without that, a card would keep showing OK (or a
        problem the edit already fixed) about a file that is not the file
        it was built from, and a Reconvert pressed from it would run
        against a verdict the edit had already made false. Updated in
        place through `AssetCard.apply_verification` rather than by calling
        `refresh()`, which destroys and rebuilds every card -- a rebuild
        while a converter is running would delete the very widget the run
        reports its result to.

        That re-verify is gated on `_verified`, not on `_stamps`. The mark
        is sticky by design, so `_stamps` goes on reporting a change every
        tick until a conversion answers it; gating the decode on the same
        baseline meant re-decoding the file and re-parsing the Makefile
        every two seconds, forever, for each marked card. `_verified`
        moves on every verify, which collapses that to once per edit.
        Do not replace it with "skip whenever the path is already marked":
        an asset edited twice would keep the verification from the first
        edit.
        """
        for card in self._cards:
            relative = card.asset.relative_path
            before = self._stamps.get(relative)
            after = assets_core.stamp(card.asset.path)
            if before is None:
                # Defensive: `refresh()` stamps every card it builds, so a
                # listed asset always has a baseline by the time the timer
                # fires. A missing one would otherwise reach `has_changed`
                # as None. `_verified` is deliberately left alone -- this
                # card has not been verified against this state, and the
                # next tick that sees a change should say so.
                self._stamps[relative] = after
                continue
            if not assets_core.has_changed(before, after):
                continue
            # Remembered on the panel, not only on the card: the card is
            # thrown away and rebuilt by every `refresh()`.
            self._changed_paths.add(relative)
            verified = self._verified.get(relative)
            if verified is None or assets_core.has_changed(verified, after):
                verification = assets_core.verify(self.binding, card.asset)
                plan = pipeline.plan_for(
                    self.binding, card.asset, verification, self._rules
                )
                card.apply_verification(verification, plan)
                self._verified[relative] = after
            card.set_changed(True)
```

Note what is *not* changed: `convert()` still calls `plan_for` with no rules, and should. It runs once per button press, and re-reading the Makefile at that moment is the stronger guarantee — it is the third of R5's three independent refusals, and its whole job is to decide against what is on disk right now.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests/garage -p 'test_panels_assets.py' -k TestVerificationBaseline -v`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 7: Run both suites and the lint**

Run:
```bash
make test-garage
make test
python tools/garage_lint.py
```
Expected: `make test-garage` reports `Ran 210 tests ... OK` (203 + Task 1's 4 + this task's 3); `make test` reports 289 tests, 0 failures, 0 errors; the lint exits 0.

Two existing tests are the ones most likely to catch a mistake here, and both must stay green:
- `TestChangedOnDisk.test_a_refresh_does_not_re_baseline_an_unconverted_asset` — if you reset `_stamps` alongside `_verified` in Step 4, this fails.
- `TestChangedOnDisk.test_a_change_that_breaks_verification_updates_the_verdict` — if `_verified` is seeded *after* the verify rather than before it, or seeded in the `before is None` branch, this can start passing for the wrong reason; it should pass on the first tick after the edit, as it does today.

- [ ] **Step 8: Commit**

```bash
git add tools/garage/panels/assets.py tests/garage/test_panels_assets.py
git commit -m "fix: re-verify a changed asset once per edit, not once per tick

The CHANGED mark is sticky by design, so a marked asset stays changed
against _stamps until a conversion answers it -- and the re-verify was
gated on that same baseline, decoding the PNG and re-parsing the game
repository's Makefile every two seconds on the GUI thread. The verify
now has a baseline of its own, and the parsed rules are cached on the
panel. Closes defect 2 of issue #9."
```

---

## Task 3: Hand-verify the eight acceptance criteria a headless suite cannot reach

**This task cannot be executed by an agent.** It needs a real screen, a real Windows file association and a human judging whether something reads correctly. An agent's job here is to prepare the run, hand the user the checklist one item at a time, record what they report, and file whatever it turns up. Do not mark an item done on the strength of a test that already passes — the suite proving the number is exactly why these items are still open.

**Files:**
- Modify: none in this repository.
- Touch and revert, in the game repository at `C:\Code\nuke-raider`: `assets/maps/track.tmx` (Check 5), `src/player_sprite.c` (rewritten by Check 4, expected to come back byte-identical).

**Interfaces:**
- Consumes: `garage.bat` at the repository root, and `garage.local.json`, which must bind `game_repo` to `C:/Code/nuke-raider`. The fixes from Tasks 1 and 2 must be committed first — several checks below exercise the code they changed.

- [ ] **Step 1: Record the starting state of the game repository**

Run:
```bash
git -C C:/Code/nuke-raider status --short
git -C C:/Code/nuke-raider log --oneline -1
(Get-ChildItem -Recurse -File C:/Code/nuke-raider/assets).Count
```

Expected at the time of writing: one untracked line, `?? assets/sprites/car-2.xcf`; `71d6a0a` as the head commit; `54` files under `assets/`. Write down whatever you actually get — Check 1 compares against this count, and Checks 4 and 5 compare against this `status` output.

If `status` shows tracked modifications you did not make, stop and ask the user before running any conversion: Check 4 rewrites a generated file, and you want to be able to tell your change from theirs.

- [ ] **Step 2: Launch Garage and open the panel**

Run from `C:\Code\nuke-raider-garage`:
```bash
.\garage.bat
```
Then in the window: **View ▸ Assets…**

Expected: a dialog titled for the active worktree, showing a status line, a row of filter chips (All, Sprites, Tiles, Maps, Music, Other), a grid of cards and a log box beneath them. If the panel says no game repository is bound, fix `garage.local.json` before going further.

- [ ] **Step 3: Check 1 — AC1, every file under `assets/` appears in its correct group**

The status line should read `C:\Code\nuke-raider\assets · 54 files · N need attention` — the same 54 Step 1 counted.

Click each chip and count the cards:

| Chip | Expected | The interesting members |
|---|---|---|
| Sprites | 22 | the 11 `.png`, the 9 `.aseprite`, `car-2.xcf`, and `.gitkeep` |
| Tiles | 3 | `assets/maps/tileset.png` and `assets/maps/overmap_tiles.png` — tilesets live beside the maps but belong here — plus `assets/tiles/.gitkeep` |
| Maps | 5 | `overmap.tmx`, `track.tmx`, `track2.tmx`, `track3.tmx`, `track_template.tmx` |
| Music | 2 | `BeepBox-Song.uge` and `BeepBox-Song.mid` |
| Other | 22 | `assets/dialog/hubs.json` and `npcs.json`; the twelve `v*_race*.png` reference screenshots; `overmap.tsx` and `track.tsx`; `create_assets.py`; `nuke-raider.tiled-project`; the two map-side `.aseprite`/`.xcf`; `assets/music/.gitkeep` |

The three groups' worth of `Other` entries are there by design: AC1 asks for *every* file, and dropping the ones the four named kinds do not cover would make the panel a filtered view that quietly disagrees with the directory it claims to list.

Two things to judge rather than assume:
- A `.gitkeep` gets a card. It is a file under `assets/`, so AC1 says it should — but decide whether you agree.
- The three `.gitkeep` files land in *different* groups: the ones under `sprites/` and `tiles/` take their directory's kind, while the one under `music/` falls to Other, because music is decided by suffix and there is no music directory rule. If you judge that wrong, it is a finding — file it, do not fix it here.

- [ ] **Step 4: Check 2 — AC2, a sprite preview reads as the art, in four shades, with a line every 8 pixels**

Find the `player_car.png` card under Sprites. It is 64×16 pixels, so expect an 8×2 grid drawn over it.

Confirm: the thumbnail reads as the car rather than as noise; you can see four distinct shades (the darkest is also the grid line's colour, deliberately — a fifth colour would be a lie about the palette); and the grid rules are evenly spaced, 8 columns by 2 rows.

**A specific thing to look for.** The image is drawn at 4× (256×64) and then scaled down to a 152px card with `Qt.TransformationMode.FastTransformation` — nearest-neighbour on a 0.59× downscale, which can drop 1-pixel grid lines entirely. If some rules are missing or unevenly spaced, that is a real defect in `tools/garage/panels/assets.py:200-203`; record it and file it rather than fixing it in this task.

- [ ] **Step 5: Check 3 — AC3, the tile cost is shown and legible**

On the same `player_car.png` card, read the cost line. It should say `64×16 · 16 tiles`.

Cross-check the number against the converter's own output:
```bash
Select-String player_tile_data_count C:/Code/nuke-raider/src/player_sprite.c
```
Expected: `const uint8_t player_tile_data_count = 16u;`

The number is already proven by a test that runs the real `png_to_tiles.py` as a subprocess. What is unverified is that the card shows it and that it is legible in a 168px-wide card — so judge the legibility, including whether the text wraps or clips.

While you are here, look at the `assets/maps/tileset.png` card: its cost line should carry the rotation note ("base tiles only — this tileset also generates rotated variants…"). Judge whether that reads at card width.

- [ ] **Step 6: Check 4 — AC6, pressing Convert reaches the same path a terminal would**

Record the output file's timestamp first:
```bash
(Get-Item C:/Code/nuke-raider/src/player_sprite.c).LastWriteTime
```

Then press **Convert** on the `player_car.png` card. Expected in the log, in order:
1. `$ make -W assets/sprites/player_car.png src/player_sprite.c`
2. whatever `make` and `png_to_tiles.py` print
3. `player_car.png converted — wrote src/player_sprite.c`

Then, back in the shell:
```bash
(Get-Item C:/Code/nuke-raider/src/player_sprite.c).LastWriteTime
git -C C:/Code/nuke-raider status --short src/player_sprite.c
```

Expected: the timestamp moved (the file really was rewritten) and `status` prints nothing (the bytes are identical to what is checked in — the converter run from the window reproduced the file exactly). A non-empty `status` here means Garage's run produced something different from what the repository holds; capture the diff and stop, because that is either a converter change nobody committed or an AC6 failure.

While the run is in flight, glance at the other cards: every Convert and Open button should be dead for its duration, and live again the moment it finishes. That is Task 1's fix, seen from the outside.

While that same run is still in flight, also close the Assets dialog and reopen it from **View ▸ Assets…**, then let the run finish. This is worth doing here rather than skipping it: it is the one trigger, mid-run dialog close and reopen, that reaches `_running_card` going stale, a known defect the review found and is filing as a follow-up issue rather than fixing in this branch. Expected: the rebuilt grid offers no action on any card, the same as the check above, and when the run completes the log reports the conversion and the `player_car.png` card clears its CHANGED mark, exactly as if the dialog had stayed open. A `RuntimeError` about a deleted C++ object, a run whose completion never appears in the log, or a card left marked CHANGED after a successful conversion are all that defect showing itself. If you see one, note which it was and move on — it is already filed, and this pass is for confirming what is known, not for chasing it further.

- [ ] **Step 7: Check 5 — AC7, a converter error appears with the converter's own message**

This needs a failure Garage's pre-flight cannot predict, so a five-colour sprite will not do — that is refused before the converter runs, which is AC5.

Open `C:\Code\nuke-raider\assets\maps\track.tmx` in a text editor. On line 8, change `<data encoding="csv">` to `<data encoding="base64">` and save. Garage checks a `.tmx` for well-formed XML and a map size; the encoding attribute is invisible to it, and `tmx_to_c.py` rejects it outright.

Within two seconds the `track.tmx` card should turn CHANGED and its button should read Reconvert. Press it.

Expected in the log: the converter's own sentence, `ValueError: Only CSV encoding supported, got: base64` (with the traceback around it), a `make: *** [src/track_map.c] Error 1` line, and then Garage's own `track.tmx — the converter failed (exit 2). The message above is the converter's own.` The exit code may differ; the converter's sentence must not.

Revert immediately:
```bash
git -C C:/Code/nuke-raider checkout -- assets/maps/track.tmx
```

The revert is itself a change on disk, so the card will go CHANGED again — expected, not a defect. Press Convert once more to put the worktree and the card back in agreement, then confirm `git -C C:/Code/nuke-raider status --short` matches what Step 1 recorded.

- [ ] **Step 8: Check 6 — AC8, opening an asset starts the associated application**

Press **Open** on the `player_car.png` card.

Expected: whatever application Windows associates with `.png` starts and shows the sprite, and the log says `Opened player_car.png in the application Windows associates with that file type.` Garage names no editor and holds no setting for one, so this is entirely the Windows association — if the wrong program opens, that is the association, not a defect.

**Do not press Open on a `.gitkeep`, `.aseprite` or `.xcf` card unless you want the "How do you want to open this file?" chooser.** A file type with no association either raises and produces a log line naming the file and suggesting Explorer's *Open with ▸ Choose another app*, or opens that chooser. Both are acceptable; the chooser is a modal dialog, so dismiss it before touching the window again.

- [ ] **Step 9: Check 7 — AC9, the change is noticed, marked, and survives a reopen**

This is the flow with the most machinery behind it and the one to check most carefully. It exercises both of the fixes above.

1. Press **Open** on the `assets/maps/track.tmx` card. If Tiled is installed it opens there; if not, open the file in a text editor by hand — R9 says "changed on disk", not "changed by the editor Garage started".
2. Make a real change and save it (in Tiled: nudge an object and save; in a text editor: add a trailing newline).
3. Return to the Garage window **without touching anything**. Within two seconds the card must turn CHANGED and its button must read Reconvert.
4. Close the dialog and reopen it: **View ▸ Assets…**. The mark must still be there and the button must still read Reconvert. The state deliberately survives a rebuild — a refresh is not the user acknowledging anything.
5. Press **Reconvert**. On success the card returns to OK and the button back to Convert.
6. Revert your edit: `git -C C:/Code/nuke-raider checkout -- assets/maps/track.tmx`, then press Convert once more so the worktree and the card agree again.

If the card marks CHANGED but never comes back to OK after a successful Reconvert, or if the mark disappears when you reopen the dialog, that is an AC9 failure — record exactly which step it broke at.

- [ ] **Step 10: Check 8 — AC11, a `.uge` opens, and both validators run on return**

1. Press **Open** on the `BeepBox-Song.uge` card. If hUGETracker is associated, it opens there. If nothing is associated, note that and skip to (2) — the open half cannot be verified on this machine, and that is a fact about the machine.
2. Press **Reconvert** (or Convert, if you never opened it). Expected in the log, in order: `$ python tools/music_song_validate.py src/music_data.c`, that tool's output, `$ python tools/music_wire_check.py .`, that tool's output, then Garage's own success or failure line.

Note the reading this implements, and confirm you agree with it: the validators run when you press Convert, **not** automatically when you come back from the editor. The return from the editor is what marks the file CHANGED; pressing the button is what runs the checks.

- [ ] **Step 11: Close Garage and confirm the game repository is as you found it**

Close the window (it stops the poll timer and joins the runner thread on the way out — a hang here is a finding worth filing).

Run:
```bash
git -C C:/Code/nuke-raider status --short
```
Expected: exactly what Step 1 recorded. Anything else is a leftover from Check 5 or Check 7 — revert it.

- [ ] **Step 12: Record the outcome on the issue**

Write up each of the eight checks as pass, fail, or not-verifiable-on-this-machine, with the evidence you actually saw (the log lines, the counts, the timestamps). Ask the user before posting — this goes on a public issue.

```bash
gh issue comment 9 --repo MatthieuGagne/nuke-raiders-garage --body-file <your-notes.md>
```

File anything the checks turned up as its own issue on `MatthieuGagne/nuke-raiders-garage`, linked to #9 and added to the board at https://github.com/users/MatthieuGagne/projects/3 — do not fix it inside this task. The one exception is a defect in Task 1's or Task 2's own fix, which belongs back in that task.

- [ ] **Step 13: Close the issue, with the user's go-ahead**

If all eight checks passed and both defects are fixed and committed, #9 is done. Ask the user first, then:

```bash
gh issue close 9 --repo MatthieuGagne/nuke-raiders-garage --comment "Both defects fixed on fix/garage-p2-defects; the eight hand-verified acceptance criteria are recorded above."
```

Then use the `superpowers:finishing-a-development-branch` skill to decide how `fix/garage-p2-defects` reaches `main`.

---

## Self-Review

**Spec coverage.** Issue #9 has three parts. "What still needs a human" — AC1, AC2, AC3, AC6, AC7, AC8, AC9, AC11 — is Task 3, Checks 1 through 8, one per criterion, in the issue's own order. "Defect 1 — a Convert button can re-enable itself during a run" is Task 1, including the panel-level-flag option the issue offers and the `check_for_changes` option it calls smaller; the plan takes a third route that subsumes both (the state on the card, read by the one method that decides the button), because the issue's smaller option fixes only the poll door and leaves `convert()`'s. "Defect 2 — an unconverted asset is re-verified every two seconds, forever" is Task 2, taking the issue's prescribed fix (two baselines) and its prescribed rules cache, with the issue's explicit warning against the "skip if already marked" shortcut turned into `test_a_second_edit_of_a_marked_asset_is_verified_again`. The section "What is already proven, so it need not be re-derived" is honoured by not re-deriving any of it: no task re-checks the Qt-free boundary, AC12's clean-clone probe, the hardcoded-path scan, R10's derived read-only set or R5's three refusals.

**Placeholders.** None. Every code step carries the code; every run step carries the command and the expected output; every hand-verification step carries what to do, what to expect, and what to do when it does not happen.

**Type consistency.** `set_busy(busy: bool)` is spelled the same on `AssetCard` and in `AssetsPanel._set_busy`'s loop. `_busy` is the card's attribute and is never read from the panel. `_verified` is `Dict[str, assets_core.Stamp]` keyed by `Asset.relative_path`, the same key `_stamps` and `_changed_paths` use. `_rules` is `Optional[List[pipeline.Rule]]` and is passed as `plan_for`'s fourth positional argument, whose existing default is `None` with the same meaning. Task 1 and Task 2 touch `refresh()` and `_apply_verdict` in different places and do not collide; if you execute them out of order, Task 2's `refresh()` insertion point (after `self._cards = []`) is above Task 1's (after the changed-marks loop).
