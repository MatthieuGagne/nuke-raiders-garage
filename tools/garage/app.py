"""Garage main window. Thin Qt layer: all logic lives in tools.garage.core.

Iteration 1 delivers the window shell and the header (AC1, AC2, AC17).
Iteration 2 adds the Tuner panel as the window body (AC7, AC8).
Iteration 4 added a diff panel beside the Tuner in a splitter, always
visible; iteration 5 replaces that with the design the user actually
approved: the Tuner is the whole window body again, the header states
change *totals* only, and the full diff lives behind a menu action,
closed until asked for (AC19, AC2).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import diff as diff_core
from tools.garage.core.project import Binding, BindingError, bind
from tools.garage.panels.diff_view import DiffPanel
from tools.garage.panels.tuner import TunerPanel


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


class GarageWindow(QMainWindow):
    def __init__(self, garage_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Garage")

        self.binding: Optional[Binding] = None
        self.binding_error: Optional[BindingError] = None
        try:
            self.binding = bind(garage_root)
        except BindingError as exc:
            self.binding_error = exc

        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.header_label = QLabel()
        self.header_label.setObjectName("garage-header")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        # The Tuner is the window body -- the tuning loop is what Garage
        # shows on launch (R19's redesign: the diff moved behind a menu,
        # see _build_menu / _open_diff below).
        self.tuner_panel = TunerPanel(self.binding, self.binding_error, parent=central)
        self.tuner_panel.setObjectName("garage-tuner-panel")
        layout.addWidget(self.tuner_panel, 1)

        self.tuner_panel.written.connect(self._on_tuner_written)

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
        self.diff_dialog.setWindowTitle("Diff against HEAD")
        dialog_layout = QVBoxLayout(self.diff_dialog)
        dialog_layout.addWidget(self.diff_panel)
        self.diff_dialog.resize(900, 700)
        # QDialog starts hidden until show()/exec() is called -- closed at
        # launch is the default, nothing further needed for that.

        self._build_menu()

        self._refresh_header()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("&View")
        self.show_diff_action = QAction("&Diff Against HEAD…", self)
        self.show_diff_action.setObjectName("garage-action-show-diff")
        self.show_diff_action.triggered.connect(self.open_diff)
        view_menu.addAction(self.show_diff_action)

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
        self.header_label.setText(format_header(self.binding, self.binding_error, summary))

    def _on_tuner_written(self) -> None:
        """A Tuner edit (or revert) writes config.h immediately -- there is
        no Save step to wait for. Called once per write so the header
        totals and, if open, the diff dialog always reflect the file as it
        now stands on disk.
        """
        self._refresh_header()
        if self.diff_dialog.isVisible():
            self.diff_panel.refresh()


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    window = GarageWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
