"""The compile bar: R11's four make calls, with their output as it arrives.

Layout follows the prototype's build bar (`garage/index.html`): a row of
controls with a status line on the right, and the log underneath. It is
pinned to the bottom of the window rather than living behind a menu,
because the tuning loop is change a value → compile → look, and a compile
that has to be found first is a compile the user runs in a terminal
instead.

Threading: `tools.garage.core.make_runner` blocks on the subprocess pipe,
which would freeze the window for the length of a compile, so the run
happens on a `QThread` and reaches the widgets as signals. Everything that
touches a widget below runs on the UI thread; the worker only emits. The
core module knows nothing about any of this -- it takes callables, and the
worker's callables happen to be `Signal.emit`.

R18/AC18: no colour and no typeface here. The log is plain text and takes
its monospace face from the stylesheet; the state of the run is exposed as
a `state` dynamic property ("idle"/"busy"/"pass"/"fail") on the status dot
for `tools/garage/theme/qss.py` to colour, and the status line says the
same thing in words.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import budgets as budgets_core
from tools.garage.core import doctor as doctor_core
from tools.garage.core import emulicious, make_runner
from tools.garage.core.project import Binding, BindingError

# Height of the log, in lines of text. The prototype gives it a fixed
# strip at the bottom of the window; enough to watch a compile scroll past
# without the tuning loop losing the space it needs.
LOG_VISIBLE_LINES = 8

# Said in the log when Build cleans first, so a two-minute recompile is
# never unexplained. See `run_build` and `make_runner.needs_clean_build`.
CONFIG_CHANGED_NOTE = (
    "src/config.h changed since these objects were compiled. The game "
    "repository's Makefile carries no header dependency, so an incremental "
    "build would relink the old values — cleaning first."
)

# How long the window waits, on close, for a run it just cancelled to end
# (milliseconds). The kill is already sent; this is only the time the
# process needs to die and the pipe to close.
STOP_TIMEOUT_MS = 5000


class _RunWorker(QObject):
    """Runs a sequence of commands on its own thread. It owns no widget;
    every signal below is delivered to the panel on the UI thread.
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


class CompileBar(QWidget):
    """R11: `make`, `make clean`, `make memory-check` and
    `make bank-post-build`, run in the active worktree, output shown as it
    arrives.

    `ran` carries the results of a finished sequence. Iteration 8 reads it
    for the budgets and the Emulicious gate; the window uses it to refresh
    the header.
    """

    ran = Signal(object)  # List[make_runner.RunResult]
    budgets_read = Signal(object)  # budgets_core.BudgetReport | None

    def __init__(
        self,
        binding: Optional[Binding],
        binding_error: Optional[BindingError] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error

        self._thread: Optional[QThread] = None
        self._worker: Optional[_RunWorker] = None
        self._cancellation: Optional[make_runner.Cancellation] = None
        self._expects_rom = False
        # The startup toolchain report, set by the window once the Doctor
        # has run. A failed target whose missing tool is already in that
        # report says so, instead of leaving the user to read a
        # FileNotFoundError and re-derive what Garage knew at launch.
        self._doctor_report = None
        # Output captured per make target, so the measuring targets can be
        # parsed into budgets (R12) without a second run of anything.
        self._output: Dict[str, List[str]] = {}
        self._current_target = ""
        self._budget_report: Optional[budgets_core.BudgetReport] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        controls = QWidget()
        controls.setObjectName("compile-controls")
        row = QHBoxLayout(controls)

        self.build_button = self._button("Build", "compile-build", primary=True)
        self.build_button.clicked.connect(self.run_build)
        row.addWidget(self.build_button)

        self.clean_build_button = self._button("Clean build", "compile-clean-build")
        self.clean_build_button.clicked.connect(self.run_clean_build)
        row.addWidget(self.clean_build_button)

        self.memory_check_button = self._button("Memory check", "compile-memory-check")
        self.memory_check_button.clicked.connect(
            lambda: self.run_target("memory-check")
        )
        row.addWidget(self.memory_check_button)

        self.bank_check_button = self._button("Bank check", "compile-bank-check")
        self.bank_check_button.clicked.connect(
            lambda: self.run_target("bank-post-build")
        )
        row.addWidget(self.bank_check_button)

        self.launch_button = self._button("Launch in Emulicious", "compile-launch")
        self.launch_button.clicked.connect(self.launch_emulicious)
        row.addWidget(self.launch_button)

        self.stop_button = self._button("Stop", "compile-stop")
        self.stop_button.setProperty("role", "danger")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        row.addWidget(self.stop_button)

        row.addStretch(1)

        self.state_dot = QLabel()
        self.state_dot.setObjectName("compile-dot")
        row.addWidget(self.state_dot)

        self.status_label = QLabel()
        self.status_label.setObjectName("compile-status")
        row.addWidget(self.status_label)

        outer.addWidget(controls)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("compile-log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES + 16
        )
        outer.addWidget(self.log_view)

        self._buttons = [
            self.build_button,
            self.clean_build_button,
            self.memory_check_button,
            self.bank_check_button,
            self.launch_button,
        ]

        if self.binding is None:
            self._set_state("fail")
            self.status_label.setText(self._binding_error_message())
            for button in self._buttons:
                button.setEnabled(False)
        else:
            self._set_state("idle")
            self.status_label.setText("ready")

    # -- public API -------------------------------------------------------

    def set_doctor_report(self, report) -> None:
        """The window hands over the startup toolchain report once the
        Doctor has run (`tools.garage.core.doctor.Report`).
        """
        self._doctor_report = report

    def is_running(self) -> bool:
        return self._thread is not None

    def status_text(self) -> str:
        return self.status_label.text()

    def state(self) -> str:
        return self.state_dot.property("state")

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def run_build(self) -> None:
        """The default target -- except that it cleans first when the
        objects on disk predate `src/config.h`.

        A tuning edit leaves every object untouched as far as `make` can
        tell (the game repository's Makefile has no header dependencies),
        so an incremental build would exit 0 and hand back the previous
        ROM. The Build button must always produce a ROM carrying the values
        on screen, so it pays for a full recompile in exactly the case that
        needs one. See `make_runner.needs_clean_build`.
        """
        if self.is_running() or self.binding is None:
            return
        if make_runner.needs_clean_build(self.binding.active_worktree.path):
            self._append_line(CONFIG_CHANGED_NOTE)
            self.run_clean_build()
            return
        self.run_target("build")

    def run_target(self, target: str) -> None:
        """One of R11's four calls. An unknown target raises out of
        `make_runner.make_command` rather than running anything.

        A build is followed by the two measuring targets, the way the
        prototype's log shows them and the way the game repository's own
        post-build hook runs them: R12 asks for the budgets *after a
        compile*, and a budget panel that only fills in when the user
        remembers to press a second button is a budget panel that is
        usually stale. They cost about a second between them.
        """
        commands = [make_runner.make_command(target)]
        if target == "build":
            commands += [
                make_runner.make_command("memory-check"),
                make_runner.make_command("bank-post-build"),
            ]
        self._start(commands, expects_rom=target == "build")

    def run_clean_build(self) -> None:
        """`make clean` then `make`, stopping if the clean fails -- the
        prototype's "Clean build" button, and the sequence the game
        repository's own workflow uses before a smoketest.
        """
        self._start(
            [
                make_runner.make_command("clean"),
                make_runner.make_command("build"),
                make_runner.make_command("memory-check"),
                make_runner.make_command("bank-post-build"),
            ],
            expects_rom=True,
        )

    def output_for(self, target: str) -> str:
        """Everything the given make target printed during the last run,
        as one string -- the input the budget parser reads (R12).
        """
        return "\n".join(self._output.get(target, []))

    @property
    def budget_report(self) -> Optional[budgets_core.BudgetReport]:
        return self._budget_report

    def emulicious_jar(self):
        """Where the jar is, resolved exactly the way the Doctor resolves
        it -- the gate and the toolchain report must never disagree about
        which file they are talking about.
        """
        return doctor_core.resolve_emulicious_jar(
            doctor_core.load_binding_settings(self.binding), os.environ
        )

    def launch_refusal(self) -> Optional[str]:
        """Why pressing Launch would refuse, or None. Exposed so the gate
        can be read without pressing it (R13/AC13).
        """
        if self.binding is None:
            return self._binding_error_message()
        return emulicious.refuse_reason(
            self._budget_report,
            make_runner.rom_path(self.binding.active_worktree.path),
            self.emulicious_jar(),
        )

    def launch_emulicious(self) -> Optional[str]:
        """Start the emulator on the ROM in the active worktree, unless a
        refusal applies (R13). Returns the refusal, or None when it
        started.

        The refusal goes in the log rather than a dialog: it belongs with
        the compile output that produced the numbers it is about, and a
        modal would have to be dismissed before the user could read them.
        """
        refusal = self.launch_refusal()
        if refusal is not None:
            self._append_line(f"Emulicious not started — {refusal}")
            self.status_label.setText("launch refused — see the log")
            return refusal

        jar = self.emulicious_jar()
        rom = make_runner.rom_path(self.binding.active_worktree.path)
        command = emulicious.launch_command(jar, rom)
        self._append_line("$ " + " ".join(command))
        emulicious.launch(jar, rom, cwd=self.binding.active_worktree.path)
        self.status_label.setText("Emulicious started")
        return None

    def stop(self) -> None:
        """Ask the running sequence to end. The process tree is killed
        immediately; the run reports itself finished once the pipe closes,
        through the same path a normal end takes.
        """
        if self._cancellation is not None:
            self._cancellation.cancel()
            self.stop_button.setEnabled(False)
            self.status_label.setText("stopping…")

    def stop_and_wait(self) -> None:
        """Stop a run and wait for its thread, for the window to call on
        close: a QThread still running when Qt tears its parent down is a
        crash, and a compile that outlives the window it reports to is
        invisible work in the user's worktree.
        """
        if self._thread is None:
            return
        self.stop()
        # Tear down here rather than waiting for the worker's `done`
        # signal: that signal is queued to the UI thread, and on the way
        # out of the window there is no event loop left to deliver it on.
        self._teardown()

    # -- the run ----------------------------------------------------------

    def _start(self, commands: List[make_runner.Command], expects_rom: bool) -> None:
        if self.binding is None or self.is_running():
            # Two runs at once would interleave two tool outputs in one log
            # and race over build/; the buttons are disabled while a run is
            # in flight, and this is the guard behind them.
            return

        self._expects_rom = expects_rom
        self._cancellation = make_runner.Cancellation()
        # One run, one set of outputs: budgets from the previous compile
        # must never be mixed with this one's.
        self._output = {}
        self._current_target = ""

        self._worker = _RunWorker(
            commands, self.binding.active_worktree.path, self._cancellation
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.line.connect(self._append_line)
        self._worker.command_started.connect(self._append_command)
        self._worker.done.connect(self._on_done)

        self._set_running(True)
        self.status_label.setText(
            f"{' && '.join(c.label for c in commands)} — running…"
        )
        self._thread.start()

    def _set_running(self, running: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not running and self.binding is not None)
        self.stop_button.setEnabled(running)
        self._set_state("busy" if running else self.state())

    def _append_command(self, label: str, target: str) -> None:
        # The prototype's log echoes each command as a shell line, so the
        # output underneath is attributable to the call that produced it.
        # The target is remembered so the lines that follow can be handed
        # to the budget parser as that target's output (R12).
        self._current_target = target
        self._output.setdefault(target, [])
        self._append_line(f"$ {label}")

    def _append_line(self, text: str) -> None:
        if self._current_target:
            self._output.setdefault(self._current_target, []).append(text)
        self.log_view.appendPlainText(text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_done(self, results: List[make_runner.RunResult]) -> None:
        self._teardown()

        if self._expects_rom and results and all(r.ok for r in results):
            # AC11: say whether the ROM is actually there, in the active
            # worktree, rather than inferring it from an exit code.
            self._append_line(
                make_runner.describe_rom(self.binding.active_worktree.path)
            )

        self._explain_failure(results)
        self._read_budgets(results)

        status = self._outcome_text(results)
        if self._budget_report is not None:
            status += " · " + self._budget_report.summary()
            if self._budget_report.has_fail:
                # R13's refusal, stated where the numbers are, before the
                # user reaches for Launch and is told no.
                status += " · launch blocked"
        self.status_label.setText(status)
        self._set_state(self._outcome_state(results))
        self._set_running(False)
        self.budgets_read.emit(self._budget_report)
        self.ran.emit(results)

    def _read_budgets(self, results: List[make_runner.RunResult]) -> None:
        """Turn what the measuring targets printed into the four budgets
        R12 names. Only a run that actually ran one of them touches the
        report: a bare `make clean` says nothing about memory, and
        replacing good numbers with blanks would be worse than keeping
        them.
        """
        ran = {r.command.target for r in results}
        if not ran & {"memory-check", "bank-post-build"}:
            return
        self._budget_report = budgets_core.build_report(
            self.output_for("memory-check"), self.output_for("bank-post-build")
        )

    def _explain_failure(self, results: List[make_runner.RunResult]) -> None:
        """After a failed run, name the toolchain check that already
        explains it. `make clean` dying on a missing `rm` and
        `make bank-post-build` dying on a missing `romusage` are both
        conditions the Doctor reported at startup; the log should close
        that gap rather than leave the user to.
        """
        failed = next((r for r in results if not r.ok and not r.cancelled), None)
        if failed is None:
            return
        explanations = make_runner.explain_failure(
            failed.command.target, self._doctor_report
        ) + make_runner.explain_missing_rom(
            failed.command.target, self.binding.active_worktree.path
        )
        for line in explanations:
            self._append_line(line)

    def _teardown(self) -> None:
        """End one run's thread and worker, and forget them. Called both
        from `_on_done` (the run ended on its own) and from
        `stop_and_wait` (the window is closing).

        The worker's signals are disconnected first: after this, a queued
        emission still in flight has nowhere to land, which is what keeps a
        late line from reaching widgets that are on their way out. Qt
        allows disconnecting during an emission, which is exactly the
        `_on_done` case.
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

    @staticmethod
    def _outcome_state(results: List[make_runner.RunResult]) -> str:
        if not results:
            return "idle"
        if any(r.cancelled for r in results):
            return "idle"
        return "pass" if all(r.ok for r in results) else "fail"

    @staticmethod
    def _outcome_text(results: List[make_runner.RunResult]) -> str:
        """What the status line says once a sequence ends. A stopped run
        reads as stopped, never as a failure: the build did not fail, the
        user changed their mind.
        """
        if not results:
            return "stopped"
        total = sum(r.duration_s for r in results)
        cancelled = next((r for r in results if r.cancelled), None)
        if cancelled is not None:
            return f"{cancelled.command.label} — stopped after {total:.1f}s"
        failed = next((r for r in results if not r.ok), None)
        if failed is not None:
            return (
                f"{failed.command.label} — failed (exit {failed.exit_code}) "
                f"after {total:.1f}s"
            )
        # The measuring targets are left out of a successful line: their
        # result is the budget clause the caller appends, and spelling out
        # "make clean && make && make memory-check && make bank-post-build"
        # buries the one number the user is waiting for -- how long it took.
        labels = [
            r.command.label
            for r in results
            if r.command.target not in make_runner.ROM_DEPENDENT_TARGETS
        ] or [r.command.label for r in results]
        return f"{' && '.join(labels)} — ok in {total:.1f}s"

    # -- helpers ----------------------------------------------------------

    def _button(self, text: str, object_name: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        if primary:
            button.setProperty("role", "primary")
        return button

    def _set_state(self, state: str) -> None:
        self.state_dot.setProperty("state", state)
        # A dynamic property that changes after the stylesheet was applied
        # needs the style re-evaluated for the new selector to take effect.
        self.state_dot.style().unpolish(self.state_dot)
        self.state_dot.style().polish(self.state_dot)

    def _binding_error_message(self) -> str:
        if self.binding_error is not None:
            return (
                f"Repository binding failed ({self.binding_error.key}): "
                f"{self.binding_error.message}"
            )
        return "No repository is bound; there is nothing to build."
