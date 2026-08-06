"""The Doctor panel: the toolchain verification R14 asks for, rendered.

Every decision about *what* is checked, what a failure prevents and how the
summary reads lives in `tools.garage.core.doctor`, which is pure and has no
Qt import. This file only turns a `doctor.Report` into widgets, the same way
`diff_view.py` renders a `WorktreeDiff` -- so the report can be (and is)
tested without a display.

R18/AC18: no colour and no typeface literal here. A row exposes its result
as a `verdict` dynamic property ("pass"/"fail") on the widgets that need to
carry the colour -- the verdict chip, the row, the detail line -- and
`tools/garage/theme/qss.py` selects on that. The chip also spells out PASS
or FAIL in text, so the result never depends on colour alone.

A failing row carries its `prevents` sentence directly underneath it rather
than in one callout at the bottom: AC14 asks the verification to name what
the failure prevents, and the answer is only useful next to the failure it
belongs to -- with eight checks, a bottom callout would make the reader
match sentences to rows themselves.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import doctor as doctor_core
from tools.garage.core.project import Binding, BindingError

_VERDICT_PROPERTY = {doctor_core.PASS: "pass", doctor_core.FAIL: "fail"}


class DoctorPanel(QWidget):
    """Runs the checks on construction (R14: "when it starts") and renders
    them. `refresh()` re-runs them -- kept for the later iterations that
    change the active worktree, which changes what the binding check
    reports. It is deliberately not wired to a button: PATH is read from
    the process environment, which a running Garage cannot see change, so a
    "re-run" control would answer with the same result and imply otherwise.
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

        self._report: Optional[doctor_core.Report] = None
        self._prevents: Dict[str, str] = {}
        self._details: Dict[str, str] = {}
        self._verdicts: Dict[str, str] = {}

        outer = QVBoxLayout(self)

        self._summary_label = QLabel()
        self._summary_label.setObjectName("doctor-summary")
        self._summary_label.setWordWrap(True)
        outer.addWidget(self._summary_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("doctor-scroll")
        self._scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.addStretch(1)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

        self.refresh()

    # -- data access (for the window and for tests) ----------------------

    @property
    def report(self) -> Optional[doctor_core.Report]:
        return self._report

    def has_failures(self) -> bool:
        return bool(self._report and self._report.failures)

    def summary_text(self) -> str:
        return self._summary_label.text()

    def check_keys(self) -> List[str]:
        return [c.key for c in self._report.checks] if self._report else []

    def verdict_of(self, key: str) -> str:
        return self._verdicts.get(key, "")

    def detail_of(self, key: str) -> str:
        return self._details.get(key, "")

    def prevents_of(self, key: str) -> str:
        """The rendered "prevents" line for `key`, or "" when that check
        passed (a passing check renders no such line at all).
        """
        return self._prevents.get(key, "")

    # -- build / refresh -------------------------------------------------

    def refresh(self) -> None:
        self._clear_content()
        self._prevents = {}
        self._details = {}
        self._verdicts = {}

        self._report = doctor_core.run_checks(self.binding, self.binding_error)
        self._summary_label.setText(self._report.summary())

        for check in self._report.checks:
            self._insert(self._build_check_row(check))

    def _clear_content(self) -> None:
        # Everything except the trailing stretch, which stays last (new
        # widgets are always inserted before it -- see _insert).
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _insert(self, widget: QWidget) -> None:
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def _build_check_row(self, check: doctor_core.CheckResult) -> QWidget:
        verdict = _VERDICT_PROPERTY.get(check.status, "fail")
        self._verdicts[check.key] = verdict
        self._details[check.key] = check.detail

        row = QFrame()
        row.setObjectName("doctor-check-row")
        row.setProperty("verdict", verdict)
        row_layout = QVBoxLayout(row)

        head = QHBoxLayout()

        chip = QLabel(check.status)
        chip.setObjectName("doctor-verdict")
        chip.setProperty("verdict", verdict)
        head.addWidget(chip)

        name = QLabel(check.name)
        name.setObjectName("doctor-check-name")
        name.setWordWrap(True)
        head.addWidget(name, 1)

        if check.tag:
            tag = QLabel(check.tag)
            tag.setObjectName("doctor-check-tag")
            tag.setProperty("verdict", verdict)
            head.addWidget(tag)

        row_layout.addLayout(head)

        detail = QLabel(check.detail)
        detail.setObjectName("doctor-check-detail")
        detail.setProperty("verdict", verdict)
        detail.setWordWrap(True)
        row_layout.addWidget(detail)

        if check.prevents:
            self._prevents[check.key] = check.prevents
            prevents = QLabel(f"Prevents: {check.prevents}")
            prevents.setObjectName("doctor-check-prevents")
            prevents.setWordWrap(True)
            row_layout.addWidget(prevents)

        return row
