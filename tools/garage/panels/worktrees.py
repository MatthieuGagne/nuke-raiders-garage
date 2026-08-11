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
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import worktrees as worktrees_core
from tools.garage.core.project import Binding, BindingError, Worktree, _same_path


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
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error
        self._worktrees: List[Worktree] = []

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

    def delete_worktree(self, worktree: Worktree, typed_name: str) -> Optional[str]:
        """Delete `worktree`, if every refusal in
        `worktrees_core.refuse_delete_reason` passes and `typed_name`
        matches. Returns the refusal, or None on success (AC4).
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
            return

        try:
            self._worktrees = worktrees_core.reload(self.binding)
        except Exception as exc:  # BindingError from list_worktrees
            self._set_status(f"Could not list the worktrees: {exc}")
            return

        for worktree in self._worktrees:
            self._insert(self._build_row(worktree))

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
        # the reason so the list itself explains the state.
        refusal = worktrees_core.refuse_delete_reason(
            worktree, self.binding.active_worktree, self._worktrees
        )
        delete.setEnabled(refusal is None)
        if refusal is not None:
            delete.setToolTip(refusal)
        delete.clicked.connect(lambda _=False, w=worktree: self._on_delete_clicked(w))
        layout.addWidget(delete)

        return row

    # -- UI plumbing -------------------------------------------------------

    def _on_create_clicked(self) -> None:
        self.create_worktree(self.branch_field.text())

    def _on_delete_clicked(self, worktree: Worktree) -> None:
        """R4's third guard: the name has to be typed. The dialog only
        collects it -- the decision lives in `delete_worktree`.
        """
        expected = worktree.path.name
        typed, accepted = QInputDialog.getText(
            self,
            "Delete worktree",
            f"This deletes the working tree at\n{worktree.path}\n\n"
            f"The branch is not deleted. Type '{expected}' to confirm:",
            QLineEdit.EchoMode.Normal,
            "",
        )
        if not accepted:
            return
        self.delete_worktree(worktree, typed)

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
