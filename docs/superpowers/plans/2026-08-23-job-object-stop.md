# Job Object Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End a stopped Garage run by terminating a kernel-owned process group the whole run lives in, instead of walking a process tree with `taskkill /F /T` that is still growing underneath the walk.

**Architecture:** A new Qt-free `tools/garage/core/process_group.py` wraps one Windows Job Object created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (via `ctypes`, no new dependency), and one POSIX session/process group as the same abstraction elsewhere. `make_runner.run` creates one group per command, adopts the child immediately after `Popen` returns, and closes the group once the child has exited. `Cancellation` carries the group alongside the `Popen`, and the kill path terminates the group. Nothing else about the run contract changes: `run_sequence`, `Cancellation._attach` and the `EXIT_CANCELLED` reporting still work against a `Popen` they can poll.

**Tech Stack:** Python 3.13, stdlib only (`ctypes`, `subprocess`, `os`, `signal`), `unittest`. No PySide6 in any file this plan touches under `tools/garage/core/` or `tests/test_garage_core.py`.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/26 (context: #8 the investigation, #24 the reporting half, #1 the epic)

## Global Constraints

- **No new dependency.** The Job Object calls go through `ctypes` against `kernel32`. `pywin32` is not to be added. `requirements.txt` names PySide6 and nothing else, and must keep naming PySide6 and nothing else.
- **No Qt import in `tools/garage/core/`** (epic #1 architecture rule). `process_group.py` and `make_runner.py` import stdlib only.
- **`make test` must pass with PySide6 absent** — `.github/workflows/test.yml` runs it on `windows-latest` and `ubuntu-latest` with no display library installed. Every test this plan adds to `tests/test_garage_core.py` must pass on both.
- **`make test`** is the default suite (`tests/`, ~330 tests, ~60s). **`make test-garage`** is the panel suite (`tests/garage/`, 225 tests, ~12 min locally / ~2.5 min on CI, needs PySide6). This plan touches both, so both must be run.
- **Garage changes no file the game repository tracks** (epic #1). Nothing here leaves this repository.
- **The race cannot be closed, only narrowed.** A Stop pressed a microsecond after git finishes can never be honoured. No test may assert that a stop always prevents the commit; the existing invariant — the panel's report matches the repository, whichever way the race went — is the one that holds.

---

### Task 1: The process group

**Files:**
- Create: `tools/garage/core/process_group.py`
- Test: `tests/test_garage_core.py` (new `TestProcessGroup` class, plus three module-level constants)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, for Task 2:
  - `process_group.ProcessGroup()` — construct one per run.
  - `ProcessGroup.spawn_kwargs() -> Dict[str, object]` — extra keyword arguments to splat into `subprocess.Popen`.
  - `ProcessGroup.adopt(process: subprocess.Popen) -> bool` — put the child, and everything it goes on to spawn, under group control. `False` means it could not be done and Stop will reach the direct child only.
  - `ProcessGroup.terminate() -> bool` — kill every member. `True` means the kernel accepted the request.
  - `ProcessGroup.close() -> None` — release the group. Idempotent. **This kills any surviving member**, so it is only ever called once the run's own process has exited.
  - `ProcessGroup` is also a context manager (`__enter__` / `__exit__` → `close()`).

- [ ] **Step 1: Write the failing tests**

Two edits to the import block at the top of `tests/test_garage_core.py`:

1. Add `import time` to the stdlib imports (the block currently reads `json, subprocess, sys, tempfile, threading, unittest, unittest.mock`).
2. Add `process_group` to the `from tools.garage.core import (...)` list, between `make_runner` and `project` — `process_group` sorts before `project` because `c` precedes `j`.

Then append this to `tests/test_garage_core.py`, placing the three constants **above** the existing `class TestCancellation` (Task 2 uses them from there too) and the new class immediately after `TestCancellation`:

```python
# A child that spawns a grandchild and then never ends, which is the shape
# #8 caught: git spawns the pre-commit hook, the hook spawns its own
# children, and the tree is still growing while the kill enumerates it.
# argv[1] is the grandchild's source, argv[2] the sentinel path.
PARENT_THAT_SPAWNS = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\n"
    "print('spawned', flush=True)\n"
    "while True:\n"
    "    time.sleep(0.05)\n"
)

# The grandchild. It waits long enough that a kill landing now is
# unambiguous, then records that it survived.
GRANDCHILD_SENTINEL = (
    "import pathlib, sys, time\n"
    "time.sleep(2.5)\n"
    "pathlib.Path(sys.argv[1]).write_text('ran')\n"
)

# Past the grandchild's sleep, with margin for a loaded CI runner.
GRANDCHILD_DEADLINE_S = 6.0
```

```python
class TestProcessGroup(unittest.TestCase):
    """The kernel-owned group a run lives in (#26).

    These tests spawn a real three-generation tree rather than mocking a
    kill, because the defect they cover is entirely about what the kernel
    does with processes the killer never enumerated.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sentinel = Path(self.tmp.name) / "grandchild-ran"

    def spawn_a_tree(self, group):
        """Start the parent, wait until it says the grandchild exists."""
        argv = [
            sys.executable,
            "-c",
            PARENT_THAT_SPAWNS,
            GRANDCHILD_SENTINEL,
            str(self.sentinel),
        ]
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            **group.spawn_kwargs(),
        )
        self.addCleanup(self._end, process)
        self.assertTrue(group.adopt(process), "the child did not join the group")
        self.assertEqual(process.stdout.readline().strip(), "spawned")
        return process

    def _end(self, process):
        try:
            process.kill()
        except OSError:
            pass
        if process.stdout is not None:
            process.stdout.close()

    def assert_the_grandchild_never_ran(self):
        time.sleep(GRANDCHILD_DEADLINE_S)
        self.assertFalse(
            self.sentinel.exists(),
            "the grandchild outlived the group it was in",
        )

    def test_terminating_the_group_kills_a_grandchild_the_child_spawned(self):
        group = process_group.ProcessGroup()
        self.addCleanup(group.close)
        process = self.spawn_a_tree(group)

        self.assertTrue(group.terminate())

        process.wait(10)
        self.assert_the_grandchild_never_ran()

    def test_the_control_case_killing_the_child_alone_leaves_the_grandchild(self):
        """Proof that the test above can fail.

        Killing the direct child -- which is what Garage degrades to when
        it cannot make a group, and what `taskkill /F /T` effectively did
        on the run #8 caught -- leaves the grandchild running.
        """
        group = process_group.ProcessGroup()
        self.addCleanup(group.close)
        process = self.spawn_a_tree(group)

        process.kill()
        process.wait(10)

        time.sleep(GRANDCHILD_DEADLINE_S)
        self.assertTrue(
            self.sentinel.exists(),
            "the grandchild died without the group being terminated -- this "
            "test no longer proves anything about the group",
        )

    def test_closing_the_group_kills_what_is_left_of_it(self):
        """`close()` is the backstop, not the mechanism.

        The Windows job carries KILL_ON_JOB_CLOSE, so a run whose reader
        thread was abandoned, or a Garage that dies outright, does not
        leave a compile running with its output going nowhere.
        """
        group = process_group.ProcessGroup()
        process = self.spawn_a_tree(group)

        group.close()

        process.wait(10)
        self.assert_the_grandchild_never_ran()

    def test_closing_twice_is_safe(self):
        group = process_group.ProcessGroup()
        group.close()
        group.close()

    def test_terminating_a_group_that_adopted_nothing_does_not_raise(self):
        group = process_group.ProcessGroup()
        self.addCleanup(group.close)
        group.terminate()

    def test_spawn_kwargs_are_accepted_by_popen(self):
        """Whatever the platform contributes has to be real Popen syntax."""
        group = process_group.ProcessGroup()
        self.addCleanup(group.close)

        process = subprocess.Popen(
            [sys.executable, "-c", "pass"], **group.spawn_kwargs()
        )
        self.assertEqual(process.wait(10), 0)
```

`test_closing_the_group_kills_what_is_left_of_it` is the reason `close()` must kill on POSIX too: on Windows the kernel does it via KILL_ON_JOB_CLOSE, and off Windows the implementation has to do it itself for the contract to be the same on both platforms. Step 3 implements it that way.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_garage_core.TestProcessGroup -v`
Expected: FAIL — `ImportError: cannot import name 'process_group' from 'tools.garage.core'`

- [ ] **Step 3: Write the implementation**

Create `tools/garage/core/process_group.py`:

```python
"""One kernel-owned group per run, so Stop ends everything the run
started (#26). Pure and Qt-free like the rest of tools/garage/core/.

**Why not `taskkill /F /T`.** That is what Garage used to do, and `/T` is
not atomic: it enumerates a process tree and then kills what it
enumerated, while the tree is still growing underneath it -- git spawns
the pre-commit hook, the hook spawns its own children. Captured on
Windows while investigating #8, it killed two nodes, failed on git
itself, returned 128, and git went on to complete the commit.

**What replaces it.** On Windows, a Job Object. Every process the run
starts is a member because the kernel owns the membership, so a process
spawned while the kill is in flight is already in the job and dies with
it. The job carries `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, which means
losing the handle -- an abandoned reader thread, a Garage that dies
outright -- ends the run's processes too, rather than leaving a compile
running with its output going nowhere.

Off Windows the same shape is a new session: the child gets its own
process group, and terminating means `killpg`.

**The window this leaves.** The child is adopted just after `Popen`
returns rather than created inside the group, so a child that spawns a
grandchild in the microseconds before adoption escapes. That is a
startup-time window measured against process creation, not the
kill-time window #8 caught, which was hundreds of milliseconds wide with
the tree actively growing. `adopt` returns False when it fails, so the
caller can say so rather than degrade in silence.

**Ordering matters.** `close()` kills survivors, so it must only be
called once the run's own process has exited. `run` in make_runner.py
does that in a `finally`, after `process.wait()`.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from typing import Dict, Optional

WINDOWS = sys.platform == "win32"

# JOBOBJECTINFOCLASS.JobObjectExtendedLimitInformation
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
# JOBOBJECT_BASIC_LIMIT_INFORMATION.LimitFlags
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# The exit code TerminateJobObject gives every member.
_JOB_KILL_EXIT_CODE = 1

if WINDOWS:
    _ULONG_PTR = ctypes.c_size_t

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", _ULONG_PTR),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # restype must be declared: the default is c_int, which truncates a
    # 64-bit HANDLE to a wrong value that then fails every later call.
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    _kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _kernel32.SetInformationJobObject.restype = ctypes.c_int
    _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    _kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _kernel32.TerminateJobObject.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int


def _create_job() -> Optional[int]:
    """An unnamed job that kills its members when the last handle closes,
    or None if the kernel would not give us one.
    """
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    if not ok:
        _kernel32.CloseHandle(handle)
        return None
    return handle


class ProcessGroup:
    """The group one run lives in. One per `make_runner.run` call."""

    def __init__(self) -> None:
        self._handle: Optional[int] = _create_job() if WINDOWS else None
        self._pgid: Optional[int] = None
        self._closed = False

    def spawn_kwargs(self) -> Dict[str, object]:
        """Keyword arguments to splat into the run's `subprocess.Popen`.

        Windows contributes nothing -- the job is joined after the fact.
        POSIX puts the child in its own session, which is what makes the
        grandchildren reachable by `killpg`.
        """
        if WINDOWS:
            return {}
        return {"start_new_session": True}

    def adopt(self, process: subprocess.Popen) -> bool:
        """Put `process` -- and everything it spawns from here on -- under
        the group. False means the caller is on its own.
        """
        if self._closed:
            return False
        if WINDOWS:
            if self._handle is None:
                return False
            handle = getattr(process, "_handle", None)
            if handle is None:
                return False
            joined = _kernel32.AssignProcessToJobObject(
                self._handle, ctypes.c_void_p(int(handle))
            )
            return bool(joined)
        try:
            self._pgid = os.getpgid(process.pid)
        except (OSError, AttributeError):
            return False
        return True

    def terminate(self) -> bool:
        """Kill every member. True means the kernel accepted the request.

        Safe to call on a group nothing joined, and safe to call twice.
        """
        if self._closed:
            return False
        if WINDOWS:
            if self._handle is None:
                return False
            return bool(
                _kernel32.TerminateJobObject(self._handle, _JOB_KILL_EXIT_CODE)
            )
        if self._pgid is None:
            return False
        try:
            os.killpg(self._pgid, signal.SIGKILL)
        except ProcessLookupError:
            # Nothing left to kill is the outcome asked for, not a failure.
            return True
        except OSError:
            return False
        return True

    def close(self) -> None:
        """Release the group, killing anything still in it.

        Only call this once the run's own process has exited -- see the
        module docstring. Idempotent.
        """
        if self._closed:
            return
        if WINDOWS:
            if self._handle is not None:
                # KILL_ON_JOB_CLOSE does the killing.
                _kernel32.CloseHandle(self._handle)
                self._handle = None
        elif self._pgid is not None:
            try:
                os.killpg(self._pgid, signal.SIGKILL)
            except OSError:
                pass
            self._pgid = None
        self._closed = True

    def __enter__(self) -> "ProcessGroup":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_garage_core.TestProcessGroup -v`
Expected: PASS, 6 tests, about 25 seconds — three of them wait out the grandchild's sleep.

If `test_the_control_case_killing_the_child_alone_leaves_the_grandchild` fails, the harness is wrong rather than the implementation: the parent died before it spawned the grandchild. Check that the `spawned` line is read before the kill.

- [ ] **Step 5: Run the whole default suite**

Run: `make test`
Expected: PASS. The wall clock should be about 25 seconds longer than before.

- [ ] **Step 6: Commit**

```bash
git add tools/garage/core/process_group.py tests/test_garage_core.py
git commit -m "feat: a kernel-owned process group a run can be ended by (#26)"
```

---

### Task 2: Stop terminates the group

**Files:**
- Modify: `tools/garage/core/make_runner.py` — imports, `Cancellation`, `run`, and `_kill_tree` (renamed to `_end_run`)
- Test: `tests/test_garage_core.py` — `TestCancellation`: one new test, and two `_kill_tree` patch sites (~2587, ~2614)
- Test: `tests/garage/test_panels.py` — two `_kill_tree` patch sites (~1985, ~3306)

**Interfaces:**
- Consumes: `process_group.ProcessGroup` with `spawn_kwargs()`, `adopt()`, `terminate()`, `close()` as defined in Task 1.
- Produces:
  - `make_runner._end_run(process: subprocess.Popen, group: Optional[process_group.ProcessGroup] = None) -> None` — replaces `_kill_tree`. This is the name tests patch.
  - `Cancellation._attach(process: Optional[subprocess.Popen], group: Optional[process_group.ProcessGroup] = None) -> None` — the second parameter is new.
  - `Command`, `RunResult`, `run` and `run_sequence` signatures are unchanged.

- [ ] **Step 1: Write the failing test**

Add this to `TestCancellation` in `tests/test_garage_core.py`, after `test_cancelling_a_running_command_ends_it`. It uses `PARENT_THAT_SPAWNS`, `GRANDCHILD_SENTINEL` and `GRANDCHILD_DEADLINE_S`, which Task 1 placed above the class.

```python
    def test_cancelling_a_run_kills_a_grandchild_the_command_spawned(self):
        """The #8 shape, end to end through `run`.

        `make` spawns bash, bash spawns lcc, lcc spawns sdcc; git spawns
        the hook and the hook spawns its own children. A stop that only
        reaches the direct child leaves the run going and the pipe open.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sentinel = Path(tmp.name) / "grandchild-ran"
        command = make_runner.Command(
            argv=(
                sys.executable,
                "-c",
                PARENT_THAT_SPAWNS,
                GRANDCHILD_SENTINEL,
                str(sentinel),
            ),
            label="spawner",
        )
        started = threading.Event()
        cancellation = make_runner.Cancellation()

        def target():
            make_runner.run(
                command, Path.cwd(), lambda line: started.set(), cancellation
            )

        worker = threading.Thread(target=target)
        worker.start()
        try:
            self.assertTrue(started.wait(10), "the child never started")
            cancellation.cancel()
            worker.join(15)
            self.assertFalse(worker.is_alive(), "the run outlived its cancellation")
        finally:
            cancellation.cancel()
            worker.join(15)

        time.sleep(GRANDCHILD_DEADLINE_S)
        self.assertFalse(
            sentinel.exists(),
            "the grandchild outlived the stop that ended its parent",
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_garage_core.TestCancellation.test_cancelling_a_run_kills_a_grandchild_the_command_spawned -v`
Expected: FAIL — `AssertionError: False is not false : the grandchild outlived the stop that ended its parent`.

On Windows it can pass by luck, if `taskkill /T` happened to enumerate the whole tree in time. Run it three times and treat any single failure as the real result. If it passes three times, make the parent sleep 200ms *before* it spawns the grandchild — that is the growing-tree condition the issue is about — and re-run.

- [ ] **Step 3: Rewrite `_kill_tree` as `_end_run`**

Add to the imports at the top of `tools/garage/core/make_runner.py`, after the stdlib block and separated from it by a blank line:

```python
from tools.garage.core import process_group
```

(`process_group` imports nothing from `make_runner`, so there is no cycle.)

Replace the whole `_kill_tree` function with:

```python
def _end_run(
    process: subprocess.Popen,
    group: Optional[process_group.ProcessGroup] = None,
) -> None:
    """End `process` and everything it started.

    `make` is a parent: it spawns bash, which spawns lcc, which spawns
    sdcc; `git commit` spawns the pre-commit hook, which spawns its own
    children. Ending the direct child alone would leave the compile
    running with its output going nowhere, and the pipe open, so the run
    would never end.

    The group is what ends them, because the kernel owns its membership:
    a process spawned while the kill is in flight is already a member.
    The group is terminated even when the direct child has already
    exited, which is exactly the #8 case -- git finished and left the
    hook's children behind holding the pipe.

    `process.kill()` is the fallback for a group that could not be made
    or joined. It reaches the direct child only; `run` says so in the log
    the moment adoption fails, rather than degrading in silence.
    """
    if group is not None and group.terminate():
        return
    if process.poll() is not None:
        return
    try:
        process.kill()
    except OSError:
        pass
```

- [ ] **Step 4: Carry the group through `Cancellation`**

Replace the `Cancellation` class with:

```python
class Cancellation:
    """The handle a caller keeps to stop a run it started.

    `cancel()` is called from another thread than `run()` -- the UI
    thread, while the run thread sits blocked on the pipe -- so the flag,
    the process reference and the group are all guarded. Ending the group
    is what actually ends the run: closing the pipe would leave `make`
    (and whatever it spawned) alive.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._group: Optional[process_group.ProcessGroup] = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            process = self._process
            group = self._group
        if process is not None:
            _end_run(process, group)

    def _attach(
        self,
        process: Optional[subprocess.Popen],
        group: Optional[process_group.ProcessGroup] = None,
    ) -> None:
        """Called by `run` around the life of one subprocess. Attaching a
        process that is already cancelled ends it immediately, closing the
        window between `cancel()` and the next command in a sequence
        starting.
        """
        with self._lock:
            self._process = process
            self._group = group
            already = self._event.is_set()
        if already and process is not None:
            _end_run(process, group)
```

- [ ] **Step 5: Spawn every run inside a group**

In `run`, replace everything from `try:` / `process = subprocess.Popen(` down to the end of the `finally` block with:

```python
    group = process_group.ProcessGroup()
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
            **group.spawn_kwargs(),
        )
    except OSError as exc:
        group.close()
        on_line(f"{command.argv[0]}: {exc.strerror or exc}")
        return RunResult(command, EXIT_NOT_STARTED, time.monotonic() - started)

    if not group.adopt(process):
        # Never silent: the old taskkill path degraded to killing the
        # direct child without saying so, and a Stop that only half works
        # is worth a line in the log the user is already reading.
        on_line(
            "warning: this run is not in a process group — Stop will reach "
            "the top-level process only."
        )

    if cancellation is not None:
        cancellation._attach(process, group)
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            on_line(raw_line.rstrip("\r\n"))
        exit_code = process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        # Detach before closing, so a cancel arriving now finds either a
        # live group or nothing at all, never a closing one.
        if cancellation is not None:
            cancellation._attach(None, None)
        group.close()
```

Then update the comment block immediately below, which still describes `taskkill`. Replace its first paragraph so the whole block reads:

```python
    stop_requested = cancellation is not None and cancellation.cancelled
    # A stop is only a stop if it ended something. Terminating the run's
    # process group is far tighter than the `taskkill /F /T` tree walk it
    # replaced (#26), but it cannot be tight enough: a stop pressed after
    # git has written the commit and before git has exited has nothing
    # left to prevent. nuke-raiders-garage#8 caught exactly that -- the
    # command completed and the panel announced "stopped -- nothing was
    # committed" over a commit that was on the branch.
    #
    # An exit code of zero is the evidence that it finished: a process
    # ended by the kernel cannot produce one. The reverse is not
    # decidable -- a non-zero exit after a stop may be the kill or may be
    # the command failing on its own -- and between those two readings
    # "the user stopped it" is the one that must not be shown as a broken
    # build, so it stays.
    was_cancelled = stop_requested and exit_code != 0
```

- [ ] **Step 6: Update the four existing patch sites**

`_kill_tree` no longer exists and `_end_run` takes two arguments.

In `tests/test_garage_core.py`, in `test_a_stop_that_lost_the_race_reports_the_run_that_finished` and in `test_a_stop_whose_kill_worked_is_still_a_stop`, replace both occurrences of:

```python
        with unittest.mock.patch.object(make_runner, "_kill_tree", lambda p: None):
```

with:

```python
        with unittest.mock.patch.object(
            make_runner, "_end_run", lambda process, group=None: None
        ):
```

In `tests/garage/test_panels.py` (~1985, split across lines; ~3306, on one line), replace both occurrences of:

```python
make_runner, "_kill_tree", lambda process: None
```

with:

```python
make_runner, "_end_run", lambda process, group=None: None
```

keeping each site's existing line wrapping.

- [ ] **Step 7: Run the default suite**

Run: `python -m unittest tests.test_garage_core.TestCancellation -v`
Expected: PASS, including the new grandchild test.

Run: `make test`
Expected: PASS.

- [ ] **Step 8: Run the panel suite**

Run: `make test-garage`
Expected: PASS, 225 tests. **Budget twelve minutes** — it is not hung. The tests that matter here are the `TestCommitPanelStop*` ones; if either fails, read `assert_the_report_matches_the_repository` first: both outcomes of the race are legal, and only a panel that contradicts the repository is a failure.

- [ ] **Step 9: Commit**

```bash
git add tools/garage/core/make_runner.py tests/test_garage_core.py tests/garage/test_panels.py
git commit -m "fix: end a stopped run by terminating its process group, not by walking a tree (#26)"
```

---

### Task 3: The prose that still describes taskkill, and hand-verification

**Files:**
- Modify: `tools/garage/core/make_runner.py` — the module docstring
- Modify: `tools/garage/panels/commit.py` — `_announce_a_commit_the_stop_did_not_prevent`'s docstring (~315-325)
- Modify: `tests/garage/test_panels.py` — the docstrings of `assert_the_report_matches_the_repository` (~3265) and `test_a_stop_whose_kill_missed_reports_the_commit_anyway` (~3290)
- Modify: `tests/test_garage_core.py` — the docstring of `test_a_stop_that_lost_the_race_reports_the_run_that_finished` (~2568)

**Interfaces:**
- Consumes: `_end_run` and the group from Task 2. Produces nothing for a later task.

Four docstrings name `taskkill /F /T` as the mechanism and explain the defect in terms of tree enumeration. After Task 2 that mechanism is gone, and a reader who greps for it finds four confident descriptions of code that no longer exists. The *behaviour* they document — the race cannot be closed, the panel must never contradict the repository — is unchanged and has to survive the edit.

- [ ] **Step 1: Add the fourth rule to the make_runner module docstring**

The docstring says "Three rules shape it." and lists three. Change `Three` to `Four`, and add this paragraph after the "A missing tool is a result, not a crash" one:

```
**A stopped run ends as a group, not as a tree.** Every run is spawned
into a kernel-owned process group (`process_group.py`), and Stop ends
the group. The kernel owns the membership, so a process spawned while
the kill is in flight is already in it -- which the `taskkill /F /T`
tree walk this replaced could not manage, because it enumerated a tree
that was still growing (#8, #26). It narrows the race; it cannot close
it, since a Stop pressed after git has written the commit has nothing
left to prevent.
```

- [ ] **Step 2: Fix `commit.py`'s docstring**

In `tools/garage/panels/commit.py`, in `_announce_a_commit_the_stop_did_not_prevent`, replace:

```
        HEAD is the only witness worth asking. The run's exit code cannot
        answer it: `taskkill /F /T` can miss a process tree that is still
        growing, in which case git finishes and exits zero, and it can also
        land after git has written the commit but before git has exited, in
        which case git dies non-zero with the commit already on the branch.
        Both were observed on Windows in #8, and both used to be announced
        as "nothing was committed".
```

with:

```
        HEAD is the only witness worth asking. The run's exit code cannot
        answer it: a stop can land after git has written the commit but
        before git has exited, in which case git dies non-zero with the
        commit already on the branch, and it can arrive after git has
        finished entirely, in which case git exits zero. Both were
        observed on Windows in #8 -- back when the kill was a `taskkill
        /F /T` tree walk that could also miss a growing tree outright
        (#26) -- and both used to be announced as "nothing was committed".
```

- [ ] **Step 3: Fix the three test docstrings**

In `tests/garage/test_panels.py`, `assert_the_report_matches_the_repository` — replace:

```
        Stop kills a process tree, and `taskkill /F /T` can miss one that
        is still growing (#8), so a stop pressed while git is committing
        genuinely has two possible outcomes: the commit was prevented, or
        it was not.
```

with:

```
        Stop ends the run's process group, which narrows the race but
        cannot close it (#8, #26), so a stop pressed while git is
        committing genuinely has two possible outcomes: the commit was
        prevented, or it was not.
```

In `tests/garage/test_panels.py`, `test_a_stop_whose_kill_missed_reports_the_commit_anyway` — the docstring line reading "Neutering \`_kill_tree\` is the only part of that sequence a test can make happen on purpose" becomes "Neutering \`_end_run\` is the only part of that sequence a test can make happen on purpose".

In `tests/test_garage_core.py`, `test_a_stop_that_lost_the_race_reports_the_run_that_finished` — replace:

```
        `taskkill /F /T` enumerates a process tree and then kills what it
        enumerated, so a tree still growing underneath it -- git spawning
        the hook, the hook spawning its own children -- can outlive the
        kill. Observed on Windows in nuke-raiders-garage#8: the kill
        returned 128 having failed on git itself, git finished the commit,
        and the panel still announced "stopped -- nothing was committed"
        over a commit that was on the branch.
```

with:

```
        A stop can miss: it can arrive after the command has already
        finished, and before #26 it could also miss a process tree that
        was still growing while `taskkill /F /T` enumerated it. Observed
        on Windows in nuke-raiders-garage#8: the kill returned 128 having
        failed on git itself, git finished the commit, and the panel still
        announced "stopped -- nothing was committed" over a commit that
        was on the branch.
```

- [ ] **Step 4: Verify no stale reference is left**

Run: `grep -rn "taskkill\|_kill_tree" --include=*.py .`
Expected: only the four deliberate historical mentions above — `make_runner.py`'s module docstring, `commit.py`'s docstring, `make_runner.py`'s `was_cancelled` comment, and `test_garage_core.py`'s docstring — and **no** `_kill_tree` anywhere.

- [ ] **Step 5: Run everything**

Run: `make test`
Expected: PASS.

Run: `make lint`
Expected: exit 0. (Run it bare and read the exit code on the next line — a pipe masks it.)

Run: `make test-garage`
Expected: PASS, 225 tests, about twelve minutes.

- [ ] **Step 6: Hand-verify in the running application**

Green tests are not the acceptance criterion here; the defect is a race in a real toolchain. Launch Garage:

```bash
python -m tools.garage
```

1. **A stopped build stops.** Bind a game worktree, press Build on a clean tree, and press Stop while `lcc` / `sdcc` output is still scrolling. Then check Task Manager (Details view, sorted by name): no `sdcc.exe`, `lcc.exe`, `sh.exe` or `make.exe` may remain. Before this change, a stopped build could leave those running.
2. **A stopped commit still tells the truth.** With the slow pre-commit hook the panel tests install, press Commit and then Stop. Whichever way the race goes, the panel's status must agree with `git log -1`: either "stopped" with HEAD unmoved, or "stopped too late — the commit was already made: …" with HEAD moved. A disagreement is #8 reopening.
3. **A normal build still works.** Build to completion with no Stop pressed, and confirm the ROM line appears and the run ends clean — the group must not interfere with a run nobody stops.

Record what you saw in the PR body. If step 1 still leaves processes behind, stop: read the log for the "not in a process group" warning line, which says adoption failed and why the fallback was reached.

- [ ] **Step 7: Commit**

```bash
git add tools/garage/core/make_runner.py tools/garage/panels/commit.py tests/garage/test_panels.py tests/test_garage_core.py
git commit -m "docs: describe the stop mechanism that exists rather than the one it replaced (#26)"
```

---

## Notes for the reviewer

- **Why the child is adopted rather than created inside the group.** Creating it inside would need `CREATE_SUSPENDED` plus a `ResumeThread`, and `subprocess.Popen` closes the child's thread handle before returning, so getting one back means a thread snapshot by PID — a lot of `ctypes` for a window measured against process creation. The window this leaves is at *startup*; the one #8 caught was at *kill time*, with the tree actively growing, and it was hundreds of milliseconds wide.
- **What happens if `AssignProcessToJobObject` fails.** Windows 8 and later support nested jobs, so running inside a CI or debugger job is not a problem. If it fails anyway, `adopt` returns False, `run` writes a warning into the log the user is already reading, and Stop degrades to killing the direct child — the same reach the old "taskkill unavailable" branch had, but stated instead of silent.
- **`taskkill` is no longer invoked**, so Garage no longer depends on it being on PATH, and no longer ignores its exit code and its output the way `_kill_tree` did.
- **Possible bearing on #28.** That issue hypothesises an interpreter-shutdown `qFatal` from a thread still blocked on a pipe that a killed tree left open. `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` attacks that from the other end: losing the job handle kills the members, so the pipe gets closed. This plan does not claim to fix #28 and adds no test for it — but if the panel suite's intermittent non-zero exit stops appearing after this lands, that is evidence worth recording on #28 rather than a coincidence.
- **Test runtime.** The new tests add roughly 30 seconds to `make test`, all of it in `time.sleep` waiting out a grandchild that must be proven absent. That is the price of testing an absence; shortening `GRANDCHILD_DEADLINE_S` trades it for flakiness on a loaded CI runner.
