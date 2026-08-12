"""The Diff panel: the active worktree's diff against `HEAD`, for every
changed file, plus the untracked file list.

R19 / AC19: a value written by the Tuner must appear here as a removed line
and an added line under src/config.h; a file changed outside Garage must
appear too; an untracked file is listed by name (a diff has no content for
one). An empty diff says the worktree is clean rather than showing a blank
box.

Colour is iteration 5's job (R18) -- for now, added/removed/context lines
are distinguished with a "+ "/"- "/"  " prefix and, on add/remove, a bold
weight. Every rendered label also carries a `diffKind` dynamic property
("add"/"remove"/"context"/"meta") so the iteration-5 stylesheet can select
on it (`QLabel[diffKind="add"]`) without this file changing again -- that
is the "clean seam".

Qt lives only in this file (and its siblings under tools/garage/panels/);
tools/garage/core/ stays pure and Qt-free.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import diff as diff_core
from tools.garage.core.project import Binding, BindingError

_LINE_PREFIX = {"add": "+ ", "remove": "- ", "context": "  ", "meta": "  "}


def _bold(label: QLabel) -> None:
    font = label.font()
    font.setBold(True)
    label.setFont(font)


class DiffPanel(QWidget):
    """Fills part of the Garage window body, alongside the Tuner. Call
    `refresh()` after anything that might change the worktree (a Tuner
    save, later a commit or a worktree switch) to pick it up.
    """

    def __init__(
        self,
        binding: Optional[Binding],
        binding_error: Optional[BindingError] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error

        self._diff: Optional[diff_core.WorktreeDiff] = None
        self._explanation: str = ""

        outer = QVBoxLayout(self)

        # Which tree this is a diff *of*. Before worktrees could be
        # switched (iteration 9), "against HEAD" was the whole answer;
        # with several checkouts of the same repository open, a diff that
        # does not name its worktree is a diff you have to take on trust.
        self._subject_label = QLabel()
        self._subject_label.setObjectName("diff-subject")
        self._subject_label.setWordWrap(True)
        self._subject_label.setText(self._subject_text())
        outer.addWidget(self._subject_label)

        self._status_label = QLabel()
        self._status_label.setObjectName("diff-status")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("diff-scroll")
        self._scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

        self.refresh()

    # -- data access (for tests and other panels) ------------------------

    @property
    def worktree_diff(self) -> Optional[diff_core.WorktreeDiff]:
        return self._diff

    def explanation_text(self) -> str:
        """Why the panel shows no diff at all (binding failure / git
        error), or "" when it built normally (clean or not).
        """
        return self._explanation

    def status_text(self) -> str:
        return self._status_label.text()

    def subject_text(self) -> str:
        return self._subject_label.text()

    def _subject_text(self) -> str:
        """The worktree this diff is of, and the branch it is on. Shown
        whether or not there is anything to display, since "no changes" is
        also a statement about a particular tree.
        """
        if self.binding is None:
            return "No worktree is bound."
        worktree = self.binding.active_worktree
        branch = worktree.branch or "(detached HEAD)"
        return f"{worktree.path}  [{branch}]  against HEAD"

    def file_paths(self) -> List[str]:
        return [f.path for f in self._diff.files] if self._diff else []

    def untracked_files(self) -> List[str]:
        return list(self._diff.untracked) if self._diff else []

    # -- build / refresh ---------------------------------------------------

    def refresh(self) -> None:
        """Re-read the diff from git and re-render. Never crashes: a
        binding failure or a git error is shown as an explanation instead.
        """
        self._clear_content()

        if self.binding is None:
            self._show_explanation(self._binding_error_message())
            return

        try:
            self._diff = diff_core.get_diff(self.binding)
        except diff_core.DiffError as exc:
            self._diff = None
            self._show_explanation(f"Could not read the diff: {exc}")
            return

        self._explanation = ""
        self._status_label.hide()
        self._render(self._diff)

    def _binding_error_message(self) -> str:
        if self.binding_error is not None:
            return (
                f"Repository binding failed ({self.binding_error.key}): "
                f"{self.binding_error.message}"
            )
        return "No repository is bound; the diff has nothing to show."

    def _show_explanation(self, message: str) -> None:
        self._explanation = message
        self._status_label.setText(message)
        self._status_label.show()

    def _clear_content(self) -> None:
        # Remove every widget except the trailing stretch (kept at index 0
        # here since we always insert new widgets before it).
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _insert(self, widget: QWidget) -> None:
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def _render(self, result: diff_core.WorktreeDiff) -> None:
        if result.is_clean:
            self._status_label.setText("Worktree is clean -- no changes against HEAD.")
            self._status_label.show()
            return

        if result.truncated:
            note = QLabel(result.truncated_reason)
            note.setObjectName("diff-truncated-note")
            note.setWordWrap(True)
            self._insert(note)

        for file_diff in result.files:
            self._insert(self._build_file_section(file_diff))

        if result.untracked:
            self._insert(self._build_untracked_section(result.untracked))

    def _build_file_section(self, file_diff: diff_core.FileDiff) -> QWidget:
        section = QFrame()
        section.setObjectName("diff-file-section")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel(f"{file_diff.path} ({file_diff.change_type})")
        header.setObjectName("diff-file-header")
        _bold(header)
        layout.addWidget(header)

        if file_diff.binary:
            note = QLabel("Binary files differ")
            note.setObjectName("diff-binary-note")
            layout.addWidget(note)
            return section

        for hunk in file_diff.hunks:
            hunk_header = QLabel(hunk.header)
            hunk_header.setObjectName("diff-hunk-header")
            layout.addWidget(hunk_header)

            for line in hunk.lines:
                prefix = _LINE_PREFIX.get(line.kind, "  ")
                line_label = QLabel(f"{prefix}{line.text}")
                line_label.setObjectName("diff-line")
                line_label.setProperty("diffKind", line.kind)
                if line.kind in ("add", "remove"):
                    _bold(line_label)
                layout.addWidget(line_label)

        return section

    def _build_untracked_section(self, untracked: List[str]) -> QWidget:
        section = QFrame()
        section.setObjectName("diff-untracked-section")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Untracked files")
        header.setObjectName("diff-untracked-header")
        _bold(header)
        layout.addWidget(header)

        for name in untracked:
            file_label = QLabel(name)
            file_label.setObjectName("diff-untracked-file")
            layout.addWidget(file_label)

        return section
