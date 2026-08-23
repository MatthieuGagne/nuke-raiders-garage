"""The dialog panel: edit an NPC's dialog tree with the Game Boy's text
limits enforced as you type (spec P3, issue #4).

Layout follows the prototype's Dialog screen (`garage/index.html`): a
narrow NPC list on the left, a column of node cards on the right, and
under them the refusal line, the Save & Generate button and the
generator's output.

Thin by rule. Every rule this panel enforces -- the 63-character node, the
three choices, the twelve-character wrap, the renumbering after a delete,
the NPC ceiling, the refusal -- lives in `tools.garage.core.dialog_model`
and is tested with no display (R12). What is here is widgets, signals and
the order things happen in.

R18/AC18 of P1 still applies: no colour literal, no font family and no
`setStyleSheet` call in this file. Appearance comes from the one
stylesheet, selected by the object names below and by the `over` dynamic
property.

Threading: the generator is a subprocess, so it runs through
`tools.garage.panels.runner.RunController` -- the same worker the compile
bar, the commit panel and the asset panel use.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import dialog_model
from tools.garage.core.project import Binding, BindingError
from tools.garage.panels.runner import RunController

# How many lines of the generator's output stay visible.
LOG_VISIBLE_LINES = 6


class NodeCard(QWidget):
    """One node: its index, its text, the live character count, the wrap
    preview, and where it goes next.

    The card holds the node dict itself, not a copy: an edit here is an
    edit to the tree the panel will save, which is what makes AC2 a
    property of the data rather than of a copy-back step someone has to
    remember.
    """

    def __init__(self, node: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("dialog-node-card")
        self.node = node

        layout = QVBoxLayout(self)

        head = QHBoxLayout()
        self.id_label = QLabel(f"[{node['idx']}]")
        self.id_label.setObjectName("dialog-node-id")
        head.addWidget(self.id_label)

        self.text_field = QLineEdit(node.get("text", ""))
        self.text_field.setObjectName("dialog-node-text")
        head.addWidget(self.text_field, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("dialog-node-count")
        head.addWidget(self.count_label)
        layout.addLayout(head)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("dialog-node-preview")
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignLeft)

        self.links_row = QHBoxLayout()
        self.links_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.links_row)
        self._link_labels: List[QLabel] = []

        # AC6: the count and the preview follow the field, keystroke by
        # keystroke -- and the node dict follows it too, so nothing has to
        # be harvested out of the widgets at save time.
        self.text_field.textChanged.connect(self._on_text_changed)
        self.refresh_text_state()
        self.refresh_links()

    # -- text, count, preview ---------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        dialog_model.set_text(self.node, text)
        self.refresh_text_state()

    def refresh_text_state(self) -> None:
        text = self.node.get("text", "")
        self.count_label.setText(dialog_model.count_label(text))
        self.preview_label.setText("\n".join(dialog_model.wrap_preview(text)))
        self._set_over_property(dialog_model.is_over_limit(text))

    def is_over(self) -> bool:
        return dialog_model.is_over_limit(self.node.get("text", ""))

    def _set_over_property(self, over: bool) -> None:
        value = "true" if over else "false"
        for widget in (self, self.count_label):
            widget.setProperty("over", value)
            # A dynamic property a stylesheet selects on does not re-apply
            # itself; the widget has to be repolished for the new value to
            # take effect.
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)

    # -- where the node goes ----------------------------------------------

    def link_texts(self) -> List[str]:
        return [label.text() for label in self._link_labels]

    def refresh_links(self) -> None:
        for label in self._link_labels:
            self.links_row.removeWidget(label)
            label.setParent(None)
            label.deleteLater()
        self._link_labels = []
        for text in self._link_strings():
            label = QLabel(text)
            label.setObjectName("dialog-link-chip")
            self.links_row.addWidget(label)
            self._link_labels.append(label)

    def _link_strings(self) -> List[str]:
        choices = self.node.get("choices", [])
        nexts = self.node.get("next", [])
        if not choices:
            target = nexts[0] if nexts else dialog_model.END
            return [f"next → {_target_text(target)}"]
        strings = []
        for position, choice in enumerate(choices):
            target = nexts[position] if position < len(nexts) else dialog_model.END
            strings.append(f"[{choice}] → {_target_text(target)}")
        return strings


def _target_text(target) -> str:
    """`END` and `SHOP` read as themselves; a node index reads as `[2]`,
    the way the prototype's chips and the node headers spell one."""
    if target in dialog_model.SENTINELS:
        return str(target)
    return f"[{target}]"


class DialogPanel(QWidget):
    """R1's two files, R2's NPC list and node list, R7's live count and
    R8's wrap preview. Editing, saving and generating are wired in on top
    of this in the same class -- see the edit controls below.
    """

    saved = Signal()

    def __init__(self, binding: Optional[Binding],
                 binding_error: Optional[BindingError], parent=None):
        super().__init__(parent)
        self.setObjectName("dialog-panel")
        self.binding = binding
        self.binding_error = binding_error
        self.data: Optional[dialog_model.DialogData] = None
        self.max_npcs: Optional[int] = None
        self._cards: List[NodeCard] = []

        layout = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setObjectName("dialog-status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        body = QHBoxLayout()

        self.npc_list = QListWidget()
        self.npc_list.setObjectName("dialog-npc-list")
        self.npc_list.currentRowChanged.connect(self._on_npc_changed)
        body.addWidget(self.npc_list)

        self.nodes_holder = QWidget()
        self.nodes_layout = QVBoxLayout(self.nodes_holder)
        self.nodes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.nodes_holder)
        body.addWidget(scroll, 1)

        layout.addLayout(body, 1)

        controls = QHBoxLayout()
        self.add_node_button = QPushButton("Add node")
        self.add_node_button.setObjectName("dialog-add-node")
        self.add_node_button.clicked.connect(lambda: self.add_node())
        controls.addWidget(self.add_node_button)

        self.npc_name_field = QLineEdit()
        self.npc_name_field.setObjectName("dialog-npc-name")
        self.npc_name_field.setPlaceholderText("NPC name")
        controls.addWidget(self.npc_name_field)

        self.rename_npc_button = QPushButton("Rename NPC")
        self.rename_npc_button.setObjectName("dialog-rename-npc")
        self.rename_npc_button.clicked.connect(
            lambda: self.rename_selected_npc(self.npc_name_field.text()))
        controls.addWidget(self.rename_npc_button)

        self.add_npc_button = QPushButton("Add NPC")
        self.add_npc_button.setObjectName("dialog-add-npc")
        self.add_npc_button.clicked.connect(
            lambda: self.add_npc(self.npc_name_field.text()))
        controls.addWidget(self.add_npc_button)

        controls.addStretch(1)

        self.save_button = QPushButton("Save & Generate")
        self.save_button.setObjectName("dialog-save")
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(lambda: self.save())
        controls.addWidget(self.save_button)

        layout.addLayout(controls)

        self.refusal_label = QLabel()
        self.refusal_label.setObjectName("dialog-refusal")
        self.refusal_label.setWordWrap(True)
        self.refusal_label.hide()
        layout.addWidget(self.refusal_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("dialog-log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES
        )
        layout.addWidget(self.log_view)

        self._runs = RunController(self)
        self._runs.line.connect(self.append_line)
        self._runs.command_started.connect(self._append_command)
        self._runs.finished.connect(self._on_run_finished)

        self.refresh()

    # -- reading the tree --------------------------------------------------

    def refresh(self) -> None:
        """Re-read both files and rebuild the list and the cards.

        Called on every open, like the asset panel: the worktree's files
        can change under a closed dialog -- a branch switch, a pull, a
        hand edit -- and a panel showing what was there last time would
        save that stale tree back over them.
        """
        self._clear_cards()
        self.npc_list.clear()
        self.data = None
        self.max_npcs = None

        if self.binding is None:
            message = (
                self.binding_error.message if self.binding_error is not None
                else "No game repository is bound, so there is no dialog to "
                     "edit."
            )
            self.status_label.setText(message)
            return

        try:
            self.data = dialog_model.load(self.binding)
            self.max_npcs = dialog_model.read_max_npcs(self.binding)
        except dialog_model.DialogError as exc:
            self.data = None
            self.status_label.setText(exc.message)
            return

        for npc in self.data.npcs:
            self.npc_list.addItem(
                f"{npc['name']}  {len(npc.get('nodes', []))}")
        self._refresh_status()
        if self.data.npcs:
            self.npc_list.setCurrentRow(0)

    def _refresh_status(self) -> None:
        if self.data is None:
            return
        self.status_label.setText(
            f"{self.data.npcs_path.name} · {len(self.data.npcs)} of "
            f"{self.max_npcs} NPCs"
        )

    def status_text(self) -> str:
        return self.status_label.text()

    def npc_names(self) -> List[str]:
        if self.data is None:
            return []
        return [npc["name"] for npc in self.data.npcs]

    def selected_npc_index(self) -> int:
        return self.npc_list.currentRow()

    def select_npc(self, index: int) -> None:
        self.npc_list.setCurrentRow(index)

    def selected_npc(self) -> Optional[dict]:
        if self.data is None:
            return None
        index = self.selected_npc_index()
        if index < 0 or index >= len(self.data.npcs):
            return None
        return self.data.npcs[index]

    def selected_nodes(self) -> List[dict]:
        npc = self.selected_npc()
        return npc["nodes"] if npc is not None else []

    def node_cards(self) -> List[NodeCard]:
        return list(self._cards)

    def _on_npc_changed(self, _row: int) -> None:
        self.rebuild_cards()

    def _clear_cards(self) -> None:
        for card in self._cards:
            self.nodes_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []

    def rebuild_cards(self) -> None:
        self._clear_cards()
        for node in self.selected_nodes():
            card = NodeCard(node, parent=self.nodes_holder)
            self.nodes_layout.addWidget(card)
            self._cards.append(card)
            card.text_field.textChanged.connect(
                lambda _text: self._refresh_refusal())
        self._refresh_refusal()

    # -- the generator's output -------------------------------------------

    def append_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def _append_command(self, label: str, _target: str) -> None:
        self.append_line(f"$ {label}")

    def is_running(self) -> bool:
        return self._runs.is_running()

    def stop_and_wait(self) -> None:
        self._runs.stop_and_wait()

    # -- editing (R3, R5, R6, R10) ----------------------------------------

    def _report(self, message: str) -> None:
        """A refused edit is said in the log, where the generator's output
        already goes. One place for everything Garage has to tell the user
        about this tree, rather than a second status line to notice.
        """
        self.append_line(message)

    def add_node(self) -> None:
        nodes = self.selected_nodes()
        if self.selected_npc() is None:
            return
        dialog_model.add_node(nodes)
        self.rebuild_cards()
        self._refresh_npc_row()
        self._refresh_refusal()

    def delete_node(self, card: "NodeCard") -> None:
        nodes = self.selected_nodes()
        try:
            index = nodes.index(card.node)
        except ValueError:
            return
        try:
            dialog_model.delete_node(nodes, index)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        # Every card is rebuilt, not only the deleted one: renumbering
        # rewrites `next` on nodes that were not touched by the user, and
        # a chip left showing the old target is a wrong answer to AC3.
        self.rebuild_cards()
        self._refresh_npc_row()
        self._refresh_refusal()

    def set_next(self, card: "NodeCard", slot: int, target) -> None:
        try:
            dialog_model.set_next(card.node, slot, target)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()

    def add_choice(self, card: "NodeCard", label: str) -> None:
        try:
            dialog_model.add_choice(card.node, label)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()
        self._refresh_refusal()

    def remove_choice(self, card: "NodeCard", choice_index: int) -> None:
        try:
            dialog_model.remove_choice(card.node, choice_index)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        card.refresh_links()
        self._refresh_refusal()

    def rename_selected_npc(self, name: str) -> None:
        if self.data is None:
            return
        index = self.selected_npc_index()
        try:
            dialog_model.rename_npc(self.data.npcs, index, name)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self._refresh_npc_row()

    def add_npc(self, name: str) -> None:
        if self.data is None or self.max_npcs is None:
            return
        try:
            dialog_model.add_npc(self.data.npcs, name, self.max_npcs)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self.npc_list.addItem(f"{self.data.npcs[-1]['name']}  1")
        self._refresh_status()
        self.npc_list.setCurrentRow(len(self.data.npcs) - 1)

    def _refresh_npc_row(self) -> None:
        """Re-label the selected NPC's row: its name and its node count
        are both shown there and both can have just changed."""
        if self.data is None:
            return
        index = self.selected_npc_index()
        npc = self.selected_npc()
        if npc is None:
            return
        item = self.npc_list.item(index)
        if item is not None:
            item.setText(f"{npc['name']}  {len(npc.get('nodes', []))}")

    # -- the refusal, live (AC8) -------------------------------------------

    def refusal_text(self) -> str:
        return self.refusal_label.text()

    def _refresh_refusal(self) -> None:
        """Recompute AC8's refusal and gate the Save button on it.

        Called on every keystroke (through the card, below) rather than
        only at save: the prototype's Dialog screen shows "save blocked"
        while the node is too long, and a button that looks live until it
        is pressed is a worse answer to the same requirement.
        """
        if self.data is None:
            self.refusal_label.hide()
            self.save_button.setEnabled(False)
            return
        message = dialog_model.refusal(self.data)
        if message is None:
            self.refusal_label.setText("")
            self.refusal_label.hide()
            self.save_button.setEnabled(not self.is_running())
            return
        self.refusal_label.setText(message)
        self.refusal_label.show()
        self.save_button.setEnabled(False)

    # -- saving and generating (R9, R11) ----------------------------------

    def save(self) -> bool:
        """Write both files and run the generator (AC2, AC10). Returns
        False when the limits refused the save.

        The refusal is recomputed here rather than trusted from the last
        keystroke: `save()` is callable from a test, from the button and
        from a future caller, and R9 must hold for all three.
        """
        if self.data is None:
            return False
        self._refresh_refusal()
        if dialog_model.refusal(self.data) is not None:
            return False
        if self.is_running():
            self._report(
                "The generator is still running; nothing was saved.")
            return False
        try:
            dialog_model.save(self.data)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return False
        self.saved.emit()
        self._start_generator()
        return True

    def _start_generator(self) -> None:
        """R11: run dialog_to_c.py against the active worktree and stream
        what it prints.

        cwd is the active worktree, because the command's file arguments
        are worktree-relative -- the same spelling the game repository's
        Makefile uses, which is what AC11's byte-identical output rests
        on.
        """
        try:
            command = dialog_model.generator_command(self.binding)
        except dialog_model.DialogError as exc:
            self._report(exc.message)
            return
        self.save_button.setEnabled(False)
        if not self._runs.start([command], self.binding.active_worktree.path):
            self.save_button.setEnabled(True)

    def _on_run_finished(self, results) -> None:
        for result in results:
            if not result.ok:
                self.append_line(
                    f"{result.command.label} failed (exit "
                    f"{result.exit_code})."
                )
        self._refresh_refusal()
