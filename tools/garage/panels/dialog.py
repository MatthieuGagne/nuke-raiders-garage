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
    QComboBox,
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

    Follows the `AssetCard` pattern (`tools/garage/panels/assets.py`):
    the card only emits signals for the edits it offers a control for --
    every rule (the three-choice ceiling, the renumbering after a delete,
    what a `next` slot may point at) lives in `dialog_model` and is called
    by `DialogPanel`, never re-derived here.
    """

    delete_requested = Signal(object)          # NodeCard
    next_changed = Signal(object, int, object)  # NodeCard, slot, target
    add_choice_requested = Signal(object, str)  # NodeCard, label
    remove_choice_requested = Signal(object, int)  # NodeCard, choice_index

    def __init__(self, node: dict, nodes: List[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("dialog-node-card")
        self.node = node
        # The whole NPC's node list, kept only to compute
        # `dialog_model.next_targets` -- what the next-combos may offer --
        # never mutated here.
        self.nodes = nodes

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

        self.delete_button = QPushButton("Delete node")
        self.delete_button.setObjectName("dialog-delete-node")
        self.delete_button.clicked.connect(
            lambda: self.delete_requested.emit(self))
        head.addWidget(self.delete_button)
        layout.addLayout(head)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("dialog-node-preview")
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignLeft)

        self.links_row = QHBoxLayout()
        self.links_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.links_row)
        self._link_labels: List[QLabel] = []

        # One combo per `next` slot (R5/AC4) and one Remove button per
        # existing choice (R6), rebuilt together because both are keyed by
        # the same slot/choice index.
        self.next_row = QHBoxLayout()
        self.next_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.next_row)
        self._next_combos: List[QComboBox] = []

        self.remove_choice_row = QHBoxLayout()
        self.remove_choice_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.remove_choice_row)
        self._remove_buttons: List[QPushButton] = []

        add_choice_row = QHBoxLayout()
        self.choice_label_field = QLineEdit()
        self.choice_label_field.setObjectName("dialog-choice-label")
        self.choice_label_field.setPlaceholderText("Choice label")
        add_choice_row.addWidget(self.choice_label_field)
        self.add_choice_button = QPushButton("Add choice")
        self.add_choice_button.setObjectName("dialog-add-choice")
        self.add_choice_button.clicked.connect(self._on_add_choice_clicked)
        add_choice_row.addWidget(self.add_choice_button)
        layout.addLayout(add_choice_row)

        # AC6: the count and the preview follow the field, keystroke by
        # keystroke -- and the node dict follows it too, so nothing has to
        # be harvested out of the widgets at save time.
        self.text_field.textChanged.connect(self._on_text_changed)
        self.refresh_text_state()
        self.refresh_links()

    # -- adding a choice ----------------------------------------------

    def _on_add_choice_clicked(self) -> None:
        label = self.choice_label_field.text()
        self.add_choice_requested.emit(self, label)
        self.choice_label_field.clear()

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
        self.refresh_next_controls()

    def refresh_next_controls(self) -> None:
        """Rebuild the next-combos and the remove-choice buttons (R5/R6).

        Built fully, then connected: a `QComboBox` fires
        `currentIndexChanged` the moment an item is added or
        `setCurrentIndex` is called, so a combo connected before it is
        populated would call `set_next` on its own, spuriously, while a
        card is merely being (re)built -- not while the user changed
        anything. Connecting last means population itself can never fire
        the handler.
        """
        for combo in self._next_combos:
            self.next_row.removeWidget(combo)
            combo.setParent(None)
            combo.deleteLater()
        self._next_combos = []
        for button in self._remove_buttons:
            self.remove_choice_row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._remove_buttons = []

        nexts = self.node.get("next", [])
        options = dialog_model.next_targets(self.nodes, self.node["idx"])
        option_texts = [_target_text(option) for option in options]
        for slot, target in enumerate(nexts):
            combo = QComboBox()
            combo.setObjectName("dialog-next-combo")
            for option, text in zip(options, option_texts):
                combo.addItem(text, option)
            current_text = _target_text(target)
            index = combo.findText(current_text)
            if index < 0:
                # The node's own current target is not among the offered
                # options -- can only happen for a hand-edited or
                # otherwise irregular tree -- so it is added rather than
                # silently swapped for the first option in the list.
                combo.addItem(current_text, target)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _index, s=slot, c=combo: self._on_next_combo_changed(s, c))
            self.next_row.addWidget(combo)
            self._next_combos.append(combo)

        choices = self.node.get("choices", [])
        for choice_index, label in enumerate(choices):
            button = QPushButton(f"Remove [{label}]")
            button.setObjectName("dialog-remove-choice")
            button.clicked.connect(
                lambda _checked=False, i=choice_index: (
                    self.remove_choice_requested.emit(self, i)))
            self.remove_choice_row.addWidget(button)
            self._remove_buttons.append(button)

    def _on_next_combo_changed(self, slot: int, combo: QComboBox) -> None:
        self.next_changed.emit(self, slot, combo.currentData())

    def next_combos(self) -> List[QComboBox]:
        return list(self._next_combos)

    def remove_choice_buttons(self) -> List[QPushButton]:
        return list(self._remove_buttons)

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


def _npc_row_label(npc: dict) -> str:
    """The NPC list's row text: the name, then its real node count -- the
    one spelling used everywhere a row is written or rewritten (Task 7,
    finding 9), so a freshly added NPC's row never claims a node count
    that isn't its own.
    """
    return f"{npc['name']}  {len(npc.get('nodes', []))}"


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
            self._refresh_refusal()
            return

        try:
            self.data = dialog_model.load(self.binding)
            self.max_npcs = dialog_model.read_max_npcs(self.binding)
        except dialog_model.DialogError as exc:
            self.data = None
            self.status_label.setText(exc.message)
            self._refresh_refusal()
            return

        for npc in self.data.npcs:
            self.npc_list.addItem(_npc_row_label(npc))
        self._refresh_status()
        if self.data.npcs:
            self.npc_list.setCurrentRow(0)
        self._refresh_refusal()

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
        nodes = self.selected_nodes()
        for node in nodes:
            card = NodeCard(node, nodes, parent=self.nodes_holder)
            self.nodes_layout.addWidget(card)
            self._cards.append(card)
            card.text_field.textChanged.connect(
                lambda _text: self._refresh_refusal())
            card.delete_requested.connect(self.delete_node)
            card.next_changed.connect(self.set_next)
            card.add_choice_requested.connect(self.add_choice)
            card.remove_choice_requested.connect(self.remove_choice)
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
        self.npc_list.addItem(_npc_row_label(self.data.npcs[-1]))
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
            item.setText(_npc_row_label(npc))

    # -- the refusal, live (AC8) -------------------------------------------

    def refusal_text(self) -> str:
        return self.refusal_label.text()

    def _refresh_refusal(self) -> Optional[str]:
        """Recompute AC8's refusal, gate the Save button on it, and return
        the message (or None) so a caller that already needs it -- `save`,
        below -- is not asking `dialog_model.refusal` a second time for
        the same answer.

        Called on every keystroke (through the card, below) rather than
        only at save: the prototype's Dialog screen shows "save blocked"
        while the node is too long, and a button that looks live until it
        is pressed is a worse answer to the same requirement.
        """
        if self.data is None:
            self.refusal_label.hide()
            self.save_button.setEnabled(False)
            return None
        message = dialog_model.refusal(self.data)
        if message is None:
            self.refusal_label.setText("")
            self.refusal_label.hide()
            self.save_button.setEnabled(not self.is_running())
            return None
        self.refusal_label.setText(message)
        self.refusal_label.show()
        self.save_button.setEnabled(False)
        return message

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
        if self._refresh_refusal() is not None:
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
