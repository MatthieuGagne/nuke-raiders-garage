"""Runs `make` in the active worktree and hands back its output as it
arrives (R11, R6). Pure and Qt-free, like every module under
tools/garage/core/: it owns a subprocess, a pipe and a stopwatch, and knows
nothing about the widget that displays what it reads.

Three rules shape it.

**Output arrives, it does not accumulate.** A compile takes tens of seconds
and the pre-commit verification R6 names takes about ninety; a display with
no progress reads as a failure. `run` therefore calls `on_line` for every
line as the pipe produces it, and never returns a captured blob for the
caller to render at the end. The caller is on another thread (see
`tools/garage/panels/compile_bar.py`), which is why nothing here touches Qt.

**Every path resolves against the active worktree** (R2). `run` takes the
directory explicitly and passes it as the subprocess's cwd -- nothing here
reads a global, and there is no default that could quietly target the main
checkout while the user is working in a worktree.

**A missing tool is a result, not a crash.** `make` absent from PATH raises
FileNotFoundError inside Popen; that becomes a failed `RunResult` whose
output names the missing executable, so the compile panel reports it the
same way it reports a compile error. The Doctor (R14) is what tells the
user this in advance; this is the backstop for the moment they press Build
anyway.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

# The exact four calls R11 names. The key is what a caller asks for; the
# value is the argument list appended to `make`. The default target is the
# empty tuple -- `make` with no argument, which is what builds the ROM.
MAKE_TARGETS = {
    "build": (),
    "clean": ("clean",),
    "memory-check": ("memory-check",),
    "bank-post-build": ("bank-post-build",),
}

MAKE_EXECUTABLE = "make"

# Which of the Doctor's checks (R14) each target actually depends on, by
# check key. Read from the game repository's Makefile:
#   clean            `rm -rf build/` -- a coreutil, and the recipe runs
#                    under `SHELL := bash`, so a machine without Git's
#                    usr\bin has neither the shell nor the tool.
#   build            `$(GBDK_HOME)/bin/lcc` per source file, under the same
#                    shell.
#   memory-check     `python tools/memory_check.py` -- no external tool
#                    beyond make itself.
#   bank-post-build  `python tools/bank_post_build.py`, which resolves
#                    romusage through shutil.which and raises without it.
TARGET_REQUIREMENTS = {
    "build": ("make", "gbdk-home", "git-unix-tools"),
    "clean": ("make", "git-unix-tools"),
    "memory-check": ("make",),
    "bank-post-build": ("make", "romusage"),
}

# The ROM the default target writes, relative to the worktree root (AC11).
ROM_RELATIVE_PATH = ("build", "nuke-raider.gb")

# Targets that measure a build rather than producing one.
ROM_DEPENDENT_TARGETS = ("memory-check", "bank-post-build")

# Exit code reported when the command could not be started at all. 127 is
# the shell convention for "command not found", and it cannot collide with
# a real make exit code (make uses 1 and 2).
EXIT_NOT_STARTED = 127

# Exit code reported for a run the user stopped. 130 is the shell
# convention for "terminated by SIGINT".
EXIT_CANCELLED = 130


class UnknownTargetError(Exception):
    """Raised for a target outside MAKE_TARGETS. R11 names four calls, and
    a typo must fail here rather than run an arbitrary make target in the
    user's worktree.
    """


@dataclass(frozen=True)
class Command:
    """One command to run, plus the text a log echoes for it ("$ make
    clean"). `label` exists so the display never has to re-join argv and
    guess at quoting; `target` is the MAKE_TARGETS key it came from, which
    is what `explain_failure` needs when it fails.
    """

    argv: Sequence[str]
    label: str
    target: str = ""


@dataclass
class RunResult:
    command: Command
    exit_code: int
    duration_s: float
    cancelled: bool = False
    # Whether a stop was asked for, whatever came of it. `cancelled` says
    # the stop worked; this says it was pressed. They differ exactly when
    # the kill lost the race, and a caller that wants to tell the user
    # "too late" rather than "nothing happened" needs both.
    stop_requested: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.cancelled


def make_command(target: str) -> Command:
    """The `make` invocation for one of R11's four targets."""
    if target not in MAKE_TARGETS:
        raise UnknownTargetError(
            f"'{target}' is not a make target Garage runs. Known targets: "
            f"{', '.join(sorted(MAKE_TARGETS))}."
        )
    arguments = MAKE_TARGETS[target]
    argv = [MAKE_EXECUTABLE, *arguments]
    return Command(argv=tuple(argv), label=" ".join(argv), target=target)


def explain_failure(target: str, report) -> List[str]:
    """Lines that connect a failed target to the toolchain checks it needs,
    for the ones the Doctor already reported as failing (R14).

    Garage knows, at startup, that `romusage` is missing and that
    `bank-post-build` is the target that needs it. Leaving the user to
    re-derive that from `FileNotFoundError` in the log wastes the check.
    The mapping below is what makes that connection; a target whose
    requirements all pass gets no explanation, so a genuine compile error
    is never buried under toolchain prose.

    `report` is a `tools.garage.core.doctor.Report` (duck-typed here to
    keep this module independent of that one).
    """
    if report is None:
        return []
    required = TARGET_REQUIREMENTS.get(target, ())
    failing = [c for c in report.failures if c.key in required]
    if not failing:
        return []
    lines = [
        "This target needs a tool the toolchain check reported as missing "
        "when Garage started (View ▸ Toolchain):"
    ]
    for check in failing:
        lines.append(f"  {check.name} — {check.detail}")
        lines.append(f"    {check.prevents}")
    return lines


def rom_path(worktree: Path) -> Path:
    """Where the default target writes the ROM, in `worktree` (AC11)."""
    return Path(worktree).joinpath(*ROM_RELATIVE_PATH)


def explain_missing_rom(target: str, worktree: Path) -> List[str]:
    """A line for a measuring target that failed with nothing to measure.

    `memory-check` and `bank-post-build` read what a build produced. Run
    either against a worktree that has never been built, or one that was
    just cleaned, and the game repository's own scripts fail on the absence
    rather than reporting it: `memory_check.py` formats a `None` and raises
    a TypeError, `bank_post_build.py` cannot find the ROM. Neither
    traceback says "build first", which is the whole content of the
    failure.
    """
    if target not in ROM_DEPENDENT_TARGETS:
        return []
    rom = rom_path(worktree)
    if rom.is_file():
        return []
    return [
        f"This target measures a build that is not there — {rom} does not "
        f"exist. Run Build first."
    ]


def needs_clean_build(worktree: Path) -> bool:
    """True when the objects already in `build/` were compiled before the
    current `src/config.h` -- so an incremental `make` would relink them
    unchanged and produce a ROM that does not carry the edited value.

    The game repository's Makefile compiles with
    `$(OBJ_DIR)/%.o: src/%.c` and generates no dependency files, so no
    object ever depends on a header. `make` therefore sees nothing to do
    after a tuning edit, exits 0, and hands back the previous ROM. Only
    `src/dialog_data.c` and `src/hub_data.c` name `src/config.h` as a
    prerequisite, so only they rebuild.

    Garage cannot fix that Makefile -- it changes no file the game
    repository tracks -- so it detects the condition instead, and the
    compile bar cleans first when this returns True. The real fix belongs
    to the game repository (MatthieuGagne/gmb-nuke-raider#612).

    Returns False when nothing has been compiled yet: a build with no
    objects compiles everything regardless, and cleaning would only delete
    an empty directory.
    """
    worktree = Path(worktree)
    config_h = worktree / "src" / "config.h"
    object_dir = worktree / "build" / "obj"
    if not config_h.is_file() or not object_dir.is_dir():
        return False
    objects = list(object_dir.glob("*.o"))
    if not objects:
        return False
    config_mtime = config_h.stat().st_mtime
    return any(obj.stat().st_mtime < config_mtime for obj in objects)


def describe_rom(worktree: Path) -> str:
    """One line about the ROM the default target should have written
    (AC11): its path and size, or the fact that it is not there.

    A build that exits 0 without producing the ROM is not a hypothetical --
    a target whose recipe is skipped, or a BUILD_DIR pointing elsewhere,
    both do it -- and "make succeeded" alone would hide it.
    """
    path = rom_path(worktree)
    if not path.is_file():
        return f"{path} was not written"
    size_kb = path.stat().st_size / 1024
    return f"{path} — {size_kb:,.0f} KB"


class Cancellation:
    """The handle a caller keeps to stop a run it started.

    `cancel()` is called from another thread than `run()` -- the UI thread,
    while the run thread sits blocked on the pipe -- so both the flag and
    the process reference are guarded. Killing the process is what actually
    ends the run: closing the pipe would leave `make` (and whatever it
    spawned) alive.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            process = self._process
        if process is not None:
            _kill_tree(process)

    def _attach(self, process: Optional[subprocess.Popen]) -> None:
        """Called by `run` around the life of one subprocess. Attaching a
        process that is already cancelled kills it immediately, closing the
        window between `cancel()` and the next command in a sequence
        starting.
        """
        with self._lock:
            self._process = process
            already = self._event.is_set()
        if already and process is not None:
            _kill_tree(process)


def run(
    command: Command,
    cwd: Path,
    on_line: Callable[[str], None],
    cancellation: Optional[Cancellation] = None,
) -> RunResult:
    """Run `command` in `cwd`, calling `on_line` for each line of its
    output as it arrives, and return how it went.

    stderr is merged into stdout so the log reads in the order the tools
    actually wrote it -- a compiler error interleaved with the make recipe
    that provoked it, rather than two blocks to reconcile afterwards.

    Output is decoded as UTF-8 with replacement: the toolchain is a mix of
    GNU tools, SDCC and Python, and a byte that decodes badly must cost one
    glyph in the log, never the whole run.

    A line is delivered when the writer ends it. A tool that draws progress
    with a bare carriage return and no newline is therefore held until it
    finishes its line -- none of R11's four targets does that, and buying
    partial lines would mean giving up line-based reading everywhere else.
    """
    started = time.monotonic()

    if cancellation is not None and cancellation.cancelled:
        return RunResult(
            command, EXIT_CANCELLED, 0.0, cancelled=True, stop_requested=True
        )

    try:
        process = subprocess.Popen(
            list(command.argv),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line buffered: the point of the whole module
        )
    except OSError as exc:
        on_line(f"{command.argv[0]}: {exc.strerror or exc}")
        return RunResult(command, EXIT_NOT_STARTED, time.monotonic() - started)

    if cancellation is not None:
        cancellation._attach(process)
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            on_line(raw_line.rstrip("\r\n"))
        exit_code = process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if cancellation is not None:
            cancellation._attach(None)

    stop_requested = cancellation is not None and cancellation.cancelled
    # A stop is only a stop if it ended something. `_kill_tree` runs
    # `taskkill /F /T`, which enumerates a process tree and then kills what
    # it enumerated -- so a tree still growing underneath it can outlive
    # the kill, and the command runs to completion regardless. That is not
    # a hypothesis: nuke-raiders-garage#8 caught taskkill returning 128
    # having failed on git itself, git going on to finish the commit, and
    # the panel announcing "stopped -- nothing was committed" over a commit
    # that was on the branch.
    #
    # An exit code of zero is the evidence that it finished: a process
    # ended by TerminateProcess cannot produce one. The reverse is not
    # decidable -- a non-zero exit after a stop may be the kill or may be
    # the command failing on its own -- and between those two readings
    # "the user stopped it" is the one that must not be shown as a broken
    # build, so it stays.
    was_cancelled = stop_requested and exit_code != 0
    if was_cancelled:
        # A killed process reports whatever the kill produced; the run's
        # own outcome is "the user stopped it", which is not a failure of
        # the build and must not be displayed as one.
        exit_code = EXIT_CANCELLED
    return RunResult(
        command,
        exit_code,
        time.monotonic() - started,
        cancelled=was_cancelled,
        stop_requested=stop_requested,
    )


def run_sequence(
    commands: List[Command],
    cwd: Path,
    on_line: Callable[[str], None],
    cancellation: Optional[Cancellation] = None,
    on_command: Optional[Callable[[Command], None]] = None,
) -> List[RunResult]:
    """Run `commands` in order, stopping at the first one that does not
    succeed -- "clean build" is `make clean` then `make`, and building on
    top of a clean that failed would compile against a half-deleted tree.

    `on_command` is called just before each command starts, so the log can
    echo it ("$ make clean") the way the prototype's does. The results
    returned are only the commands that actually ran.
    """
    results: List[RunResult] = []
    for command in commands:
        if cancellation is not None and cancellation.cancelled:
            break
        if on_command is not None:
            on_command(command)
        result = run(command, cwd, on_line, cancellation)
        results.append(result)
        if not result.ok:
            break
    return results


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill `process` and everything it started.

    `make` is a parent: it spawns bash, which spawns lcc, which spawns
    sdcc. Terminating make alone would leave the compile running with its
    output going nowhere, and the pipe open, so the run would never end.
    On Windows `taskkill /T` is what walks the tree; elsewhere, and if
    taskkill is unavailable, killing the direct child is the fallback.
    """
    if process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
