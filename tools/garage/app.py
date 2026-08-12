"""Garage main window. Thin Qt layer: all logic lives in tools.garage.core.

Iteration 1 delivers the window shell and the header (AC1, AC2, AC17).
Iteration 2 adds the Tuner panel as the window body (AC7, AC8).
Iteration 4 added a diff panel beside the Tuner in a splitter, always
visible; iteration 5 replaces that with the design the user actually
approved: the Tuner is the whole window body again, the header states
change *totals* only, and the full diff lives behind a menu action,
closed until asked for (AC19, AC2).

Iteration 10 adds the commit dialog (R5/R6, AC5/AC6): a message, the
`master` refusal, and the pre-commit verification streamed while it runs.

Iteration 9 adds the worktrees dialog (R3/R4, AC3/AC4). Activating one
rebuilds the whole body through `_build_ui`, so no panel is left pointing
at the tree Garage no longer means.

Iteration 8 adds the budgets aside (R12/AC12) and the Emulicious gate
(R13/AC13): what a compile spent, beside the values that spend it.

Iteration 7 adds the compile bar (R11/AC11): the four make calls, run in
the active worktree, with their output as it arrives.

Iteration 6 adds the Doctor (R14/AC14): the toolchain verification runs at
startup, states a failure in the window itself, and opens its own dialog
over the window when something is missing.

Iteration 5 also applies the dark stylesheet (R18/AC18): `main()` installs
it once, on the QApplication, via `tools.garage.theme.apply`. This file
holds no colour and no typeface literal of its own -- the one exception is
the header line below, which mixes prose with monospace values and a
warning clause; it renders as rich text built from `tools.garage.theme`'s
named tokens (never a hex literal spelled out here), never with a
`setStyleSheet` call.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from tools.garage import theme
from tools.garage.core import diff as diff_core
from tools.garage.core import worktrees as worktrees_core
from tools.garage.core.project import (
    Binding,
    BindingError,
    bind,
    default_garage_root,
)
from tools.garage.panels.budgets import BudgetsPanel
from tools.garage.panels.commit import CommitPanel
from tools.garage.panels.compile_bar import CompileBar
from tools.garage.panels.diff_view import DiffPanel
from tools.garage.panels.doctor import DoctorPanel
from tools.garage.panels.tuner import TunerPanel
from tools.garage.panels.worktrees import WorktreesPanel
from tools.garage.theme.tokens import FONT_MONO, TOKENS


def _format_change_clause(summary: Optional[diff_core.ChangeSummary]) -> str:
    """The totals-only clause of the header: "no changes", "no changes ·
    N untracked" (no tracked change at all, only untracked files), or
    "N file(s) +A -R[ . M untracked]". Never a per-file list, and its
    length depends only on how many digits the counts have -- never on
    how many lines or files actually changed (the point of totals).

    AC20: "no changes" always describes *tracked* files -- an untracked
    file is named in its own "· N untracked" clause regardless, since it is
    real state the user should see, but it never turns "no changes" into
    something else; there being untracked files does not mean there are
    changes to a tracked file.

    `summary` is None when the core call that would produce it failed;
    that is not fatal to the header, it just has nothing to add here.
    """
    if summary is None:
        return "no changes"
    if summary.changed_file_count == 0 and summary.untracked_count == 0:
        return "no changes"
    if summary.changed_file_count == 0:
        return f"no changes · {summary.untracked_count} untracked"

    files_word = "file" if summary.changed_file_count == 1 else "files"
    clause = f"{summary.changed_file_count} {files_word} +{summary.added_lines} −{summary.removed_lines}"
    if summary.untracked_count:
        clause += f" · {summary.untracked_count} untracked"
    return clause


def format_header(
    binding: Optional[Binding],
    error: Optional[BindingError],
    summary: Optional[diff_core.ChangeSummary] = None,
) -> str:
    """Pure text for the header. When the binding failed, name the key to
    fix and what the failure prevents (AC17) instead of a path/branch.

    R2/AC2, redesigned: the header states change totals only (never a
    per-file list -- see `_format_change_clause`), so its length does not
    grow with the size of the change. It also carries:
      - a "*dirty*" mark next to the branch when `summary` reports a
        *tracked* file differing from HEAD -- AC20: the mark stands for
        "a tracked file differs from HEAD", not "there is any uncommitted
        state at all", so an untracked-only tree never raises it (see
        `diff_core.ChangeSummary.dirty`);
      - "commit blocked on master", always, when on `master` (R5's
        refusal is known before the work is done, whether the tree is
        dirty or not).
    `summary` is optional so callers that have not computed one yet (or
    could not -- a git error is not fatal to the header) still get a
    branch/path line.
    """
    if error is not None:
        return f"Repository binding failed ({error.key}): {error.message}"

    branch = binding.active_worktree.branch or "(detached HEAD)"
    dirty = summary.dirty if summary is not None else False
    mark = " ●" if dirty else ""  # filled circle -- a tracked file differs from HEAD
    header = f"{binding.active_worktree.path}  [{branch}{mark}]"
    header += f"  {_format_change_clause(summary)}"

    if diff_core.is_master_branch(binding.active_worktree.branch):
        header += "   commit blocked on master"

    return header


def _mono_span(text: str) -> str:
    return f'<span style="font-family:{FONT_MONO};">{html.escape(text)}</span>'


def _warn_span(text: str) -> str:
    return f'<span style="color:{TOKENS["warn"]};">{html.escape(text)}</span>'


def format_header_html(
    binding: Optional[Binding],
    error: Optional[BindingError],
    summary: Optional[diff_core.ChangeSummary] = None,
) -> str:
    """Rich-text rendering of `format_header`'s exact content -- the same
    words, in the same order and spacing, so every substring a caller
    already looks for in `format_header`'s plain output is still there in
    this one (R18's header requirement is presentation only; the decision
    of *what* the header says still lives in `format_header`, which this
    mirrors rather than replaces).

    R18: the path, the branch/mark and the change-totals clause carry the
    monospace face (`tools.garage.theme.FONT_MONO`); "commit blocked on
    master" reads as a warning, in the warn token
    (`tools.garage.theme.TOKENS["warn"]`). Every value is escaped, since
    this string is set on the QLabel as rich text -- an unescaped `<`, `>`
    or `&` in a path would otherwise be parsed as markup.
    """
    if error is not None:
        return (
            f"Repository binding failed ({html.escape(error.key)}): "
            f"{html.escape(error.message)}"
        )

    branch = binding.active_worktree.branch or "(detached HEAD)"
    dirty = summary.dirty if summary is not None else False
    mark = " ●" if dirty else ""
    path_html = _mono_span(str(binding.active_worktree.path))
    branch_html = _mono_span(f"{branch}{mark}")
    clause_html = _mono_span(_format_change_clause(summary))
    header = f"{path_html}  [{branch_html}]  {clause_html}"

    if diff_core.is_master_branch(binding.active_worktree.branch):
        header += "   " + _warn_span("commit blocked on master")

    return header


class GarageWindow(QMainWindow):
    def __init__(self, garage_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Garage")

        # Kept because a worktree switch re-binds from the same root
        # (R3: "make one active"), and `bind` needs it again.
        self.garage_root = (
            Path(garage_root) if garage_root is not None else default_garage_root()
        )

        self.binding: Optional[Binding] = None
        self.binding_error: Optional[BindingError] = None
        self._rebind()

        self._build_ui()

        # Built once, and deliberately not rebuilt: it is the panel that
        # triggers a rebuild, and a widget that deletes itself while
        # handling its own signal is a crash.
        self._build_worktrees()
        self._build_menu()

        # The verification has already run (in the panel's constructor);
        # this states its result in the window. Opening the Doctor over the
        # window is deferred to the first showEvent, so it appears over a
        # window that exists rather than before one does.
        self._toolchain_reported = False
        self._report_toolchain()

    def _rebind(self) -> None:
        try:
            self.binding = bind(self.garage_root)
            self.binding_error = None
        except BindingError as exc:
            self.binding = None
            self.binding_error = exc

    def _build_ui(self) -> None:
        """Everything that resolves against the active worktree. Called
        again, whole, when that worktree changes: every panel below holds a
        binding, and rebuilding them is both shorter and safer than
        threading a new one through each -- there is no path where half of
        the window still points at the old tree.
        """
        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.header_label = QLabel()
        self.header_label.setObjectName("garage-header")
        self.header_label.setWordWrap(True)
        # Rich text so format_header_html's monospace/warn spans render --
        # see that function's docstring for why every value in it is
        # html-escaped first.
        self.header_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.header_label)

        # R14: the toolchain verification runs at startup, and a failure is
        # stated in the window itself -- not only inside a panel the user
        # would have to think to open. The notice is hidden when every
        # check passes, so a healthy machine shows the tuning loop and
        # nothing else. See _build_doctor / _refresh_toolchain_notice.
        self.toolchain_label = QLabel()
        self.toolchain_label.setObjectName("garage-toolchain-status")
        self.toolchain_label.setWordWrap(True)
        self.toolchain_label.hide()
        layout.addWidget(self.toolchain_label)

        # The Tuner is the window body -- the tuning loop is what Garage
        # shows on launch (R19's redesign: the diff moved behind a menu,
        # see _build_menu / _open_diff below).
        #
        # Iteration 8 puts the budgets in a narrow column beside it, where
        # the prototype's `<aside>` puts them: they are what a tuning edit
        # is spent against, so they belong in view while the edit is made,
        # not behind an action. The aside has a fixed width, so the Tuner
        # takes every pixel a wider window offers.
        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        self.tuner_panel = TunerPanel(self.binding, self.binding_error, parent=body)
        self.tuner_panel.setObjectName("garage-tuner-panel")
        body_layout.addWidget(self.tuner_panel, 1)

        self.budgets_panel = BudgetsPanel(parent=body)
        body_layout.addWidget(self.budgets_panel)

        layout.addWidget(body, 1)

        self.tuner_panel.written.connect(self._on_tuner_written)

        # Iteration 7 (R11/AC11): the compile bar is pinned under the
        # Tuner, following the prototype's build bar. The loop is change a
        # value → compile → look, so the compile controls sit in the same
        # window as the values, not behind a menu action like the diff.
        self.compile_bar = CompileBar(self.binding, self.binding_error, parent=central)
        self.compile_bar.setObjectName("garage-compile-bar")
        self.compile_bar.ran.connect(self._on_compile_ran)
        # R12: the budgets are read from what the measuring targets printed
        # during the run that just ended, and shown beside the values that
        # spend them.
        self.compile_bar.budgets_read.connect(self.budgets_panel.set_report)
        layout.addWidget(self.compile_bar)

        self.setCentralWidget(central)
        self.resize(1200, 700)

        # The full diff (tools/garage/panels/diff_view.py) is unchanged --
        # only its home moved. It is built once and reused across opens so
        # a write while it is closed is picked up on the next open without
        # rebuilding it (refresh() re-reads git; see _open_diff).
        #
        # Dialog, not a dock or a second top-level window: a modeless
        # QDialog never touches the main window's central-widget layout,
        # so opening/closing it can never disturb the Tuner underneath --
        # a dock widget, by contrast, resizes the central widget when
        # shown/hidden. A dialog also gives a free, native close button
        # and is trivially re-openable (`show()` again), which is all R19
        # asks for: closed at launch, opened from the menu, closable and
        # re-openable.
        self.diff_panel = DiffPanel(self.binding, self.binding_error)
        self.diff_panel.setObjectName("garage-diff-panel")
        self.diff_dialog = QDialog(self)
        self.diff_dialog.setObjectName("garage-diff-dialog")
        self.diff_dialog.setWindowTitle(self._diff_dialog_title())
        dialog_layout = QVBoxLayout(self.diff_dialog)
        dialog_layout.addWidget(self.diff_panel)
        self.diff_dialog.resize(900, 700)
        # QDialog starts hidden until show()/exec() is called -- closed at
        # launch is the default, nothing further needed for that.

        self._build_commit()

        self._build_doctor()
        # A failed target whose tool the Doctor already reported missing
        # says so in the compile log -- see CompileBar._explain_failure.
        self.compile_bar.set_doctor_report(self.doctor_panel.report)

        self._refresh_header()

    def _build_commit(self) -> None:
        """R5/R6 in a dialog: the message, the refusals, and the ninety
        seconds of pre-commit verification streamed. Rebuilt with the body,
        since what it commits to is the active worktree.
        """
        self.commit_panel = CommitPanel(self.binding, self.binding_error)
        self.commit_panel.setObjectName("garage-commit-panel")
        self.commit_panel.committed.connect(self._on_committed)
        self.commit_dialog = QDialog(self)
        self.commit_dialog.setObjectName("garage-commit-dialog")
        self.commit_dialog.setWindowTitle("Commit")
        layout = QVBoxLayout(self.commit_dialog)
        layout.addWidget(self.commit_panel)
        self.commit_dialog.resize(900, 700)

    def open_commit(self) -> None:
        self.commit_panel.refresh()
        self.commit_dialog.show()
        self.commit_dialog.raise_()
        self.commit_dialog.activateWindow()

    def _on_committed(self, head_line: str) -> None:
        """A commit changes what the worktree holds, so the header totals
        and any open diff are re-read."""
        self._refresh_header()
        if self.diff_dialog.isVisible():
            self.diff_panel.refresh()

    def _build_worktrees(self) -> None:
        """R3's list, create, delete and activate, in a dialog like the
        diff and the Doctor. Switching worktrees is something done between
        sessions of tuning, not while tuning.
        """
        self.worktrees_panel = WorktreesPanel(self.binding, self.binding_error)
        self.worktrees_panel.setObjectName("garage-worktrees-panel")
        self.worktrees_panel.activated.connect(self.activate_worktree)
        self.worktrees_dialog = QDialog(self)
        self.worktrees_dialog.setObjectName("garage-worktrees-dialog")
        self.worktrees_dialog.setWindowTitle("Worktrees")
        layout = QVBoxLayout(self.worktrees_dialog)
        layout.addWidget(self.worktrees_panel)
        self.worktrees_dialog.resize(860, 560)

    def open_worktrees(self) -> None:
        self.worktrees_panel.refresh()
        self.worktrees_dialog.show()
        self.worktrees_dialog.raise_()
        self.worktrees_dialog.activateWindow()

    def activate_worktree(self, worktree) -> Optional[str]:
        """Make `worktree` the active one and point the whole window at it
        (R3). Returns a refusal, or None.

        A compile in flight refuses the switch: it is running `make` in the
        tree Garage is about to stop pointing at, and its output would land
        in a window describing a different worktree.
        """
        if self.compile_bar.is_running():
            return self.worktrees_panel._set_status(
                "A compile is running in the current worktree. Stop it before "
                "switching."
            )

        worktrees_core.activate(self.garage_root, worktree)
        self._rebind()

        # The dialogs hold panels bound to the old worktree; they go with it.
        for dialog in (self.diff_dialog, self.doctor_dialog, self.commit_dialog):
            dialog.close()
            dialog.deleteLater()

        self._build_ui()
        self._report_toolchain()

        self.worktrees_panel.binding = self.binding
        self.worktrees_panel.binding_error = self.binding_error
        self.worktrees_panel.refresh()
        self.worktrees_panel._set_status(
            f"Active worktree is now {worktree.path}"
        )
        return None

    def _build_doctor(self) -> None:
        """The Doctor lives in its own dialog, for the same reasons the
        diff does (see below): a modeless QDialog never disturbs the
        window's central layout, and re-opening it is a `show()`.

        Unlike the diff, it is built and run *before* it is ever shown --
        the checks run at startup whether or not the user opens the panel,
        because the window's toolchain notice reads its result.
        """
        self.doctor_panel = DoctorPanel(self.binding, self.binding_error)
        self.doctor_panel.setObjectName("garage-doctor-panel")
        self.doctor_dialog = QDialog(self)
        self.doctor_dialog.setObjectName("garage-doctor-dialog")
        self.doctor_dialog.setWindowTitle("Toolchain")
        dialog_layout = QVBoxLayout(self.doctor_dialog)
        dialog_layout.addWidget(self.doctor_panel)
        self.doctor_dialog.resize(760, 620)

    def _report_toolchain(self) -> None:
        """The one-line notice under the header: which checks failed, and
        where to read what they prevent. Hidden entirely when the toolchain
        is whole, so a healthy machine shows the tuning loop and nothing
        else.
        """
        report = self.doctor_panel.report
        if report is None or report.ok:
            self.toolchain_label.hide()
            return
        failed = len(report.failures)
        checks_word = "check" if failed == 1 else "checks"
        self.toolchain_label.setText(
            f"Toolchain: {failed} {checks_word} failing — "
            + ", ".join(c.key for c in report.failures)
            + ".  View ▸ Toolchain names what each one prevents."
        )
        self.toolchain_label.show()

    def showEvent(self, event) -> None:
        """R14: a failure is reported when Garage starts. The notice above
        is always there, but a missing tool also opens the Doctor once, the
        first time the window is shown -- the whole point of the check is
        that a missing tool cannot go unnoticed, and a line the user has to
        read before they start is easy to scroll past.
        """
        super().showEvent(event)
        if self._toolchain_reported:
            return
        self._toolchain_reported = True
        if self.doctor_panel.has_failures():
            self.open_doctor()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("&View")
        self.show_diff_action = QAction("&Diff of the Active Worktree…", self)
        self.show_diff_action.setObjectName("garage-action-show-diff")
        self.show_diff_action.triggered.connect(self.open_diff)
        view_menu.addAction(self.show_diff_action)

        self.show_doctor_action = QAction("&Toolchain…", self)
        self.show_doctor_action.setObjectName("garage-action-show-doctor")
        self.show_doctor_action.triggered.connect(self.open_doctor)
        view_menu.addAction(self.show_doctor_action)

        self.show_commit_action = QAction("&Commit…", self)
        self.show_commit_action.setObjectName("garage-action-show-commit")
        self.show_commit_action.triggered.connect(self.open_commit)
        view_menu.addAction(self.show_commit_action)

        self.show_worktrees_action = QAction("&Worktrees…", self)
        self.show_worktrees_action.setObjectName("garage-action-show-worktrees")
        self.show_worktrees_action.triggered.connect(self.open_worktrees)
        view_menu.addAction(self.show_worktrees_action)

    def open_doctor(self) -> None:
        """Show the Doctor. The checks are not re-run here: they read the
        process environment, which cannot change under a running Garage,
        so re-running them would only redraw the same answer.
        """
        self.doctor_dialog.show()
        self.doctor_dialog.raise_()
        self.doctor_dialog.activateWindow()

    def _diff_dialog_title(self) -> str:
        """The dialog names the worktree it is a diff of. With several
        checkouts of one repository open (R3), "Diff against HEAD" alone
        does not say against which tree's HEAD.
        """
        if self.binding is None:
            return "Diff against HEAD"
        worktree = self.binding.active_worktree
        branch = worktree.branch or "(detached HEAD)"
        return f"Diff — {worktree.path.name} [{branch}] against HEAD"

    def open_diff(self) -> None:
        """Show the diff dialog, re-reading git first so it reflects
        whatever changed while it was closed (e.g. a Tuner edit).
        """
        self.diff_panel.refresh()
        self.diff_dialog.show()
        self.diff_dialog.raise_()
        self.diff_dialog.activateWindow()

    def _change_summary(self) -> Optional[diff_core.ChangeSummary]:
        if self.binding is None:
            return None
        try:
            return diff_core.get_change_summary(self.binding.active_worktree.path)
        except diff_core.DiffError:
            # A git failure here is not fatal to the header -- it just
            # loses the totals; the master warning (which needs no git
            # call) still shows.
            return None

    def _refresh_header(self) -> None:
        summary = self._change_summary()
        self.header_label.setText(
            format_header_html(self.binding, self.binding_error, summary)
        )

    def _on_tuner_written(self) -> None:
        """A Tuner edit (or revert) writes config.h immediately -- there is
        no Save step to wait for. Called once per write so the header
        totals and, if open, the diff dialog always reflect the file as it
        now stands on disk.
        """
        self._refresh_header()
        if self.diff_dialog.isVisible():
            self.diff_panel.refresh()

    def _on_compile_ran(self, results) -> None:
        """A compile writes into the worktree (build/, and the generated
        sources the Makefile regenerates), so the header's change totals
        can be stale the moment it ends. An open diff is re-read for the
        same reason.
        """
        self._refresh_header()
        if self.diff_dialog.isVisible():
            self.diff_panel.refresh()

    def closeEvent(self, event) -> None:
        """A stepped edit debounces briefly before it writes (see
        tools/garage/panels/tuner.py's STEP_DEBOUNCE_MS); closing the
        window must not race that timer and lose the write. Flush any
        step still waiting to settle before Qt tears the window down.

        A compile runs on its own thread, and a QThread still running when
        Qt destroys its parent is a crash -- so a run in flight is stopped
        and joined here too.
        """
        self.tuner_panel.flush_pending_writes()
        self.compile_bar.stop_and_wait()
        self.commit_panel.stop_and_wait()
        super().closeEvent(event)


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    theme.apply(app)  # R18/AC18: the dark stylesheet, applied once at startup.
    window = GarageWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
