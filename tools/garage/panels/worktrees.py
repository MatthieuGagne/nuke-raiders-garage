"""The Worktrees panel: list, create, activate, delete (R3, R4).

Follows the prototype's `table.grid` — one row per worktree, the active one
marked, actions on the right. It lives in a dialog opened from the menu,
like the diff and the Doctor: switching worktrees is something the user
does between sessions of tuning, not while tuning.

Every refusal is computed by `tools.garage.core.worktrees` and shown as a
sentence in the panel's status line, never as a modal. Two reasons: the
reason is often about state the user can see in the same list (this one is
dirty, that one is active), and a modal would cover it.

The delete confirmation is the one modal here, because R4 asks for the name
to be typed. `delete_worktree` takes the typed name as an argument, so the
decision is testable without driving a dialog.

R18/AC18: no colour and no typeface here — the active row carries an
`active` dynamic property for the stylesheet.

The work-item section (#5) is the panel's one GitHub write. It is manual:
Garage files nothing when a worktree is created and nothing when a commit
is made (R2), because most tuning work is thrown away and an issue per
abandoned experiment is worse than the problem this solves. The section is
hidden outright until the worktree holds a changed value or a commit of
its own (AC1) — an action that cannot do anything useful is not offered.

The filing runs on a worker thread. Four network round trips on the UI
thread would freeze the window, and a live QThread at teardown is a
Windows fail-fast (#8) — hence `stop_and_wait()`, which `app.py` calls
when the dialog closes.
"""
from __future__ import annotations

import shutil
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import workitem
from tools.garage.core import worktrees as worktrees_core
from tools.garage.core.project import Binding, BindingError, Worktree, _same_path


# How long to wait for the filing thread to end (milliseconds).
#
# This is not long enough to cover the worst case, and it is not meant to
# be: the sequence makes up to five `gh` calls, each bounded by
# `workitem.COMMAND_TIMEOUT_S` (20 s), so a filing stalled on a dropped
# VPN can need a hundred seconds and this join really can expire with the
# worker still inside call two. `_release_thread`'s abandon path is the
# guarantee for that case, not a fallback — thirty seconds is simply how
# long the window is willing to hang before handing the thread over to it.
# After a normal completion the worker has already returned and only the
# thread's event loop has to unwind, which is immediate.
STOP_TIMEOUT_MS = 30000
DONE_TIMEOUT_MS = 5000


class _FileWorker(QObject):
    """Runs the `gh` sequence off the UI thread. One shot, then finished."""

    done = Signal(object)  # WorkItem | WorkItemFailure

    def __init__(self, call):
        super().__init__()
        self._call = call

    def run(self) -> None:
        """Always emits, whatever the call does.

        `workitem.file_work_item` is written not to raise, but this slot is
        invoked from C++ on a worker thread: an exception escaping it does
        not become a traceback the user can read, it becomes a `done` that
        never fires — the button stays disabled and the label stays
        "Filing…" until Garage is restarted, and on PySide6 the escape may
        abort the process outright. So anything that gets out is turned
        into the failure object the panel already knows how to display.
        """
        try:
            outcome = self._call()
        except Exception as exc:  # noqa: BLE001 — nothing may cross this boundary
            outcome = workitem.WorkItemFailure(
                step="file the work item",
                message=f"Garage hit an unexpected error: {exc!r}",
            )
        self.done.emit(outcome)


class WorktreesPanel(QWidget):
    """`activated` carries the worktree the user chose; the window rebinds
    everything to it. `changed` fires when the list itself changed, so a
    caller can re-read anything derived from it.
    """

    activated = Signal(object)  # Worktree
    changed = Signal()

    def __init__(
        self,
        binding: Optional[Binding],
        binding_error: Optional[BindingError] = None,
        parent=None,
        *,
        runner: Optional[workitem.Runner] = None,
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error
        self._worktrees: List[Worktree] = []
        self._runner = runner or workitem.run_capture
        self._thread: Optional[QThread] = None
        self._worker: Optional[_FileWorker] = None
        # Filing threads that outlived their join, held so Qt cannot
        # destroy one while it is still running — see `_release_thread`.
        self._abandoned: List[tuple] = []
        self._last_item = None
        self._copied: Optional[str] = None
        self._changes: List[workitem.ChangedDefine] = []
        self._commits: List[str] = []

        outer = QVBoxLayout(self)

        create_row = QHBoxLayout()
        self.branch_field = QLineEdit()
        self.branch_field.setObjectName("worktrees-branch-field")
        self.branch_field.setPlaceholderText("branch name, e.g. feat/handling-tuning")
        self.branch_field.returnPressed.connect(self._on_create_clicked)
        create_row.addWidget(self.branch_field, 1)

        self.create_button = QPushButton("Create worktree")
        self.create_button.setObjectName("worktrees-create")
        self.create_button.setProperty("role", "primary")
        self.create_button.clicked.connect(self._on_create_clicked)
        create_row.addWidget(self.create_button)
        outer.addLayout(create_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("worktrees-status")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("worktrees-scroll")
        self._scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

        self.work_item_section = self._build_work_item_section()
        outer.addWidget(self.work_item_section)

        self.refresh()

    # -- data access (for the window and for tests) ----------------------

    def status_text(self) -> str:
        return self.status_label.text()

    def worktrees(self) -> List[Worktree]:
        return list(self._worktrees)

    def rows(self) -> List[str]:
        return [
            label.text()
            for label in self.findChildren(QLabel)
            if label.objectName() == "worktrees-row-label"
        ]

    def row_paths(self) -> List[str]:
        return [str(w.path) for w in self._worktrees]

    # -- actions ----------------------------------------------------------

    def create_worktree(self, branch: str) -> Optional[str]:
        """Create a worktree for `branch`. Returns the refusal, or None on
        success (AC3 -- it appears in `git worktree list` afterwards).
        """
        if self.binding is None:
            return self._set_status(self._binding_error_message())
        try:
            path = worktrees_core.create(
                self.binding.game_repo, self.binding.worktree_root, branch
            )
        except worktrees_core.WorktreeError as exc:
            return self._set_status(str(exc))
        self._set_status(f"Created {path}")
        self.branch_field.clear()
        self.refresh()
        self.changed.emit()
        return None

    def delete_worktree(
        self, worktree: Worktree, typed_name: str, force: bool = False
    ) -> Optional[str]:
        """Delete `worktree`, if every structural refusal in
        `worktrees_core.refuse_delete_reason` passes, `typed_name` matches,
        and (when `force` is False) nothing would be destroyed. Returns the
        refusal, or None on success (AC4).
        """
        if self.binding is None:
            return self._set_status(self._binding_error_message())
        try:
            worktrees_core.delete(
                self.binding.game_repo,
                worktree,
                self.binding.active_worktree,
                typed_name,
                self._worktrees,
                force=force,
            )
        except worktrees_core.WorktreeError as exc:
            return self._set_status(str(exc))
        self._set_status(f"Deleted {worktree.path} — the branch is untouched.")
        self.refresh()
        self.changed.emit()
        return None

    def activate_worktree(self, worktree: Worktree) -> None:
        self.activated.emit(worktree)

    # -- rendering --------------------------------------------------------

    def refresh(self) -> None:
        self._clear()
        if self.binding is None:
            self._set_status(self._binding_error_message())
            self.create_button.setEnabled(False)
            self.branch_field.setEnabled(False)
            self.refresh_work_item()
            return

        try:
            self._worktrees = worktrees_core.reload(self.binding)
        except Exception as exc:  # BindingError from list_worktrees
            self._set_status(f"Could not list the worktrees: {exc}")
            self.refresh_work_item()
            return

        for worktree in self._worktrees:
            self._insert(self._build_row(worktree))

        self.refresh_work_item()

    def _clear(self) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _insert(self, widget: QWidget) -> None:
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def _build_row(self, worktree: Worktree) -> QWidget:
        active = _same_path(worktree.path, self.binding.active_worktree.path)

        row = QFrame()
        row.setObjectName("worktrees-row")
        row.setProperty("active", "true" if active else "false")
        layout = QHBoxLayout(row)

        text = QLabel(f"{worktree.path}\n{worktrees_core.describe(worktree, self.binding.active_worktree)}")
        text.setObjectName("worktrees-row-label")
        text.setWordWrap(True)
        layout.addWidget(text, 1)

        activate = QPushButton("Activate")
        activate.setObjectName("worktrees-activate")
        activate.setEnabled(not active)
        activate.clicked.connect(lambda _=False, w=worktree: self.activate_worktree(w))
        layout.addWidget(activate)

        delete = QPushButton("Delete…")
        delete.setObjectName("worktrees-delete")
        delete.setProperty("role", "danger")
        # The refusal is computed now, not on click: a button that cannot
        # do anything says so before it is pressed, and its tooltip carries
        # the reason so the list itself explains the state. Only the
        # structural refusal disables the button -- a dirty worktree is
        # still deletable, so its tooltip carries the destructive warning
        # instead, telling the user what would be lost before they click.
        refusal = worktrees_core.refuse_delete_reason(
            worktree, self.binding.active_worktree, self._worktrees
        )
        delete.setEnabled(refusal is None)
        if refusal is not None:
            delete.setToolTip(refusal)
        else:
            warning = worktrees_core.destructive_delete_warning(worktree)
            if warning is not None:
                delete.setToolTip(warning)
        delete.clicked.connect(lambda _=False, w=worktree: self._on_delete_clicked(w))
        layout.addWidget(delete)

        return row

    # -- work item (#5) ----------------------------------------------------

    def _build_work_item_section(self) -> QFrame:
        section = QFrame()
        section.setObjectName("worktrees-workitem")
        layout = QVBoxLayout(section)

        heading = QLabel("Work item")
        heading.setObjectName("worktrees-workitem-title")
        layout.addWidget(heading)

        self.title_field = QLineEdit()
        self.title_field.setPlaceholderText("What this tuning work is for")
        layout.addWidget(self.title_field)

        self.description_field = QPlainTextEdit()
        self.description_field.setPlaceholderText("Optional description")
        layout.addWidget(self.description_field)

        buttons = QHBoxLayout()
        self.file_button = QPushButton("File work item")
        self.file_button.setObjectName("worktrees-file-issue")
        self.file_button.setProperty("role", "primary")
        self.file_button.clicked.connect(self._on_file_clicked)
        buttons.addWidget(self.file_button)

        self.finish_button = QPushButton("Finish the board entry")
        self.finish_button.clicked.connect(self._on_finish_clicked)
        self.finish_button.setVisible(False)
        buttons.addWidget(self.finish_button)

        # The way out of the guard below: a user who would rather fix the
        # board on GitHub than retry here has to be able to say so, or the
        # panel files nothing more for the rest of the session.
        self.dismiss_button = QPushButton("Leave it and file another")
        self.dismiss_button.setObjectName("worktrees-dismiss-partial")
        self.dismiss_button.clicked.connect(self._on_dismiss_clicked)
        self.dismiss_button.setVisible(False)
        buttons.addWidget(self.dismiss_button)
        layout.addLayout(buttons)

        self.work_item_result = QLabel("")
        self.work_item_result.setObjectName("worktrees-workitem-result")
        self.work_item_result.setWordWrap(True)
        self.work_item_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.work_item_result)

        return section

    def refresh_work_item(self) -> None:
        """Show the section only when there is something to file about (AC1)."""
        self._changes = []
        self._commits = []
        if self.binding is not None:
            self._changes = workitem.changed_defines(self.binding)
            self._commits = workitem.branch_commits(self.binding.active_worktree.path)
        allowed = workitem.refuse_reason(self.binding, self._changes, self._commits)
        self.work_item_section.setVisible(allowed is None)

    def work_item_visible(self) -> bool:
        return self.work_item_section.isVisible()

    def file_work_item(self) -> Optional[str]:
        """Start the filing. Returns a refusal, or None once it is running.

        A partial result blocks this outright (R8). The natural gesture
        after a failure is to press the same button again — but the last
        filing left a real issue on the board with `Type` or `Status`
        unset, and filing a second one would overwrite `self._last_item`,
        leaving the first unreachable from Garage with nothing further
        said. That is exactly the state R8 forbids, reached through the UI
        rather than the core. Finish it, or dismiss it deliberately.
        """
        partial = self._last_item
        if partial is not None:
            return self._set_work_item_result(
                f"Issue #{partial.number} is still on the board without its "
                f"Type or Status. Finish its board entry, or choose to leave "
                f"it, before filing another work item."
            )
        if shutil.which("gh") is None:
            return self._set_work_item_result(
                "`gh` is not on PATH, so Garage cannot file a work item. "
                "The Doctor panel says the same, with the repair."
            )
        binding, title = self.binding, self.title_field.text()
        description = self.description_field.toPlainText()
        changes, commits = list(self._changes), list(self._commits)
        runner = self._runner

        def call():
            return workitem.file_work_item(
                binding, title, description,
                changes=changes, commits=commits, run=runner,
            )

        return self._start(call)

    def finish_board_entry(self) -> Optional[str]:
        """Resume a partial filing. Files no second issue (R9)."""
        partial = self._last_item
        if partial is None:
            return self._set_work_item_result("There is no partial work item to finish.")
        binding, runner = self.binding, self._runner

        def call():
            return workitem.file_work_item(
                binding, "", "", existing=partial, run=runner
            )

        return self._start(call)

    def dismiss_partial_work_item(self) -> Optional[str]:
        """Stop tracking a partial filing, on purpose.

        The issue is not touched — Garage does not close or edit issues
        (R9). This only says the user has taken responsibility for the
        board entry, which is what releases the guard in `file_work_item`.
        """
        partial = self._last_item
        if partial is None:
            return self._set_work_item_result("There is no partial work item to leave.")
        self._last_item = None
        self.finish_button.setVisible(False)
        self.dismiss_button.setVisible(False)
        return self._set_work_item_result(
            f"Issue #{partial.number} ({partial.url}) is left as it is — finish "
            f"its board entry on GitHub. Garage will file another work item now.",
            failed=False,
        )

    def _start(self, call) -> Optional[str]:
        # Both entry points inherit this. Through the GUI a second start is
        # unreachable (the buttons are disabled), but `_start` overwrites
        # `self._thread` unconditionally, and dropping the only reference
        # to a live QThread that is still a Qt child is #8: a qFatal, an
        # abort(), and a Windows fail-fast with no traceback.
        if self.is_filing():
            return self._set_work_item_result("A work item is already being filed.")
        self.file_button.setEnabled(False)
        self.finish_button.setEnabled(False)
        self._set_work_item_result("Filing…", failed=False)

        self._thread = QThread(self)
        self._worker = _FileWorker(call)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_filed)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()
        return None

    def is_filing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _on_filed(self, outcome) -> None:
        # The run is over, so its thread and worker are released here as
        # well as at window close. Without this the panel would keep a
        # finished QThread as a Qt child for every filing made in one
        # session, and `is_filing()` would answer from a stale handle.
        self._release_thread(DONE_TIMEOUT_MS)
        self.file_button.setEnabled(True)
        if isinstance(outcome, workitem.WorkItem):
            self._last_item = outcome if not outcome.complete else None
            self.finish_button.setVisible(False)
            self.dismiss_button.setVisible(False)
            line = workitem.closes_line(outcome.number)
            copied = self._copy(line)
            self._set_work_item_result(
                f"Filed issue #{outcome.number} — {outcome.url}\n"
                + (
                    f"`{line}` is on the clipboard for the pull request body."
                    if copied
                    else f"Copy `{line}` into the pull request body."
                ),
                failed=False,
            )
            self.title_field.clear()
            self.description_field.clear()
        else:
            self._last_item = outcome.item
            self.finish_button.setVisible(outcome.item is not None)
            self.finish_button.setEnabled(True)
            self.dismiss_button.setVisible(outcome.item is not None)
            message = outcome.text
            if outcome.item is not None:
                # R6 is unconditional: the issue exists, so its `Closes #N`
                # belongs on the clipboard whether or not the board entry
                # was finished. A user who decides to repair the board on
                # GitHub must not have to hand-type the one line the pull
                # request workflow greps for.
                line = workitem.closes_line(outcome.item.number)
                copied = self._copy(line)
                message += "\n" + (
                    f"`{line}` is on the clipboard for the pull request body."
                    if copied
                    else f"Copy `{line}` into the pull request body."
                )
            self._set_work_item_result(message, failed=True)

    def _copy(self, text: str) -> bool:
        """Put `text` on the clipboard, and say whether it landed.

        `clipboard()` answers None when there is no GUI application, which
        is every headless test run — the text is still recorded so the
        panel can be asserted against without a clipboard.
        """
        self._copied = text
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True

    def copied_text(self) -> Optional[str]:
        return self._copied

    def last_work_item(self):
        return self._last_item

    def work_item_result_text(self) -> str:
        return self.work_item_result.text()

    def _set_work_item_result(self, message: str, failed: bool = True) -> Optional[str]:
        self.work_item_result.setText(message)
        self.work_item_result.setProperty("verdict", "fail" if failed else "pass")
        self.work_item_result.style().unpolish(self.work_item_result)
        self.work_item_result.style().polish(self.work_item_result)
        return message if failed else None

    def stop_and_wait(self) -> None:
        """Let a filing finish before the panel dies. Destroying a live
        QThread is a Windows fail-fast (#8), and the sequence is four short
        network calls, not a build — waiting is the honest option, and
        cancelling midway is what R8 forbids.
        """
        self._release_thread(STOP_TIMEOUT_MS)

    def _release_thread(self, timeout_ms: int) -> None:
        """End the filing thread and forget it — unless it will not end.

        `wait()` answers False when the thread is still running after the
        timeout, and that answer is the whole point. Dropping the panel's
        only reference then would leave a running QThread parented to a
        widget Qt is about to destroy, and Qt does not report that as an
        error: it is a qFatal, and qFatal calls abort(), which on Windows
        is a fail-fast — the process disappears with 0xC0000409, no
        message and no traceback. That is nuke-raiders-garage#8, and
        `RunController._teardown` in `runner.py` solves it the same way.

        So a thread that outstays its wait is kept, alive and referenced,
        until it says it has finished. That branch is reachable in real
        use, not merely in a test: five `gh` calls at
        `workitem.COMMAND_TIMEOUT_S` each is up to a hundred seconds
        against a thirty-second join, so closing the window on a filing
        stalled by a dropped network expires the wait. This is the
        guarantee for that case; `COMMAND_TIMEOUT_S` only guarantees the
        abandoned thread ends soon afterwards rather than never.

        The worker's signal is dropped first, so a late completion from an
        abandoned thread has nowhere to land rather than reaching widgets
        on their way out. Qt allows disconnecting during an emission,
        which is exactly the normal-completion case.
        """
        thread, worker = self._thread, self._worker
        self._thread, self._worker = None, None
        if worker is not None:
            try:
                worker.done.disconnect()
            except (RuntimeError, TypeError):
                pass
        if thread is None:
            if worker is not None:
                worker.deleteLater()
            return

        thread.quit()
        if thread.wait(timeout_ms):
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()
            return

        self._abandoned.append((thread, worker))
        thread.finished.connect(self._release_finished_threads)

    def _release_finished_threads(self) -> None:
        """Delete the threads that outlived their wait, now they are done.

        Connected to `finished` on a QObject living on the UI thread, so
        Qt queues it there rather than running it on the thread that is
        ending — and it re-checks `isRunning` rather than trusting which
        signal woke it.
        """
        still_running = []
        for thread, worker in self._abandoned:
            if thread.isRunning():
                still_running.append((thread, worker))
                continue
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()
        self._abandoned = still_running

    def abandoned_thread_count(self) -> int:
        """How many filing threads outlived their wait and are still
        running. Zero in every ordinary case; a test asserts the panel is
        not destroying them.
        """
        return len(self._abandoned)

    def _on_file_clicked(self) -> None:
        self.file_work_item()

    def _on_finish_clicked(self) -> None:
        self.finish_board_entry()

    def _on_dismiss_clicked(self) -> None:
        self.dismiss_partial_work_item()

    # -- UI plumbing -------------------------------------------------------

    def _on_create_clicked(self) -> None:
        self.create_worktree(self.branch_field.text())

    def _on_delete_clicked(self, worktree: Worktree) -> None:
        """R4's third guard: the name has to be typed. The dialog only
        collects it -- the decision lives in `delete_worktree`.

        When deleting would destroy something, the warning goes into the
        prompt above the "type to confirm" line, so the user reads exactly
        what dies before typing anything. Typing the name back is what
        turns that warning into an acknowledgement, so once it is accepted
        the panel is entitled to pass `force=True`.
        """
        expected = worktree.path.name
        warning = worktrees_core.destructive_delete_warning(worktree)
        prompt = f"This deletes the working tree at\n{worktree.path}\n\n"
        if warning is not None:
            prompt += f"{warning}\n\n"
        prompt += f"The branch is not deleted. Type '{expected}' to confirm:"
        typed, accepted = QInputDialog.getText(
            self,
            "Delete worktree",
            prompt,
            QLineEdit.EchoMode.Normal,
            "",
        )
        if not accepted:
            return
        self.delete_worktree(worktree, typed, force=True)

    def _set_status(self, message: str) -> Optional[str]:
        self.status_label.setText(message)
        return message

    def _binding_error_message(self) -> str:
        if self.binding_error is not None:
            return (
                f"Repository binding failed ({self.binding_error.key}): "
                f"{self.binding_error.message}"
            )
        return "No repository is bound; there are no worktrees to list."
