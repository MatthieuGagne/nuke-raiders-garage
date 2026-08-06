"""The Tuner panel: every `tunable` #define from tunables.json, grouped by
category, bound to the active worktree's `src/config.h`.

R7 / AC7: only `tunable` entries are ever offered, edits are clamped to the
declared [min, max] at the widget level, and every committed edit goes
through `core.config_io.write` so comments, order and formatting survive
untouched. AC8: `structural` / `derived` / `marker` entries -- including
MAX_SPRITES -- never appear here.

Redesign (iteration 4): there is no Save button and no pending state.
The user rejected the pending-then-save model -- nothing exists only inside
Garage. A row is either equal to git HEAD or differs from it; there is no
third "edited but not yet saved" state. `config.h` is written the moment an
edit is *committed* -- Enter, focus leaving the field, or a programmatic
revert -- never on every tick of a held arrow key or every keystroke of a
multi-digit number. That is exactly what QSpinBox's `editingFinished` signal
gives (fires on Return/Enter or on focus-out; NOT on stepUp()/arrow-key
repeats or on each character typed) -- see `_make_row` below.

Qt lives only in this file (and its siblings under tools/garage/panels/);
tools/garage/core/ stays pure and Qt-free.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import config_io
from tools.garage.core.project import Binding, BindingError
from tools.garage.core.schema import Schema, SchemaError, TunableEntry

# Matches the "#define NAME" head of a #define line, so the rest of the
# line (its value/expression, with any trailing comment stripped) can be
# scanned for identifiers.
_DEFINE_HEAD_RE = re.compile(r"^#define[ \t]+\w+\b")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")

_DIFFERS_STYLE = "font-weight: bold; color: #b35c00;"
_DIFFERS_PREFIX = "● "  # filled circle, marks a row that differs from HEAD


def compute_derived_dependents(
    schema: Schema, config: config_io.ConfigFile
) -> Dict[str, List[str]]:
    """Map every `tunable` name to the `derived` names whose header
    expression reads it -- e.g. {"RACER_HP": ["PATROL_HP"]}.

    Computed fresh each call from tunables.json's classification (which
    entries are "derived") and config.h's literal expression text (which
    names each one actually references) -- never a hardcoded list, so a
    future derived/tunable pair is picked up automatically.
    """
    dependents: Dict[str, List[str]] = {}
    for name, define in config.defines.items():
        try:
            cls = schema.classify(name)
        except SchemaError:
            continue
        if cls != "derived":
            continue
        head_match = _DEFINE_HEAD_RE.match(define.raw_line)
        rest = define.raw_line[head_match.end():] if head_match else define.raw_line
        expr = rest.split("/*", 1)[0]  # drop any trailing comment
        for ident in _IDENT_RE.findall(expr):
            if schema.is_tunable(ident):
                dependents.setdefault(ident, []).append(name)
    return dependents


class _TunableRow:
    """The widgets and bookkeeping for one tunable's row.

    There is no "dirty"/pending state anymore -- a row is either equal to
    HEAD or differs from it (`differs_from_head`), full stop. `persisted_value`
    is not a third UI state; it is bookkeeping only, so a committed edit that
    reproduces the value already on disk (e.g. typing the same number back
    in) does not trigger a redundant write.
    """

    def __init__(
        self,
        entry: TunableEntry,
        spin: QSpinBox,
        name_label: QLabel,
        range_label: QLabel,
        dependents_label: QLabel,
        persisted_value: int,
        head_value: Optional[int],
        head_label: QLabel,
        revert_button: QPushButton,
    ):
        self.entry = entry
        self.spin = spin
        self.name_label = name_label
        self.range_label = range_label
        self.dependents_label = dependents_label
        # The value currently written to config.h on disk. Updated after
        # every successful write (including a revert). Used only to skip a
        # no-op write, never shown to the user as a state of its own.
        self.persisted_value = persisted_value
        # R9/AC10: the value at git HEAD, or None when HEAD (or this
        # define at HEAD) could not be read.
        self.head_value = head_value
        self.head_label = head_label
        self.revert_button = revert_button

    def differs_from_head(self) -> bool:
        return self.head_value is not None and self.spin.value() != self.head_value


class TunerPanel(QWidget):
    """Fills the Garage window body. One tab per category; a persistent
    top bar (visible across tabs) carries Revert All and a status message.

    Layout choice: 60 tunables across ~8 categories is too much for a
    single flat list on one screen without heavy scrolling, but the
    categories are small and well-separated (2-21 rows each), so tabs --
    one per category, each independently scrollable -- keep any single
    screen to a manageable size while the top bar stays visible no matter
    which tab is open.
    """

    # R19/AC19: the Diff panel (and the header) must refresh after a write
    # with no relaunch. Emitted once at the end of every write (whether it
    # wrote one value or several, via a committed edit or a revert) so a
    # listener can always just re-read the current diff/header rather than
    # track what changed.
    written = Signal()

    def __init__(
        self,
        binding: Optional[Binding],
        binding_error: Optional[BindingError] = None,
        schema: Optional[Schema] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.binding = binding
        self.binding_error = binding_error

        self._schema: Optional[Schema] = None
        self._config: Optional[config_io.ConfigFile] = None
        self._rows: Dict[str, _TunableRow] = {}
        self._dependents: Dict[str, List[str]] = {}
        self._explanation: str = ""

        # R9/AC10: the whole config.h at git HEAD, read once per refresh
        # (never once per row -- see config_io.read_config_at_head), plus
        # why it is unavailable when it is (no commit yet / config.h not
        # present at HEAD). Neither failure is fatal to the panel.
        self._head_config: Optional[config_io.ConfigFile] = None
        self._head_error: str = ""

        outer = QVBoxLayout(self)

        self._explanation_label = QLabel()
        self._explanation_label.setObjectName("tuner-explanation")
        self._explanation_label.setWordWrap(True)
        self._explanation_label.hide()
        outer.addWidget(self._explanation_label)

        self._head_status_label = QLabel()
        self._head_status_label.setObjectName("tuner-head-status")
        self._head_status_label.setWordWrap(True)
        self._head_status_label.hide()
        outer.addWidget(self._head_status_label)

        top_bar = QHBoxLayout()
        self._status_label = QLabel()
        self._status_label.setObjectName("tuner-status")
        top_bar.addWidget(self._status_label, 1)
        self._revert_all_button = QPushButton("Revert All")
        self._revert_all_button.setObjectName("tuner-revert-all")
        self._revert_all_button.clicked.connect(self.revert_all)
        top_bar.addWidget(self._revert_all_button)
        outer.addLayout(top_bar)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("tuner-tabs")
        outer.addWidget(self._tabs, 1)

        self._load(schema)

    # -- construction ---------------------------------------------------

    def _load(self, schema: Optional[Schema]) -> None:
        if self.binding is None:
            self._set_error(self._binding_error_message())
            return

        if schema is not None:
            self._schema = schema
        else:
            try:
                self._schema = Schema.load()
            except SchemaError as exc:
                self._set_error(f"Could not load tunables.json: {exc}")
                return

        try:
            self._config = config_io.read(self.binding, self._schema)
        except OSError as exc:
            self._set_error(f"Could not read '{self.binding.config_h}': {exc}")
            return

        self._load_head()
        self._dependents = compute_derived_dependents(self._schema, self._config)
        self._build_rows()

    def _load_head(self) -> None:
        """Read git HEAD's config.h once for this refresh (R9/AC10). A
        missing HEAD or a config.h absent at HEAD is not fatal -- rows
        still build and stay editable; only the HEAD/revert annotations
        are unavailable, and the panel says so.
        """
        assert self.binding is not None
        try:
            self._head_config = config_io.read_config_at_head(self.binding, self._schema)
        except config_io.ConfigIOError as exc:
            self._head_config = None
            self._head_error = (
                f"Git HEAD values unavailable, so nothing can be reverted: {exc}"
            )
            self._head_status_label.setText(self._head_error)
            self._head_status_label.show()

    def head_status_text(self) -> str:
        """Why HEAD values/revert are unavailable, or "" when they are fine."""
        return self._head_error

    def _binding_error_message(self) -> str:
        if self.binding_error is not None:
            return (
                f"Repository binding failed ({self.binding_error.key}): "
                f"{self.binding_error.message}"
            )
        return "No repository is bound; the Tuner has nothing to show."

    def _set_error(self, message: str) -> None:
        self._explanation = message
        self._explanation_label.setText(message)
        self._explanation_label.show()
        self._tabs.hide()
        self._revert_all_button.setEnabled(False)

    def explanation_text(self) -> str:
        """Why the panel is empty, or "" when it built normally."""
        return self._explanation

    def _build_rows(self) -> None:
        assert self._schema is not None and self._config is not None
        categories: Dict[str, List[TunableEntry]] = {}
        order: List[str] = []
        for entry in self._schema.tunables():
            if entry.category not in categories:
                categories[entry.category] = []
                order.append(entry.category)
            categories[entry.category].append(entry)

        for category in order:
            entries = categories[category]
            page = QWidget()
            form = QFormLayout(page)

            for entry in entries:
                define = self._config.defines.get(entry.name)
                if define is None or not define.has_value:
                    # tunables.json/config.h drift is garage_lint's job
                    # (R8); the Tuner simply skips what it cannot read.
                    continue
                row = self._make_row(entry, define)
                self._rows[entry.name] = row
                form.addRow(row.name_label, self._row_field(row))

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self._tabs.addTab(scroll, f"{category} ({len(entries)})")

    def _make_row(self, entry: TunableEntry, define: config_io.DefineLine) -> _TunableRow:
        name_label = QLabel(entry.name)
        name_label.setObjectName("tuner-row-name")
        name_label.setToolTip(entry.reason)

        spin = QSpinBox()
        spin.setObjectName(f"tuner-spin-{entry.name}")
        # The clamp is unbreakable at the widget level: QSpinBox refuses
        # any value outside [minimum, maximum], so a bad edit cannot even
        # be entered, let alone saved.
        spin.setRange(entry.min, entry.max)
        spin.setToolTip(entry.reason)
        persisted_value = self._schema.clamp(entry.name, define.value)  # type: ignore[union-attr]
        spin.setValue(persisted_value)

        # The range is stated up front -- no need to hit the ceiling to
        # discover it.
        range_label = QLabel(f"[{entry.min}–{entry.max}]")
        range_label.setObjectName("tuner-range")

        dependent_names = self._dependents.get(entry.name, [])
        dependents_text = (
            f"also updates: {', '.join(dependent_names)} (derived, read-only)"
            if dependent_names
            else ""
        )
        dependents_label = QLabel(dependents_text)
        dependents_label.setObjectName("tuner-dependents")
        dependents_label.setWordWrap(True)

        head_define = self._head_config.defines.get(entry.name) if self._head_config else None
        head_value = head_define.value if head_define is not None and head_define.has_value else None

        head_label = QLabel()
        head_label.setObjectName(f"tuner-head-{entry.name}")
        head_label.hide()

        revert_button = QPushButton("Revert")
        revert_button.setObjectName(f"tuner-revert-{entry.name}")
        revert_button.hide()
        revert_button.clicked.connect(lambda _checked=False, name=entry.name: self.revert_row(name))

        row = _TunableRow(
            entry=entry,
            spin=spin,
            name_label=name_label,
            range_label=range_label,
            dependents_label=dependents_label,
            persisted_value=persisted_value,
            head_value=head_value,
            head_label=head_label,
            revert_button=revert_button,
        )
        # valueChanged fires on every tick (typing a digit, holding an
        # arrow key, scrubbing) -- used only to keep the differs-from-HEAD
        # styling live as the user edits, never to write.
        spin.valueChanged.connect(lambda _value, name=entry.name: self._on_value_changed(name))
        # editingFinished fires once an edit is *committed* -- Return/Enter
        # or the field losing focus -- and NOT on stepUp()/arrow-key
        # repeats or per keystroke (verified empirically: typing "100"
        # digit by digit emits valueChanged three times and editingFinished
        # zero times; Enter or a focus-out then emits editingFinished once).
        # This is the signal that writes to disk.
        spin.editingFinished.connect(lambda name=entry.name: self._on_edit_finished(name))
        self._set_row_style(row)
        return row

    @staticmethod
    def _row_field(row: _TunableRow) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QHBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        row.spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        inner.addWidget(row.spin)
        inner.addWidget(row.range_label)
        inner.addWidget(row.head_label)
        inner.addWidget(row.revert_button)
        inner.addStretch(1)
        outer.addLayout(inner)

        if row.dependents_label.text():
            outer.addWidget(row.dependents_label)
        return container

    # -- HEAD-diff styling --------------------------------------------------

    def _set_row_style(self, row: "_TunableRow") -> None:
        # R9/AC10: the HEAD value (and its revert control), and the bold
        # "differs" styling, are visible exactly on rows that currently
        # differ from HEAD -- regardless of whether that difference came
        # from this session's edits or was already there (e.g. a
        # hand-edited config.h) when the panel opened. There is no other
        # row state: a row is either equal to HEAD or it differs.
        differs = row.differs_from_head()
        row.name_label.setStyleSheet(_DIFFERS_STYLE if differs else "")
        prefix = _DIFFERS_PREFIX if differs else ""
        row.name_label.setText(f"{prefix}{row.entry.name}")

        if differs:
            row.head_label.setText(f"HEAD: {row.head_value}")
            row.head_label.show()
            row.revert_button.show()
        else:
            row.head_label.setText("")
            row.head_label.hide()
            row.revert_button.hide()

    def _on_value_changed(self, name: str) -> None:
        # Fires on every tick (typing, holding an arrow key, scrubbing).
        # Only ever touches styling -- never writes. See _on_edit_finished
        # for the write path.
        self._set_row_style(self._rows[name])

    def status_text(self) -> str:
        return self._status_label.text()

    # -- writing --------------------------------------------------------
    #
    # There is no Save button and no pending state: an edit writes the
    # instant it is committed (_on_edit_finished, below), and revert writes
    # immediately too. Every write goes through _write_values so the
    # "refresh totals/diff" side effect (the `written` signal) always fires
    # from one place.

    def _write_values(self, changes: Dict[str, int]) -> None:
        """Write `changes` (name -> new value) through config_io in a
        single call, refresh this panel's rows from the result, and tell
        listeners (the header, the diff dialog) to refresh. A write
        failure (a refused non-tunable target, or an I/O error) is shown
        and nothing is written -- config_io.write is all-or-nothing.
        """
        if self.binding is None or self._schema is None or self._config is None or not changes:
            return
        try:
            config_io.write(self.binding, self._schema, changes)
        except config_io.ConfigIOError as exc:
            self._status_label.setText(f"Write failed, nothing written: {exc}")
            self.written.emit()
            return

        self._config = config_io.read(self.binding, self._schema)
        for name in changes:
            row = self._rows[name]
            row.persisted_value = self._schema.clamp(name, self._config.defines[name].value)
            self._set_row_style(row)

        count = len(changes)
        self._status_label.setText(f"Wrote {count} value{'s' if count != 1 else ''}.")
        self.written.emit()

    def _on_edit_finished(self, name: str) -> None:
        """The edit-finished write path: Enter, or the field losing focus
        (QSpinBox.editingFinished -- never fires per keystroke or per
        arrow-key tick, only once an edit is committed). A value equal to
        what is already on disk is not written again.
        """
        row = self._rows[name]
        new_value = row.spin.value()
        if new_value == row.persisted_value:
            return
        self._write_values({name: new_value})

    # -- revert (R9/AC10) -----------------------------------------------

    def revert_row(self, name: str) -> None:
        """Set `name`'s value back to its HEAD value and write it at once.

        A row with no HEAD value available (no HEAD, or config.h absent at
        HEAD) is a no-op. A row whose HEAD value already equals what is on
        disk performs a no-op write (persisted_value already matches).
        """
        row = self._rows.get(name)
        if row is None or row.head_value is None:
            return
        row.spin.setValue(row.head_value)  # emits valueChanged -> style refresh
        self._on_edit_finished(name)

    def revert_all(self) -> None:
        """Revert every row that currently differs from HEAD, writing every
        one of them in a single config_io.write call -- not one write per
        row.
        """
        changes = {
            name: row.head_value
            for name, row in self._rows.items()
            if row.differs_from_head()
        }
        if not changes:
            return
        for name, value in changes.items():
            self._rows[name].spin.setValue(value)  # emits valueChanged -> style refresh
        self._write_values(changes)
