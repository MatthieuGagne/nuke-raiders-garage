"""Garage's dark theme (R18/AC18).

`tools/garage/theme/` is the single place a colour or a typeface may be
named as a literal in this application. Everything else -- `app.py` and
every module under `tools/garage/panels/` -- refers to a token by name
(`TOKENS["accent"]`, `FONT_MONO`, ...) or selects on an object name / Qt
dynamic property (`changed`, `role`, `diffKind`) that `tokens.py` and
`qss.py` define; no panel spells out a hex value or a font family.

`apply(app)` is the one entry point a panel needs: it builds the
stylesheet from the tokens and installs it on the QApplication once, at
startup (see `tools.garage.app.main`).
"""
from __future__ import annotations

from tools.garage.theme.qss import build_stylesheet
from tools.garage.theme.tokens import FONT_INTERFACE, FONT_MONO, TOKENS


def apply(app) -> None:
    """Install the dark stylesheet on `app` (a QApplication). Idempotent:
    calling it again just re-sets the same string, so tests may call it
    freely without needing to guard against a double-apply.
    """
    app.setStyleSheet(build_stylesheet())


__all__ = ["TOKENS", "FONT_INTERFACE", "FONT_MONO", "build_stylesheet", "apply"]
