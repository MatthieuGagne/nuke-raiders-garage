"""Committing to the active worktree (R5), and the refusals that come
first. Pure and Qt-free.

The commit itself is one more command run through
`tools.garage.core.make_runner`, for R6's sake: the game repository's
pre-commit hook runs its whole tool suite, which takes about ninety
seconds, and `git commit` prints that hook's output as it goes. Reusing the
streaming runner means the commit panel shows that output line by line
exactly as the compile bar shows a build, instead of freezing until git
returns.

**The hook is never skipped.** Nothing here passes `--no-verify`, and
nothing should: the verification is the reason a commit takes ninety
seconds, and a tool that quietly bypasses it would be worse than a tool
that cannot commit at all.

Only tracked changes are committed (`git commit -a`). An untracked file is
not work git is following — the header does not count it as dirty (AC20)
and Garage does not sweep it into a commit the user did not ask for. That
is a real limit: a new file has to be added in a terminal first, and the
panel says so rather than leaving the user to notice.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from tools.garage.core import diff as diff_core, make_runner
from tools.garage.core.project import Binding

COMMIT_TARGET = "commit"


def commit_command(message: str) -> make_runner.Command:
    """`git commit -a -m <message>`, as a runnable command.

    The label leaves the message out: it can be long, and a log line that
    echoes a paragraph back is not a log line. No `--no-verify`.
    """
    return make_runner.Command(
        argv=("git", "commit", "-a", "-m", message),
        label="git commit -a",
        target=COMMIT_TARGET,
    )


def refuse_reason(
    binding: Optional[Binding],
    message: str,
    summary: Optional[diff_core.ChangeSummary] = None,
) -> Optional[str]:
    """Why this commit must not be made, or None when it may (R5/AC5).

    Order matters: the branch is checked before the message, so a user on
    `master` is told the thing they cannot fix by typing more.
    """
    if binding is None:
        return "No repository is bound; there is nothing to commit to."

    branch = binding.active_worktree.branch
    if branch is None:
        return (
            f"'{binding.active_worktree.path}' is on a detached HEAD. Check "
            f"out a branch before committing, or the commit belongs to "
            f"nothing."
        )
    if diff_core.is_master_branch(branch):
        return (
            f"The active worktree is on {branch}. Garage does not commit "
            f"there — make a branch first, and the work merges through a "
            f"pull request."
        )
    if not (message or "").strip():
        return "A commit message is required."
    if summary is not None and not summary.dirty:
        if summary.untracked_count:
            return (
                f"No tracked file differs from HEAD. The "
                f"{summary.untracked_count} untracked file(s) in this "
                f"worktree are not committed by Garage — add them in a "
                f"terminal first if they belong in the commit."
            )
        return "Nothing to commit: no tracked file differs from HEAD."
    return None


def describe_pending(summary: Optional[diff_core.ChangeSummary]) -> str:
    """What a commit would carry, stated before it is made. Names the
    untracked files that will *not* be in it, since that is the part the
    user cannot see from the totals alone.
    """
    if summary is None:
        return "Garage could not read what this worktree holds."
    if not summary.dirty:
        base = "No tracked change to commit."
    else:
        files = "file" if summary.changed_file_count == 1 else "files"
        base = (
            f"{summary.changed_file_count} {files} "
            f"+{summary.added_lines} −{summary.removed_lines}"
        )
    if summary.untracked_count:
        one = summary.untracked_count == 1
        base += (
            f" · {summary.untracked_count} untracked "
            f"{'file' if one else 'files'} will not be included"
        )
    return base


def git_dir(worktree: Path) -> Optional[Path]:
    """The git directory serving `worktree` — for a linked worktree that
    is `.git/worktrees/<name>`, not the repository's own `.git`. Read with
    `rev-parse`, which needs no lock and so still answers when the index is
    locked.
    """
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    return Path(path) if path else None


def remove_stale_index_lock(worktree: Path) -> Optional[str]:
    """Delete `index.lock` in the worktree's git directory, and say so.
    Returns None when there was nothing to remove.

    Called only after Garage has killed a `git commit` it started. git
    takes that lock while it stages, and removes it on any exit it
    controls — but Garage stops a run by killing the process tree, which
    is the one exit it does not control. The lock is left behind and every
    later git write in that worktree fails with "Another git process seems
    to be running in this repository, or the lock file may be stale".

    Removing a lock file is only safe when the holder is known to be dead,
    which is exactly the case here: Garage killed it and waited for its
    pipe to close. Nothing else in Garage removes this file, and no caller
    should — a lock left by a git command Garage did not start may well be
    live.
    """
    directory = git_dir(worktree)
    if directory is None:
        return None
    lock = directory / "index.lock"
    if not lock.exists():
        return None
    try:
        lock.unlink()
    except OSError as exc:
        return (
            f"The interrupted commit left {lock}, and Garage could not "
            f"remove it ({exc}). Delete it by hand — git will refuse every "
            f"write in this worktree until it is gone."
        )
    return (
        f"Removed {lock.name}, left behind by the interrupted commit. "
        f"Without it, git would refuse every later write in this worktree."
    )


def head_line(worktree: Path) -> Optional[str]:
    """`<short sha> <subject>` for the worktree's HEAD, or None when it
    cannot be read. This is what AC6 checks — a commit made in Garage
    appears in `git log` — so the panel reports it from git rather than
    from its own success.
    """
    result = subprocess.run(
        ["git", "-C", str(worktree), "log", "-1", "--format=%h %s"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    return line or None


def log_lines(worktree: Path, count: int = 5) -> List[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), "log", f"-{count}", "--format=%h %s"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]
