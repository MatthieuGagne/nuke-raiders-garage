"""The diff of the active worktree against `HEAD`, the untracked file list,
and the dirty/`master` check the header (and later the Worktree and Commit
panels) need.

No Qt import belongs in this module or anywhere under tools/garage/core/.

R19 / AC19: Garage shows the diff of the active worktree against HEAD, for
every changed file (not only src/config.h), covering staged and unstaged
changes in one view. An added and a removed line are tagged distinctly; the
file name, hunk header and surrounding context that `git diff` gives are
kept. An untracked file is listed by name, since a diff holds nothing to
show for one.

R2 / AC2, redesigned in iteration 5: the header states change *totals*
only (never a per-file list), and its length must not grow with the size
of the change -- so `get_change_summary()` lives here, returning the four
numbers (`changed_file_count`, `untracked_count`, `added_lines`,
`removed_lines`) the header needs. It is cheap on purpose: a
`git status --porcelain` call for the file counts and a
`git diff --numstat` call for the line counts -- neither one parses full
hunk text, so a multi-thousand-line change costs the header the same two
small calls as a one-line change (unlike `get_diff()`, whose hunk parsing
is capped by MAX_DIFF_LINES). It takes a bare worktree path (not a
Binding), so iterations 9 and 10 can call it on any worktree the Worktree
panel is about to delete or the Commit panel is about to commit, not only
the active one. The Qt layer only ever formats these numbers; it never
computes them.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .project import Binding

# The empty tree's well-known SHA (`git hash-object -t tree /dev/null`).
# Diffing against it makes a repository with no commits yet ("unborn HEAD")
# behave like a normal diff: staged content shows up as added lines instead
# of the whole file falling back to "untracked".
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_NO_HEAD_MARKERS = (
    "unknown revision",
    "bad revision",
    "invalid object name",
    "ambiguous argument 'head'",
)

# A cap on the number of added/removed/context lines rendered per refresh,
# across the whole diff. 2000 lines is generous for the config.h-sized
# changes this tool exists to show, while still protecting the panel (and
# the person reading it) from a multi-thousand-line diff that is no longer
# skimmable -- usually a sign the wrong thing is staged, not something to
# render in full. Truncation is reported, never silent (WorktreeDiff.
# truncated / truncated_reason).
MAX_DIFF_LINES = 2000

_FILE_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")


class DiffError(Exception):
    """Raised when a `git` call this module depends on fails outright (not
    the "no commits yet" case, which get_diff() handles transparently).
    """


@dataclass(frozen=True)
class DiffLine:
    """One line of a hunk. `kind` is "add", "remove", "context", or "meta"
    (currently only git's "\\ No newline at end of file" marker). `text` is
    the line's content with git's leading +/-/space marker stripped -- a
    panel renders its own prefix from `kind`.
    """

    kind: str
    text: str


@dataclass(frozen=True)
class Hunk:
    """One `@@ ... @@` hunk of a file diff, header text as `git diff` gives
    it (including any trailing function context), plus its tagged lines.
    """

    header: str
    lines: List[DiffLine] = field(default_factory=list)


@dataclass(frozen=True)
class FileDiff:
    """One changed file. `change_type` is "added", "deleted", or
    "modified" (renames are disabled -- see get_diff -- so a rename always
    shows as a deleted file plus an added file, never a third type).
    `hunks` is empty for a binary file (`binary` is True) and for a
    changed-mode-only file.
    """

    path: str
    change_type: str
    binary: bool = False
    hunks: List[Hunk] = field(default_factory=list)


@dataclass(frozen=True)
class WorktreeDiff:
    """The full result of one refresh: every changed file's diff, the
    untracked file list, and whether the diff was capped (see
    MAX_DIFF_LINES).
    """

    files: List[FileDiff]
    untracked: List[str]
    truncated: bool = False
    truncated_reason: str = ""

    @property
    def is_clean(self) -> bool:
        return not self.files and not self.untracked


@dataclass(frozen=True)
class ChangeSummary:
    """The four numbers the header needs to describe the active worktree's
    uncommitted state -- totals only, never a per-file breakdown.

    `changed_file_count` counts tracked files with a staged and/or
    unstaged change (what `git diff HEAD` would show) -- it does NOT
    include untracked files; those are counted separately in
    `untracked_count` so the two are never double-reported as one number.
    `added_lines`/`removed_lines` are the total +/- line counts across
    every changed tracked file, from `git diff --numstat` (not from
    parsing `get_diff()`'s hunk text, so they are exact even when a huge
    diff would otherwise hit MAX_DIFF_LINES).
    """

    changed_file_count: int
    untracked_count: int
    added_lines: int
    removed_lines: int

    @property
    def dirty(self) -> bool:
        """AC20: the header's "●" mark stands for a *tracked* file that
        differs from HEAD. An untracked file is counted and named in the
        header's clause, but on its own it does not raise this mark --
        untracked_count plays no part here, deliberately.
        """
        return self.changed_file_count > 0


def is_master_branch(branch: Optional[str]) -> bool:
    """R5/iteration 10 refuses to commit on `master`; R2/AC2 states that
    refusal in the header before the work is done. Both call sites must
    agree on what "on master" means, so it lives here once.
    """
    return branch == "master"


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True,
        text=True,
    )


# -- diff text parsing (pure, no git call) -----------------------------------


def parse_diff_text(text: str, max_lines: int = MAX_DIFF_LINES) -> Tuple[List[FileDiff], bool, str]:
    """Parse the text of `git diff`, tagging every hunk line added /
    removed / context / meta. Pure and testable without touching git.

    Stops once `max_lines` total hunk lines (across every file) have been
    parsed, leaving `truncated` True and `truncated_reason` naming the cap
    -- never silently drops the tail of a huge diff.
    """
    if not text:
        return [], False, ""

    lines = text.splitlines()
    n = len(lines)
    files: List[FileDiff] = []
    i = 0
    total_lines = 0
    truncated = False
    truncated_reason = ""

    while i < n:
        header_match = _FILE_HEADER_RE.match(lines[i])
        if not header_match:
            i += 1
            continue
        path_a, path_b = header_match.group(1), header_match.group(2)
        i += 1

        change_type = "modified"
        binary = False
        while i < n and not lines[i].startswith("@@") and not lines[i].startswith("diff --git "):
            extra = lines[i]
            if extra.startswith("new file mode"):
                change_type = "added"
            elif extra.startswith("deleted file mode"):
                change_type = "deleted"
            elif extra.startswith("Binary files ") and extra.endswith("differ"):
                binary = True
            i += 1

        path = path_a if change_type == "deleted" else path_b

        hunks: List[Hunk] = []
        if not binary:
            while i < n and lines[i].startswith("@@"):
                header = lines[i]
                i += 1
                hunk_lines: List[DiffLine] = []
                while i < n and not lines[i].startswith("@@") and not lines[i].startswith("diff --git "):
                    content = lines[i]
                    if content.startswith("\\"):
                        hunk_lines.append(DiffLine(kind="meta", text=content[2:]))
                    elif content.startswith("+"):
                        hunk_lines.append(DiffLine(kind="add", text=content[1:]))
                    elif content.startswith("-"):
                        hunk_lines.append(DiffLine(kind="remove", text=content[1:]))
                    elif content.startswith(" "):
                        hunk_lines.append(DiffLine(kind="context", text=content[1:]))
                    else:  # pragma: no cover - defensive; git always marks a hunk line
                        hunk_lines.append(DiffLine(kind="context", text=content))
                    total_lines += 1
                    i += 1
                    if total_lines >= max_lines:
                        truncated = True
                        truncated_reason = (
                            f"diff truncated after {max_lines} lines -- refine what you "
                            f"changed, or read the rest with `git diff` directly"
                        )
                        break
                hunks.append(Hunk(header=header, lines=hunk_lines))
                if truncated:
                    break
        files.append(FileDiff(path=path, change_type=change_type, binary=binary, hunks=hunks))
        if truncated:
            break

    return files, truncated, truncated_reason


# -- git-backed reads ---------------------------------------------------------


def _diff_against_head(extra_args: List[str], worktree: Path) -> str:
    """Run `git diff HEAD` (plus `extra_args`, e.g. `--numstat`), which
    already covers staged and unstaged changes together (R19). Falls back
    to diffing against the empty tree when there is no HEAD yet (a
    repository with no commits) so staged content there still shows up as
    added instead of vanishing.
    """
    args = ["diff", "--no-color", "--no-renames"] + extra_args
    result = _run_git(args + ["HEAD"], worktree)
    if result.returncode == 0:
        return result.stdout

    stderr_lower = result.stderr.lower()
    if any(marker in stderr_lower for marker in _NO_HEAD_MARKERS):
        fallback = _run_git(args + [EMPTY_TREE_SHA], worktree)
        if fallback.returncode != 0:
            raise DiffError(
                f"'git diff' failed in '{worktree}': {fallback.stderr.strip()}"
            )
        return fallback.stdout

    raise DiffError(f"'git diff' failed in '{worktree}': {result.stderr.strip()}")


def _diff_text_against_head(worktree: Path) -> str:
    return _diff_against_head([], worktree)


def _numstat_against_head(worktree: Path) -> str:
    return _diff_against_head(["--numstat"], worktree)


def _list_untracked(worktree: Path) -> List[str]:
    result = _run_git(["ls-files", "--others", "--exclude-standard"], worktree)
    if result.returncode != 0:
        raise DiffError(f"'git ls-files' failed in '{worktree}': {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def get_diff(binding: Binding, max_lines: int = MAX_DIFF_LINES) -> WorktreeDiff:
    """The full diff of the active worktree against HEAD, plus its
    untracked files. Two `git` calls per refresh (one diff, one untracked
    list) -- distinct queries that cannot be folded into one, but neither
    is ever called per-file.
    """
    worktree = binding.active_worktree.path
    diff_text = _diff_text_against_head(worktree)
    files, truncated, truncated_reason = parse_diff_text(diff_text, max_lines=max_lines)
    untracked = _list_untracked(worktree)
    return WorktreeDiff(
        files=files,
        untracked=untracked,
        truncated=truncated,
        truncated_reason=truncated_reason,
    )


def _status_file_counts(worktree_path: Path) -> Tuple[int, int]:
    """(tracked changed file count, untracked file count) from one
    `git status --porcelain=v1 -z` call. A `??` entry is untracked; every
    other code is a tracked file with a staged and/or unstaged change --
    the two are counted separately so neither double-reports the other.
    """
    result = _run_git(["status", "--porcelain=v1", "-z"], worktree_path)
    if result.returncode != 0:
        raise DiffError(
            f"'git status' failed in '{worktree_path}': {result.stderr.strip()}"
        )

    fields = [f for f in result.stdout.split("\0") if f]
    changed = 0
    untracked = 0
    i = 0
    while i < len(fields):
        entry = fields[i]
        code = entry[:2]
        if code == "??":
            untracked += 1
        else:
            changed += 1
        i += 1
        if code[0] in ("R", "C"):
            # Rename/copy entries carry a second NUL-separated field (the
            # original path) that isn't a file of its own.
            i += 1

    return changed, untracked


def _numstat_line_totals(worktree_path: Path) -> Tuple[int, int]:
    """(total added lines, total removed lines) across every tracked
    changed file, from one `git diff --numstat HEAD` call. A binary file's
    columns are `-`/`-` (no line count to add), so those are skipped.
    """
    text = _numstat_against_head(worktree_path)
    added = 0
    removed = 0
    for line in text.splitlines():
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        a, r = cols[0], cols[1]
        if a.isdigit():
            added += int(a)
        if r.isdigit():
            removed += int(r)
    return added, removed


def get_change_summary(worktree_path: Path) -> ChangeSummary:
    """The four numbers the header needs (R2/AC2): tracked changed-file
    count, untracked count, and total added/removed line counts -- two
    cheap `git` calls, neither of which parses full hunk text. Takes a
    bare path (not a Binding) so R4/R5 (iterations 9/10) can check a
    worktree that is not necessarily the active one before refusing to
    delete or commit.
    """
    changed_file_count, untracked_count = _status_file_counts(worktree_path)
    added_lines, removed_lines = _numstat_line_totals(worktree_path)
    return ChangeSummary(
        changed_file_count=changed_file_count,
        untracked_count=untracked_count,
        added_lines=added_lines,
        removed_lines=removed_lines,
    )
