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
