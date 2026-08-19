# Tunable Range Guard Drift Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach Garage's drift check to read the `#if (NAME) < min || (NAME) > max` range guards in the bound game repository's `src/config.h` and fail when a guard disagrees with that tunable's `min`/`max` in `tools/garage/tunables.json`.

**Architecture:** Three layers, matching the split the existing name-drift check already uses. `config_io.py` parses C, so it learns to recognize the guard `#if` and records one `GuardRange` per guarded `#define` on the `ConfigFile` it already returns. `schema.py` classifies and compares but never parses C, so it gains `find_range_drift(schema, guards)` returning a `RangeDriftReport` — the mirror of `find_drift`. The two consumers of `find_drift` (`tools/garage_lint.py`, the blocking gate; `doctor.check_classification`, the startup report) each call the new comparison alongside the old one. No UI change: the Tuner already builds its spin-box range from `schema.tunable(name)`, so a corrected `tunables.json` is all it needs.

**Tech Stack:** Python 3.13 stdlib only (`re`, `dataclasses`, `pathlib`, `unittest`). No pytest in this environment. `make test` / `make lint` in the repo-root `Makefile`; GitHub Actions workflows `.github/workflows/test.yml` (default suite + drift check, Windows + Linux, no PySide6) and `test-garage.yml` (Qt panels).

**Spec:** https://github.com/MatthieuGagne/nuke-raider-garage/issues/18 — "PRD: Fix PLAYER_HANDLING's tunable range and add a guard/tunables.json drift check". R1–R6 and AC1–AC4 below are quoted from that issue body.

## Global Constraints

- **No file in the game repository may be changed.** `C:/Code/nuke-raider` is read-only for this work — Garage never edits the game repo. The `#if` guard at `src/config.h:40` is the input, not the deliverable.
- **No Qt import** in anything under `tools/garage/core/`, in `tools/garage_lint.py`, or in `tests/test_*.py`. The default suite (`make test`) must pass with PySide6 absent — that is what the `test.yml` workflow proves.
- **Every new test must pass with no game repository bound.** CI checks this repository out alone. A test that reads the real `src/config.h` must `skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)` (in `tests/test_garage_core.py`) or `self.skipTest(...)` after catching `project.BindingError` (in `tests/test_garage_lint.py`), exactly like the existing ones.
- **R4: silence, not a flag.** A tunable with no matching `#if` guard is skipped — not reported, not an error, not "unverified". Today that is every tunable except `PLAYER_HANDLING`.
- **R6: no table/array `#define` support.** `PLAYER_TURN_FRAMES_TABLE` stays `structural` and unrepresented. Nothing in this plan touches it.
- **ASCII only in `tools/garage/tunables.json`** — the file uses `--`, never an em dash. `tools/garage/core/doctor.py` already contains `·` and `—` in existing strings; reproduce those characters exactly when editing near them.
- Run tests with `python -m unittest ...` or `make test`. `python -m pytest` does not exist here.
- Never read `$LASTEXITCODE` after a piped command — the pipe masks it. Run the command bare and read the printed summary.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Reference `(#18)` in the subject.
- Work on a branch, not `main`. Suggested: `feat/tunable-range-guard-drift-check`.

## Acceptance Criteria (from the issue)

- **AC1.** `tunables.json`'s `PLAYER_HANDLING` entry has `max: 7` and reason text that no longer claims the value is unread.
- **AC2.** A new test/lint pass fails if `PLAYER_HANDLING`'s range in `tunables.json` disagrees with the `#if` guard in a bound game repo's `config.h`.
- **AC3.** The same check passes for every other current tunable (all guard-less) without modification, proving R4.
- **AC4.** The check is red on an intentionally-mismatched range and green once corrected — the flip test, not just the passing case.

## Prerequisite: AC1 is already satisfied — verify, do not redo

Commit `483f3d1` ("fix: clamp PLAYER_HANDLING to 0-7 …(#21)") already applied R1 and R2. Before starting Task 1, confirm it, from the repo root `C:\Code\nuke-raider-garage`:

```
python -c "import json; e=json.load(open('tools/garage/tunables.json'))['entries']['PLAYER_HANDLING']; print(e['min'], e['max']); print(e['reason'])"
```

Expected: `0 7`, and a reason that mentions `PLAYER_TURN_FRAMES_TABLE` / `gmb-nuke-raider#628` and does **not** contain "no code currently reads it".

```
python -m unittest tests.test_garage_core.TestSchemaClamp -v
```

Expected: PASS, including `test_player_handling_clamps_to_the_headers_error_guard`, which pins `(min, max) == (0, 7)`.

If either check disagrees, fix `tools/garage/tunables.json` first (that is R1/R2) and commit it separately before Task 1. If both agree — the expected case — AC1 needs no change and this plan delivers R3, R4, R5 and AC2–AC4.

Also confirm the guard this whole plan reads actually exists (it landed with the game repo's PR #644):

```
grep -n "PLAYER_HANDLING" C:/Code/nuke-raider/src/config.h
```

Expected: line 33 `#define PLAYER_HANDLING  3` and line 40 `#if (PLAYER_HANDLING) < 0 || (PLAYER_HANDLING) > 7`. If line 40 is absent, the game repo checkout predates PR #644: the code in this plan is still correct and its fixture tests still pass, but the real-binding tests (Task 2 Step 6, Task 3 Step 6) will skip their `PLAYER_HANDLING` assertion — note that in the PR rather than weakening the assertion.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/garage/core/config_io.py` | Parses and writes `src/config.h`. The only module that reads C syntax. | **Modify** — add `GuardRange`, the two guard regexes, `parse_guard_condition()`, and a `guards` dict on `ConfigFile`, filled by `parse()`. |
| `tools/garage/core/schema.py` | Loads/validates `tunables.json`; compares it against the header. Never parses C. | **Modify** — add `RangeMismatch`, `RangeDriftReport`, `find_range_drift()`, beside the existing `DriftReport` / `find_drift()`. |
| `tools/garage_lint.py` | The blocking gate: `make lint`, the `Drift check` CI step, and (via the suite) `make test`. | **Modify** — run the range comparison alongside the name comparison; fail on either. |
| `tools/garage/core/doctor.py` | Startup toolchain report. `check_classification` is the existing drift consumer. | **Modify** — fold the range mismatch into that same check, so the report keeps 9 checks and one `classification` row. |
| `tools/garage/tunables.json` | The classification itself. | **Modify** — one sentence added to `_shape` documenting the new contract. No entry changes (AC1 already landed). |
| `Makefile` | `test` / `test-garage` / `lint` targets. | **Modify** — the `lint` target's comment names what the check now covers. |
| `tests/test_garage_core.py` | Non-Qt coverage of `config_io.py`, `schema.py`, `doctor.py`. | **Modify** — new `TestConfigIOGuards` and `TestFindRangeDrift` classes; two tests added to `TestDoctorClassification`. |
| `tests/test_garage_lint.py` | Coverage of the gate script, fixture-driven plus two real-binding tests. | **Modify** — the AC4 flip test, the AC3 guard-less test, and a real-binding test. |
| `tools/garage/panels/tuner.py` | Builds one spin box per `schema.tunables()` entry, ranged from its `min`/`max`. | **Unchanged** — it already reads the corrected range. |
| `.github/workflows/*.yml` | CI. | **Unchanged** — the `Drift check` step already runs `python tools/garage_lint.py`, and `make test` already runs the suite. R5 is satisfied by wiring into those two, not by adding a workflow. |

---

### Task 1: Parse `#if` range guards out of `src/config.h`

**Files:**
- Modify: `tools/garage/core/config_io.py:44` (after `_DEFINE_NAME_RE`), `:64-77` (`ConfigFile`), `:79-125` (`parse`)
- Test: `tests/test_garage_core.py` (new class `TestConfigIOGuards`, placed immediately after `class TestConfigIOParse` ends at line 662, before `class TestConfigIOApplyChanges` at line 665)

**Interfaces:**
- Consumes: nothing from another task. Existing: `config_io.parse(text, schema=None, path=None) -> ConfigFile`, `dataclasses.dataclass`.
- Produces:
  - `config_io.GuardRange(name: str, min: int, max: int, line_no: int, raw_line: str)` — frozen dataclass.
  - `config_io.parse_guard_condition(condition: str) -> Optional[Tuple[str, int, int]]` — `(name, min, max)` or `None`.
  - `ConfigFile.guards: Dict[str, GuardRange]` — new field, defaults to `{}`, keyed by `#define` name.

- [ ] **Step 1: Write the failing tests**

In `tests/test_garage_core.py`, add this fixture constant immediately after the existing `SAMPLE_TUNABLES_FOR_CONFIG_IO` dict (it ends at line 414, just before `def write_json`):

```python
# The same header, plus the shape #18 R3 is about: a two-sided #if guard
# with an #error, as gmb-nuke-raider PR #644 added for PLAYER_HANDLING.
# GEAR1_MAX_SPEED carries it here so the fixture needs no new #define,
# and PLAYER_ARMOR deliberately carries none -- R4's skipped case.
GUARDED_CONFIG_TEXT = """\
#ifndef CONFIG_H
#define CONFIG_H

#define GEAR1_MAX_SPEED        2u
#define GEAR1_ACCEL            2u

#if (GEAR1_MAX_SPEED) < 1 || (GEAR1_MAX_SPEED) > 15
#error "GEAR1_MAX_SPEED must be 1-15"
#endif

#define PLAYER_ARMOR     5   /* reduces damage */
#define PLAYER_MAX_HP              100u  /* max HP pool */
#define DEBUG_LOG_ADDR    0xDF80U  /* WRAM: ring buffer content (64 bytes) */
#define MAX_SPRITES  32
#define LOADER_BG_START  ((uint8_t)(HUD_FONT_BASE + HUD_FONT_COUNT))

#endif /* CONFIG_H */
"""
```

Then add this class after `TestConfigIOParse` (which ends at line 662):

```python
class TestConfigIOGuards(unittest.TestCase):
    """#18 R3's first half: the header's own `#if ... #error` range guard,
    read off the same parse that reads the #defines.

    Only the two-sided shape is a range guard. Everything else -- the
    include guard, `#if defined(...)`, a one-sided comparison, a guard
    naming two different #defines -- is not one, and R4 asks for silence
    rather than a report, so those cases must leave `guards` empty rather
    than raise or half-record.
    """

    def test_a_two_sided_guard_is_recorded_with_its_range(self):
        config = config_io.parse(GUARDED_CONFIG_TEXT)
        guard = config.guards["GEAR1_MAX_SPEED"]
        self.assertEqual((guard.min, guard.max), (1, 15))
        self.assertEqual(guard.line_no, 7)
        self.assertIn("#if", guard.raw_line)

    def test_an_unguarded_define_has_no_guard(self):
        config = config_io.parse(GUARDED_CONFIG_TEXT)
        self.assertNotIn("PLAYER_ARMOR", config.guards)

    def test_a_header_with_no_guards_at_all_parses_to_an_empty_map(self):
        # The include guard's `#ifndef` must not be mistaken for one.
        config = config_io.parse(SAMPLE_CONFIG_TEXT)
        self.assertEqual(config.guards, {})

    def test_parentheses_are_optional(self):
        self.assertEqual(
            config_io.parse_guard_condition("X < 0 || X > 7"), ("X", 0, 7)
        )

    def test_either_order_of_the_two_halves_is_read(self):
        # The header could just as well be written high-side first; a
        # guard this check silently stops seeing is a check that quietly
        # stops guarding anything (R4 makes an unread guard invisible).
        self.assertEqual(
            config_io.parse_guard_condition("(X) > 7 || (X) < 0"), ("X", 0, 7)
        )

    def test_inclusive_operators_shift_the_bound_by_one(self):
        # `#if X <= -1` fails the build at -1, so the legal minimum is 0.
        self.assertEqual(
            config_io.parse_guard_condition("(X) <= -1 || (X) >= 8"), ("X", 0, 7)
        )

    def test_hex_and_u_suffixed_literals_are_read(self):
        self.assertEqual(
            config_io.parse_guard_condition("(X) < 0x0 || (X) > 0x1F"), ("X", 0, 31)
        )
        self.assertEqual(
            config_io.parse_guard_condition("(X) < 0u || (X) > 7u"), ("X", 0, 7)
        )

    def test_a_trailing_comment_does_not_hide_the_guard(self):
        self.assertEqual(
            config_io.parse_guard_condition("(X) < 0 || (X) > 7 /* 8 entries */"),
            ("X", 0, 7),
        )

    def test_shapes_that_are_not_range_guards_are_not_read(self):
        for condition in (
            "defined(FOO)",
            "(X) < 0",  # one-sided
            "(X) < 0 || (Y) > 7",  # two different names
            "(X) < 0 || (X) < 7",  # two lower bounds
            "(X) < 8 || (X) > 7",  # empty legal range
        ):
            with self.subTest(condition=condition):
                self.assertIsNone(config_io.parse_guard_condition(condition))
```

- [ ] **Step 2: Run the tests to verify they fail**

```
python -m unittest tests.test_garage_core.TestConfigIOGuards -v
```

Expected: every test errors with `AttributeError: module 'tools.garage.core.config_io' has no attribute 'parse_guard_condition'`, and the three `config.guards` tests with `AttributeError: 'ConfigFile' object has no attribute 'guards'`.

- [ ] **Step 3: Write the implementation**

In `tools/garage/core/config_io.py`, change the `dataclasses` import (line 6) from:

```python
from dataclasses import dataclass
```

to:

```python
from dataclasses import dataclass, field
```

and the `typing` import (line 8) from:

```python
from typing import Dict, List, Optional
```

to:

```python
from typing import Dict, List, Optional, Tuple
```

Then, immediately after `_DEFINE_NAME_RE` (line 44), add:

```python
# A two-sided range guard: the `#if` a header uses to fail its own build
# when a #define leaves its legal range, e.g. (src/config.h:40)
#
#   #if (PLAYER_HANDLING) < 0 || (PLAYER_HANDLING) > 7
#   #error "PLAYER_HANDLING must be 0-7 (it indexes ...)"
#   #endif
#
# Recognized with or without parentheses, in either order, with `<`/`<=`
# and `>`/`>=`, and with decimal or hex literals carrying an optional u/U
# suffix. Anything else -- `#if defined(...)`, a one-sided comparison, a
# condition naming two different #defines -- is not a range guard and is
# left unparsed: #18 R4 asks an unrecognized guard to be skipped in
# silence rather than reported.
#
# `#ifdef`/`#ifndef` do not match: the pattern requires whitespace right
# after `if`, so the include guard is never mistaken for a range guard.
_GUARD_IF_RE = re.compile(r"^[ \t]*#[ \t]*if[ \t]+(?P<condition>.+?)[ \t]*$")
_GUARD_HALF_RE = re.compile(
    r"^\(?[ \t]*(?P<name>\w+)[ \t]*\)?[ \t]*"
    r"(?P<op><=?|>=?)[ \t]*"
    r"\(?[ \t]*(?P<literal>-?(?:0[xX][0-9a-fA-F]+|\d+))[uU]?[ \t]*\)?$"
)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/")


@dataclass(frozen=True)
class GuardRange:
    """The legal range a `#if ... #error` guard in config.h permits.

    `min` and `max` are inclusive and already normalized: `#if X <= -1`
    records min 0, because -1 is what the guard rejects.
    """

    name: str
    min: int
    max: int
    line_no: int  # 1-based, the `#if` line
    raw_line: str


def _parse_guard_half(half: str) -> Optional[Tuple[str, str, int]]:
    """`(name, operator, literal)` for one side of the `||`, or None."""
    match = _GUARD_HALF_RE.match(half.strip())
    if match is None:
        return None
    text = match.group("literal")
    base = 16 if "x" in text.lower() else 10
    return match.group("name"), match.group("op"), int(text, base)


def parse_guard_condition(condition: str) -> Optional[Tuple[str, int, int]]:
    """Read `(name, min, max)` out of a two-sided range-guard condition.

    Returns None for anything that is not one -- see `_GUARD_IF_RE`. An
    empty legal range (`X < 8 || X > 7`) is treated as unreadable rather
    than reported: a header that says that is broken in its own right,
    and this check's job is to compare ranges, not to review C.
    """
    condition = _BLOCK_COMMENT_RE.sub(" ", condition).split("//")[0]
    halves = condition.split("||")
    if len(halves) != 2:
        return None

    name: Optional[str] = None
    lower: Optional[int] = None
    upper: Optional[int] = None
    for half in halves:
        parsed = _parse_guard_half(half)
        if parsed is None:
            return None
        half_name, op, value = parsed
        if name is None:
            name = half_name
        elif half_name != name:
            return None
        if op.startswith("<"):
            if lower is not None:
                return None
            # `< L` rejects everything below L, so L is legal; `<= L`
            # rejects L itself, so the first legal value is L + 1.
            lower = value if op == "<" else value + 1
        else:
            if upper is not None:
                return None
            upper = value if op == ">" else value - 1

    if name is None or lower is None or upper is None or lower > upper:
        return None
    return name, lower, upper
```

Then extend `ConfigFile` (line 64) — add the field and one docstring sentence:

```python
@dataclass
class ConfigFile:
    """A parsed `src/config.h`: the exact original lines plus an index of
    every #define found in it. `lines` joined back together always
    reproduces the original text exactly when nothing has changed.

    `guards` indexes the two-sided `#if ... #error` range guards the
    header declares, by the #define name each one constrains. Most
    #defines have none; those simply do not appear (#18 R4).
    """

    path: Path
    lines: List[str]
    defines: Dict[str, DefineLine]
    guards: Dict[str, GuardRange] = field(default_factory=dict)
```

Finally, in `parse()` (line 79), add the `guards` accumulator beside `defines` and recognize the guard line. Replace:

```python
    lines = text.splitlines(keepends=True)
    defines: Dict[str, DefineLine] = {}

    for idx, line in enumerate(lines):
        line_no = idx + 1
        name_match = _DEFINE_NAME_RE.match(line)
        if not name_match:
            continue
```

with:

```python
    lines = text.splitlines(keepends=True)
    defines: Dict[str, DefineLine] = {}
    guards: Dict[str, GuardRange] = {}

    for idx, line in enumerate(lines):
        line_no = idx + 1

        guard_match = _GUARD_IF_RE.match(line.rstrip("\r\n"))
        if guard_match:
            parsed = parse_guard_condition(guard_match.group("condition"))
            if parsed is not None:
                guard_name, low, high = parsed
                # First guard wins. A header with two guards over one name
                # is already contradicting itself; the first is the one the
                # preprocessor reaches first, so it is the one reported.
                guards.setdefault(
                    guard_name,
                    GuardRange(
                        name=guard_name,
                        min=low,
                        max=high,
                        line_no=line_no,
                        raw_line=line,
                    ),
                )
            continue

        name_match = _DEFINE_NAME_RE.match(line)
        if not name_match:
            continue
```

and the return at line 125:

```python
    return ConfigFile(path=path, lines=lines, defines=defines, guards=guards)
```

- [ ] **Step 4: Run the tests to verify they pass**

```
python -m unittest tests.test_garage_core.TestConfigIOGuards -v
```

Expected: `OK`, 9 tests.

- [ ] **Step 5: Run the whole default suite — `parse()` is on every read path**

```
python -m unittest discover -s tests -p "test_*.py"
```

Expected: `OK` (some tests skipped only if no game repository is bound). The byte-identical round-trip test `test_zero_change_write_is_byte_identical_against_real_config_h` is the one that matters here: `parse()` now `continue`s on a `#if` line, and the guard branch must not touch `lines`.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/config_io.py tests/test_garage_core.py
git commit -m "$(cat <<'EOF'
feat: parse #if range guards out of src/config.h (#18 R3)

config_io is the only module that reads C syntax, so the guard the game
repo's PR #644 added for PLAYER_HANDLING is read on the same parse that
reads the #defines, and recorded as a GuardRange per guarded name.

Only the two-sided shape counts. An unrecognized #if -- one-sided, two
names, defined(...) -- records nothing rather than raising: R4 asks a
guard-less tunable to be skipped in silence, and an unreadable guard is
the same case from this layer's point of view.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Compare a guard against `tunables.json`'s declared range

**Files:**
- Modify: `tools/garage/core/schema.py:232-243` (append after `find_drift`)
- Test: `tests/test_garage_core.py` (new class `TestFindRangeDrift`, placed immediately after the new `TestConfigIOGuards` class from Task 1)

**Interfaces:**
- Consumes: `config_io.parse(text) -> ConfigFile` with `.guards: Dict[str, GuardRange]` and `GuardRange.min/.max/.line_no` (Task 1); existing `Schema.load(path)`, `Schema.tunables() -> List[TunableEntry]` where `TunableEntry` has `.name`, `.min`, `.max`.
- Produces:
  - `schema.RangeMismatch(name, schema_min, schema_max, guard_min, guard_max, line_no)` — frozen dataclass with `.describe() -> str`.
  - `schema.RangeDriftReport(mismatches: List[RangeMismatch], checked: List[str])` with `.clean: bool` and `.summary() -> str`.
  - `schema.find_range_drift(schema, guards) -> RangeDriftReport` — `guards` is any mapping from name to an object carrying `min`, `max`, `line_no`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_garage_core.py`, extend the schema import at line 34 from:

```python
from tools.garage.core.schema import Schema, SchemaError  # noqa: E402
```

to:

```python
from tools.garage.core.schema import (  # noqa: E402
    Schema,
    SchemaError,
    find_range_drift,
)
```

Then add this class right after `TestConfigIOGuards`:

```python
class TestFindRangeDrift(unittest.TestCase):
    """#18 R3's second half: does a tunable's declared [min, max] agree
    with the range the header's own guard permits?

    The comparison lives in schema.py and takes the parsed guards rather
    than a ConfigFile, for the same reason `find_drift` takes bare names:
    this module classifies, it does not parse C -- and config_io imports
    it, so the dependency may only point one way.
    """

    def setUp(self):
        self.tunables_path = write_json(
            Path(tempfile.mkdtemp()) / "tunables.json", SAMPLE_TUNABLES_FOR_CONFIG_IO
        )
        self.schema = Schema.load(self.tunables_path)

    def test_a_guard_that_agrees_is_clean_and_counted_as_checked(self):
        config = config_io.parse(GUARDED_CONFIG_TEXT, schema=self.schema)

        report = find_range_drift(self.schema, config.guards)

        self.assertTrue(report.clean)
        self.assertEqual(report.checked, ["GEAR1_MAX_SPEED"])
        self.assertEqual(report.summary(), "no range drift")

    def test_a_guard_that_disagrees_is_reported_with_both_ranges(self):
        # AC2, at the unit: tunables.json says 1-15, the header says 1-7.
        narrowed = GUARDED_CONFIG_TEXT.replace(
            "(GEAR1_MAX_SPEED) > 15", "(GEAR1_MAX_SPEED) > 7"
        )
        config = config_io.parse(narrowed, schema=self.schema)

        report = find_range_drift(self.schema, config.guards)

        self.assertFalse(report.clean)
        self.assertEqual([m.name for m in report.mismatches], ["GEAR1_MAX_SPEED"])
        mismatch = report.mismatches[0]
        self.assertEqual((mismatch.schema_min, mismatch.schema_max), (1, 15))
        self.assertEqual((mismatch.guard_min, mismatch.guard_max), (1, 7))
        # Both ranges in the message, or the reader cannot tell which side
        # is wrong without opening two files.
        described = mismatch.describe()
        self.assertIn("GEAR1_MAX_SPEED", described)
        self.assertIn("1-15", described)
        self.assertIn("1-7", described)
        self.assertEqual(report.summary(), "1 range mismatch")

    def test_a_tunable_with_no_guard_is_skipped_not_flagged(self):
        # R4/AC3. Every tunable in the real file except PLAYER_HANDLING is
        # in this case, so "skipped" has to mean silence -- not a warning,
        # not an entry in `checked`.
        config = config_io.parse(SAMPLE_CONFIG_TEXT, schema=self.schema)

        report = find_range_drift(self.schema, config.guards)

        self.assertTrue(report.clean)
        self.assertEqual(report.checked, [])
        self.assertEqual(report.mismatches, [])

    def test_a_guard_over_a_non_tunable_define_is_skipped(self):
        # A structural/derived/marker entry declares no min or max, so
        # there is nothing for its guard to disagree with.
        guarded_structural = SAMPLE_CONFIG_TEXT.replace(
            "#define MAX_SPRITES  32",
            "#define MAX_SPRITES  32\n#if (MAX_SPRITES) < 1 || (MAX_SPRITES) > 40",
        ).replace("#endif /* CONFIG_H */", "#endif\n\n#endif /* CONFIG_H */")
        config = config_io.parse(guarded_structural, schema=self.schema)

        report = find_range_drift(self.schema, config.guards)

        self.assertIn("MAX_SPRITES", config.guards)  # it was parsed...
        self.assertTrue(report.clean)  # ...and then skipped
        self.assertEqual(report.checked, [])

    def test_two_mismatches_are_both_reported(self):
        both = GUARDED_CONFIG_TEXT.replace(
            "(GEAR1_MAX_SPEED) > 15", "(GEAR1_MAX_SPEED) > 7"
        ).replace(
            "#define PLAYER_ARMOR     5   /* reduces damage */",
            "#define PLAYER_ARMOR     5   /* reduces damage */\n"
            "#if (PLAYER_ARMOR) < 0 || (PLAYER_ARMOR) > 9\n#endif",
        )
        config = config_io.parse(both, schema=self.schema)

        report = find_range_drift(self.schema, config.guards)

        self.assertEqual(
            sorted(m.name for m in report.mismatches),
            ["GEAR1_MAX_SPEED", "PLAYER_ARMOR"],
        )
        self.assertEqual(report.summary(), "2 range mismatches")

    @unittest.skipIf(NO_GAME_REPO, NO_GAME_REPO_REASON)
    def test_the_real_header_and_the_real_tunables_json_agree(self):
        # AC2/AC3 against the real pair, not a fixture. The `checked`
        # assertion is the important half: R4 makes an unparsed guard
        # invisible, so a `clean` report proves nothing on its own -- this
        # pins that PLAYER_HANDLING's guard is actually being read.
        text = REAL_CONFIG_H_PATH.read_text(encoding="utf-8")
        schema = Schema.load(REAL_TUNABLES_PATH)
        config = config_io.parse(text, schema=schema)

        report = find_range_drift(schema, config.guards)

        self.assertIn("PLAYER_HANDLING", report.checked)
        self.assertTrue(
            report.clean,
            "tunables.json disagrees with a range guard in src/config.h:\n"
            + "".join(f"  - {m.describe()}\n" for m in report.mismatches),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```
python -m unittest tests.test_garage_core.TestFindRangeDrift -v
```

Expected: collection fails first with `ImportError: cannot import name 'find_range_drift' from 'tools.garage.core.schema'`.

- [ ] **Step 3: Write the implementation**

Append to `tools/garage/core/schema.py`, after `find_drift` (the file currently ends at line 243):

```python
@dataclass(frozen=True)
class RangeMismatch:
    """One tunable whose declared [min, max] disagrees with the range the
    header's own `#if ... #error` guard permits (#18 R3).
    """

    name: str
    schema_min: int
    schema_max: int
    guard_min: int
    guard_max: int
    line_no: int

    def describe(self) -> str:
        return (
            f"'{self.name}' is {self.schema_min}-{self.schema_max} in "
            f"tunables.json but src/config.h line {self.line_no} guards it "
            f"to {self.guard_min}-{self.guard_max}"
        )


@dataclass
class RangeDriftReport:
    """How `tunables.json`'s clamps and `src/config.h`'s range guards
    disagree. `checked` names the tunables that had a guard at all --
    every other tunable was skipped, which R4 asks to be silent, and which
    makes `clean` alone a weak claim: a report can be clean because
    nothing was compared.
    """

    mismatches: List[RangeMismatch]
    checked: List[str]

    @property
    def clean(self) -> bool:
        return not self.mismatches

    def summary(self) -> str:
        if not self.mismatches:
            return "no range drift"
        count = len(self.mismatches)
        return f"{count} range mismatch" + ("es" if count > 1 else "")


def find_range_drift(schema: "Schema", guards) -> RangeDriftReport:
    """Compare every tunable's declared [min, max] against the range the
    header guards it to (#18 R3).

    `guards` maps a #define name to an object carrying `min`, `max` and
    `line_no` -- `config_io.GuardRange`. Taken duck-typed rather than
    imported for the same reason `find_drift` takes bare names: this
    module classifies, it does not parse C, and config_io imports this
    one, so the dependency may only point one way.

    Two kinds of entry are skipped in silence, per R4:
      - a tunable with no guard (today, every tunable but PLAYER_HANDLING);
      - a guard over a name that is not a tunable entry -- structural,
        derived, marker or unclassified -- which declares no range for the
        guard to disagree with.
    """
    mismatches: List[RangeMismatch] = []
    checked: List[str] = []
    for entry in schema.tunables():
        guard = guards.get(entry.name)
        if guard is None:
            continue
        checked.append(entry.name)
        if (entry.min, entry.max) != (guard.min, guard.max):
            mismatches.append(
                RangeMismatch(
                    name=entry.name,
                    schema_min=entry.min,
                    schema_max=entry.max,
                    guard_min=guard.min,
                    guard_max=guard.max,
                    line_no=guard.line_no,
                )
            )
    return RangeDriftReport(mismatches=mismatches, checked=checked)
```

- [ ] **Step 4: Run the tests to verify they pass**

```
python -m unittest tests.test_garage_core.TestFindRangeDrift -v
```

Expected: `OK`, 6 tests (5 plus the real-header one, which runs on a machine with the game repo beside this checkout and skips otherwise).

- [ ] **Step 5: Run the whole default suite**

```
python -m unittest discover -s tests -p "test_*.py"
```

Expected: `OK`.

- [ ] **Step 6: Confirm the real guard is genuinely being read**

```
python -m unittest tests.test_garage_core.TestFindRangeDrift.test_the_real_header_and_the_real_tunables_json_agree -v
```

Expected on a machine with `C:/Code/nuke-raider` beside this checkout: `OK` (1 test, not skipped). If it reports `skipped`, the binding is not resolving — check `garage.local.json`'s `game_repo`. If it *fails* on the `assertIn("PLAYER_HANDLING", report.checked)` line, the guard at `src/config.h:40` is not being parsed: re-check Task 1's regex against the real line rather than relaxing this assertion.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/core/schema.py tests/test_garage_core.py
git commit -m "$(cat <<'EOF'
feat: compare a tunable's declared range against the header's guard (#18 R3)

find_range_drift mirrors find_drift: schema.py owns the comparison, takes
the parsed guards duck-typed so it still never imports config_io, and
returns both the mismatches and the names it actually compared.

`checked` is not decoration. R4 skips a guard-less tunable silently, so a
clean report can mean "nothing disagreed" or "nothing was compared", and
only the second list tells them apart -- which is what the real-header
test asserts on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Fail `tools/garage_lint.py` on a range mismatch (the blocking gate)

**Files:**
- Modify: `tools/garage_lint.py:1-18` (module docstring), `:25-34` (imports), `:68-90` (the body of `run`)
- Modify: `tools/garage/tunables.json:2` (the `_shape` string)
- Modify: `Makefile:16-20` (the `lint` target's comment)
- Test: `tests/test_garage_lint.py` (three tests: one in `TestTheBoundGameRepositoryIsInStep`, two in `TestGarageLint`)

**Interfaces:**
- Consumes: `schema.find_range_drift(schema, guards) -> RangeDriftReport` with `.clean`, `.mismatches` (each `.describe()`), `.checked` (Task 2); `config_io.read(binding, schema) -> ConfigFile` with `.guards` (Task 1); existing `garage_lint.run(garage_root=None, schema_path=None) -> int`.
- Produces: `garage_lint.run` returns 1 (was 0) when a guard disagrees, and prints one line per mismatch. No new symbol.

- [ ] **Step 1: Write the failing tests**

In `tests/test_garage_lint.py`, add these two fixture constants after `MATCHING_TUNABLES` (which ends at line 56, before `def _run_git`):

```python
# The same header with the shape #18 R3 reads: a two-sided #if guard, as
# gmb-nuke-raider PR #644 added for PLAYER_HANDLING. Its range agrees with
# MATCHING_TUNABLES' 1-15 for GEAR1_MAX_SPEED.
GUARDED_CONFIG = SAMPLE_CONFIG.replace(
    "#endif /* CONFIG_H */",
    "#if (GEAR1_MAX_SPEED) < 1 || (GEAR1_MAX_SPEED) > 15\n"
    '#error "GEAR1_MAX_SPEED must be 1-15"\n'
    "#endif\n\n#endif /* CONFIG_H */",
)
```

Then add to `class TestGarageLint`, after `test_stale_schema_entry_fails_and_names_it`:

```python
    def test_a_range_that_disagrees_with_the_headers_guard_fails(self):
        # AC4, red half. The classification is in perfect step -- every
        # #define classified, no stale entry -- and the check still has to
        # fail, because the Tuner would otherwise offer a value the guard
        # turns into an #error.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", GUARDED_CONFIG)
            wrong = json.loads(json.dumps(MATCHING_TUNABLES))
            wrong["entries"]["GEAR1_MAX_SPEED"]["max"] = 20
            tunables_path = write_tunables(tmp_path, wrong)

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 1)
            self.assertIn("GEAR1_MAX_SPEED", output)
            self.assertIn("1-20", output)  # what tunables.json declares
            self.assertIn("1-15", output)  # what the header permits
            self.assertIn("tunables.json", output)

    def test_the_same_check_is_green_once_the_range_is_corrected(self):
        # AC4, green half -- the flip. Same header, same fixture, only the
        # declared max corrected back to the guarded one.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", GUARDED_CONFIG)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 0)
            self.assertIn("garage_lint: OK", output)

    def test_guard_less_tunables_pass_unchanged(self):
        # AC3/R4. SAMPLE_CONFIG declares no guard at all, which is every
        # tunable in the real file but PLAYER_HANDLING. The check must
        # stay silent about them rather than call them unverified.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", SAMPLE_CONFIG)
            tunables_path = write_tunables(tmp_path, MATCHING_TUNABLES)

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 0)
            self.assertNotIn("unverified", output)
            self.assertNotIn("GEAR1_MAX_SPEED", output)
```

And add to `class TestTheBoundGameRepositoryIsInStep`, after `test_the_drift_check_script_agrees_with_it`:

```python
    def test_the_declared_ranges_match_the_headers_guards(self):
        # AC2 against the real pair. Like the classification test above,
        # this runs the comparison against whatever this checkout is bound
        # to, and skips when nothing is bound (the CI case).
        try:
            binding = project.bind()
        except project.BindingError as exc:
            self.skipTest(f"no game repository bound: {exc}")

        schema = Schema.load()
        config = config_io.read(binding, schema)
        report = find_range_drift(schema, config.guards)

        # A clean report proves nothing unless something was compared: R4
        # skips an unguarded -- or unparsed -- tunable in silence.
        self.assertIn("PLAYER_HANDLING", report.checked)
        self.assertTrue(
            report.clean,
            f"tunables.json disagrees with {binding.config_h}:\n"
            + "".join(f"  - {m.describe()}\n" for m in report.mismatches),
        )
```

with the import at line 20 extended from:

```python
from tools.garage.core.schema import Schema, find_drift  # noqa: E402
```

to:

```python
from tools.garage.core.schema import (  # noqa: E402
    Schema,
    find_drift,
    find_range_drift,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

```
python -m unittest tests.test_garage_lint -v
```

Expected: `test_a_range_that_disagrees_with_the_headers_guard_fails` fails with `0 != 1` — the script currently compares names only, so the mismatch passes. The other three pass already (they describe behaviour that must not regress); `test_the_declared_ranges_match_the_headers_guards` passes on a bound machine and skips in CI.

- [ ] **Step 3: Write the implementation**

In `tools/garage_lint.py`, replace the module docstring's failure list (lines 4-13) so it names the third mode:

```python
"""Garage's drift check (R8 / AC9, and #18 R3/R5).

tools/garage/tunables.json is the single source of truth for which
#defines in the game repository's src/config.h Garage may edit. This
script fails when the two disagree:

  - a #define exists in config.h but tunables.json places it in none of
    the four classes ("unclassified" -- config.h has drifted ahead), or
  - tunables.json names a #define that no longer exists in config.h
    ("stale" -- config.h has since dropped it), or
  - config.h guards a tunable with `#if (NAME) < min || (NAME) > max` and
    tunables.json declares a different min/max. That one is not cosmetic:
    the Tuner's spin box offers whatever tunables.json declares, so a
    wider clamp hands the user a value the next build rejects with the
    guard's own #error. A tunable the header does not guard is skipped,
    silently (#18 R4).
```

Extend the schema import (lines 28-34) to:

```python
from tools.garage.core.schema import (
    DriftReport,
    Schema,
    SchemaError,
    find_drift as schema_drift,
    find_range_drift,
)
```

Then replace the body of `run` from line 68 (`config = config_io.read(...)`) through line 90 (`return 1`) with:

```python
    config = config_io.read(binding, schema)
    report = find_drift(schema, config)
    range_report = find_range_drift(schema, config.guards)

    if report.clean and range_report.clean:
        print(
            "garage_lint: OK -- every #define in "
            f"'{binding.config_h}' is classified in tunables.json, every "
            "tunables.json entry still exists in the header, and the "
            f"{len(range_report.checked)} tunable(s) the header guards "
            "with an #if declare the guarded range."
        )
        return 0

    if not report.clean:
        print("garage_lint: FAIL -- tunables.json has drifted from src/config.h")
        for name in report.unclassified:
            print(
                f"  - '{name}' is defined in src/config.h but is not classified "
                "in tunables.json (add it as tunable/structural/derived/marker)."
            )
        for name in report.stale:
            print(
                f"  - '{name}' is classified in tunables.json but no longer "
                "exists in src/config.h (remove it from tunables.json)."
            )

    if not range_report.clean:
        print(
            "garage_lint: FAIL -- a tunable's declared range disagrees with "
            "the #if guard src/config.h states for it"
        )
        for mismatch in range_report.mismatches:
            print(
                f"  - {mismatch.describe()} (fix 'min'/'max' in "
                "tunables.json, or the guard in the header -- the Tuner "
                "offers what tunables.json declares, and the build rejects "
                "what the guard forbids)."
            )

    return 1
```

Next, document the contract where the file it constrains lives. In `tools/garage/tunables.json`, the `_shape` value (line 2) currently ends with:

```
This file is the single source of truth for tools/garage_lint.py's drift check (R8): every #define in config.h must appear here exactly once, and every entry here must still exist in the header.
```

Append one sentence to that same string (ASCII only, no em dash):

```
 Where config.h guards a tunable with '#if (NAME) < min || (NAME) > max', the 'min'/'max' here must equal the guarded range -- the same check fails otherwise (#18 R3). A tunable config.h does not guard is not checked (R4).
```

Finally, in `Makefile`, replace the `lint` target's comment (lines 16-20) with:

```make
# The drift check on its own (R8/AC9 and #18 R3): is every #define in the
# game repository's src/config.h classified in tunables.json, does every
# tunables.json entry still exist in the header, and does every tunable
# the header range-guards with an #if declare that same range? `make test`
# fails on the same drift; this prints the names without running the
# suite, and exits 0 with an explanation when no game repository is bound.
```

- [ ] **Step 4: Run the tests to verify they pass**

```
python -m unittest tests.test_garage_lint -v
```

Expected: `OK`. On a bound machine 10 tests run; in CI three of them skip.

- [ ] **Step 5: Run the gate exactly as CI runs it**

```
python tools/garage_lint.py
```

Expected on a bound machine: `garage_lint: OK -- ... and the 1 tunable(s) the header guards with an #if declare the guarded range.` — the `1` is `PLAYER_HANDLING`. If it prints `0`, the real guard is not being read; do not proceed to Task 4, fix Task 1's parse first.

- [ ] **Step 6: Prove the gate is red on real drift, then put it back (AC4, end to end)**

```
python -c "import json,io; p='tools/garage/tunables.json'; d=json.load(io.open(p,encoding='utf-8')); d['entries']['PLAYER_HANDLING']['max']=10; io.open(p,'w',encoding='utf-8').write(json.dumps(d,indent=2)+'\n')"
python tools/garage_lint.py
```

Expected: exit code 1 and a line naming `PLAYER_HANDLING`, `0-10` and `0-7`. Then restore the file — the edit above also reformats it, so restore from git rather than by re-editing:

```
git checkout -- tools/garage/tunables.json
python tools/garage_lint.py
```

Expected: `garage_lint: OK`, and `git status` clean for that file. Then re-apply the `_shape` sentence from Step 3 if the checkout reverted it, and re-run `python tools/garage_lint.py` to confirm OK.

- [ ] **Step 7: Run the whole default suite**

```
python -m unittest discover -s tests -p "test_*.py"
```

Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
git add tools/garage_lint.py tools/garage/tunables.json Makefile tests/test_garage_lint.py
git commit -m "$(cat <<'EOF'
feat: fail the drift check when a tunable's range disagrees with its guard (#18 R3/R5)

The gate that already runs in `make test`, `make lint` and the CI drift
step now compares ranges as well as names, so it is blocking by wiring
rather than by a new workflow (R5).

The failure names both ranges and both files: on its own, "PLAYER_HANDLING
is wrong" leaves the reader to work out which of tunables.json and
config.h to edit, and either can be the one that moved.

A tunable the header does not guard stays unmentioned (R4) -- that is
every tunable but PLAYER_HANDLING today, and a per-entry "unverified"
line would bury the one row that means something.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Report the same mismatch in the Doctor

**Files:**
- Modify: `tools/garage/core/doctor.py:43` (import), `:188-258` (`check_classification`)
- Test: `tests/test_garage_core.py` (two tests added to `class TestDoctorClassification`, after `test_a_classification_entry_the_header_dropped_is_reported_too` at line 1589)

**Interfaces:**
- Consumes: `schema.find_range_drift(schema, guards) -> RangeDriftReport` with `.clean`, `.mismatches` (each `.describe()`), `.checked`, `.summary()` (Task 2); `config_io.read(binding, schema) -> ConfigFile` with `.guards` (Task 1).
- Produces: no new symbol and **no new check key** — the report keeps its nine checks and its single `classification` row. `CheckResult.status`, `.detail` and `.tag` for that row now also answer for range drift.

- [ ] **Step 1: Write the failing tests**

In `tests/test_garage_core.py`, add to `class TestDoctorClassification`:

```python
    def test_a_range_that_disagrees_with_the_headers_guard_fails(self):
        # #18 R3, in the window: the classification is in perfect step and
        # the row still has to go red, because the Tuner is about to offer
        # a value the next build rejects.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._bound(tmp_path, GUARDED_CONFIG_TEXT)
            wrong = json.loads(json.dumps(SAMPLE_TUNABLES_FOR_CONFIG_IO))
            wrong["entries"]["GEAR1_MAX_SPEED"]["max"] = 20
            schema = Schema.load(write_json(tmp_path / "t.json", wrong))

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("GEAR1_MAX_SPEED", check.detail)
            self.assertIn("1-20", check.detail)
            self.assertIn("1-15", check.detail)
            self.assertIn("tunables.json", check.prevents)
            self.assertEqual(check.tag, "1 range mismatch")

    def test_a_guard_that_agrees_passes_and_says_how_many_were_checked(self):
        # The pass has to state the coverage: R4 skips an unguarded
        # tunable in silence, so "in step" alone cannot distinguish a
        # header whose guards agree from one whose guards were never read.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._bound(tmp_path, GUARDED_CONFIG_TEXT)
            schema = Schema.load(
                write_json(tmp_path / "t.json", SAMPLE_TUNABLES_FOR_CONFIG_IO)
            )

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.PASS)
            self.assertIn("all classified", check.detail)
            self.assertIn("1 range guard", check.detail)
            self.assertEqual(check.tag, "in step")
```

- [ ] **Step 2: Run the tests to verify they fail**

```
python -m unittest tests.test_garage_core.TestDoctorClassification -v
```

Expected: `test_a_range_that_disagrees_with_the_headers_guard_fails` fails with `'PASS' != 'FAIL'`, and `test_a_guard_that_agrees_passes_and_says_how_many_were_checked` fails on `'1 range guard' not found in '8 #defines, all classified'`. The four existing tests in the class must still pass.

- [ ] **Step 3: Write the implementation**

In `tools/garage/core/doctor.py`, extend the schema import (line 43) from:

```python
from tools.garage.core.schema import Schema, SchemaError, find_drift
```

to:

```python
from tools.garage.core.schema import (
    Schema,
    SchemaError,
    find_drift,
    find_range_drift,
)
```

Add one paragraph to `check_classification`'s docstring (after the existing one, which ends at line 199 with "…exactly what R8 exists to end."):

```python
    #18 R3 adds the second disagreement this row answers for: a tunable
    whose declared [min, max] is not the range src/config.h guards it to.
    It shares this row rather than adding its own, because it is the same
    question -- does tunables.json still describe this header -- and the
    user acts on it in the same place. A tunable the header does not
    guard is not mentioned at all (R4).
```

Then replace the block from line 232 (`drift = find_drift(...)`) to the end of the function (line 258) with:

```python
    drift = find_drift(schema, config.defines.keys())
    range_drift = find_range_drift(schema, config.guards)
    if drift.clean and range_drift.clean:
        return CheckResult(
            key="classification",
            name=name,
            status=PASS,
            detail=(
                f"{len(config.defines)} #defines, all classified; "
                f"{len(range_drift.checked)} range guard(s) in step"
            ),
            tag="in step",
        )

    details = []
    if drift.unclassified:
        details.append("unclassified in tunables.json: " + ", ".join(drift.unclassified))
    if drift.stale:
        details.append("gone from src/config.h: " + ", ".join(drift.stale))
    for mismatch in range_drift.mismatches:
        details.append(mismatch.describe())
    tags = [
        report.summary()
        for report in (drift, range_drift)
        if not report.clean
    ]
    return CheckResult(
        key="classification",
        name=name,
        status=FAIL,
        detail=" · ".join(details),
        prevents=(
            "The Tuner does not offer an unclassified #define, and says "
            "nothing about it — the drift has to be fixed in tunables.json "
            "before that value can be tuned. A tunable whose range is wider "
            "than the header's guard is worse than silent: the Tuner offers "
            "the value and the build rejects it. This repository's test "
            "suite fails until both are fixed."
        ),
        tag=", ".join(tags),
    )
```

Note the two non-ASCII characters already in this file: `·` in the `" · ".join(details)` separator and `—` in the `prevents` text. Keep both exactly as written.

- [ ] **Step 4: Run the tests to verify they pass**

```
python -m unittest tests.test_garage_core.TestDoctorClassification -v
```

Expected: `OK`, 6 tests. In particular `test_an_unclassified_define_is_reported_by_name` must still assert `check.tag == "1 unclassified"` — with no range drift, only the name-drift summary joins the tag.

- [ ] **Step 5: Run the whole default suite and the panel suite**

```
python -m unittest discover -s tests -p "test_*.py"
```

Expected: `OK`. Watch `test_a_complete_machine_passes_every_check`, which asserts `"8 of 9 checks passing · failing: classification"` — no check was added, so the count is unchanged.

Then the Qt panels (needs PySide6; takes about six minutes — give it a long timeout):

```
python -m unittest discover -s tests/garage -p "test_*.py"
```

Expected: `OK`. The relevant one is `test_the_doctor_carries_a_classification_row`, which reads the `classification` row's detail and prevents text.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/doctor.py tests/test_garage_core.py
git commit -m "$(cat <<'EOF'
feat: report a range/guard mismatch in the Doctor's classification row (#18 R3)

Same comparison, same consumers: the drift check fails the suite and the
Doctor shows it at startup, and the range mismatch now travels with it.

It shares the existing `classification` row instead of adding a tenth
check. It answers the same question -- does tunables.json still describe
this header -- and a second row would have split one answer across two
lines the user reads in the same glance.

The pass now states how many guards were compared. R4 skips an unguarded
tunable in silence, so "in step" on its own cannot tell a header whose
guards agree from one whose guards were never parsed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Both suites, from a clean tree**

```
python -m unittest discover -s tests -p "test_*.py"
python -m unittest discover -s tests/garage -p "test_*.py"
python tools/garage_lint.py
```

Expected: `OK`, `OK`, `garage_lint: OK`.

- [ ] **AC-by-AC walkthrough for the PR body**

| AC | Evidence |
|---|---|
| AC1 | `tunables.json` `PLAYER_HANDLING` is `min 0 / max 7` with a reason naming `PLAYER_TURN_FRAMES_TABLE` — landed in `483f3d1`, pinned by `test_player_handling_clamps_to_the_headers_error_guard`. |
| AC2 | `tests/test_garage_lint.py::TestTheBoundGameRepositoryIsInStep::test_the_declared_ranges_match_the_headers_guards` and `tests/test_garage_core.py::TestFindRangeDrift::test_the_real_header_and_the_real_tunables_json_agree` — both run against the bound repo and both assert `PLAYER_HANDLING` is in `checked`. |
| AC3 | `test_guard_less_tunables_pass_unchanged` and `test_a_tunable_with_no_guard_is_skipped_not_flagged` — no tunables.json entry changed for any guard-less tunable. |
| AC4 | `test_a_range_that_disagrees_with_the_headers_guard_fails` (red) and `test_the_same_check_is_green_once_the_range_is_corrected` (green), plus the manual flip in Task 3 Step 6. |
| R5 | The check runs inside `run()` in `tools/garage_lint.py`, which `make lint`, the `Drift check` CI step, and (via `tests/test_garage_lint.py`) `make test` all execute. Exit code 1 on mismatch. |
| R6 | No entry added to `tunables.json`; `PLAYER_TURN_FRAMES_TABLE` stays `structural`, pinned by the existing `test_the_turn_frames_table_is_classified_and_never_offered`. |

- [ ] **Nothing in the game repository changed**

```
git -C C:/Code/nuke-raider status --short
```

Expected: whatever was there before this work — no file this plan names.

- [ ] **Open the PR** referencing `#18`, with the AC table above in the body (write the body to a temp file and use `gh pr create --body-file`; PowerShell flattens an inline multi-line body).
