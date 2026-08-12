"""The budgets aside: WRAM, VRAM, OAM and the ROM banks after a compile
(R12), with the per-scene OAM peaks underneath.

Layout follows the prototype's `<aside class="aside">`: a narrow column
beside the Tuner, one meter per budget — name and numbers on top, a bar,
then the verdict chip and a hint. It is a *reading* panel: nothing here is
editable, and nothing here recomputes a number. Every figure comes from
`tools.garage.core.budgets`, which parses what `make memory-check` and
`make bank-post-build` printed, so AC12 ("the same numbers as
`make memory-check`") holds by construction rather than by arithmetic
Garage would have to keep in step.

R18/AC18: no colour here. Each meter and verdict chip carries a `status`
dynamic property ("pass"/"warn"/"fail"/"blocked") for
`tools/garage/theme/qss.py` to colour, and the chip spells the word out.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import budgets as budgets_core

# The widest the aside may get. The prototype gives it a fixed column; the
# Tuner is the panel that should take the space a wider window offers.
PANEL_WIDTH = 260

_STATUS_PROPERTY = {
    budgets_core.PASS: "pass",
    budgets_core.WARN: "warn",
    budgets_core.FAIL: "fail",
    budgets_core.BLOCKED: "blocked",
}


class BudgetsPanel(QWidget):
    """Shows a `budgets_core.BudgetReport`. Call `set_report` after a
    compile; before the first one, it says so rather than showing four
    empty meters that could be mistaken for measurements.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("budgets-panel")
        self.setFixedWidth(PANEL_WIDTH)

        self._report: Optional[budgets_core.BudgetReport] = None
        self._meters: Dict[str, QProgressBar] = {}
        self._verdicts: Dict[str, QLabel] = {}
        self._values: Dict[str, QLabel] = {}
        self._hints: Dict[str, QLabel] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Memory budgets")
        title.setObjectName("budgets-title")
        self._layout.addWidget(title)

        self._status_label = QLabel("No compile yet — budgets are measured after a build.")
        self._status_label.setObjectName("budgets-status")
        self._status_label.setWordWrap(True)
        self._layout.addWidget(self._status_label)

        self._meters_holder = QWidget()
        self._meters_layout = QVBoxLayout(self._meters_holder)
        self._meters_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._meters_holder)

        self._scenes_holder = QWidget()
        self._scenes_layout = QVBoxLayout(self._scenes_holder)
        self._scenes_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._scenes_holder)
        self._scenes_holder.hide()

    # -- data access (for the window and for tests) ----------------------

    @property
    def report(self) -> Optional[budgets_core.BudgetReport]:
        return self._report

    def status_text(self) -> str:
        return self._status_label.text()

    def budget_keys(self) -> List[str]:
        return list(self._meters)

    def value_text(self, key: str) -> str:
        label = self._values.get(key)
        return label.text() if label is not None else ""

    def verdict_text(self, key: str) -> str:
        label = self._verdicts.get(key)
        return label.text() if label is not None else ""

    def status_of(self, key: str) -> str:
        meter = self._meters.get(key)
        return meter.property("status") if meter is not None else ""

    def scene_rows(self) -> List[str]:
        return [
            label.text()
            for label in self._scenes_holder.findChildren(QLabel)
            if label.objectName() == "budgets-scene"
        ]

    # -- rendering --------------------------------------------------------

    def set_report(self, report: Optional[budgets_core.BudgetReport]) -> None:
        self._report = report
        self._clear()

        if report is None or not report.budgets:
            self._status_label.setText(
                "No compile yet — budgets are measured after a build."
            )
            self._status_label.show()
            return

        self._status_label.setText(report.summary())
        self._status_label.show()

        for budget in report.budgets:
            self._meters_layout.addWidget(self._build_meter(budget))

        if report.scenes:
            self._build_scenes(report)
            self._scenes_holder.show()

    def _clear(self) -> None:
        self._meters.clear()
        self._verdicts.clear()
        self._values.clear()
        self._hints.clear()
        for layout in (self._meters_layout, self._scenes_layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    # Unparent *before* deleteLater: the deletion happens on
                    # a later event-loop turn, and until then the widget is
                    # still a child -- so a second report would find both
                    # its own rows and the previous ones.
                    widget.setParent(None)
                    widget.deleteLater()
        self._scenes_holder.hide()

    def _build_meter(self, budget: budgets_core.Budget) -> QWidget:
        status = _STATUS_PROPERTY.get(budget.status, "blocked")

        section = QFrame()
        section.setObjectName("budgets-meter-section")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        name = QLabel(budget.name)
        name.setObjectName("budgets-name")
        top.addWidget(name)
        top.addStretch(1)
        value = QLabel(budget.value_text())
        value.setObjectName("budgets-value")
        top.addWidget(value)
        layout.addLayout(top)

        meter = QProgressBar()
        meter.setObjectName("budgets-meter")
        meter.setProperty("status", status)
        meter.setTextVisible(False)
        meter.setRange(0, 100)
        # An unmeasured budget draws an empty track: a bar at 0% would read
        # as "nothing used", which is a measurement it does not have.
        meter.setValue(budget.percent or 0)
        layout.addWidget(meter)

        foot = QHBoxLayout()
        verdict = QLabel(budget.status)
        verdict.setObjectName("budgets-verdict")
        verdict.setProperty("status", status)
        foot.addWidget(verdict)
        foot.addStretch(1)
        hint_text = budget.hint or (
            f"{budget.percent}%" if budget.percent is not None else ""
        )
        hint = QLabel(hint_text)
        hint.setObjectName("budgets-hint")
        hint.setWordWrap(True)
        foot.addWidget(hint)
        layout.addLayout(foot)

        self._meters[budget.key] = meter
        self._verdicts[budget.key] = verdict
        self._values[budget.key] = value
        self._hints[budget.key] = hint
        return section

    def _build_scenes(self, report: budgets_core.BudgetReport) -> None:
        title = QLabel("Peak OAM per scene")
        title.setObjectName("budgets-scenes-title")
        self._scenes_layout.addWidget(title)

        peak = report.peak_scene()
        for scene in report.scenes:
            row = QLabel(f"{scene.name}   {scene.used} / {scene.limit}")
            row.setObjectName("budgets-scene")
            # The busiest scene is the one that decides the OAM verdict, so
            # it is marked -- the same "peak" treatment the prototype gives.
            row.setProperty("peak", "true" if peak is not None and scene is peak else "false")
            self._scenes_layout.addWidget(row)
