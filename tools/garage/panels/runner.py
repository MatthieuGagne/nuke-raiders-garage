"""Running a sequence of commands on a worker thread, and getting its
output back as Qt signals.

Extracted from the compile bar when the commit panel needed the same
thing (R6: the pre-commit verification takes about ninety seconds, and a
display with no progress reads as a failure). The two panels differ in
what they run and what they do with the result; the thread lifecycle —
start, stream, cancel, join, disconnect — is identical, and having one
copy of it means a fix to the teardown is a fix everywhere.

`tools.garage.core.make_runner` does the actual work and knows nothing
about Qt; this is the thin layer that moves it off the UI thread. Nothing
here touches a widget.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from tools.garage.core import make_runner

# How long to wait for a cancelled run's thread to end (milliseconds). The
# kill has already been sent; this is only the time the process needs to
# die and the pipe to close.
STOP_TIMEOUT_MS = 5000


class RunWorker(QObject):
    """Runs a sequence on its own thread. Owns no widget: every signal is
    delivered to the controller on the UI thread.
    """

    line = Signal(str)
    command_started = Signal(str, str)  # label, target
    done = Signal(object)  # List[make_runner.RunResult]

    def __init__(
        self,
        commands: List[make_runner.Command],
        cwd,
        cancellation: make_runner.Cancellation,
    ):
        super().__init__()
        self._commands = commands
        self._cwd = cwd
        self._cancellation = cancellation

    def run(self) -> None:
        results = make_runner.run_sequence(
            self._commands,
            self._cwd,
            self.line.emit,
            self._cancellation,
            on_command=lambda command: self.command_started.emit(
                command.label, command.target
            ),
        )
        self.done.emit(results)


class RunController(QObject):
    """One run at a time, on a thread, with its output as signals.

    A second `start` while a run is in flight is refused rather than
    queued: two runs would interleave two tools' output in one log and
    race over the same worktree.
    """

    line = Signal(str)
    command_started = Signal(str, str)
    finished = Signal(object)  # List[make_runner.RunResult]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[RunWorker] = None
        self._cancellation: Optional[make_runner.Cancellation] = None

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, commands: List[make_runner.Command], cwd: Path) -> bool:
        """Begin a run. Returns False when one is already in flight."""
        if self.is_running():
            return False

        self._cancellation = make_runner.Cancellation()
        self._worker = RunWorker(commands, cwd, self._cancellation)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.line.connect(self.line.emit)
        self._worker.command_started.connect(self.command_started.emit)
        self._worker.done.connect(self._on_done)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Ask the run to end. The process tree is killed immediately; the
        run reports itself finished once the pipe closes, through the same
        path a normal end takes.
        """
        if self._cancellation is not None:
            self._cancellation.cancel()

    def stop_and_wait(self) -> None:
        """Stop a run and join its thread, for a window closing: a QThread
        still running when Qt tears its parent down is a crash, and a
        command that outlives the window it reports to is invisible work in
        the user's worktree.
        """
        if self._thread is None:
            return
        self.stop()
        self._teardown()

    def _on_done(self, results) -> None:
        self._teardown()
        self.finished.emit(results)

    def _teardown(self) -> None:
        """End the thread and worker and forget them.

        The worker's signals are disconnected first: after this, a queued
        emission still in flight has nowhere to land, which is what keeps a
        late line from reaching widgets on their way out. Qt allows
        disconnecting during an emission, which is exactly the `_on_done`
        case.
        """
        thread, worker = self._thread, self._worker
        self._thread, self._worker, self._cancellation = None, None, None
        if worker is not None:
            for signal in (worker.line, worker.command_started, worker.done):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if thread is not None:
            thread.quit()
            thread.wait(STOP_TIMEOUT_MS)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
