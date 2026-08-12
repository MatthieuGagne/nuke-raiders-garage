"""The Commit panel: a message, the refusals, and the pre-commit
verification streamed while it runs (R5, R6).

R6 is the reason this panel is not a modal with a spinner. The game
repository's pre-commit hook runs its whole tool suite — about ninety
seconds — and a display with no progress reads as a failure, so the hook's
output arrives here line by line, through the same `RunController` the
compile bar uses.

The refusals are computed before the button is pressed and shown as a
sentence next to it, so `master` is known to be blocked while the message
is being written rather than after (R2 already says so in the header; this
is the same fact where the action is).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import commit as commit_core
from tools.garage.core import diff as diff_core
from tools.garage.core import make_runner
from tools.garage.core.project import Binding, BindingError
from tools.garage.panels.runner import RunController

# The log is taller than the compile bar's: this one carries a ninety
# second verification whose failure is the reason to read it.
LOG_VISIBLE_LINES = 16


class CommitPanel(QWidget):
    """`committed` fires after a commit that succeeded, so the window can
    refresh the header and the diff -- both describe the worktree the
    commit just changed.
    """

    committed = Signal(str)  # the new HEAD line, "<sha> <subject>"

    def __init__(
        self,
        binding: Optional[Binding],
        binding_error: Optional[BindingError] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error
        self._summary: Optional[diff_core.ChangeSummary] = None

        self._runs = RunController(self)
        self._runs.line.connect(self._append_line)
        self._runs.command_started.connect(
            lambda label, target: self._append_line(f"$ {label}")
        )
        self._runs.finished.connect(self._on_done)

        outer = QVBoxLayout(self)

        self.pending_label = QLabel()
        self.pending_label.setObjectName("commit-pending")
        self.pending_label.setWordWrap(True)
        outer.addWidget(self.pending_label)

        self.message_edit = QPlainTextEdit()
        self.message_edit.setObjectName("commit-message")
        self.message_edit.setPlaceholderText(
            "Commit message. The first line is the subject."
        )
        self.message_edit.setFixedHeight(
            self.message_edit.fontMetrics().lineSpacing() * 6 + 16
        )
        self.message_edit.textChanged.connect(self._refresh_refusal)
        outer.addWidget(self.message_edit)

        row = QHBoxLayout()
        self.commit_button = QPushButton("Commit")
        self.commit_button.setObjectName("commit-commit")
        self.commit_button.setProperty("role", "primary")
        self.commit_button.clicked.connect(self.commit)
        row.addWidget(self.commit_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("commit-stop")
        self.stop_button.setProperty("role", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)

        row.addStretch(1)

        self.status_label = QLabel()
        self.status_label.setObjectName("commit-status")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1)
        outer.addLayout(row)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("commit-log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES + 16
        )
        outer.addWidget(self.log_view, 1)

        self.refresh()

    # -- data access (for the window and for tests) ----------------------

    def status_text(self) -> str:
        return self.status_label.text()

    def pending_text(self) -> str:
        return self.pending_label.text()

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def message(self) -> str:
        return self.message_edit.toPlainText()

    def set_message(self, text: str) -> None:
        self.message_edit.setPlainText(text)

    def is_running(self) -> bool:
        return self._runs.is_running()

    def refusal(self) -> Optional[str]:
        """Why pressing Commit would refuse, or None. Read without
        pressing (AC5).
        """
        return commit_core.refuse_reason(self.binding, self.message(), self._summary)

    # -- actions ----------------------------------------------------------

    def refresh(self) -> None:
        """Re-read what the worktree holds and re-state the refusal. Called
        when the panel opens, and after a commit.
        """
        self._summary = None
        if self.binding is not None:
            try:
                self._summary = diff_core.get_change_summary(
                    self.binding.active_worktree.path
                )
            except diff_core.DiffError:
                self._summary = None
        self.pending_label.setText(commit_core.describe_pending(self._summary))
        self._refresh_refusal()

    def commit(self) -> Optional[str]:
        """Commit the message to the active worktree, unless a refusal
        applies. Returns the refusal, or None once the run has started.

        The commit is not finished when this returns: the pre-commit
        verification runs for about ninety seconds, and its output arrives
        in the log until `_on_done`.
        """
        if self.is_running():
            return None
        refusal = self.refusal()
        if refusal is not None:
            self.status_label.setText(refusal)
            return refusal

        self.log_view.clear()
        self._set_running(True)
        self.status_label.setText(
            "committing — the pre-commit verification runs the tool suite, "
            "about 90 seconds…"
        )
        self._runs.start(
            [commit_core.commit_command(self.message())],
            self.binding.active_worktree.path,
        )
        return None

    def stop(self) -> None:
        """Stop the verification. git is killed with its hook, so nothing
        is committed -- a half-verified commit is exactly what R6 exists to
        prevent.
        """
        if not self.is_running():
            return
        self._runs.stop()
        self.stop_button.setEnabled(False)
        self.status_label.setText("stopping…")

    def stop_and_wait(self) -> None:
        """Called when the window closes. `_on_done` never runs on this
        path -- its signal is queued to an event loop that is going away --
        so the lock cleanup happens here too, or closing Garage mid-commit
        would leave the worktree unwritable by git.
        """
        was_running = self.is_running()
        self._runs.stop_and_wait()
        if was_running and self.binding is not None:
            commit_core.remove_stale_index_lock(self.binding.active_worktree.path)

    # -- internals ---------------------------------------------------------

    def _refresh_refusal(self) -> None:
        if self.is_running():
            return
        refusal = self.refusal()
        self.commit_button.setEnabled(refusal is None)
        # A disabled button that says nothing is a bug report waiting to
        # happen; the reason goes beside it and in its tooltip.
        self.commit_button.setToolTip(refusal or "")
        self.status_label.setText(refusal or "ready to commit")

    def _set_running(self, running: bool) -> None:
        self.commit_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.message_edit.setReadOnly(running)

    def _append_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_done(self, results: List[make_runner.RunResult]) -> None:
        """What the run came to. Every branch below refreshes *first* and
        states the outcome after: `refresh` re-reads the worktree and
        re-states the refusal, which would otherwise overwrite the outcome
        with "A commit message is required" the moment the message is
        cleared -- the user would never see that the commit succeeded.
        """
        self._set_running(False)
        result = results[0] if results else None

        if result is None or result.cancelled:
            # Garage killed git mid-stage, so the index lock it was holding
            # is still there — and every later git write in this worktree
            # (including the next Build, which runs git through the
            # Makefile's hooks) would fail on it. Garage knows the holder is
            # dead because it did the killing.
            removed = commit_core.remove_stale_index_lock(
                self.binding.active_worktree.path
            )
            if removed:
                self._append_line(removed)
            self.refresh()
            self.status_label.setText("stopped — nothing was committed")
            return

        if not result.ok:
            # The hook's own output is already in the log above; this only
            # says which half failed.
            self.refresh()
            self.status_label.setText(
                f"commit refused by git (exit {result.exit_code}) after "
                f"{result.duration_s:.0f}s — the pre-commit verification or "
                f"git itself rejected it. The log above says which."
            )
            return

        head = commit_core.head_line(self.binding.active_worktree.path)
        branch = self.binding.active_worktree.branch
        self.message_edit.clear()
        self.refresh()
        self.status_label.setText(
            f"committed in {result.duration_s:.0f}s — {head} on {branch}"
        )
        self.committed.emit(head or "")
