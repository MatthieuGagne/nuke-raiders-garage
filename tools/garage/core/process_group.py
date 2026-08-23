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
