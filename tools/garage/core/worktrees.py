"""Create, delete and activate git worktrees of the game repository
(R3, R4). Pure and Qt-free, like every module under tools/garage/core/.

This is the first module in Garage that *writes* to the game repository's
git state, so it is built around its refusals rather than its actions:

- The active worktree is never deleted. Everything Garage resolves —
  `src/config.h`, the diff, every make call, the ROM — resolves against it,
  and deleting the ground the application is standing on is not a thing to
  do politely.
- A worktree holding uncommitted work is never deleted. `git worktree
  remove` would need `--force` for tracked changes, and Garage never passes
  it. Untracked files are refused too: git will not stop for them, and the
  removal destroys them (see `refuse_delete_reason` for why that decision
  is stricter than R4's letter).
- The name must be typed back. A misclick cannot delete a worktree.
- **No branch is ever deleted.** `git worktree remove` detaches the working
  tree and leaves the branch alone; nothing here calls `git branch -d` or
  `-D`, and nothing here should. The work survives the worktree.

Refusals are computed separately from the actions that honour them
(`refuse_delete_reason` is a pure function returning a sentence), so the
window can grey out a button and explain itself without attempting
anything, and so the tests can prove the decision without touching a repo.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional

from tools.garage.core import diff as diff_core
from tools.garage.core.project import Binding, Worktree, _same_path, list_worktrees

# Characters that cannot appear in a directory name on Windows, plus the
# path separators a branch name is allowed to contain (`feat/thing` is a
# perfectly good branch and a terrible directory).
_UNSAFE_IN_DIRNAME = re.compile(r'[\\/:*?"<>|]+')


class WorktreeError(Exception):
    """A worktree operation that could not be carried out. The message is
    written to be shown to the user as-is.
    """


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )


def directory_name_for(branch: str) -> str:
    """The directory a branch's worktree lives in. `feat/garage-p1` gives
    `feat-garage-p1`: a branch name may contain slashes, a directory name
    inside the worktree root may not.
    """
    return _UNSAFE_IN_DIRNAME.sub("-", branch.strip()).strip("-")


def validate_branch_name(game_repo: Path, branch: str) -> None:
    """Raise WorktreeError unless git would accept `branch` as a branch
    name. Asking git rather than reproducing its rules here: the rules are
    long (no `..`, no trailing `.lock`, no control characters, ...) and a
    private copy of them would drift.
    """
    name = (branch or "").strip()
    if not name:
        raise WorktreeError("A branch name is required.")
    result = _run_git(["check-ref-format", "--branch", name], game_repo)
    if result.returncode != 0:
        raise WorktreeError(
            f"'{name}' is not a valid branch name. git rejected it: "
            f"{result.stderr.strip() or 'no reason given'}."
        )


def branch_exists(game_repo: Path, branch: str) -> bool:
    result = _run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], game_repo
    )
    return result.returncode == 0


def create(
    game_repo: Path,
    worktree_root: Path,
    branch: str,
    base: Optional[str] = None,
) -> Path:
    """Add a worktree for `branch` under `worktree_root` and return its
    path (AC3: it appears in `git worktree list` afterwards).

    An existing branch is checked out; a new one is created from `base`
    (default: the repository's current HEAD). Garage does not guess which
    of the two the user meant — it asks git.
    """
    branch = (branch or "").strip()
    validate_branch_name(game_repo, branch)

    path = Path(worktree_root) / directory_name_for(branch)
    if path.exists():
        raise WorktreeError(
            f"'{path}' already exists. Choose another branch name, or "
            f"remove that directory first."
        )

    if branch_exists(game_repo, branch):
        args = ["worktree", "add", str(path), branch]
    else:
        args = ["worktree", "add", "-b", branch, str(path)]
        if base:
            args.append(base)

    path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_git(args, game_repo)
    if result.returncode != 0:
        raise WorktreeError(
            f"git could not create the worktree: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return path


def refuse_delete_reason(
    worktree: Worktree, active: Worktree, worktrees: Optional[List[Worktree]] = None
) -> Optional[str]:
    """Why `worktree` must not be deleted, or None when it may be (R4).

    The uncommitted-work rule is deliberately stricter than "tracked files
    differ from HEAD". An untracked file is not work git is following, so
    it never marks the header dirty (AC20) — but deleting the worktree
    deletes the file, and unlike a tracked change it exists nowhere else.
    The consequences of the two mistakes are not symmetric: refusing costs
    the user one `git clean` or one moved file; not refusing costs them
    whatever was in it.
    """
    # "It is the active one" comes first, and stays first even when the
    # active worktree is also the main one (the common case: nothing has
    # been activated yet). Both sentences are true then, and the active one
    # is the reason the user can act on -- activate another, then delete.
    if _same_path(worktree.path, active.path):
        return (
            f"'{worktree.path}' is the active worktree. Activate another one "
            f"first: every path Garage resolves — src/config.h, the diff, "
            f"every make call — resolves against it."
        )
    if worktrees and _same_path(worktree.path, worktrees[0].path):
        return (
            f"'{worktree.path}' is the repository's main working tree. Garage "
            f"does not delete it — every other worktree hangs off it."
        )
    try:
        summary = diff_core.get_change_summary(worktree.path)
    except diff_core.DiffError as exc:
        return (
            f"Garage could not read the state of '{worktree.path}' ({exc}), "
            f"so it will not delete it."
        )
    if summary.dirty:
        files = "file" if summary.changed_file_count == 1 else "files"
        return (
            f"'{worktree.path}' holds uncommitted work: {summary.changed_file_count} "
            f"{files} differ from HEAD (+{summary.added_lines} −{summary.removed_lines}). "
            f"Commit or discard it first."
        )
    if summary.untracked_count:
        one = summary.untracked_count == 1
        return (
            f"'{worktree.path}' holds {summary.untracked_count} untracked "
            f"{'file' if one else 'files'}. Deleting the worktree would "
            f"delete {'it' if one else 'them'}, and git has no copy. Move or "
            f"commit {'it' if one else 'them'} first."
        )
    return None


def delete(
    game_repo: Path,
    worktree: Worktree,
    active: Worktree,
    typed_name: str,
    worktrees: Optional[List[Worktree]] = None,
) -> None:
    """Remove `worktree`, having refused every reason not to (R4).

    `typed_name` must match the worktree's directory name exactly — the
    third guard, and the one that catches a misclick on the right row of a
    list. The branch is untouched: `git worktree remove` leaves it, and
    nothing here deletes a branch.
    """
    reason = refuse_delete_reason(worktree, active, worktrees)
    if reason is not None:
        raise WorktreeError(reason)

    expected = worktree.path.name
    if (typed_name or "").strip() != expected:
        raise WorktreeError(
            f"To delete this worktree, type its name exactly: '{expected}'."
        )

    result = _run_git(["worktree", "remove", str(worktree.path)], game_repo)
    if result.returncode != 0:
        raise WorktreeError(
            f"git could not remove the worktree: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def activate(garage_root: Path, worktree: Worktree) -> None:
    """Record `worktree` as the active one, in garage.local.json (R3).

    Only the `active` key is rewritten; every other setting the user may
    have edited by hand is carried through untouched.
    """
    from tools.garage.core import project

    settings = project.load_settings(garage_root) or {}
    settings["active"] = Path(worktree.path).as_posix()
    project.save_settings(garage_root, settings)


def describe(worktree: Worktree, active: Worktree) -> str:
    """One line for a list row: branch, whether it is active, and what it
    holds. Pure, so the panel renders it and the tests read it.
    """
    branch = worktree.branch or "(detached HEAD)"
    marks = []
    if _same_path(worktree.path, active.path):
        marks.append("active")
    try:
        summary = diff_core.get_change_summary(worktree.path)
    except diff_core.DiffError:
        summary = None
    if summary is not None:
        if summary.dirty:
            marks.append(
                f"{summary.changed_file_count} changed "
                f"+{summary.added_lines} −{summary.removed_lines}"
            )
        if summary.untracked_count:
            marks.append(f"{summary.untracked_count} untracked")
    if not marks:
        marks.append("clean")
    return f"{branch} — {', '.join(marks)}"


def reload(binding: Binding) -> List[Worktree]:
    """The current worktree list, re-read from git rather than from the
    binding's snapshot: a create or a delete in this session makes that
    snapshot stale immediately.
    """
    return list_worktrees(binding.game_repo)
