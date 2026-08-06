"""The Tuner panel: every `tunable` #define from tunables.json, grouped by
category, bound to the active worktree's `src/config.h`.

R7 / AC7: only `tunable` entries are ever offered, edits are clamped to the
declared [min, max] at the widget level, and Save goes through
`core.config_io.write` so comments, order and formatting survive untouched.
AC8: `structural` / `derived` / `marker` entries -- including MAX_SPRITES --
never appear here.

Qt lives only in this file (and its siblings under tools/garage/panels/);
tools/garage/core/ stays pure and Qt-free.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

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

_DIRTY_STYLE = "font-weight: bold; color: #b35c00;"
_DIRTY_PREFIX = "● "  # filled circle, marks a changed-but-unsaved row


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
    """The widgets and bookkeeping for one tunable's row."""

    def __init__(
        self,
        entry: TunableEntry,
        spin: QSpinBox,
        name_label: QLabel,
        range_label: QLabel,
        dependents_label: QLabel,
        original_value: int,
    ):
        self.entry = entry
        self.spin = spin
        self.name_label = name_label
        self.range_label = range_label
        self.dependents_label = dependents_label
        self.original_value = original_value

    def is_dirty(self) -> bool:
        return self.spin.value() != self.original_value


class TunerPanel(QWidget):
    """Fills the Garage window body. One tab per category; a persistent
    top bar (visible across tabs) reports how many edits are pending and
    what Save did.

    Layout choice: 60 tunables across ~8 categories is too much for a
    single flat list on one screen without heavy scrolling, but the
    categories are small and well-separated (2-21 rows each), so tabs --
    one per category, each independently scrollable -- keep any single
    screen to a manageable size while the pending-count/Save bar above
    the tabs stays visible no matter which tab is open.
    """

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

        outer = QVBoxLayout(self)

        self._explanation_label = QLabel()
        self._explanation_label.setObjectName("tuner-explanation")
        self._explanation_label.setWordWrap(True)
        self._explanation_label.hide()
        outer.addWidget(self._explanation_label)

        top_bar = QHBoxLayout()
        self._status_label = QLabel()
        self._status_label.setObjectName("tuner-status")
        top_bar.addWidget(self._status_label, 1)
        self._save_button = QPushButton("Save")
        self._save_button.setObjectName("tuner-save")
        self._save_button.clicked.connect(self.save)
        top_bar.addWidget(self._save_button)
        outer.addLayout(top_bar)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("tuner-tabs")
        outer.addWidget(self._tabs, 1)

        self._load(schema)
        self._update_status()

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

        self._dependents = compute_derived_dependents(self._schema, self._config)
        self._build_rows()

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
        self._save_button.setEnabled(False)

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
        original_value = self._schema.clamp(entry.name, define.value)  # type: ignore[union-attr]
        spin.setValue(original_value)

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

        row = _TunableRow(
            entry=entry,
            spin=spin,
            name_label=name_label,
            range_label=range_label,
            dependents_label=dependents_label,
            original_value=original_value,
        )
        spin.valueChanged.connect(lambda _value, name=entry.name: self._on_value_changed(name))
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
        inner.addStretch(1)
        outer.addLayout(inner)

        if row.dependents_label.text():
            outer.addWidget(row.dependents_label)
        return container

    # -- change tracking --------------------------------------------------

    def _set_row_style(self, name: str) -> None:
        row = self._rows[name]
        dirty = row.is_dirty()
        row.name_label.setStyleSheet(_DIRTY_STYLE if dirty else "")
        prefix = _DIRTY_PREFIX if dirty else ""
        row.name_label.setText(f"{prefix}{row.entry.name}")

    def _on_value_changed(self, name: str) -> None:
        self._set_row_style(name)
        self._update_status()

    def pending_count(self) -> int:
        return sum(1 for row in self._rows.values() if row.is_dirty())

    def _update_status(self) -> None:
        n = self.pending_count()
        if n == 0:
            self._status_label.setText("No changes pending.")
        else:
            self._status_label.setText(f"{n} change{'s' if n != 1 else ''} pending.")

    def status_text(self) -> str:
        return self._status_label.text()

    # -- save ---------------------------------------------------------------

    def save(self) -> str:
        """Write every pending change through config_io and report what
        happened. Never silent: returns (and shows) either how many
        values were written or the error that stopped it.
        """
        if self.binding is None or self._schema is None or self._config is None:
            message = "Cannot save: " + (self._explanation or "no repository is bound.")
            self._status_label.setText(message)
            return message

        changes = {name: row.spin.value() for name, row in self._rows.items() if row.is_dirty()}
        if not changes:
            message = "0 values written -- nothing to save."
            self._status_label.setText(message)
            return message

        try:
            config_io.write(self.binding, self._schema, changes)
        except config_io.ConfigIOError as exc:
            message = f"Save failed, nothing written: {exc}"
            self._status_label.setText(message)
            return message

        self._config = config_io.read(self.binding, self._schema)
        for name in changes:
            row = self._rows[name]
            row.original_value = self._schema.clamp(name, self._config.defines[name].value)
            self._set_row_style(name)

        count = len(changes)
        message = f"Saved {count} value{'s' if count != 1 else ''}."
        self._status_label.setText(message)
        return message
