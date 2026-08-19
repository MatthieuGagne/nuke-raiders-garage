# Classify PLAYER_TURN_FRAMES_TABLE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one `structural` entry for `PLAYER_TURN_FRAMES_TABLE` to `tools/garage/tunables.json` so the game repository's new `config.h` drift gate stops blocking every local commit there.

**Architecture:** Data-only change. `tools/garage/tunables.json` is the single source of truth for which `#define`s in the game repo's `src/config.h` Garage may edit; both drift checks (Garage's `tools/garage_lint.py` and the game repo's `tools/garage_drift_lint.py`) treat *any* of the four classes as "classified". Classifying the table `structural` records "Garage does not edit this" and clears both gates, without making it editable. No Garage code changes; the two tests added here pin the classification and the not-editable half so a later edit cannot quietly promote it to `tunable`.

**Tech Stack:** Python 3.13, `unittest` (no pytest installed), `make` targets in the repo root `Makefile`, JSON.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/19 (the issue body is the spec; AC1-AC3 below are quoted from it)

## Global Constraints

- The class assigned MUST NOT be `tunable` (AC1). Use `structural`.
- `tools/garage/tunables.json`'s `_shape` states entries are ordered "in the same order as the header". The new entry goes immediately **after** `PLAYER_HANDLING` and **before** `PLAYER_ARMOR`, matching `src/config.h` where the table is declared at line 38, between `PLAYER_HANDLING` (line 33) and `PLAYER_ARMOR` (line 46).
- `schema._parse_entry` rejects a non-`tunable` entry that declares `category`, `min` or `max`. The new record carries exactly two keys: `class` and `reason`.
- `reason` must be a non-empty string. Keep it ASCII - the surrounding file uses `--` rather than an em dash.
- No file under `tools/garage/core/` or `tests/test_*.py` may import Qt. The tests added here are pure `unittest` and must pass with PySide6 absent.
- No Garage change may touch a file in the game repository (`C:/Code/nuke-raider`). The game repo is read-only for this work.
- `python -m pytest` does not exist in this environment. Run tests with `python -m unittest ...` or `make test`.
- Never read `$LASTEXITCODE` after a piped command - the pipe masks it. Read the printed summary instead.

## Acceptance Criteria (from the issue)

- **AC1.** `tools/garage/tunables.json` classifies `PLAYER_TURN_FRAMES_TABLE`, with a class other than `tunable`.
- **AC2.** Garage's Tuner panel does not offer it for editing (unchanged behaviour, per #18 R6).
- **AC3.** With a Garage checkout beside the game repo, `python tools/garage_drift_lint.py` in the game repo reports OK.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/garage/tunables.json` | Classification of every `#define` in the game repo's `src/config.h`. | **Modify** - one new entry after `PLAYER_HANDLING`. |
| `tests/test_garage_core.py` | Non-Qt coverage of `schema.py` / `config_io.py`. | **Modify** - two new tests in `TestSchemaValidation`. |
| `tests/test_garage_lint.py` | Coverage of the drift check, including two tests that run against the *real* bound header. | **Unchanged** - these two already fail today and go green with the fix; they are the AC3 regression net. |
| `tools/garage/panels/tuner.py` | Builds one row per `schema.tunables()` entry. | **Unchanged** - a `structural` entry is never in `tunables()`, so AC2 holds by construction. The new tests pin that. |

---

### Task 1: Classify PLAYER_TURN_FRAMES_TABLE as structural

**Files:**
- Modify: `tools/garage/tunables.json:76-82` (insert after the `PLAYER_HANDLING` record's closing `},`)
- Modify: `tests/test_garage_core.py:438-441` (add two tests after `test_ac8_max_sprites_not_offered_and_max_racers_is_derived`)

**Interfaces:**
- Consumes: `tools.garage.core.schema.Schema.load(path)`, `.classify(name) -> str`, `.is_tunable(name) -> bool`, `.tunables() -> List[TunableEntry]` (each has `.name`); `tools.garage.core.config_io.parse(text, schema=...) -> ConfigFile` with `.defines: Dict[str, DefineLine]` and `DefineLine.has_value: bool` / `.cls: Optional[str]`; `config_io.apply_changes(config, schema, changes) -> str` raising `config_io.ConfigIOError`. Module-level test constants already defined in `tests/test_garage_core.py`: `REAL_TUNABLES_PATH` (line 361), `REAL_CONFIG_H_PATH` (line 377), `NO_GAME_REPO` (line 378), `NO_GAME_REPO_REASON` (line 379).
- Produces: nothing consumed by a later task - this is the only task.

- [ ] **Step 1: Observe the current failure on both sides**

Run, from the Garage repo root (`C:\Code\nuke-raider-garage`):

```
python -m unittest tests.test_garage_lint -v
```

Expected: `FAILED (failures=2)` - `test_the_classification_matches_the_headers_defines` reporting
`'PLAYER_TURN_FRAMES_TABLE' is in src/config.h and classified nowhere`, and
`test_the_drift_check_script_agrees_with_it` asserting `1 != 0`.

Then, from the game repo (`C:\Code\nuke-raider`):

```
python tools/garage_drift_lint.py
```

Expected: `garage_drift_lint: FAIL -- src/config.h has drifted ahead of Garage's tunables.json`,
naming `PLAYER_TURN_FRAMES_TABLE`.

If either command is already clean, stop: someone has already applied the entry, and this plan is done.

- [ ] **Step 2: Write the two failing tests**

In `tests/test_garage_core.py`, inside `class TestSchemaValidation`, immediately after
`test_ac8_max_sprites_not_offered_and_max_racers_is_derived`, add:

```python
    def test_the_turn_frames_table_is_classified_and_never_offered(self):
        # #19 AC1/AC2: the game repo's config.h drift gate needs this name
        # to carry *some* class, and #18 R6 says it must not be a tunable
        # -- a brace-initialiser table is not a dial the Tuner can edit.
        schema = Schema.load(REAL_TUNABLES_PATH)
        self.assertEqual(schema.classify("PLAYER_TURN_FRAMES_TABLE"), "structural")
        self.assertFalse(schema.is_tunable("PLAYER_TURN_FRAMES_TABLE"))
        offered = [entry.name for entry in schema.tunables()]
        self.assertNotIn("PLAYER_TURN_FRAMES_TABLE", offered)

    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_the_turn_frames_table_carries_no_writable_value(self):
        # The Tuner builds a row only from schema.tunables(), and skips any
        # entry whose #define has no parseable value; config_io refuses the
        # write outright. Both halves are asserted here so a later edit
        # cannot make the table editable by accident.
        text = REAL_CONFIG_H_PATH.read_text(encoding="utf-8")
        schema = Schema.load(REAL_TUNABLES_PATH)
        config = config_io.parse(text, schema=schema)

        define = config.defines["PLAYER_TURN_FRAMES_TABLE"]
        self.assertEqual(define.cls, "structural")
        self.assertFalse(define.has_value)

        with self.assertRaises(config_io.ConfigIOError) as ctx:
            config_io.apply_changes(config, schema, {"PLAYER_TURN_FRAMES_TABLE": 4})
        self.assertIn("PLAYER_TURN_FRAMES_TABLE", str(ctx.exception))
```

- [ ] **Step 3: Run the new tests to verify they fail**

```
python -m unittest tests.test_garage_core.TestSchemaValidation -v
```

Expected: both new tests FAIL.
`test_the_turn_frames_table_is_classified_and_never_offered` raises
`SchemaError: 'PLAYER_TURN_FRAMES_TABLE' is not classified in tunables.json`;
`test_the_turn_frames_table_carries_no_writable_value` fails on
`self.assertEqual(define.cls, "structural")` with `None != 'structural'`.
The pre-existing tests in that class must still pass.

- [ ] **Step 4: Add the classification entry**

In `tools/garage/tunables.json`, insert the new record between the `PLAYER_HANDLING`
record and the `PLAYER_ARMOR` record, so the file reads:

```json
    "PLAYER_HANDLING": {
      "class": "tunable",
      "category": "Player Stats",
      "min": 0,
      "max": 10,
      "reason": "Block comment explicitly labels this a 'tunable placeholder'; its own comment says the turning system is 'not yet implemented', so no code currently reads it for anything -- there is no correctness dependency to break. Range mirrors the small integer scale of sibling player-stat placeholders."
    },
    "PLAYER_TURN_FRAMES_TABLE": {
      "class": "structural",
      "reason": "A brace-initialiser table of per-handling-level turn durations, indexed by PLAYER_HANDLING (game repo #628 / PR #644). Not a scalar dial -- Garage does not edit it; see nuke-raiders-garage#18 R6. Classified so the game repo's config.h drift gate (gmb-nuke-raider#612 R4) can tell 'deliberately not tunable' from 'not yet looked at'."
    },
    "PLAYER_ARMOR": {
```

Two keys only, `class` and `reason` - `schema._parse_entry` rejects a `structural` record
that also declares `category`, `min` or `max`.

- [ ] **Step 5: Run the new tests to verify they pass**

```
python -m unittest tests.test_garage_core.TestSchemaValidation -v
```

Expected: `OK` - every test in the class passes, none skipped (this checkout has a game repo bound).

- [ ] **Step 6: Run the drift check and its suite**

```
python -m unittest tests.test_garage_lint -v
```

Expected: `OK` (7 tests) - the two tests that were red in Step 1 are now green.

```
make lint
```

Expected: `garage_lint: OK -- every #define in 'C:\Code\nuke-raider\src\config.h' is classified in tunables.json, and every tunables.json entry still exists in the header.`

- [ ] **Step 7: Run the full default suite**

```
make test
```

Expected: `OK`, with no `garage_lint: FAIL` text anywhere in the output.

- [ ] **Step 8: Verify AC2 against the Tuner panel itself**

The panel suite takes about six minutes in full, so run only the Tuner classes:

```
python -m unittest tests.garage.test_panels.TestTunerPanel tests.garage.test_panels.TestTunerPanelRevert -v
```

Expected: `OK`, unchanged from before the edit. This is a no-regression check, not new coverage -
`_build_rows` (`tools/garage/panels/tuner.py:339`) iterates `schema.tunables()`, which a
`structural` entry never enters.

If PySide6 is unavailable in the current interpreter, record that this step could not run and say so
in the final report; do not claim AC2 verified from the core tests alone.

- [ ] **Step 9: Verify AC3 in the game repository**

From `C:\Code\nuke-raider` (read-only - change nothing there):

```
python tools/garage_drift_lint.py
```

Expected: an OK line naming Garage's `tunables.json`, replacing the Step 1 FAIL.

- [ ] **Step 10: Commit**

```bash
git add tools/garage/tunables.json tests/test_garage_core.py
git commit -m "fix: classify PLAYER_TURN_FRAMES_TABLE as structural (#19)"
```

Commit in the **Garage** repo only. Nothing in the game repo changes.

---

## Out of scope - one finding to report, not to fix here

While confirming the header, a separate defect surfaced that #19's ACs do not cover:

`src/config.h:40-42` in the game repo now guards `PLAYER_HANDLING` with
`#if (PLAYER_HANDLING) < 0 || (PLAYER_HANDLING) > 7` / `#error`, and `src/player.c:368`
indexes the 8-entry table with it. Garage's entry for `PLAYER_HANDLING` still declares
`"min": 0, "max": 10`. The Tuner will therefore happily persist 8, 9 or 10, and the game
repo then fails to compile on the `#error`. The entry's `reason` is also now stale - it says
"no code currently reads it for anything", which #628 made untrue.

This is a real bug, but fixing it changes a `tunable`'s clamp, which is a different decision
from #19's "give the table a class". Report it and offer to open a follow-up issue
(`max` 10 -> 7, plus a refreshed `reason`); do not fold it into the Task 1 commit.
