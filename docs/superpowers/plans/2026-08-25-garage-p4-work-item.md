# Garage P4 — File a Work Item Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Garage file one GitHub issue for the tuning work in the active worktree — titled `chore:`, carrying the changed `#define` values, landed on the shared board with `Type = Chore` and `Status = Todo` — so the pull request that follows satisfies the PR Linked Issue workflow without that workflow being weakened.

**Architecture:** A Qt-free `tools/garage/core/workitem.py` owns everything worth testing: the changed-`#define` comparison against HEAD, the title rule, the issue body, the by-name resolution of project field and option ids, and the four-step `gh` sequence expressed against an injected runner seam. A section added to `tools/garage/panels/worktrees.py` wires a title field, a description field and one button to it, runs the sequence on a worker thread so the network never freezes the window, and copies `Closes #N` to the clipboard. `tools/garage/core/doctor.py` gains one row that separates "`gh` is absent" from "`gh` is present but unauthenticated".

**Tech Stack:** Python 3.13, standard-library `unittest`, PySide6 (panel layer only), `git` and `gh` 2.96.0 as subprocesses.

**Spec:** MatthieuGagne/nuke-raiders-garage#5 — "feat: Garage P4 — file a work item for tuning work on demand". Read it alongside this plan; every R and AC number below is its number.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.13, `unittest` only.** `pytest` is not installed in this repository and must not be used. No build step.
- **`tools/garage/core/` imports no Qt** (R10). `tests/test_garage_core.py::TestCoreImportsNoQt` rglobs `tools/garage/core/*.py` and fails on any `import`/`from` line containing `PySide6` or `shiboken`. A new core module is auto-enrolled.
- **No file under `tests/` may import Qt** (AC12). `make test` must pass with PySide6 absent. Panel coverage lives under `tests/garage/`, which has no `__init__.py`, so default discovery never descends into it. That omission is load-bearing.
- **No path into the game repository may be hardcoded** (R11). Resolve through `tools.garage.core.project.Binding`: `binding.active_worktree.path`, `binding.config_h`, `binding.resolve(...)`.
- **Anything that reads the game repository skips when none is bound.** CI checks this repository out alone. `bind()` raises `BindingError`; it never returns `None`. Panels take `Optional[Binding]` plus a `binding_error`, and the unbound path is *not* skipped in panel tests — it is the CI case.
- **No colour literal, no font family, no `setStyleSheet` in a panel.** `tests/garage/test_panels.py::TestNoColourLiteralInPanelSource` globs `tools/garage/panels/*.py`, so a new widget is auto-enrolled. Bans: bare `#rrggbb`, any `QColor(` other than the exact `QColor(TOKENS[...])`, `Qt.<colour>` constants, and `setStyleSheet(`. Styling comes from object names and string-valued dynamic properties, selected in `tools/garage/theme/qss.py`.
- **Board literals, copied verbatim from the `file-an-issue` skill.** Project "Nuke Raider — Documents" is number `3`, owner `MatthieuGagne`, id `PVT_kwHOAv4a5M4BepB5`. Those three are stable and may be constants. **Field ids and single-select option ids are regenerated when an option set is edited and must be resolved by name at the moment of use** (R5) from `gh project field-list 3 --owner MatthieuGagne --format json`. This is not a game-repository path, so R11 does not reach it.
- **The issue is filed in the game repository, not this one.** The active worktree belongs to `gmb-nuke-raider`, and the pull request the `Closes #N` serves targets its `master`. The `--repo` slug is derived from that repository's `origin` remote via `project.get_git_remote_url`; it is never spelled out.
- **The body goes to `gh` through `--body-file`, never through `--title`/`--body` inline.** Not for shell-quoting reasons — `subprocess.run` with an argv list never reaches a shell — but because the body is multi-paragraph markdown and a temp file is the form that stays readable when it is logged or retried.
- **Commit style:** `feat: lowercase sentence (#5)`, `test: …`, `fix: …`, `docs: …`. One commit per step that says "Commit".
- **Test targets:** `make test` for anything under `tools/garage/core/` and `tests/`; `make test-garage` for anything under `tools/garage/panels/`, `tools/garage/theme/` or `app.py`. Tasks 1–5 need `make test`; Tasks 6–7 need both.

## Three design decisions this plan makes, and why

**1. `gh` runs through an injected runner seam, not through `make_runner`.**

`commit.py` builds a `make_runner.Command` and streams it, and that is the right shape when the output *is* the product — a ninety-second pre-commit hook the user watches scroll. It is the wrong shape here. `make_runner.run` merges stderr into stdout and delivers everything through an `on_line` callback; it returns an exit code and no captured output. This sequence needs values, not lines: the issue URL feeds the board add, and the board add's JSON feeds both field edits. Scraping those back out of an interleaved stream would be fragile in exactly the place R8 demands reliability.

So `workitem.py` defines `run_capture(argv, cwd=None) -> CommandResult` over `subprocess.run(capture_output=True, text=True)`, and every I/O function takes `run: Runner = run_capture` as a keyword-only parameter. This follows the house seam convention already set by `doctor.run_checks`, which injects `which`, `environ` and `probe` the same way, and it is what makes R10 achievable: the whole sequence is testable with no network and no display.

**2. Field and option ids are resolved *before* the issue is created.**

R8's second sentence — "must never leave an issue on the board with `Type` or `Status` unset" — is a sequencing requirement, and there is no atomic API that satisfies it directly. `gh project item-edit` sets one field per invocation, and the item id only exists after `item-add`, which only accepts a URL that only exists after `issue create`. Four writes, no transaction.

What can be done is to move every *resolvable* failure ahead of the first write. `field-list` is a read; if `Type`'s field id, `Chore`'s option id, `Status`'s field id or `Todo`'s option id cannot be resolved by name, the sequence fails having created nothing. After that point the only remaining failures are transport, and a partial result is reported as one — `WorkItemFailure` carries the `WorkItem` built so far, naming exactly which of the three board properties is unset, and the panel offers "Finish the board entry", which resumes from the failed step against the issue that already exists. R9 is untouched: resuming files nothing new, and nothing here closes, edits or pushes.

**3. The panel gets its own worker thread rather than `RunController`.**

`RunController` runs a list of `make_runner.Command`s; this sequence cannot be expressed as one, per decision 1. Four network round trips on the UI thread would freeze the window for seconds, so `WorktreesPanel` gains a `QThread` and a worker object modelled on `runner.RunWorker`. That has a consequence Task 6 must not skip: a live `QThread` at teardown is a Windows fail-fast (`0xC0000409`, issue #8). `WorktreesPanel` therefore grows `stop_and_wait()`, `app.py` calls it when the worktrees dialog closes, and every panel test calls it in `tearDown`.

## What this plan does *not* build

- No push, no pull request, no branch delete, no issue close, no issue edit (R9, AC11). The button files one issue and sets two fields.
- No automatic filing at worktree creation or at commit (R2, AC2, AC3). Task 6's tests assert the absence.
- No change to `.github/workflows/pr-linked-issue.yml`, and no edit to the game repository's `docs/dev-workflow.md` — that file is tracked there, and recording the Garage route is R6 of MatthieuGagne/gmb-nuke-raider#613.
- No board *view*. There is no API that creates one.

## One thing the interactive prototype does not answer

`garage/index.html` has no work-item screen — the prototype covers worktrees, commit, assets and tuning, and stops there. This panel's layout is therefore designed fresh rather than transcribed, and Task 6 places it inside the existing worktrees dialog below the commit area, using the section spacing already established there. Nothing in this plan needs the prototype updated; it is a design reference, not a spec.

## File Structure

| File | Responsibility |
|---|---|
| **Create** `tools/garage/core/workitem.py` | Everything Qt-free: `ChangedDefine`, the HEAD comparison, the title rule, the body, the `CommandResult`/`Runner` seam, by-name project field resolution, and the four-step sequence with its partial-failure result. One module, because the spec names one and the pieces are one transaction. |
| **Modify** `tools/garage/core/doctor.py` | One `check_gh` row and one `probe_exit` seam. Nothing else moves. |
| **Modify** `tools/garage/panels/worktrees.py` | The work-item section, its visibility gate, the worker thread, `stop_and_wait()`, and the clipboard copy. |
| **Modify** `tools/garage/theme/qss.py` | Style rules for the new object names, and the matching bullets in `build_stylesheet`'s docstring index. |
| **Modify** `tools/garage/app.py` | Call `stop_and_wait()` when the worktrees dialog closes. |
| **Create** `tests/test_garage_workitem.py` | Core coverage. Reached by `make test`. No Qt import. |
| **Modify** `tests/test_garage_core.py` | The doctor key list and the toolchain fixture. |
| **Create** `tests/garage/test_panels_workitem.py` | Panel coverage, outside default discovery. |

---

## Task 1: The changed-`#define` comparison

Nothing in the repository computes a name/old/new triple today. `diff.py` produces raw textual hunks and `config_io.read_value_at_head` answers for one name at a time while warning against being called per row. The comparison is `config_io.read` against `config_io.read_config_at_head`, run once each.

**Files:**
- Create: `tools/garage/core/workitem.py`
- Test: `tests/test_garage_workitem.py`

**Interfaces:**
- Consumes: `config_io.read(binding, schema=None) -> ConfigFile`, `config_io.read_config_at_head(binding, schema=None) -> ConfigFile`, `config_io.ConfigIOError`, `ConfigFile.defines: Dict[str, DefineLine]`, `DefineLine.has_value: bool` / `.value: Optional[int]` / `.value_text: Optional[str]`, `project.Binding`.
- Produces: `ChangedDefine(name, head_text, new_text)`, `changed_defines(binding) -> List[ChangedDefine]`, `branch_commits(worktree, base="master") -> List[str]`, `refuse_reason(binding, changes, commits) -> Optional[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_garage_workitem.py`:

```python
"""Coverage for tools/garage/core/workitem.py — MatthieuGagne/nuke-raiders-garage#5.

No Qt import anywhere in this file, and no network. Must pass with PySide6
absent: `make test` discovers it, and that target installs no Qt.

Every `gh` call goes through the injected `run` seam, so the sequence is
exercised end to end against recorded output rather than against GitHub.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage.core import project, workitem  # noqa: E402

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"

CONFIG_H = """\
#ifndef CONFIG_H
#define CONFIG_H

#define PLAYER_SPEED 4
#define PLAYER_HANDLING 3u
#define TILE_BASE 0xDF80U
#define MAX_NPCS 8

#endif
"""


def tmp_root(tmp: str) -> Path:
    """A temporary directory, spelled the way Garage spells it. On Windows
    the system temp path is a short name; `resolve()` gives the long form
    git and Garage both report, so path comparisons hold.
    """
    return Path(tmp).resolve()


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_game_repo(path: Path, config_h: str = CONFIG_H) -> Path:
    """A real git repository with `src/config.h` committed at HEAD."""
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)
    (path / "src").mkdir(exist_ok=True)
    (path / "src" / "config.h").write_text(config_h, encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)
    _run_git(["remote", "add", "origin", GAME_REPO_REMOTE_URL], path)
    return path


def bind_over(root: Path, repo: Path) -> project.Binding:
    """A binding onto `repo`, recorded rather than detected — the fixture
    repository is not a sibling named `nuke-raider`.
    """
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


def edit_config(binding: project.Binding, replacements) -> None:
    text = binding.config_h.read_text(encoding="utf-8")
    for old, new in replacements:
        text = text.replace(old, new)
    binding.config_h.write_text(text, encoding="utf-8")


class TestChangedDefines(unittest.TestCase):
    """R4/AC5: each changed `#define`, with its value at HEAD and its new value."""

    def test_a_clean_worktree_has_no_changed_defines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            self.assertEqual(workitem.changed_defines(binding), [])

    def test_an_edited_define_reports_head_and_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(binding, [("#define PLAYER_SPEED 4", "#define PLAYER_SPEED 6")])

            changes = workitem.changed_defines(binding)

            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].name, "PLAYER_SPEED")
            self.assertEqual(changes[0].head_text, "4")
            self.assertEqual(changes[0].new_text, "6")

    def test_the_value_is_reported_as_written_not_as_parsed(self):
        # `0xDF80U` must not come back as `57216`: the issue body is read by
        # someone who will look the value up in config.h.
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(binding, [("#define TILE_BASE 0xDF80U", "#define TILE_BASE 0xDF00U")])

            changes = workitem.changed_defines(binding)

            self.assertEqual(changes[0].head_text, "0xDF80U")
            self.assertEqual(changes[0].new_text, "0xDF00U")

    def test_changes_are_ordered_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            edit_config(
                binding,
                [
                    ("#define PLAYER_SPEED 4", "#define PLAYER_SPEED 6"),
                    ("#define MAX_NPCS 8", "#define MAX_NPCS 9"),
                ],
            )

            names = [c.name for c in workitem.changed_defines(binding)]

            self.assertEqual(names, ["MAX_NPCS", "PLAYER_SPEED"])

    def test_a_define_added_since_head_is_not_a_change(self):
        # It has no value at HEAD, so there is no "from" to state. R4 asks
        # for a comparison, and a comparison needs two sides.
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            text = binding.config_h.read_text(encoding="utf-8")
            binding.config_h.write_text(
                text.replace("#endif", "#define BRAND_NEW 1\n\n#endif"), encoding="utf-8"
            )

            self.assertEqual(workitem.changed_defines(binding), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.garage.core.workitem'`, or `ImportError` on the `workitem` name.

- [ ] **Step 3: Write the minimal implementation**

Create `tools/garage/core/workitem.py`:

```python
"""Filing one GitHub issue for the work in the active worktree (#5). Pure
and Qt-free (R10): everything here composes text, parses recorded output,
or shells out through an injected runner, and none of it needs a display.

**Why this module exists at all.** `.github/workflows/pr-linked-issue.yml`
fails any pull request whose body holds no `Closes #N`, and tuning work
starts with no issue behind it. The alternative — an exemption keyed to a
branch prefix or a body marker — is asserted by whoever opens the pull
request, so it would be an opt-out available to everybody with a
Garage-flavoured name. Filing an issue costs one action and keeps the
property the workflow exists to protect.

**The issue is filed in the game repository**, whose worktree the work is
in and whose `master` the pull request will target. The slug comes from
that repository's `origin` remote; no path and no repository name is
spelled out here (R11).

**Nothing here pushes, opens a pull request, closes an issue or edits
one** (R9). The only write is `gh issue create`, plus the two field values
that put it on the board.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from tools.garage.core import config_io
from tools.garage.core.project import Binding

MASTER_BRANCHES = ("master", "main")


@dataclass(frozen=True)
class ChangedDefine:
    """One `#define` whose value in the worktree differs from HEAD (R4).

    Both values are the text as written — `0xDF80U`, `4u`, `32` — not the
    parsed integer. The body is read by someone who will go and look the
    value up in `config.h`, and a radix change on the way there is a lie.
    """

    name: str
    head_text: str
    new_text: str


def changed_defines(binding: Binding) -> List[ChangedDefine]:
    """Every `#define` that differs between the worktree and HEAD, by name.

    Two `git`-backed reads, once each: `config_io.read_value_at_head` warns
    in its own docstring against being called per row, because it re-runs
    `git show` every time.

    A `#define` that has no value at HEAD is not a change — there is no
    "from" to state — and neither is one that has no value now. Returns an
    empty list when either side cannot be read; the caller reports that
    through `refuse_reason`, not through an exception it would have to
    catch around a button press.
    """
    try:
        current = config_io.read(binding)
        head = config_io.read_config_at_head(binding)
    except config_io.ConfigIOError:
        return []

    changes = []
    for name in sorted(current.defines):
        new = current.defines[name]
        old = head.defines.get(name)
        if old is None or not old.has_value or not new.has_value:
            continue
        if old.value == new.value and old.value_text == new.value_text:
            continue
        changes.append(
            ChangedDefine(
                name=name,
                head_text=old.value_text or str(old.value),
                new_text=new.value_text or str(new.value),
            )
        )
    return changes
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Write the failing test for the commit list and the gate**

Append to `tests/test_garage_workitem.py`:

```python
class TestBranchCommits(unittest.TestCase):
    """AC1's other half: a worktree can have earned a work item through a
    commit rather than through an uncommitted edit.
    """

    def test_a_branch_at_master_has_no_commits_of_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(root / "game")

            self.assertEqual(workitem.branch_commits(repo), [])

    def test_a_commit_on_a_branch_is_listed_subject_and_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            repo = make_game_repo(root / "game")
            _run_git(["checkout", "-b", "tune-speed"], repo)
            (repo / "src" / "config.h").write_text(
                CONFIG_H.replace("PLAYER_SPEED 4", "PLAYER_SPEED 6"), encoding="utf-8"
            )
            _run_git(["commit", "-am", "tune player speed"], repo)

            commits = workitem.branch_commits(repo)

            self.assertEqual(len(commits), 1)
            self.assertTrue(commits[0].endswith("tune player speed"))

    def test_an_unreadable_worktree_yields_no_commits_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)

            self.assertEqual(workitem.branch_commits(root / "nowhere"), [])


class TestRefuseReason(unittest.TestCase):
    """AC1: the action is absent until there is something to file about."""

    def test_no_binding_is_refused(self):
        reason = workitem.refuse_reason(None, [], [])

        self.assertIsNotNone(reason)
        self.assertIn("No repository is bound", reason)

    def test_a_clean_worktree_with_no_commits_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            reason = workitem.refuse_reason(binding, [], [])

            self.assertIsNotNone(reason)
            self.assertIn("nothing to file", reason)

    def test_one_changed_define_is_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))
            change = workitem.ChangedDefine("PLAYER_SPEED", "4", "6")

            self.assertIsNone(workitem.refuse_reason(binding, [change], []))

    def test_one_commit_is_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tmp_root(tmp)
            binding = bind_over(root, make_game_repo(root / "game"))

            self.assertIsNone(workitem.refuse_reason(binding, [], ["abc1234 tune"]))
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.workitem' has no attribute 'branch_commits'`.

- [ ] **Step 7: Implement**

Append to `tools/garage/core/workitem.py`:

```python
def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )


def branch_commits(worktree: Path, count: int = 20) -> List[str]:
    """`<short sha> <subject>` for the commits this branch holds that its
    base does not, newest first. Empty when the branch is at its base, when
    no base is found, or when the worktree cannot be read.

    The base is whichever of `master` or `main` this repository actually
    has — the game repository uses `master`, but naming one branch here
    would be a second place to change if that ever moved.
    """
    for base in MASTER_BRANCHES:
        probe = _git(["rev-parse", "--verify", "--quiet", base], worktree)
        if probe.returncode != 0:
            continue
        result = _git(
            ["log", f"-{count}", "--format=%h %s", f"{base}..HEAD"], worktree
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    return []


def refuse_reason(
    binding: Optional[Binding],
    changes: Sequence[ChangedDefine],
    commits: Sequence[str],
) -> Optional[str]:
    """Why no work item may be filed, or None when one may (AC1).

    The binding is checked first, so a user with nothing bound is told the
    thing they cannot fix by editing a value.
    """
    if binding is None:
        return "No repository is bound; there is nothing to file a work item for."
    if not changes and not commits:
        return (
            "This worktree holds no changed value and no commit of its own, "
            "so there is nothing to file a work item about."
        )
    return None
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: PASS, 12 tests.

- [ ] **Step 9: Commit**

```bash
git add tools/garage/core/workitem.py tests/test_garage_workitem.py
git commit -m "feat: compare the worktree's #define values against HEAD for a work item (#5)"
```

---

## Task 2: The title rule and the issue body

**Files:**
- Modify: `tools/garage/core/workitem.py`
- Test: `tests/test_garage_workitem.py`

**Interfaces:**
- Consumes: `ChangedDefine` from Task 1.
- Produces: `title_for(raw) -> str`, `compose_body(changes, description, branch, commits) -> str`, `closes_line(number) -> str`, `TITLE_PREFIX`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_workitem.py`:

```python
class TestTitle(unittest.TestCase):
    """R3/AC4: the title starts with `chore:`, which is what gives the
    board `Type = Chore` when a human reads it back.
    """

    def test_a_bare_title_gains_the_prefix(self):
        self.assertEqual(workitem.title_for("tune player speed"), "chore: tune player speed")

    def test_a_title_that_already_has_the_prefix_does_not_gain_a_second(self):
        self.assertEqual(
            workitem.title_for("chore: tune player speed"), "chore: tune player speed"
        )

    def test_the_prefix_is_recognised_whatever_its_case_and_spacing(self):
        self.assertEqual(workitem.title_for("Chore:tune speed"), "chore: tune speed")

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(workitem.title_for("  tune speed  "), "chore: tune speed")

    def test_an_empty_title_is_refused_rather_than_prefixed(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.title_for("   ")


class TestBody(unittest.TestCase):
    """R4/AC5: the body lists each changed `#define` with both values."""

    CHANGES = [
        workitem.ChangedDefine("MAX_NPCS", "8", "9"),
        workitem.ChangedDefine("PLAYER_SPEED", "4", "6"),
    ]

    def test_every_changed_define_appears_with_both_values(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("PLAYER_SPEED", body)
        self.assertIn("`4`", body)
        self.assertIn("`6`", body)
        self.assertIn("MAX_NPCS", body)
        self.assertIn("`8`", body)
        self.assertIn("`9`", body)

    def test_the_description_leads_the_body(self):
        body = workitem.compose_body(self.CHANGES, "The car turns too late.", "b", [])

        self.assertTrue(body.startswith("The car turns too late."))

    def test_a_body_with_no_description_still_lists_the_changes(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("PLAYER_SPEED", body)
        self.assertNotIn("\n\n\n", body)

    def test_no_changed_define_says_so_rather_than_showing_an_empty_table(self):
        body = workitem.compose_body([], "", "tune-speed", ["abc1234 tune"])

        self.assertIn("No `#define` differs from HEAD", body)
        self.assertNotIn("| HEAD |", body)

    def test_commits_are_listed_when_there_are_any(self):
        body = workitem.compose_body([], "", "tune-speed", ["abc1234 tune player speed"])

        self.assertIn("abc1234 tune player speed", body)

    def test_the_branch_is_named_so_the_issue_can_be_traced_back(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("tune-speed", body)

    def test_the_body_says_garage_filed_it(self):
        body = workitem.compose_body(self.CHANGES, "", "tune-speed", [])

        self.assertIn("Garage", body)


class TestClosesLine(unittest.TestCase):
    """R6/AC8: what goes on the clipboard is what the workflow greps for."""

    def test_the_line_is_the_form_the_workflow_matches(self):
        self.assertEqual(workitem.closes_line(614), "Closes #614")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.workitem' has no attribute 'title_for'`.

- [ ] **Step 3: Implement**

Append to `tools/garage/core/workitem.py`:

```python
TITLE_PREFIX = "chore:"

_PREFIX_RE = re.compile(r"^\s*chore\s*:\s*", re.IGNORECASE)


class WorkItemError(Exception):
    """A refusal Garage makes on its own, before any `gh` call."""


def title_for(raw: str) -> str:
    """`chore: <what the user typed>` (R3/AC4).

    The prefix is what gives the board `Type = Chore` when the conventions
    are read back by a human, so it is applied here rather than left to the
    user to remember. An existing prefix is normalised, not doubled — a
    user who types the convention correctly must not be punished with
    `chore: chore: …`.
    """
    stripped = (raw or "").strip()
    if not stripped:
        raise WorkItemError("A work item needs a title.")
    body = _PREFIX_RE.sub("", stripped).strip()
    if not body:
        raise WorkItemError("A work item needs a title beyond the `chore:` prefix.")
    return f"{TITLE_PREFIX} {body}"


def closes_line(number: int) -> str:
    """The reference `.github/workflows/pr-linked-issue.yml` greps for.

    Spelled here rather than at the call site because it is the one string
    in this module whose exact form another repository's CI depends on.
    """
    return f"Closes #{number}"


def compose_body(
    changes: Sequence[ChangedDefine],
    description: str,
    branch: Optional[str],
    commits: Sequence[str],
) -> str:
    """The issue body: what the user said, what changed, and where.

    The parameter table is the part R4 requires and the part a reviewer
    actually reads — an issue that says "tuned the handling" and nothing
    else cannot be checked against the diff six weeks later.
    """
    parts: List[str] = []

    text = (description or "").strip()
    if text:
        parts.append(text)

    if changes:
        rows = "\n".join(
            f"| `{c.name}` | `{c.head_text}` | `{c.new_text}` |" for c in changes
        )
        parts.append(
            "## Changed parameters\n\n"
            "| `#define` | At HEAD | New |\n"
            "|---|---|---|\n" + rows
        )
    else:
        parts.append(
            "## Changed parameters\n\n"
            "No `#define` differs from HEAD; this work item covers the "
            "commits below."
        )

    if commits:
        listed = "\n".join(f"- `{line}`" for line in commits)
        parts.append("## Commits\n\n" + listed)

    where = f"Filed by Garage from the `{branch}` worktree." if branch else "Filed by Garage."
    parts.append(where)

    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: PASS, 26 tests.

- [ ] **Step 5: Commit**

```bash
git add tools/garage/core/workitem.py tests/test_garage_workitem.py
git commit -m "feat: compose the work item's title and body (#5)"
```

---

## Task 3: The runner seam, the repository slug, and by-name field resolution

R5 is the requirement with the sharpest failure mode: option ids are regenerated whenever an option set is edited, so an id captured today is a time bomb. Everything is resolved by name, at the moment of use.

**Files:**
- Modify: `tools/garage/core/workitem.py`
- Test: `tests/test_garage_workitem.py`

**Interfaces:**
- Produces: `CommandResult(argv, exit_code, stdout, stderr)` with `.ok`, `Runner`, `run_capture`, `PROJECT_NUMBER`, `PROJECT_OWNER`, `PROJECT_ID`, `repo_slug(url) -> Optional[str]`, `resolve_option(fields, field_name, option_name) -> Tuple[str, str]`, `issue_number(url) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_workitem.py`:

```python
# The shape `gh project field-list 3 --owner MatthieuGagne --format json`
# returns, trimmed to the two single-select fields this spec sets. Recorded
# from gh 2.96.0 on 2026-08-25. The ids below are deliberately not the real
# ones: nothing may pass by matching a literal a future edit will change.
FIELD_LIST_JSON = json.dumps(
    {
        "fields": [
            {"id": "PVTF_title", "name": "Title", "type": "ProjectV2Field"},
            {
                "id": "PVTSSF_status",
                "name": "Status",
                "type": "ProjectV2SingleSelectField",
                "options": [
                    {"id": "opt_todo", "name": "Todo"},
                    {"id": "opt_wip", "name": "In Progress"},
                    {"id": "opt_done", "name": "Done"},
                ],
            },
            {
                "id": "PVTSSF_type",
                "name": "Type",
                "type": "ProjectV2SingleSelectField",
                "options": [
                    {"id": "opt_epic", "name": "Epic"},
                    {"id": "opt_prd", "name": "PRD"},
                    {"id": "opt_chore", "name": "Chore"},
                ],
            },
        ],
        "totalCount": 3,
    }
)


class TestRepoSlug(unittest.TestCase):
    """The issue is filed in the game repository, resolved from its remote."""

    def test_an_https_remote_yields_owner_and_name(self):
        self.assertEqual(
            workitem.repo_slug("https://github.com/MatthieuGagne/gmb-nuke-raider.git"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_a_remote_without_the_git_suffix_still_yields_the_slug(self):
        self.assertEqual(
            workitem.repo_slug("https://github.com/MatthieuGagne/gmb-nuke-raider"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_an_ssh_remote_yields_the_same_slug(self):
        self.assertEqual(
            workitem.repo_slug("git@github.com:MatthieuGagne/gmb-nuke-raider.git"),
            "MatthieuGagne/gmb-nuke-raider",
        )

    def test_something_that_is_not_a_github_remote_yields_nothing(self):
        self.assertIsNone(workitem.repo_slug("https://example.com/whatever"))

    def test_no_remote_yields_nothing(self):
        self.assertIsNone(workitem.repo_slug(None))


class TestResolveOption(unittest.TestCase):
    """R5: field ids and option ids are resolved by name, never recorded."""

    def setUp(self):
        self.fields = json.loads(FIELD_LIST_JSON)["fields"]

    def test_type_chore_resolves_to_its_field_and_option(self):
        field_id, option_id = workitem.resolve_option(self.fields, "Type", "Chore")

        self.assertEqual(field_id, "PVTSSF_type")
        self.assertEqual(option_id, "opt_chore")

    def test_status_todo_resolves_to_its_field_and_option(self):
        field_id, option_id = workitem.resolve_option(self.fields, "Status", "Todo")

        self.assertEqual(field_id, "PVTSSF_status")
        self.assertEqual(option_id, "opt_todo")

    def test_an_unknown_field_names_the_field_in_the_refusal(self):
        with self.assertRaises(workitem.WorkItemError) as caught:
            workitem.resolve_option(self.fields, "Priority", "High")

        self.assertIn("Priority", str(caught.exception))

    def test_an_unknown_option_names_both_the_field_and_the_option(self):
        with self.assertRaises(workitem.WorkItemError) as caught:
            workitem.resolve_option(self.fields, "Type", "Sonnet")

        self.assertIn("Type", str(caught.exception))
        self.assertIn("Sonnet", str(caught.exception))

    def test_a_field_with_no_options_is_refused_rather_than_crashing(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.resolve_option(self.fields, "Title", "Anything")


class TestIssueNumber(unittest.TestCase):
    """`gh issue create` answers with a URL; AC7 shows a number."""

    def test_the_number_is_read_off_the_url_gh_prints(self):
        self.assertEqual(
            workitem.issue_number(
                "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"
            ),
            614,
        )

    def test_trailing_whitespace_and_noise_do_not_defeat_it(self):
        self.assertEqual(
            workitem.issue_number(
                "Creating issue\nhttps://github.com/MatthieuGagne/gmb-nuke-raider/issues/7\n"
            ),
            7,
        )

    def test_output_with_no_url_is_refused(self):
        with self.assertRaises(workitem.WorkItemError):
            workitem.issue_number("something went sideways")


class TestRunCapture(unittest.TestCase):
    """The seam itself: a real subprocess, since a mock would prove nothing
    about the shape the rest of the module depends on.
    """

    def test_stdout_exit_code_and_argv_come_back(self):
        result = workitem.run_capture([sys.executable, "-c", "print('hi')"])

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_a_failing_command_is_not_ok_and_keeps_its_stderr(self):
        result = workitem.run_capture(
            [sys.executable, "-c", "import sys; sys.stderr.write('nope'); sys.exit(3)"]
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 3)
        self.assertIn("nope", result.stderr)

    def test_a_command_that_cannot_start_is_a_result_not_an_exception(self):
        # A button press must not raise out of a worker thread.
        result = workitem.run_capture(["no-such-tool-anywhere-at-all"])

        self.assertFalse(result.ok)
        self.assertNotEqual(result.exit_code, 0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.workitem' has no attribute 'repo_slug'`.

- [ ] **Step 3: Implement**

Append to `tools/garage/core/workitem.py`:

```python
# The shared board, from the `file-an-issue` skill. These three are stable
# literals; the field and option ids below them are not, and are resolved
# by name every time (R5).
PROJECT_NUMBER = "3"
PROJECT_OWNER = "MatthieuGagne"
PROJECT_ID = "PVT_kwHOAv4a5M4BepB5"

TYPE_FIELD = "Type"
TYPE_OPTION = "Chore"
STATUS_FIELD = "Status"
STATUS_OPTION = "Todo"

_SLUG_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$")
_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


@dataclass(frozen=True)
class CommandResult:
    argv: Sequence[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def message(self) -> str:
        """What the tool said, preferring stderr — which is where `gh` puts
        the reason a call was refused (R8 shows this verbatim).
        """
        return (self.stderr.strip() or self.stdout.strip()) or (
            f"`{' '.join(self.argv)}` failed with exit code {self.exit_code} "
            f"and said nothing."
        )


Runner = Callable[..., CommandResult]

EXIT_NOT_STARTED = 127


def run_capture(argv: Sequence[str], cwd: Optional[Path] = None) -> CommandResult:
    """Run `argv` and capture everything, without a shell.

    Never raises. A `gh` call happens behind a button, on a worker thread,
    and an exception crossing that boundary is a crash rather than a
    message in the window (R8).
    """
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return CommandResult(
            argv=tuple(argv), exit_code=EXIT_NOT_STARTED, stdout="", stderr=str(exc)
        )
    return CommandResult(
        argv=tuple(argv),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def repo_slug(remote_url: Optional[str]) -> Optional[str]:
    """`owner/name` for a GitHub remote, or None when it is not one.

    Derived rather than spelled out: the game repository's name appears
    nowhere in Garage (R11), and a user working against a fork must not
    have their work item filed against somebody else's repository.
    """
    if not remote_url:
        return None
    match = _SLUG_RE.search(remote_url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def issue_number(create_output: str) -> int:
    """The number in the issue URL `gh issue create` prints (AC7)."""
    match = _ISSUE_URL_RE.search(create_output or "")
    if not match:
        raise WorkItemError(
            "`gh issue create` did not print an issue URL, so Garage cannot "
            "say which issue it filed. Check the repository on GitHub before "
            "filing again — one may already exist."
        )
    return int(match.group(1))


def resolve_option(fields, field_name: str, option_name: str):
    """`(field_id, option_id)` for one single-select value, by name (R5).

    Option ids are regenerated whenever the option set is edited, so
    recording one would work until the day somebody renames a `Type` and
    then silently write the wrong value. Both halves are looked up every
    time, and a name that is gone is a refusal — never a guess.
    """
    for field in fields or ():
        if field.get("name") != field_name:
            continue
        options = field.get("options") or []
        if not options:
            raise WorkItemError(
                f"The board's `{field_name}` field carries no options, so "
                f"`{option_name}` cannot be resolved."
            )
        for option in options:
            if option.get("name") == option_name:
                return field["id"], option["id"]
        available = ", ".join(o.get("name", "?") for o in options)
        raise WorkItemError(
            f"The board's `{field_name}` field has no `{option_name}` "
            f"option. It offers: {available}."
        )
    raise WorkItemError(
        f"The board has no `{field_name}` field, so Garage cannot set it."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: PASS, 42 tests.

- [ ] **Step 5: Commit**

```bash
git add tools/garage/core/workitem.py tests/test_garage_workitem.py
git commit -m "feat: resolve the board's field and option ids by name (#5)"
```

---

## Task 4: The four-step sequence, and what it does when a step fails

**Files:**
- Modify: `tools/garage/core/workitem.py`
- Test: `tests/test_garage_workitem.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `WorkItem(number, url, on_board, type_set, status_set)` with `.complete`, `WorkItemFailure(step, message, item)`, `file_work_item(binding, title, description, *, changes=None, commits=None, existing=None, run=run_capture) -> Union[WorkItem, WorkItemFailure]`, and the step constants `STEP_FIELDS`, `STEP_CREATE`, `STEP_BOARD`, `STEP_TYPE`, `STEP_STATUS`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_garage_workitem.py`:

```python
ISSUE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"
ITEM_ADD_JSON = json.dumps({"id": "PVTI_item614", "title": "chore: tune speed"})


class FakeRunner:
    """A `Runner` that answers from a script rather than from GitHub.

    Keyed on the first two argv words (`gh issue`, `gh project`) plus the
    subcommand, because that is the granularity the sequence branches on.
    Records every call so a test can assert what was and was not run — R9
    is a requirement about calls that must not happen.
    """

    def __init__(self, **overrides):
        self.calls = []
        self.responses = {
            "field-list": CommandOK(FIELD_LIST_JSON),
            "create": CommandOK(ISSUE_URL + "\n"),
            "item-add": CommandOK(ITEM_ADD_JSON),
            "item-edit": CommandOK(""),
        }
        self.responses.update(overrides)

    def __call__(self, argv, cwd=None):
        argv = list(argv)
        self.calls.append(argv)
        for key, response in self.responses.items():
            if key in argv:
                return workitem.CommandResult(
                    argv=tuple(argv),
                    exit_code=response.exit_code,
                    stdout=response.stdout,
                    stderr=response.stderr,
                )
        raise AssertionError(f"the fake runner has no answer for {argv}")

    def ran(self, needle) -> bool:
        return any(needle in call for call in self.calls)

    def edited_fields(self):
        """The (field-id, option-id) pairs the sequence actually set."""
        pairs = []
        for call in self.calls:
            if "item-edit" not in call:
                continue
            pairs.append(
                (
                    call[call.index("--field-id") + 1],
                    call[call.index("--single-select-option-id") + 1],
                )
            )
        return pairs


class CommandOK:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code


def CommandFail(stderr, exit_code=1):
    return CommandOK(stdout="", stderr=stderr, exit_code=exit_code)


class WorkItemSequenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = tmp_root(self._tmp.name)
        self.repo = make_game_repo(self.root / "game")
        self.binding = bind_over(self.root, self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def file_it(self, runner, **kwargs):
        return workitem.file_work_item(
            self.binding,
            "tune speed",
            "The car turns too late.",
            changes=[workitem.ChangedDefine("PLAYER_SPEED", "4", "6")],
            commits=[],
            run=runner,
            **kwargs,
        )


class TestHappyPath(WorkItemSequenceTestCase):
    """AC6, AC7: the issue lands on the board, typed and statused."""

    def test_the_issue_number_comes_back(self):
        result = self.file_it(FakeRunner())

        self.assertIsInstance(result, workitem.WorkItem)
        self.assertEqual(result.number, 614)
        self.assertTrue(result.complete)

    def test_both_fields_are_set_from_the_resolved_ids(self):
        runner = FakeRunner()

        self.file_it(runner)

        self.assertEqual(
            sorted(runner.edited_fields()),
            sorted([("PVTSSF_type", "opt_chore"), ("PVTSSF_status", "opt_todo")]),
        )

    def test_the_fields_are_resolved_before_anything_is_created(self):
        # R8: a name that cannot be resolved must fail while nothing exists.
        runner = FakeRunner()

        self.file_it(runner)

        first = runner.calls[0]
        self.assertIn("field-list", first)

    def test_the_title_is_prefixed_on_the_way_to_gh(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        self.assertEqual(create[create.index("--title") + 1], "chore: tune speed")

    def test_the_body_travels_as_a_file_that_does_not_outlive_the_call(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        body_path = Path(create[create.index("--body-file") + 1])
        self.assertFalse(body_path.exists(), "the body file was left behind")

    def test_the_issue_is_filed_against_the_game_repository(self):
        runner = FakeRunner()

        self.file_it(runner)

        create = next(c for c in runner.calls if "create" in c)
        self.assertEqual(
            create[create.index("--repo") + 1], "MatthieuGagne/gmb-nuke-raider"
        )

    def test_nothing_pushes_closes_or_opens_a_pull_request(self):
        # R9/AC11, asserted rather than assumed.
        runner = FakeRunner()

        self.file_it(runner)

        for banned in ("push", "close", "pr", "delete", "edit"):
            self.assertFalse(
                runner.ran(banned), f"the sequence ran a `{banned}` subcommand"
            )


class TestFailures(WorkItemSequenceTestCase):
    """AC10: GitHub's own message, and never a half-typed board entry left
    without anyone being told.
    """

    def test_an_unresolvable_option_fails_before_the_issue_is_created(self):
        runner = FakeRunner(**{"field-list": CommandOK(json.dumps({"fields": []}))})

        result = self.file_it(runner)

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(result.step, workitem.STEP_FIELDS)
        self.assertIsNone(result.item)
        self.assertFalse(runner.ran("create"))

    def test_a_field_list_that_gh_refuses_reports_ghs_message(self):
        runner = FakeRunner(
            **{"field-list": CommandFail("gh: Your token has not been granted 'project'")}
        )

        result = self.file_it(runner)

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertIn("'project'", result.message)

    def test_a_refused_create_leaves_no_issue_and_says_why(self):
        runner = FakeRunner(**{"create": CommandFail("gh: Not Found (HTTP 404)")})

        result = self.file_it(runner)

        self.assertEqual(result.step, workitem.STEP_CREATE)
        self.assertIsNone(result.item)
        self.assertIn("404", result.message)

    def test_a_failed_board_add_names_the_issue_that_now_exists(self):
        runner = FakeRunner(**{"item-add": CommandFail("gh: could not add item")})

        result = self.file_it(runner)

        self.assertEqual(result.step, workitem.STEP_BOARD)
        self.assertIsNotNone(result.item)
        self.assertEqual(result.item.number, 614)
        self.assertFalse(result.item.on_board)
        self.assertFalse(result.item.complete)

    def test_a_failed_status_edit_reports_type_as_set_and_status_as_not(self):
        calls = {"n": 0}
        base = FakeRunner()

        def flaky(argv, cwd=None):
            argv = list(argv)
            if "item-edit" in argv:
                calls["n"] += 1
                if calls["n"] == 2:
                    return workitem.CommandResult(
                        argv=tuple(argv), exit_code=1, stdout="", stderr="gh: 502"
                    )
            return base(argv, cwd)

        result = self.file_it(flaky)

        self.assertEqual(result.step, workitem.STEP_STATUS)
        self.assertTrue(result.item.on_board)
        self.assertTrue(result.item.type_set)
        self.assertFalse(result.item.status_set)
        self.assertIn("502", result.message)

    def test_resuming_from_a_partial_result_files_no_second_issue(self):
        # The panel's "Finish the board entry" path (R9: nothing new is filed).
        runner = FakeRunner()
        partial = workitem.WorkItem(
            number=614, url=ISSUE_URL, on_board=False, type_set=False, status_set=False
        )

        result = self.file_it(runner, existing=partial)

        self.assertIsInstance(result, workitem.WorkItem)
        self.assertTrue(result.complete)
        self.assertFalse(runner.ran("create"))


class TestRefusalsBeforeAnyCall(WorkItemSequenceTestCase):
    def test_an_empty_title_never_reaches_gh(self):
        runner = FakeRunner()

        result = workitem.file_work_item(
            self.binding, "   ", "", changes=[], commits=["abc1234 x"], run=runner
        )

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(runner.calls, [])

    def test_a_worktree_with_nothing_in_it_never_reaches_gh(self):
        runner = FakeRunner()

        result = workitem.file_work_item(
            self.binding, "tune speed", "", changes=[], commits=[], run=runner
        )

        self.assertIsInstance(result, workitem.WorkItemFailure)
        self.assertEqual(runner.calls, [])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: FAIL — `AttributeError: module 'tools.garage.core.workitem' has no attribute 'file_work_item'`.

- [ ] **Step 3: Implement**

Append to `tools/garage/core/workitem.py`:

```python
import json
import tempfile

from tools.garage.core.project import get_git_remote_url

STEP_FIELDS = "resolve the board's fields"
STEP_CREATE = "create the issue"
STEP_BOARD = "add the issue to the board"
STEP_TYPE = "set Type"
STEP_STATUS = "set Status"


@dataclass(frozen=True)
class WorkItem:
    """An issue Garage filed, and how far onto the board it got.

    The three booleans exist because the board is reached in three separate
    writes and R8 forbids leaving any of them silently undone. A caller
    that sees `complete is False` has something to tell the user.
    """

    number: int
    url: str
    on_board: bool = False
    type_set: bool = False
    status_set: bool = False

    @property
    def complete(self) -> bool:
        return self.on_board and self.type_set and self.status_set


@dataclass(frozen=True)
class WorkItemFailure:
    """A step that did not happen, in GitHub's own words (R8/AC10).

    `item` is None when nothing was created, and otherwise carries exactly
    what does exist — which is what the panel offers to finish.
    """

    step: str
    message: str
    item: Optional[WorkItem] = None

    @property
    def text(self) -> str:
        lead = f"Garage could not {self.step}: {self.message}"
        if self.item is None:
            return lead + "\nNo issue was created."
        missing = []
        if not self.item.on_board:
            missing.append("it is not on the board")
        else:
            if not self.item.type_set:
                missing.append("Type is unset")
            if not self.item.status_set:
                missing.append("Status is unset")
        return (
            f"{lead}\nIssue #{self.item.number} exists ({self.item.url}), but "
            f"{', and '.join(missing)}."
        )


def _gh_project(*args: str) -> List[str]:
    return ["gh", "project", *args]


def _field_list_argv() -> List[str]:
    return _gh_project(
        "field-list", PROJECT_NUMBER, "--owner", PROJECT_OWNER, "--format", "json"
    )


def _item_edit_argv(item_id: str, field_id: str, option_id: str) -> List[str]:
    return _gh_project(
        "item-edit",
        "--id",
        item_id,
        "--project-id",
        PROJECT_ID,
        "--field-id",
        field_id,
        "--single-select-option-id",
        option_id,
    )


def file_work_item(
    binding: Optional[Binding],
    title: str,
    description: str,
    *,
    changes: Optional[Sequence[ChangedDefine]] = None,
    commits: Optional[Sequence[str]] = None,
    existing: Optional[WorkItem] = None,
    run: Runner = run_capture,
):
    """File one issue for the active worktree and put it on the board.

    Returns a `WorkItem` when every step succeeded, and a
    `WorkItemFailure` otherwise. Nothing raises: this runs behind a button,
    on a worker thread.

    The order is deliberate (R8). `field-list` is a read, and it comes
    first, so a `Type` or `Status` option that has been renamed fails while
    nothing exists yet. After the issue is created there is no transaction
    to fall back on — GitHub sets one field per call — so a later failure
    is reported as a partial `WorkItem` and the caller may pass it back as
    `existing` to finish the remaining steps. Resuming files no second
    issue.
    """
    changes = list(changes or [])
    commits = list(commits or [])

    if existing is None:
        refusal = refuse_reason(binding, changes, commits)
        if refusal:
            return WorkItemFailure(step=STEP_CREATE, message=refusal)
        try:
            full_title = title_for(title)
        except WorkItemError as exc:
            return WorkItemFailure(step=STEP_CREATE, message=str(exc))
    else:
        full_title = title_for(title) if title.strip() else ""

    assert binding is not None  # refuse_reason has already returned otherwise

    # Step 1 — resolve both field/option pairs by name, before any write.
    listed = run(_field_list_argv())
    if not listed.ok:
        return WorkItemFailure(step=STEP_FIELDS, message=listed.message)
    try:
        fields = json.loads(listed.stdout or "{}").get("fields", [])
        type_field, type_option = resolve_option(fields, TYPE_FIELD, TYPE_OPTION)
        status_field, status_option = resolve_option(
            fields, STATUS_FIELD, STATUS_OPTION
        )
    except (ValueError, WorkItemError) as exc:
        return WorkItemFailure(step=STEP_FIELDS, message=str(exc))

    # Step 2 — the issue itself.
    item = existing
    if item is None:
        slug = repo_slug(get_git_remote_url(binding.game_repo))
        if slug is None:
            return WorkItemFailure(
                step=STEP_CREATE,
                message=(
                    "The bound repository has no GitHub `origin` remote, so "
                    "Garage cannot tell which repository to file in."
                ),
            )
        body = compose_body(
            changes, description, binding.active_worktree.branch, commits
        )
        created = _create_issue(run, slug, full_title, body, binding)
        if isinstance(created, WorkItemFailure):
            return created
        item = created

    # Step 3 — the board.
    if not item.on_board:
        added = run(
            _gh_project(
                "item-add",
                PROJECT_NUMBER,
                "--owner",
                PROJECT_OWNER,
                "--url",
                item.url,
                "--format",
                "json",
            )
        )
        if not added.ok:
            return WorkItemFailure(step=STEP_BOARD, message=added.message, item=item)
        try:
            item_id = json.loads(added.stdout or "{}")["id"]
        except (ValueError, KeyError):
            return WorkItemFailure(
                step=STEP_BOARD,
                message=(
                    "`gh project item-add` printed no item id, so Garage "
                    "cannot set Type or Status."
                ),
                item=item,
            )
        item = replace(item, on_board=True)
    else:
        found = _find_item_id(run, item.url)
        if isinstance(found, WorkItemFailure):
            return replace(found, item=item)
        item_id = found

    # Step 4 — the two fields, Type first: it is the one that decides how
    # the board groups the issue, so a failure between them leaves the more
    # useful half done.
    for step, field_id, option_id, attribute in (
        (STEP_TYPE, type_field, type_option, "type_set"),
        (STEP_STATUS, status_field, status_option, "status_set"),
    ):
        if getattr(item, attribute):
            continue
        edited = run(_item_edit_argv(item_id, field_id, option_id))
        if not edited.ok:
            return WorkItemFailure(step=step, message=edited.message, item=item)
        item = replace(item, **{attribute: True})

    return item


def _create_issue(run: Runner, slug: str, title: str, body: str, binding: Binding):
    """`gh issue create`, with the body in a file rather than an argument.

    The file is removed whatever happens: a body left in the temp directory
    is a copy of work-in-progress notes nobody asked to keep.
    """
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False, newline="\n"
    )
    try:
        handle.write(body)
        handle.close()
        created = run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                slug,
                "--title",
                title,
                "--body-file",
                handle.name,
            ],
            binding.active_worktree.path,
        )
    finally:
        Path(handle.name).unlink(missing_ok=True)

    if not created.ok:
        return WorkItemFailure(step=STEP_CREATE, message=created.message)
    try:
        number = issue_number(created.stdout)
    except WorkItemError as exc:
        return WorkItemFailure(step=STEP_CREATE, message=str(exc))
    return WorkItem(number=number, url=_ISSUE_URL_RE.search(created.stdout).group(0))


def _find_item_id(run: Runner, url: str):
    """The board item id for an issue already on the board — needed only on
    the resume path, where the `item-add` that would have printed it has
    already succeeded in an earlier attempt.
    """
    listed = run(
        _gh_project(
            "item-list",
            PROJECT_NUMBER,
            "--owner",
            PROJECT_OWNER,
            "--limit",
            "500",
            "--format",
            "json",
        )
    )
    if not listed.ok:
        return WorkItemFailure(step=STEP_BOARD, message=listed.message)
    try:
        items = json.loads(listed.stdout or "{}").get("items", [])
    except ValueError:
        items = []
    for entry in items:
        if entry.get("content", {}).get("url") == url:
            return entry["id"]
    return WorkItemFailure(
        step=STEP_BOARD,
        message=f"{url} is not on the board, so its fields cannot be set.",
    )
```

Add `replace` to the dataclasses import at the top of the module: `from dataclasses import dataclass, replace`. Move the `json` and `tempfile` imports up into the module's import block rather than leaving them where this step appended them — the file keeps one import block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_workitem -v`
Expected: PASS, 58 tests.

- [ ] **Step 5: Run the whole Qt-free suite**

Run: `make test`
Expected: OK. The count rises by the new file's tests; nothing else moves.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/workitem.py tests/test_garage_workitem.py
git commit -m "feat: file the work item and put it on the board, resolving ids first (#5)"
```

---

## Task 5: The `gh` doctor row

R7 and AC9 want two distinct failures, reported before the user reaches the action. `probe_version` cannot serve: it returns a version token and discards the exit code, and every existing doctor test stubs it as `probe=lambda command: "1.2.3"` for *every* command, so an auth check built on it would be untestable in the harness that already exists. This task adds an honest second seam.

**Files:**
- Modify: `tools/garage/core/doctor.py`
- Modify: `tests/test_garage_core.py`

**Interfaces:**
- Consumes: `doctor.Which`, `doctor.VersionProbe`, `doctor.CheckResult`, `doctor.PASS`, `doctor.FAIL`.
- Produces: `doctor.ExitProbe = Callable[[List[str]], int]`, `doctor.probe_exit(command) -> int`, `doctor.check_gh(which, probe, exit_probe) -> CheckResult`, and a `check_exit: ExitProbe = probe_exit` keyword parameter on `run_checks`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_garage_core.py`, in the doctor section beside the other row tests:

```python
class TestCheckGh(unittest.TestCase):
    """R7/AC9: `gh` absent and `gh` unauthenticated are different failures,
    because they have different repairs.
    """

    def test_gh_present_and_authenticated_passes(self):
        result = doctor.check_gh(
            which=lambda name: "C:/tools/gh.exe",
            probe=lambda command: "2.96.0",
            exit_probe=lambda command: 0,
        )

        self.assertEqual(result.status, doctor.PASS)
        self.assertEqual(result.key, "gh")
        self.assertEqual(result.tag, "2.96.0")

    def test_gh_absent_fails_with_the_path_reason(self):
        result = doctor.check_gh(
            which=lambda name: None,
            probe=lambda command: "",
            exit_probe=lambda command: 0,
        )

        self.assertEqual(result.status, doctor.FAIL)
        self.assertIn("not found on PATH", result.detail)
        self.assertIn("work item", result.prevents)

    def test_gh_present_but_unauthenticated_fails_differently(self):
        result = doctor.check_gh(
            which=lambda name: "C:/tools/gh.exe",
            probe=lambda command: "2.96.0",
            exit_probe=lambda command: 1,
        )

        self.assertEqual(result.status, doctor.FAIL)
        self.assertNotIn("not found on PATH", result.detail)
        self.assertIn("gh auth login", result.detail)

    def test_the_auth_probe_asks_gh_and_nothing_else(self):
        asked = []

        doctor.check_gh(
            which=lambda name: "C:/tools/gh.exe",
            probe=lambda command: "2.96.0",
            exit_probe=lambda command: asked.append(command) or 0,
        )

        self.assertEqual(len(asked), 1)
        self.assertIn("auth", asked[0])
        self.assertIn("status", asked[0])

    def test_the_auth_probe_is_not_run_when_gh_is_absent(self):
        # A missing tool cannot be interrogated, and the timeout would be
        # paid on every doctor run for nothing.
        asked = []

        doctor.check_gh(
            which=lambda name: None,
            probe=lambda command: "",
            exit_probe=lambda command: asked.append(command) or 0,
        )

        self.assertEqual(asked, [])
```

Update the existing key-list assertion in `test_report_covers_every_required_item` (around line 1766) to include `"gh"` after `"git-unix-tools"`:

```python
        self.assertEqual(
            [check.key for check in report.checks],
            [
                "game-repo",
                "classification",
                "make",
                "gcc",
                "gbdk-home",
                "romusage",
                "git-unix-tools",
                "gh",
                "java",
                "emulicious",
            ],
        )
```

Add `"gh"` to the `make_toolchain(tmp_path)` fixture's `which` map (around line 1696), beside the other tools, and give the `run_doctor(...)` wrapper (around line 1748) a default for the new seam:

```python
def run_doctor(binding=None, binding_error=None, **kwargs):
    kwargs.setdefault("probe", lambda command: "1.2.3")
    kwargs.setdefault("check_exit", lambda command: 0)
    return doctor.run_checks(binding, binding_error, **kwargs)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_core -v -k Gh`
Expected: FAIL — `AttributeError: module 'tools.garage.core.doctor' has no attribute 'check_gh'`.

- [ ] **Step 3: Implement**

In `tools/garage/core/doctor.py`, beside `VersionProbe` and `probe_version`:

```python
ExitProbe = Callable[[List[str]], int]


def probe_exit(command: List[str]) -> int:
    """The exit code of `command`, and nothing else. Never raises.

    `probe_version` cannot serve here: it reads output and returns a
    version token, and a tool that answers "not logged in" on stderr while
    still printing a version would read as healthy. `gh auth status`
    reports through its exit code, so that is what is read.
    """
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=VERSION_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return EXIT_PROBE_FAILED
    return completed.returncode
```

with `EXIT_PROBE_FAILED = 127` beside `VERSION_TIMEOUT_S`. Then, in the individual-checks section:

```python
def check_gh(
    which: Which, probe: VersionProbe, exit_probe: ExitProbe
) -> CheckResult:
    """`gh` present *and* authenticated (R7/AC9).

    Two failures, not one, because they have different repairs: an absent
    `gh` is an install and an unauthenticated one is `gh auth login`. Both
    are reported here rather than at the button, so a user learns about
    them before they have composed a work item they cannot file.

    Unlike every other row, this one can go stale under a running Garage —
    PATH cannot change beneath the process, but `gh auth login` in a
    terminal can. The doctor panel's refresh is what re-reads it.
    """
    path = which("gh")
    if not path:
        return CheckResult(
            key="gh",
            name="gh — files a work item for tuning work",
            status=FAIL,
            detail="not found on PATH",
            prevents=(
                "Filing a work item from Garage. A tuning pull request needs "
                "a linked issue, and without gh the issue has to be opened by "
                "hand."
            ),
            tag="blocked",
        )
    if exit_probe([path, "auth", "status"]) != 0:
        return CheckResult(
            key="gh",
            name="gh — files a work item for tuning work",
            status=FAIL,
            detail=f"{path} is installed but not authenticated — run `gh auth login`",
            prevents=(
                "Filing a work item from Garage. Every GitHub call it makes "
                "would be refused."
            ),
            tag="not signed in",
        )
    return CheckResult(
        key="gh",
        name="gh — files a work item for tuning work",
        status=PASS,
        detail=path,
        tag=probe([path, "--version"]),
    )
```

and in `run_checks`, add the parameter and the row:

```python
def run_checks(
    binding: Optional[Binding] = None,
    binding_error: Optional[BindingError] = None,
    *,
    which: Which = shutil.which,
    environ=None,
    settings: Optional[dict] = None,
    probe: VersionProbe = probe_version,
    check_exit: ExitProbe = probe_exit,
) -> Report:
    ...
        check_git_unix_tools(which),
        check_gh(which, probe, check_exit),
        check_java(which, probe),
```

`tools/garage/panels/doctor.py` needs no change: it loops the report and keys everything off `check.key`, `check.status`, `check.prevents` and `check.tag`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_core -v -k Doctor` then `python -m unittest tests.test_garage_core -v -k Gh`
Expected: PASS. The key-list test now expects ten rows.

- [ ] **Step 5: Run the whole Qt-free suite**

Run: `make test`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/doctor.py tests/test_garage_core.py
git commit -m "feat: report gh's presence and its authentication as separate doctor rows (#5)"
```

---

## Task 6: The panel — the section, the gate, the thread, the clipboard

**Files:**
- Modify: `tools/garage/panels/worktrees.py`
- Modify: `tools/garage/theme/qss.py`
- Modify: `tools/garage/app.py`

**Interfaces:**
- Consumes: `workitem.file_work_item`, `workitem.changed_defines`, `workitem.branch_commits`, `workitem.refuse_reason`, `workitem.closes_line`, `workitem.WorkItem`, `workitem.WorkItemFailure`, `workitem.Runner`, `workitem.run_capture`.
- Produces, on `WorktreesPanel`: `work_item_visible() -> bool`, `file_work_item() -> Optional[str]`, `finish_board_entry() -> Optional[str]`, `is_filing() -> bool`, `stop_and_wait() -> None`, `copied_text() -> Optional[str]`, `last_work_item() -> Optional[WorkItem]`, and the widgets `title_field`, `description_field`, `file_button`, `finish_button`.

- [ ] **Step 1: Add the styling and its index entry**

In `tools/garage/theme/qss.py`, add to `build_stylesheet()`'s docstring index, beside the existing `#worktrees-*` bullet:

```
    - `#worktrees-workitem` — the work-item section frame, and
      `#worktrees-workitem-title` / `#worktrees-workitem-result` inside it.
```

and to the stylesheet body, beside the other `worktrees` rules:

```python
QFrame#worktrees-workitem {{
    background-color: {t['surface']};
    border: 1px solid {t['line-soft']};
    border-radius: 4px;
}}
QLabel#worktrees-workitem-title {{
    color: {t['text-1']};
}}
QLabel#worktrees-workitem-result {{
    color: {t['text-2']};
}}
QLabel#worktrees-workitem-result[verdict="fail"] {{
    color: {t['danger']};
}}
```

Check the token names against `tools/garage/theme/tokens.py` before writing them — use whatever that file actually calls the danger and secondary-text tokens rather than the names above if they differ.

- [ ] **Step 2: Write the panel section and the worker**

In `tools/garage/panels/worktrees.py`, add to the module docstring:

```
The work-item section (#5) is the panel's one GitHub write. It is manual:
Garage files nothing when a worktree is created and nothing when a commit
is made (R2), because most tuning work is thrown away and an issue per
abandoned experiment is worse than the problem this solves. The section is
hidden outright until the worktree holds a changed value or a commit of
its own (AC1) — an action that cannot do anything useful is not offered.

The filing runs on a worker thread. Four network round trips on the UI
thread would freeze the window, and a live QThread at teardown is a
Windows fail-fast (#8) — hence `stop_and_wait()`, which `app.py` calls
when the dialog closes.
```

Then the worker, modelled on `runner.RunWorker`:

```python
class _FileWorker(QObject):
    """Runs the `gh` sequence off the UI thread. One shot, then finished."""

    done = Signal(object)  # WorkItem | WorkItemFailure

    def __init__(self, call):
        super().__init__()
        self._call = call

    def run(self) -> None:
        self.done.emit(self._call())
```

and, in `WorktreesPanel`:

```python
    def _build_work_item_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("worktrees-workitem")
        layout = QVBoxLayout(section)

        heading = QLabel("Work item")
        heading.setObjectName("worktrees-workitem-title")
        layout.addWidget(heading)

        self.title_field = QLineEdit()
        self.title_field.setPlaceholderText("What this tuning work is for")
        layout.addWidget(self.title_field)

        self.description_field = QPlainTextEdit()
        self.description_field.setPlaceholderText("Optional description")
        layout.addWidget(self.description_field)

        buttons = QHBoxLayout()
        self.file_button = QPushButton("File work item")
        self.file_button.setObjectName("worktrees-file-issue")
        self.file_button.setProperty("role", "primary")
        self.file_button.clicked.connect(self._on_file_clicked)
        buttons.addWidget(self.file_button)

        self.finish_button = QPushButton("Finish the board entry")
        self.finish_button.clicked.connect(self._on_finish_clicked)
        self.finish_button.setVisible(False)
        buttons.addWidget(self.finish_button)
        layout.addLayout(buttons)

        self.work_item_result = QLabel("")
        self.work_item_result.setObjectName("worktrees-workitem-result")
        self.work_item_result.setWordWrap(True)
        self.work_item_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.work_item_result)

        return section

    def refresh_work_item(self) -> None:
        """Show the section only when there is something to file about (AC1)."""
        self._changes = []
        self._commits = []
        if self.binding is not None:
            self._changes = workitem.changed_defines(self.binding)
            self._commits = workitem.branch_commits(self.binding.active_worktree.path)
        allowed = workitem.refuse_reason(self.binding, self._changes, self._commits)
        self.work_item_section.setVisible(allowed is None)

    def work_item_visible(self) -> bool:
        return self.work_item_section.isVisible()

    def file_work_item(self) -> Optional[str]:
        """Start the filing. Returns a refusal, or None once it is running."""
        if self.is_filing():
            return self._set_work_item_result("A work item is already being filed.")
        if shutil.which("gh") is None:
            return self._set_work_item_result(
                "`gh` is not on PATH, so Garage cannot file a work item. "
                "The Doctor panel says the same, with the repair."
            )
        binding, title = self.binding, self.title_field.text()
        description = self.description_field.toPlainText()
        changes, commits = list(self._changes), list(self._commits)
        runner = self._runner

        def call():
            return workitem.file_work_item(
                binding, title, description,
                changes=changes, commits=commits, run=runner,
            )

        return self._start(call)

    def finish_board_entry(self) -> Optional[str]:
        """Resume a partial filing. Files no second issue (R9)."""
        partial = self._last_item
        if partial is None:
            return self._set_work_item_result("There is no partial work item to finish.")
        binding, runner = self.binding, self._runner

        def call():
            return workitem.file_work_item(
                binding, "", "", existing=partial, run=runner
            )

        return self._start(call)

    def _start(self, call) -> Optional[str]:
        self.file_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self._set_work_item_result("Filing…", failed=False)

        self._thread = QThread(self)
        self._worker = _FileWorker(call)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_filed)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()
        return None

    def is_filing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _on_filed(self, outcome) -> None:
        self.file_button.setEnabled(True)
        if isinstance(outcome, workitem.WorkItem):
            self._last_item = outcome if not outcome.complete else None
            self.finish_button.setVisible(False)
            line = workitem.closes_line(outcome.number)
            copied = self._copy(line)
            self._set_work_item_result(
                f"Filed issue #{outcome.number} — {outcome.url}\n"
                + (
                    f"`{line}` is on the clipboard for the pull request body."
                    if copied
                    else f"Copy `{line}` into the pull request body."
                ),
                failed=False,
            )
            self.title_field.clear()
            self.description_field.clear()
        else:
            self._last_item = outcome.item
            self.finish_button.setVisible(outcome.item is not None)
            self.finish_button.setEnabled(True)
            self._set_work_item_result(outcome.text, failed=True)

    def _copy(self, text: str) -> bool:
        """Put `text` on the clipboard, and say whether it landed.

        `clipboard()` answers None when there is no GUI application, which
        is every headless test run — the text is still recorded so the
        panel can be asserted against without a clipboard.
        """
        self._copied = text
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    def copied_text(self) -> Optional[str]:
        return self._copied

    def last_work_item(self):
        return self._last_item

    def work_item_result_text(self) -> str:
        return self.work_item_result.text()

    def _set_work_item_result(self, message: str, failed: bool = True) -> Optional[str]:
        self.work_item_result.setText(message)
        self.work_item_result.setProperty("verdict", "fail" if failed else "pass")
        self.work_item_result.style().unpolish(self.work_item_result)
        self.work_item_result.style().polish(self.work_item_result)
        return message if failed else None

    def stop_and_wait(self) -> None:
        """Let a filing finish before the panel dies. Destroying a live
        QThread is a Windows fail-fast (#8), and the sequence is four short
        network calls, not a build — waiting is the honest option, and
        cancelling midway is what R8 forbids.
        """
        if self._thread is None:
            return
        self._thread.quit()
        self._thread.wait(30000)
        self._thread = None

    def _on_file_clicked(self) -> None:
        self.file_work_item()

    def _on_finish_clicked(self) -> None:
        self.finish_board_entry()
```

Initialise `self._thread = None`, `self._worker = None`, `self._last_item = None`, `self._copied = None`, `self._changes = []`, `self._commits = []` in `__init__` before the section is built, add the keyword-only `runner: Optional[workitem.Runner] = None` parameter storing `self._runner = runner or workitem.run_capture`, add `self.work_item_section = self._build_work_item_section()` to the layout, and call `self.refresh_work_item()` at the end of `refresh()` so activating another worktree re-evaluates the gate.

- [ ] **Step 3: Wire the teardown**

In `tools/garage/app.py`, where the worktrees dialog is closed (around line 433, beside the `CommitPanel.stop_and_wait()` precedent at line 664), call `panel.stop_and_wait()` before the dialog is destroyed.

- [ ] **Step 4: Run both suites**

Run: `make test` then `make test-garage`
Expected: both OK. `make test-garage` is long and prints nothing while it runs — give it a generous timeout and do not kill it for being quiet.

- [ ] **Step 5: Commit**

```bash
git add tools/garage/panels/worktrees.py tools/garage/theme/qss.py tools/garage/app.py
git commit -m "feat: file a work item from the worktrees panel (#5)"
```

---

## Task 7: Panel coverage

**Files:**
- Create: `tests/garage/test_panels_workitem.py`

- [ ] **Step 1: Write the tests**

```python
"""Panel coverage for the work-item section — MatthieuGagne/nuke-raiders-garage#5.

Imports PySide6, so this file must never be reachable by
`python -m unittest discover -s tests` (tests/garage/ has no __init__.py, so
default discovery never descends into it). Run via `make test-garage`.

Every `gh` call goes through the runner the panel is constructed with, so
nothing here reaches GitHub.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.garage import theme  # noqa: E402
from tools.garage.core import project, workitem  # noqa: E402
from tools.garage.panels.worktrees import WorktreesPanel  # noqa: E402

_app = QApplication.instance() or QApplication([])

GAME_REPO_REMOTE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider.git"
ISSUE_URL = "https://github.com/MatthieuGagne/gmb-nuke-raider/issues/614"

CONFIG_H = "#define PLAYER_SPEED 4\n#define MAX_NPCS 8\n"

FIELDS = {
    "fields": [
        {
            "id": "PVTSSF_status",
            "name": "Status",
            "options": [{"id": "opt_todo", "name": "Todo"}],
        },
        {
            "id": "PVTSSF_type",
            "name": "Type",
            "options": [{"id": "opt_chore", "name": "Chore"}],
        },
    ]
}


def scripted_runner(create_stdout=ISSUE_URL, create_code=0):
    """A `Runner` that answers from a script. Records its calls."""
    calls = []

    def run(argv, cwd=None):
        argv = list(argv)
        calls.append(argv)
        if "field-list" in argv:
            return workitem.CommandResult(tuple(argv), 0, json.dumps(FIELDS), "")
        if "create" in argv:
            return workitem.CommandResult(
                tuple(argv), create_code, create_stdout, "gh: Not Found (HTTP 404)"
            )
        if "item-add" in argv:
            return workitem.CommandResult(
                tuple(argv), 0, json.dumps({"id": "PVTI_x"}), ""
            )
        return workitem.CommandResult(tuple(argv), 0, "", "")

    run.calls = calls
    return run


def _run_git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True, capture_output=True, text=True
    )


def make_worktree(root: Path) -> Path:
    repo = root / "game"
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "master"], repo)
    _run_git(["config", "user.email", "t@example.com"], repo)
    _run_git(["config", "user.name", "T"], repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "config.h").write_text(CONFIG_H, encoding="utf-8")
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


class WorkItemPanelTestCase(unittest.TestCase):
    """Not gated on a bound game repository: the fixture builds its own git
    repository and every `gh` call is scripted, so this runs in CI.
    """

    def setUp(self):
        theme.apply(_app)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.repo = make_worktree(self.root)
        self.binding = bind_over(self.root, self.repo)
        self.runner = scripted_runner()
        self.panel = WorktreesPanel(self.binding, None, runner=self.runner)

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self._tmp.cleanup()

    def dirty(self):
        (self.repo / "src" / "config.h").write_text(
            CONFIG_H.replace("PLAYER_SPEED 4", "PLAYER_SPEED 6"), encoding="utf-8"
        )
        self.panel.refresh_work_item()

    def wait(self, timeout_ms=15000):
        from PySide6.QtTest import QTest

        waited = 0
        while waited < timeout_ms and self.panel.is_filing():
            QTest.qWait(20)
            waited += 20
        QApplication.processEvents()
        self.assertFalse(self.panel.is_filing(), "the filing never ended")


class TestVisibility(WorkItemPanelTestCase):
    """AC1: the action is absent until there is something to file about."""

    def test_a_clean_worktree_hides_the_section(self):
        self.assertFalse(self.panel.work_item_visible())

    def test_a_changed_define_reveals_it(self):
        self.dirty()

        self.assertTrue(self.panel.work_item_visible())


class TestNoAutomaticFiling(WorkItemPanelTestCase):
    """AC2, AC3: creating a worktree and committing file nothing."""

    def test_building_the_panel_calls_no_gh(self):
        self.assertEqual(self.runner.calls, [])

    def test_creating_a_worktree_calls_no_gh(self):
        self.panel.create_worktree("tune-speed")

        self.assertEqual(self.runner.calls, [])


class TestFiling(WorkItemPanelTestCase):
    """AC4, AC7, AC8."""

    def test_the_issue_number_is_shown(self):
        self.dirty()
        self.panel.title_field.setText("tune speed")

        self.panel.file_work_item()
        self.wait()

        self.assertIn("614", self.panel.work_item_result_text())

    def test_closes_n_goes_to_the_clipboard(self):
        self.dirty()
        self.panel.title_field.setText("tune speed")

        self.panel.file_work_item()
        self.wait()

        self.assertEqual(self.panel.copied_text(), "Closes #614")

    def test_the_title_reaches_gh_with_the_chore_prefix(self):
        self.dirty()
        self.panel.title_field.setText("tune speed")

        self.panel.file_work_item()
        self.wait()

        create = next(c for c in self.runner.calls if "create" in c)
        self.assertEqual(create[create.index("--title") + 1], "chore: tune speed")


class TestFailureIsShown(WorkItemPanelTestCase):
    """AC10: GitHub's message, in the window."""

    def setUp(self):
        super().setUp()
        self.runner = scripted_runner(create_stdout="", create_code=1)
        self.panel.stop_and_wait()
        self.panel.deleteLater()
        self.panel = WorktreesPanel(self.binding, None, runner=self.runner)

    def test_githubs_own_message_appears(self):
        self.dirty()
        self.panel.title_field.setText("tune speed")

        self.panel.file_work_item()
        self.wait()

        self.assertIn("404", self.panel.work_item_result_text())

    def test_no_issue_number_is_claimed(self):
        self.dirty()
        self.panel.title_field.setText("tune speed")

        self.panel.file_work_item()
        self.wait()

        self.assertIsNone(self.panel.last_work_item())


class TestUnbound(unittest.TestCase):
    """The CI case: no game repository, so no section and no crash."""

    def setUp(self):
        theme.apply(_app)
        self.panel = WorktreesPanel(
            None, project.BindingError("game_repo", "nothing is bound")
        )

    def tearDown(self):
        self.panel.stop_and_wait()
        self.panel.deleteLater()

    def test_the_section_is_hidden(self):
        self.assertFalse(self.panel.work_item_visible())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the panel suite**

Run: `make test-garage`
Expected: OK. Long and silent; do not kill it for being quiet.

- [ ] **Step 3: Run the Qt-free suite one more time**

Run: `make test`
Expected: OK, and it must not have discovered the new panel file.

- [ ] **Step 4: Commit**

```bash
git add tests/garage/test_panels_workitem.py
git commit -m "test: cover the work-item panel section (#5)"
```

---

## Hand verification

Six of the thirteen acceptance criteria cannot be reached by either suite: they need a real GitHub, a real board and a real clipboard. Run these against a scratch worktree before opening the pull request, and record the results in the PR body the way #9 did for P2.

| AC | How to check | What must be true |
|---|---|---|
| AC6 | File a work item, then open the board | The issue is on "Nuke Raider — Documents" with `Type = Chore` and `Status = Todo` |
| AC8 | Paste into a real pull request body | The PR Linked Issue workflow passes |
| AC9 | Rename `gh.exe` out of PATH, open Doctor; restore it and `gh auth logout`, open Doctor | Two different failures, each with its own repair |
| AC10 | File against a repository you cannot write to | GitHub's message appears in the window, and the board holds nothing half-typed |
| AC11 | Read the panel | No push, no pull-request, no close affordance anywhere |
| — | `gh project item-add … --format json` | The item id is under the key `id`. **This is the one output shape in the plan taken from documentation rather than from a recorded run** — confirm it here, and correct Task 4 if it differs |

Close the loop by deleting the scratch issue from the board by hand — Garage cannot, and must not be able to (R9).

## Self-review

**Spec coverage.** R1 → Task 6. R2 → Task 6 (`TestNoAutomaticFiling`). R3 → Task 2. R4 → Tasks 1–2. R5 → Task 3. R6 → Tasks 2, 6. R7 → Task 5. R8 → Task 4 (ordering, `WorkItemFailure`) and Task 6 (`finish_board_entry`). R9 → Task 4 (`test_nothing_pushes_closes_or_opens_a_pull_request`). R10 → the global constraint plus `TestCoreImportsNoQt`. R11 → Task 3 (`repo_slug`) and the binding used throughout. AC1–AC13 map to Tasks 6, 6, 6, 2, 2, hand-verify, 6, hand-verify, 5, hand-verify, hand-verify, 4, 7.

**Names.** `file_work_item` is used as both the core function and the panel method; that is deliberate and mirrors `commit`/`commit_command`. `refuse_reason` matches `commit.refuse_reason`'s signature shape. `stop_and_wait` matches `CommitPanel`'s.

**Known soft spot.** The `item-add --format json` key is the one shape not recorded from a real run; the hand-verification table calls it out rather than burying it.
