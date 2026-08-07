"""Starting Emulicious on the ROM the active worktree just built, and the
refusals that come first (R13).

Separate from `budgets.py` because it does the one thing that module must
not: it starts a process. The decision to refuse lives here too, since it
is about launching rather than about measuring -- `budgets` answers "what
are the numbers", this answers "may we run this".

No Qt. The emulator is started detached and unwatched: it is a GUI
application the user drives, not a build step whose output Garage streams,
and it must outlive the run that started it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from tools.garage.core.budgets import BudgetReport

JAVA_EXECUTABLE = "java"


def launch_command(jar: Path, rom: Path) -> List[str]:
    """`java -jar Emulicious.jar <rom>` -- the invocation the game
    repository's own workflow uses.
    """
    return [JAVA_EXECUTABLE, "-jar", str(jar), str(rom)]


def refuse_reason(
    report: Optional[BudgetReport], rom: Path, jar: Optional[Path]
) -> Optional[str]:
    """Why Emulicious must not start, or None when it may.

    R13/AC13 gates on FAIL and on FAIL only. A WARN is a number worth
    watching, not a broken ROM -- the build that ships today reports OAM
    32/40 WARN, and refusing to run that would make the gate the thing the
    user routes around rather than the thing that protects them. A budget
    that could not be measured is not a failure either: R13 says "when a
    memory budget result is FAIL", and naming why a check could not run is
    the Doctor's job.
    """
    if jar is None or not Path(jar).is_file():
        return (
            f"Emulicious is not where Garage expects it ({jar}). "
            f"View ▸ Toolchain names what that prevents."
        )
    if not Path(rom).is_file():
        return f"There is no ROM to run — {rom} does not exist. Build first."
    if report is not None and report.has_fail:
        failed = ", ".join(f"{b.name} {b.value_text()}" for b in report.failures)
        return (
            f"A memory budget is over: {failed}. Emulicious is not started, "
            f"because a ROM that breaks a hardware budget is not the ROM you "
            f"meant to test."
        )
    return None


def launch(jar: Path, rom: Path, cwd: Optional[Path] = None) -> subprocess.Popen:
    """Start Emulicious on `rom`. The caller must have checked
    `refuse_reason` first -- this function starts what it is told to.

    Detached, with its streams sent to the null device: Garage neither
    reads nor waits for the emulator, and inheriting a pipe nobody drains
    would eventually block it. On Windows the process also gets its own
    group, so closing Garage (which kills the compile's process tree) can
    never take the emulator with it.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return subprocess.Popen(
        launch_command(jar, rom),
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
