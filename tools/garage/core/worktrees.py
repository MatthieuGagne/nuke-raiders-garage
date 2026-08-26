"""Create, delete and activate git worktrees of the game repository
(R3, R4). Pure and Qt-free, like every module under tools/garage/core/.

This is the first module in Garage that *writes* to the game repository's
git state, so it is built around its refusals rather than its actions —
but not every refusal is the same kind:

- Two refusals are structural and absolute, and nothing overrides them.
  The active worktree is never deleted: everything Garage resolves —
  `src/config.h`, the diff, every make call, the ROM — resolves against it,
  and deleting the ground the application is standing on is not a thing to
  do politely. The repository's main working tree is never deleted either —
  every other worktree hangs off it.
- Everything else — uncommitted tracked changes, untracked files, or a
  worktree whose state Garage could not even read — is destructive rather
  than structural: deleting it would lose something, but there is nothing
  about the worktree itself that forbids it. `destructive_delete_warning`
  says what would be lost. `delete` shows that warning to the caller by
  raising unless `force=True`, and the caller is expected to have put the
  warning in front of the user first — the typed-name confirmation (R4's
  third guard, see below) is what turns "shown" into "acknowledged".
- The name must be typed back. A misclick cannot delete a worktree.
- **No branch is ever deleted.** `git worktree remove` detaches the working
  tree and leaves the branch alone; nothing here calls `git branch -d` or
  `-D`, and nothing here should. The work survives the worktree.

`refuse_delete_reason` and `destructive_delete_warning` are both pure
functions returning a sentence (or None), computed separately from the
action that honours them, so a window can grey out a button, explain a row,
or warn before deleting, all without attempting anything — and so the
tests can prove each decision without touching a repo.
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
    """Why `worktree` must never be deleted, or None when it structurally
    may be (R4). These two refusals are absolute — nothing overrides them,
    not even `force`. Everything about data loss (uncommitted work,
    untracked files, unreadable state) lives in `destructive_delete_warning`
    instead, because those are shown and can be acknowledged, not refused
    outright.
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
    return None


def destructive_delete_warning(worktree: Worktree) -> Optional[str]:
    """What deleting `worktree` would destroy, or None when nothing would
    be lost. Unlike `refuse_delete_reason`, this is shown to the user
    rather than enforced unconditionally: `delete(..., force=True)`
    proceeds anyway, once the typed-name confirmation has acknowledged it.

    The uncommitted-work case is deliberately stricter than "tracked files
    differ from HEAD". An untracked file is not work git is following, so
    it never marks the header dirty (AC20) — but deleting the worktree
    deletes the file, and unlike a tracked change it exists nowhere else.
    """
    try:
        summary = diff_core.get_change_summary(worktree.path)
    except diff_core.DiffError as exc:
        return (
            f"Garage could not read the state of '{worktree.path}' ({exc}), "
            f"so it cannot tell what deleting it would destroy."
        )
    if summary.dirty:
        one = summary.changed_file_count == 1
        return (
            f"'{worktree.path}' holds uncommitted work: "
            f"{summary.changed_file_count} {'file' if one else 'files'} "
            f"{'differs' if one else 'differ'} from HEAD "
            f"(+{summary.added_lines} −{summary.removed_lines}). "
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
    force: bool = False,
) -> None:
    """Remove `worktree`, having refused every structural reason not to,
    and either refused or honoured the destructive ones (R4).

    `typed_name` must match the worktree's directory name exactly — the
    third guard, and the one that catches a misclick on the right row of a
    list. `force` defaults to False, so a caller that has not shown the
    destructive warning gets today's safety: a dirty or untracked worktree
    is refused. A caller passes `force=True` only once it has shown that
    warning and the typed name has confirmed it. The branch is untouched
    either way: `git worktree remove` leaves it, and nothing here deletes
    a branch.
    """
    reason = refuse_delete_reason(worktree, active, worktrees)
    if reason is not None:
        raise WorktreeError(reason)

    expected = worktree.path.name
    if (typed_name or "").strip() != expected:
        raise WorktreeError(
            f"To delete this worktree, type its name exactly: '{expected}'."
        )

    if not force:
        warning = destructive_delete_warning(worktree)
        if warning is not None:
            raise WorktreeError(warning)

    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree.path))
    result = _run_git(args, game_repo)
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
