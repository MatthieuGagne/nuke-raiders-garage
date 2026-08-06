"""Garage main window. Thin Qt layer: all logic lives in tools.garage.core.

Iteration 1 delivers the window shell and the header (AC1, AC2, AC17).
Iteration 2 adds the Tuner panel as the window body (AC7, AC8).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core.project import Binding, BindingError, bind
from tools.garage.panels.tuner import TunerPanel


def format_header(binding: Optional[Binding], error: Optional[BindingError]) -> str:
    """Pure text for the header. When the binding failed, name the key to
    fix and what the failure prevents (AC17) instead of a path/branch.
    """
    if error is not None:
        return f"Repository binding failed ({error.key}): {error.message}"
    branch = binding.active_worktree.branch or "(detached HEAD)"
    return f"{binding.active_worktree.path}  [{branch}]"


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

        self.header_label = QLabel(format_header(self.binding, self.binding_error))
        self.header_label.setObjectName("garage-header")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.tuner_panel = TunerPanel(self.binding, self.binding_error, parent=central)
        self.tuner_panel.setObjectName("garage-tuner-panel")
        layout.addWidget(self.tuner_panel, 1)

        self.setCentralWidget(central)
        self.resize(900, 600)


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    window = GarageWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
