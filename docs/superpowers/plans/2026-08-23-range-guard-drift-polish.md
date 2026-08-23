# Range-Guard Drift Check Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four wording/parser polish items accepted as Minor at the merge of #22, so the range-guard drift check says only what is true for the failure at hand and its guard parser rejects a half it should never have accepted.

**Architecture:** Four independent, non-overlapping edits to code that already exists and is already tested. One tightens a regex in `tools/garage/core/config_io.py`; one turns a hardcoded path string in `tools/garage/core/schema.py` into a parameter; two rewrite user-facing text in `tools/garage/core/doctor.py` and `tools/garage_lint.py`. No new module, no new type, no change to what the check passes or fails — except that one malformed C guard shape now goes unread (which R4 already defines as "skipped in silence") instead of being read as a range it does not mean.

**Tech Stack:** Python 3, standard library only (`re`, `dataclasses`, `pathlib`), `unittest` for tests. Run tests with `python -m unittest`, the lint with `python tools/garage_lint.py` (`make test` / `make lint`).

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/23 — "chore: polish the range-guard drift check's wording and parser edges (#18 follow-up)". Read the issue before starting; it is short, and each task below quotes the finding it answers.

## Global Constraints

- **No Qt import** in `tools/garage/core/**` or in `tests/test_garage_core.py` / `tests/test_garage_lint.py`. Those must pass with PySide6 absent.
- **The dependency points one way:** `config_io.py` imports `schema.py`. `schema.py` must never import `config_io`; it takes guards duck-typed (`Mapping[str, Any]`). Do not add an import to "fix" a type hint.
- **Scope: wording and parser edges only.** Issue #23's first finding — strict equality forbidding a deliberately narrower clamp (e.g. `2-6` under a `0-7` guard) — is a recorded decision, **not** in scope. Do not relax `find_range_drift`'s `(entry.min, entry.max) != (guard.min, guard.max)` comparison, and do not touch `tunables.json`'s `_shape` text.
- **No entry in the real `tools/garage/tunables.json` changes.** Every test fixture is a temp-directory JSON file; the shipped classification file is not edited by this plan.
- **Standard-library `re` only.** The conditional-group syntax `(?(name)yes)` used in Task 1 is standard `re`; no third-party regex module.
- **Every task ends green on both** `python -m unittest discover -s tests -p 'test_*.py'` **and** `python tools/garage_lint.py` (the latter needs a bound game repository; if it prints "no game repository is bound … skipping", that is exit 0 and acceptable).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/garage/core/config_io.py` | Parses `src/config.h`: `#define`s and two-sided `#if … #error` range guards | Modify `_GUARD_HALF_RE` (Task 1) |
| `tools/garage/core/schema.py` | Classification + the two drift comparisons; `RangeMismatch.describe()` | Modify `describe()` (Task 2) |
| `tools/garage_lint.py` | CI consumer: prints the drift report, returns an exit code | Pass the resolved path to `describe()` (Task 2); zero-guard OK wording (Task 4) |
| `tools/garage/core/doctor.py` | Startup consumer: the same comparison as one Doctor row | Compose `prevents` per branch (Task 3); zero-guard PASS wording (Task 4) |
| `tests/test_garage_core.py` | Unit coverage for `config_io`, `schema`, `doctor` | New tests in `TestConfigIOGuards`, `TestFindRangeDrift`, `TestDoctorClassification` |
| `tests/test_garage_lint.py` | End-to-end coverage of `garage_lint.run` | New tests in `TestGarageLint` |

Tasks are independent — they touch disjoint lines — but are ordered so a reviewer can gate each one alone. Do them in order and commit each separately.

---

### Task 1: Reject a guard half whose parentheses are not its own

**The finding (issue #23, "Also worth recording"):** `_GUARD_HALF_RE`'s leading `\(?` and trailing `\)?` are independently optional, so a malformed half like `(X < 0 || X) > 7` still parses as `0-7`. The review justified this as "such a header would not compile" — that is wrong. `(X < 0 || X) > 7` is valid, compilable C: the `||` yields 0 or 1, so the guard never fires. Under R4 an unreadable guard is skipped in silence, which is the correct outcome here — reading it as `0-7` is not.

Note how the split works: `parse_guard_condition` splits the condition on `||` first, so `(X < 0 || X) > 7` reaches `_parse_guard_half` as two halves, `"(X < 0 "` and `" X) > 7"`. Today the first matches (leading `(` consumed, no `)` required) and the second matches too (no leading `(`, and the optional `\)?` after the name absorbs the stray `)`). Requiring each operand's parentheses to be *paired* rejects both halves, and `parse_guard_condition` returns `None`.

**Files:**
- Modify: `tools/garage/core/config_io.py:63-67` (`_GUARD_HALF_RE`)
- Test: `tests/test_garage_core.py`, class `TestConfigIOGuards` (line ~695)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks rely on. `config_io.parse_guard_condition(condition: str) -> Optional[Tuple[str, int, int]]` keeps its exact signature and return type.

- [x] **Step 1: Write the failing tests**

Add these two methods to `TestConfigIOGuards` in `tests/test_garage_core.py`, immediately after `test_a_partly_parenthesized_half_is_still_read` (the last method of the class, ~line 779):

```python
    def test_a_half_whose_parentheses_are_not_its_own_is_not_read(self):
        # `(X < 0 || X) > 7` is valid, compilable C -- the `||` yields 0
        # or 1, so the guard never fires -- and it does not mean 0-7.
        # Read as a range it would silently contradict the header. R4
        # already asks an unreadable guard to be skipped in silence, so
        # None (not a wrong range) is the honest answer.
        self.assertIsNone(config_io.parse_guard_condition("(X < 0 || X) > 7"))

    def test_a_half_with_an_unclosed_paren_is_not_read(self):
        for condition in (
            "(X < 0 || (X) > 7",  # lower half opens a paren it never closes
            "(X) < 0 || X) > 7",  # upper half closes one it never opened
        ):
            with self.subTest(condition=condition):
                self.assertIsNone(config_io.parse_guard_condition(condition))
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_core.TestConfigIOGuards -v`

Expected: `test_a_half_whose_parentheses_are_not_its_own_is_not_read` FAILS with `AssertionError: ('X', 0, 7) is not None`. `test_a_half_with_an_unclosed_paren_is_not_read` FAILS on at least the first subTest. Every other test in the class passes.

- [x] **Step 3: Make each operand's parentheses paired**

In `tools/garage/core/config_io.py`, replace the `_GUARD_HALF_RE` definition (currently lines 63-67):

```python
_GUARD_HALF_RE = re.compile(
    r"^\(?[ \t]*(?P<name>\w+)[ \t]*\)?[ \t]*"
    r"(?P<op><=?|>=?)[ \t]*"
    r"\(?[ \t]*(?P<literal>-?(?:0[xX][0-9a-fA-F]+|\d+))[uU]?[ \t]*\)?$"
)
```

with:

```python
# The `(?(lp)\))` / `(?(rp)\))` conditionals make each operand's
# parentheses paired rather than independently optional: `(X)` and `X`
# are both read, `(X` and `X)` are not. Without them a half like
# `(X < 0 || X) > 7` -- valid, compilable C whose `||` yields 0 or 1, so
# the guard never fires -- read as the range 0-7, which is not what it
# means. R4 asks an unreadable guard to be skipped in silence; a
# *misread* one is the failure mode that costs something.
_GUARD_HALF_RE = re.compile(
    r"^(?P<lp>\()?[ \t]*(?P<name>\w+)[ \t]*(?(lp)\))[ \t]*"
    r"(?P<op><=?|>=?)[ \t]*"
    r"(?P<rp>\()?[ \t]*(?P<literal>-?(?:0[xX][0-9a-fA-F]+|\d+))[uU]?[ \t]*(?(rp)\))$"
)
```

Nothing else in the file changes. `_parse_guard_half` reads `match.group("name")`, `match.group("op")` and `match.group("literal")`, all of which still exist.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_core.TestConfigIOGuards -v`

Expected: PASS, all methods — including the pre-existing `test_parentheses_are_optional`, `test_a_fully_parenthesized_half_is_still_read` and `test_a_partly_parenthesized_half_is_still_read`, which are the regression guard that this tightening did not also stop reading the shapes real headers use.

- [x] **Step 5: Run the whole suite and the lint**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK.

Run: `python tools/garage_lint.py`
Expected: exit 0 — either `garage_lint: OK -- …` or `garage_lint: no game repository is bound …`. If it prints FAIL, stop: the tightened regex has stopped reading a guard the real `src/config.h` relies on, and the regex is wrong.

- [x] **Step 6: Commit**

```bash
git add tools/garage/core/config_io.py tests/test_garage_core.py
git commit -m "fix: a guard half's parentheses must be paired to be read (#23)"
```

---

### Task 2: `RangeMismatch.describe()` takes the header path instead of hardcoding it

**The finding (issue #23):** `RangeMismatch.describe()` hardcodes the string `src/config.h` while `garage_lint` elsewhere prints the resolved `binding.config_h`. Harmless today (the path is fixed by contract) but it is a second spelling of the same fact.

**The design.** Make the path a parameter with `"src/config.h"` as its default. `garage_lint` passes `binding.config_h` — its OK line already prints the resolved path, so its FAIL lines now agree with its OK line. `doctor` keeps the default: every other string in that Doctor row spells the repo-relative `src/config.h`, and a Doctor row is a narrow one-line cell that an absolute worktree path would swamp. The fact is stated once, in one place, and each consumer chooses the spelling it already uses everywhere else.

**Files:**
- Modify: `tools/garage/core/schema.py:259-265` (`RangeMismatch.describe`)
- Modify: `tools/garage_lint.py:106-113` (the mismatch loop)
- Test: `tests/test_garage_core.py`, class `TestFindRangeDrift` (line ~785)
- Test: `tests/test_garage_lint.py`, class `TestGarageLint` (line ~185)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `RangeMismatch.describe(config_path: str | Path = "src/config.h") -> str`. `doctor.py` calls it with no argument, and Task 3 does not change that.

- [x] **Step 1: Write the failing unit tests**

Add these two methods to `TestFindRangeDrift` in `tests/test_garage_core.py`, after `test_a_guard_over_a_non_tunable_define_is_skipped` (~line 856):

```python
    def test_describe_names_the_header_path_it_is_given(self):
        # The path is a second spelling of a fact garage_lint already
        # prints resolved in its OK line. Passing it in keeps the two
        # halves of one report from naming the same file two ways.
        narrowed = GUARDED_CONFIG_TEXT.replace(
            "(GEAR1_MAX_SPEED) > 15", "(GEAR1_MAX_SPEED) > 7"
        )
        config = config_io.parse(narrowed, schema=self.schema)
        mismatch = find_range_drift(self.schema, config.guards).mismatches[0]

        described = mismatch.describe("/tmp/wt/src/config.h")

        self.assertIn("/tmp/wt/src/config.h", described)
        self.assertIn("1-15", described)
        self.assertIn("1-7", described)

    def test_describe_falls_back_to_the_repo_relative_path(self):
        # The Doctor row spells src/config.h everywhere else and is one
        # narrow line; the default is what it keeps using.
        narrowed = GUARDED_CONFIG_TEXT.replace(
            "(GEAR1_MAX_SPEED) > 15", "(GEAR1_MAX_SPEED) > 7"
        )
        config = config_io.parse(narrowed, schema=self.schema)
        mismatch = find_range_drift(self.schema, config.guards).mismatches[0]

        self.assertIn("src/config.h line", mismatch.describe())
```

- [x] **Step 2: Run the tests to verify the first fails**

Run: `python -m unittest tests.test_garage_core.TestFindRangeDrift -v`

Expected: `test_describe_names_the_header_path_it_is_given` FAILS with `TypeError: describe() takes 1 positional argument but 2 were given`. `test_describe_falls_back_to_the_repo_relative_path` PASSES already — it pins today's behaviour so the parameterization does not lose it.

- [x] **Step 3: Parameterize `describe()`**

In `tools/garage/core/schema.py`, replace the `describe` method of `RangeMismatch`:

```python
    def describe(self) -> str:
        return (
            f"'{self.name}' is {self.schema_min}-{self.schema_max} in "
            f"tunables.json but src/config.h line {self.line_no} guards it "
            f"to {self.guard_min}-{self.guard_max}"
        )
```

with:

```python
    def describe(self, config_path: str | Path = "src/config.h") -> str:
        """One line naming both ranges and where the guard is.

        `config_path` is how the caller spells the header. garage_lint
        passes the resolved `binding.config_h`, because its OK line
        already does; the Doctor takes the default, because its row
        spells the repo-relative path everywhere else and is one narrow
        line. Either way the path is stated once here, not twice.
        """
        return (
            f"'{self.name}' is {self.schema_min}-{self.schema_max} in "
            f"tunables.json but {config_path} line {self.line_no} guards it "
            f"to {self.guard_min}-{self.guard_max}"
        )
```

`Path` is already imported at the top of `schema.py`, and `from __future__ import annotations` is already in force, so the `str | Path` annotation is a deferred string and needs no `typing.Union`.

- [x] **Step 4: Run the unit tests to verify they pass**

Run: `python -m unittest tests.test_garage_core.TestFindRangeDrift -v`
Expected: PASS, all methods.

- [x] **Step 5: Write the failing lint test**

Add this method to `TestGarageLint` in `tests/test_garage_lint.py`, immediately after `test_a_range_that_disagrees_with_the_headers_guard_fails` (~line 281):

```python
    def test_the_failure_names_the_same_header_path_the_ok_line_would(self):
        # garage_lint's OK line prints the resolved binding.config_h. Its
        # FAIL line used to print the literal "src/config.h" -- the same
        # fact, spelled two ways in one report.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            garage_root = tmp_path / "nuke-raider-garage"
            garage_root.mkdir()
            make_game_repo(tmp_path / "nuke-raider", GUARDED_CONFIG)
            wrong = json.loads(json.dumps(MATCHING_TUNABLES))
            wrong["entries"]["GEAR1_MAX_SPEED"]["max"] = 20
            tunables_path = write_tunables(tmp_path, wrong)
            expected_path = project.bind(garage_root).config_h

            code, output = run_lint(
                garage_root=garage_root, schema_path=tunables_path
            )

            self.assertEqual(code, 1)
            self.assertIn(str(expected_path), output)
```

`project`, `tempfile`, `json`, `Path`, `make_game_repo`, `write_tunables` and `run_lint` are all already imported or defined in this file.

- [x] **Step 6: Run the lint test to verify it fails**

Run: `python -m unittest tests.test_garage_lint.TestGarageLint.test_the_failure_names_the_same_header_path_the_ok_line_would -v`

Expected: FAIL — the resolved temp-directory path is not in the output, only the literal `src/config.h`.

- [x] **Step 7: Pass the resolved path from garage_lint**

In `tools/garage_lint.py`, inside the `if not range_report.clean:` block, replace:

```python
        for mismatch in range_report.mismatches:
            print(
                f"  - {mismatch.describe()} (fix 'min'/'max' in "
                "tunables.json, or the guard in the header -- the Tuner "
                "offers what tunables.json declares, and the build rejects "
                "what the guard forbids)."
            )
```

with:

```python
        for mismatch in range_report.mismatches:
            print(
                f"  - {mismatch.describe(binding.config_h)} (fix 'min'/'max' "
                "in tunables.json, or the guard in the header -- the Tuner "
                "offers what tunables.json declares, and the build rejects "
                "what the guard forbids)."
            )
```

`binding` is in scope: it is bound at the top of `run()`.

- [x] **Step 8: Run the lint tests to verify they pass**

Run: `python -m unittest tests.test_garage_lint -v`

Expected: OK. In particular `test_unclassified_define_and_range_drift_both_reported` and `test_a_range_that_disagrees_with_the_headers_guard_fails` still pass — they assert on the tunable name and both ranges, none of which moved.

- [x] **Step 9: Run the whole suite and the lint**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK.

Run: `python tools/garage_lint.py`
Expected: exit 0.

- [x] **Step 10: Commit**

```bash
git add tools/garage/core/schema.py tools/garage_lint.py tests/test_garage_core.py tests/test_garage_lint.py
git commit -m "refactor: describe() takes the header path rather than spelling it again (#23)"
```

---

### Task 3: The Doctor's `prevents` names only the failure the user has

**The finding (issue #23):** `doctor.py`'s `prevents` text talks about range guards even on a pure name-drift failure. A user whose only problem is one unclassified `#define` is told "A tunable whose range is wider than the header's guard is worse than silent…", which has nothing to do with their row. The fix the issue names: compose `prevents` from the same `if not drift.clean` / `if not range_drift.clean` branches the `details` list already uses.

**Files:**
- Modify: `tools/garage/core/doctor.py:257-282` (the FAIL branch of `check_classification`)
- Test: `tests/test_garage_core.py`, class `TestDoctorClassification` (line ~1776)

**Interfaces:**
- Consumes: `RangeMismatch.describe()` from Task 2, called with **no argument** — the Doctor keeps the repo-relative default. Do not pass `binding.config_h` here.
- Produces: nothing other tasks rely on. `CheckResult`'s fields are unchanged.

- [x] **Step 1: Write the failing tests**

Add these three methods to `TestDoctorClassification` in `tests/test_garage_core.py`, after `test_a_range_that_disagrees_with_the_headers_guard_fails` (~line 1856):

```python
    def test_pure_name_drift_says_nothing_about_range_guards(self):
        # A user whose only problem is one unclassified #define was being
        # told about a range guard their row does not have. `prevents` is
        # the sentence that tells them what they lost; a sentence about
        # someone else's failure is noise in the one place they read.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            drifted = SAMPLE_CONFIG_TEXT.replace(
                "#endif /* CONFIG_H */",
                "#define NEW_UNCLASSIFIED_DEFINE 3u\n\n#endif /* CONFIG_H */",
            )
            binding = self._bound(tmp_path, drifted)
            schema = Schema.load(
                write_json(tmp_path / "t.json", SAMPLE_TUNABLES_FOR_CONFIG_IO)
            )

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("unclassified #define", check.prevents)
            self.assertNotIn("guard", check.prevents)

    def test_pure_range_drift_says_nothing_about_unclassified_defines(self):
        # And the mirror: every #define is classified, so "the Tuner does
        # not offer an unclassified #define" describes nothing here.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._bound(tmp_path, GUARDED_CONFIG_TEXT)
            wrong = json.loads(json.dumps(SAMPLE_TUNABLES_FOR_CONFIG_IO))
            wrong["entries"]["GEAR1_MAX_SPEED"]["max"] = 20
            schema = Schema.load(write_json(tmp_path / "t.json", wrong))

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("guard", check.prevents)
            self.assertNotIn("unclassified", check.prevents)

    def test_both_drifts_at_once_name_both(self):
        # Neither sentence may be dropped when both failures are real --
        # the composition must add, not choose.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            both = GUARDED_CONFIG_TEXT.replace(
                "#endif /* CONFIG_H */",
                "#define NEW_UNCLASSIFIED_DEFINE 3u\n\n#endif /* CONFIG_H */",
            )
            binding = self._bound(tmp_path, both)
            wrong = json.loads(json.dumps(SAMPLE_TUNABLES_FOR_CONFIG_IO))
            wrong["entries"]["GEAR1_MAX_SPEED"]["max"] = 20
            schema = Schema.load(write_json(tmp_path / "t.json", wrong))

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.FAIL)
            self.assertIn("unclassified #define", check.prevents)
            self.assertIn("guard", check.prevents)
            self.assertIn("both", check.prevents)
```

`GUARDED_CONFIG_TEXT` (defined at `tests/test_garage_core.py:634`) ends with `#endif /* CONFIG_H */`, the same as `SAMPLE_CONFIG_TEXT`, so the third test's `.replace` does insert the unclassified `#define` before the include guard's close.

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_core.TestDoctorClassification -v`

Expected: `test_pure_name_drift_says_nothing_about_range_guards` FAILS (the current single blob contains "guard"). `test_pure_range_drift_says_nothing_about_unclassified_defines` FAILS (the same blob contains "unclassified"). `test_both_drifts_at_once_name_both` may already pass — the blob names both — which is fine; it is the regression guard for the composition.

- [x] **Step 3: Compose `prevents` from the same branches as `details`**

In `tools/garage/core/doctor.py`, replace the tail of `check_classification` from `details = []` to the end of the function:

```python
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

with:

```python
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
    # `prevents` is composed from the same two branches `details` is,
    # rather than stated as one blob naming both failures: a user whose
    # only problem is one unclassified #define was being told what a
    # disagreeing range guard costs, which is not their row.
    losses = []
    if not drift.clean:
        losses.append(
            "The Tuner does not offer an unclassified #define, and says "
            "nothing about it — the drift has to be fixed in tunables.json "
            "before that value can be tuned."
        )
    if not range_drift.clean:
        losses.append(
            "A tunable whose declared range is not the one the header "
            "guards is worse than silent: the Tuner offers the value and "
            "the build rejects it — reconcile the range in tunables.json "
            "or in the header's guard."
        )
    losses.append(
        "This repository's test suite fails until both are fixed."
        if len(losses) == 2
        else "This repository's test suite fails until it is fixed."
    )
    return CheckResult(
        key="classification",
        name=name,
        status=FAIL,
        detail=" · ".join(details),
        prevents=" ".join(losses),
        tag=", ".join(tags),
    )
```

Two things to notice. The range sentence is reworded from "wider than the header's guard" to "not the one the header guards" — the check compares for equality, so a *narrower* declared range fails it too, and the old wording described a failure mode the code does not have. (The equality decision itself stays: see Global Constraints.) And the trailing sentence now agrees in number with how many failures are actually present.

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_core.TestDoctorClassification -v`

Expected: PASS, all methods. The name-drift sentence carries "tunables.json", which is what
`test_an_unclassified_define_is_reported_by_name` requires. The range sentence names both places a
range can be reconciled — "reconcile the range in tunables.json or in the header's guard" — which is
what `test_a_range_that_disagrees_with_the_headers_guard_fails` (a *pure* range-drift case, where the
name-drift sentence never fires) requires when it asserts `"tunables.json"` is in `prevents`.

- [x] **Step 5: Run the whole suite and the lint**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK.

Run: `python tools/garage_lint.py`
Expected: exit 0.

- [x] **Step 6: Commit**

```bash
git add tools/garage/core/doctor.py tests/test_garage_core.py
git commit -m "fix: the Doctor's prevents names only the drift the user has (#23)"
```

---

### Task 4: A header that guards nothing says so in words

**The finding (issue #23):** `"0 range guard(s) in step"` reads awkwardly on a header that guards nothing — which is every header but the current one. `tools/garage_lint.py`'s OK line carries the identical `"the 0 tunable(s)"` edge. If either is touched, touch both — so this task touches both, in one commit.

The nonzero wording does not change: `"1 range guard(s) in step"` and `"the 1 tunable(s) the header guards"` stay exactly as they are. Only the zero case gets a sentence.

**Files:**
- Modify: `tools/garage/core/doctor.py:246-256` (the PASS branch of `check_classification`)
- Modify: `tools/garage_lint.py:79-87` (the OK branch of `run`)
- Test: `tests/test_garage_core.py`, class `TestDoctorClassification`
- Test: `tests/test_garage_lint.py`, class `TestGarageLint`

**Interfaces:**
- Consumes: nothing from Tasks 1-3. Task 3's composition is in the FAIL branch; this is the PASS branch.
- Produces: nothing.

- [x] **Step 1: Write the failing Doctor test**

Add this method to `TestDoctorClassification` in `tests/test_garage_core.py`, after `test_a_guard_that_agrees_passes_and_says_how_many_were_checked`:

```python
    def test_a_header_that_guards_nothing_says_so_rather_than_counting_zero(self):
        # SAMPLE_CONFIG_TEXT declares no guard at all, which is every
        # header but the current one. "0 range guard(s) in step" claims a
        # count where the honest statement is that there was nothing to
        # compare -- and R4 makes that the normal case, not an error.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = tmp_root(tmp)
            binding = self._bound(tmp_path, SAMPLE_CONFIG_TEXT)
            schema = Schema.load(
                write_json(tmp_path / "t.json", SAMPLE_TUNABLES_FOR_CONFIG_IO)
            )

            check = doctor.check_classification(binding, schema)

            self.assertEqual(check.status, doctor.PASS)
            self.assertIn("all classified", check.detail)
            self.assertNotIn("0 range guard", check.detail)
            self.assertIn("no range guards to check", check.detail)
```

- [x] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_core.TestDoctorClassification.test_a_header_that_guards_nothing_says_so_rather_than_counting_zero -v`

Expected: FAIL with `'0 range guard' unexpectedly found in '… #defines, all classified; 0 range guard(s) in step'`.

- [x] **Step 3: Word the Doctor's zero case**

In `tools/garage/core/doctor.py`, replace the PASS branch of `check_classification`:

```python
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
```

with:

```python
    if drift.clean and range_drift.clean:
        # R4 makes a header that guards nothing the normal case, not an
        # error -- so it gets a sentence, not the count zero.
        guard_note = (
            f"{len(range_drift.checked)} range guard(s) in step"
            if range_drift.checked
            else "no range guards to check"
        )
        return CheckResult(
            key="classification",
            name=name,
            status=PASS,
            detail=f"{len(config.defines)} #defines, all classified; {guard_note}",
            tag="in step",
        )
```

- [x] **Step 4: Run the Doctor tests to verify they pass**

Run: `python -m unittest tests.test_garage_core.TestDoctorClassification -v`

Expected: PASS, all methods — including `test_a_guard_that_agrees_passes_and_says_how_many_were_checked`, which asserts `"1 range guard"` is in the detail and so pins that the nonzero wording did not move.

- [x] **Step 5: Write the failing lint tests**

Add these two methods to `TestGarageLint` in `tests/test_garage_lint.py`, immediately after `test_guard_less_tunables_pass_unchanged` (~line 350):

```python
    def test_the_ok_line_on_a_guard_less_header_does_not_count_zero(self):
        # The same edge as the Doctor's "0 range guard(s) in step".
        # SAMPLE_CONFIG has no #if guard, so "the 0 tunable(s) the header
        # guards with an #if declare the guarded range" is a sentence
        # about nothing.
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
            self.assertIn("garage_lint: OK", output)
            self.assertNotIn("0 tunable(s)", output)
            self.assertIn("guards no tunable with an #if", output)

    def test_the_ok_line_still_counts_the_guards_a_header_has(self):
        # The nonzero wording is unchanged: GUARDED_CONFIG guards one.
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
            self.assertIn("1 tunable(s) the header guards", output)
```

- [x] **Step 6: Run them to verify the first fails**

Run: `python -m unittest tests.test_garage_lint.TestGarageLint -v`

Expected: `test_the_ok_line_on_a_guard_less_header_does_not_count_zero` FAILS on `'0 tunable(s)' unexpectedly found`. `test_the_ok_line_still_counts_the_guards_a_header_has` PASSES already — it pins the wording this task must not change.

- [x] **Step 7: Word garage_lint's zero case**

In `tools/garage_lint.py`, replace the OK branch of `run`:

```python
    if report.clean and range_report.clean:
        print(
            "garage_lint: OK -- every #define in "
            f"'{binding.config_h}' is classified in tunables.json, every "
            "tunables.json entry still exists in the header, and the "
            f"{len(range_report.checked)} tunable(s) the header guards "
            "with an #if declare the guarded range."
        )
        return 0
```

with:

```python
    if report.clean and range_report.clean:
        # The same edge the Doctor's PASS row carries: R4 makes a header
        # that guards nothing the normal case, so it gets a clause rather
        # than the count zero. Touch one of the two and touch both.
        guard_clause = (
            f"the {len(range_report.checked)} tunable(s) the header guards "
            "with an #if declare the guarded range."
            if range_report.checked
            else "the header guards no tunable with an #if."
        )
        print(
            "garage_lint: OK -- every #define in "
            f"'{binding.config_h}' is classified in tunables.json, every "
            "tunables.json entry still exists in the header, and "
            f"{guard_clause}"
        )
        return 0
```

Note that `and the ` became `and ` — the `the` now lives inside the nonzero clause, so the nonzero sentence reads identically to before.

- [x] **Step 8: Run the lint tests to verify they pass**

Run: `python -m unittest tests.test_garage_lint -v`

Expected: OK, all methods — including `TestTheBoundGameRepositoryIsInStep`, which exercises the real header rather than a fixture.

- [x] **Step 9: Run the whole suite and the lint, and read the real OK line**

Run: `python -m unittest discover -s tests -p 'test_*.py'`
Expected: OK.

Run: `python tools/garage_lint.py`
Expected: exit 0. If a game repository is bound, read the printed OK sentence end to end and confirm it is grammatical — this task's entire product is that sentence, and no assertion checks that a human can read it.

- [x] **Step 10: Commit**

```bash
git add tools/garage/core/doctor.py tools/garage_lint.py tests/test_garage_core.py tests/test_garage_lint.py
git commit -m "fix: a header that guards nothing says so instead of counting zero (#23)"
```

---

## Done when

- [x] `python -m unittest discover -s tests -p 'test_*.py'` is green.
- [x] `python tools/garage_lint.py` exits 0.
- [ ] `make test-garage` is green (the Qt panel suite; anywhere from 3 to 13 minutes — size any timeout to the high end. Nothing here touches a panel, so this is a smoke check, not the gate). — not run; nothing on this branch touches a panel
- [x] Four commits, one per task, each naming `#23`.
- [x] Issue #23's first finding is **not** implemented, and `tools/garage/tunables.json` is unchanged — that was the scope decision, and a reviewer should see no diff there.
