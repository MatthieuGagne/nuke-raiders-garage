"""Builds the Qt Style Sheet from `tools.garage.theme.tokens`.

Every rule below reads a token by name (`t["accent"]`, `FONT_MONO`, ...);
none spells out a colour or a font family of its own, so the whole palette
lives in exactly one place (`tokens.py`) and a change there is the only
edit a re-theme would need.

Selectors are either a widget type (`QPushButton`, `QSpinBox` -- every
instance of that type in the app looks the same) or one of the object
names / dynamic properties the panels already expose for this purpose:

- `#garage-header` -- the header line (`tools/garage/app.py`).
- `#tuner-row-name`, `#tuner-range`, `#tuner-dependents`, `#tuner-tabs`,
  `#tuner-explanation`, `#tuner-head-status`, `#tuner-status`,
  `#tuner-revert-all`, `#tuner-row-field` -- the Tuner
  (`tools/garage/panels/tuner.py`). `[changed="true"]` on a row's name
  label and its field container is the changed-row treatment: a left
  accent stripe, following the prototype (`.prow.changed` in
  `garage/index.html`).
- `[role="tuner-head-value"]`, `[role="tuner-revert"]` -- the per-row HEAD
  value and revert button, whose object names are unique per row (so
  cannot be selected by object name alone).
- `#diff-status`, `#diff-file-header`, `#diff-hunk-header`,
  `#diff-untracked-header`, `#diff-untracked-file`, `#diff-line`,
  `#diff-truncated-note`, `#diff-binary-note` -- the diff view
  (`tools/garage/panels/diff_view.py`). `[diffKind="add"|"remove"]` carry
  the colour distinction R19 deliberately left out; the "+ "/"- " prefix
  and bold weight diff_view.py already sets stay as the non-colour cue
  colour alone should never be the only signal.
"""
from __future__ import annotations

from tools.garage.theme.tokens import FONT_INTERFACE, FONT_MONO, TOKENS


def build_stylesheet() -> str:
    t = TOKENS
    return f"""
/* ============================================================
   Base -- every widget, unless a more specific rule below wins.
   ============================================================ */
QWidget {{
    background-color: {t['bg']};
    color: {t['text']};
    font-family: {FONT_INTERFACE};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {t['bg']};
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QLabel {{
    color: {t['text']};
    background-color: transparent;
}}
QToolTip {{
    background-color: {t['surface-2']};
    color: {t['text']};
    border: 1px solid {t['line']};
    padding: 4px 6px;
}}
QMenuBar {{
    background-color: {t['surface']};
    color: {t['text']};
    border-bottom: 1px solid {t['line']};
}}
QMenu {{
    background-color: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {t['accent-soft']};
    color: {t['accent']};
}}

/* ============================================================
   Buttons and spin boxes.
   ============================================================ */
QPushButton {{
    background-color: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    border-radius: 4px;
    padding: 4px 12px;
}}
QPushButton:hover {{
    border-color: {t['text-3']};
}}
QPushButton:pressed {{
    background-color: {t['surface-2']};
}}
QPushButton:disabled {{
    color: {t['text-3']};
    border-color: {t['line-soft']};
}}
QSpinBox {{
    background-color: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    border-radius: 3px;
    /* Right padding clears the 16px-wide up/down button column below (plus
       a small gap) so a long value never runs underneath the buttons. */
    padding: 2px 22px 2px 6px;
    font-family: {FONT_MONO};
}}
QSpinBox:focus {{
    border-color: {t['accent']};
}}
/* Regression fix: once a QSpinBox gets ANY box styling (border/padding/
   background, above) from a stylesheet, Qt stops delegating its up/down
   sub-controls to the native style -- they still exist and still work
   programmatically, but with no rule of their own here they fell back to
   an unstyled, misplaced default box, so the drawn arrows and the actual
   clickable hit region drifted apart (in effect: the field's own left/
   right symmetric padding used to leave no room for them and nothing
   painted a button there at all). These rules give both buttons an
   explicit position and size that matches the padding reserved above, and
   paint an arrow into each one, so what is drawn is exactly what is
   clickable. */
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 16px;
    background-color: {t['surface-2']};
    border-left: 1px solid {t['line']};
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 3px;
    border-bottom: 1px solid {t['line']};
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {t['surface-3']};
}}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
    background-color: {t['accent-soft']};
}}
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{
    background-color: {t['surface']};
}}
/* No image assets exist (and none should be added as binary files) -- the
   arrows are drawn with the CSS zero-size-box-plus-borders triangle
   technique instead. */
QSpinBox::up-arrow {{
    width: 0;
    height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {t['text-2']};
}}
QSpinBox::down-arrow {{
    width: 0;
    height: 0;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {t['text-2']};
}}
QSpinBox::up-arrow:hover {{
    border-bottom-color: {t['text']};
}}
QSpinBox::down-arrow:hover {{
    border-top-color: {t['text']};
}}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{
    border-bottom-color: {t['line']};
}}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {{
    border-top-color: {t['line']};
}}

/* ============================================================
   Header line (tools/garage/app.py).
   ============================================================ */
QLabel#garage-header {{
    background-color: {t['surface-2']};
    border-bottom: 1px solid {t['line']};
    padding: 8px 12px;
}}

/* ============================================================
   Tuner panel (tools/garage/panels/tuner.py).
   ============================================================ */
QLabel#tuner-explanation {{
    color: {t['fail']};
    background-color: {t['fail-soft']};
    border: 1px solid {t['line']};
    border-radius: 4px;
    padding: 10px 12px;
}}
QLabel#tuner-head-status {{
    color: {t['warn']};
    background-color: {t['warn-soft']};
    border: 1px solid {t['line']};
    border-radius: 4px;
    padding: 8px 10px;
}}
QLabel#tuner-status {{
    color: {t['text-2']};
}}
QPushButton#tuner-revert-all {{
    color: {t['accent']};
    border: 1px solid {t['accent-line']};
}}
QPushButton#tuner-revert-all:hover {{
    background-color: {t['accent']};
    color: {t['accent-ink']};
}}

QTabWidget#tuner-tabs::pane {{
    border: 1px solid {t['line']};
    background-color: {t['surface']};
}}
QTabBar::tab {{
    background-color: {t['surface-2']};
    color: {t['text-2']};
    border: 1px solid {t['line']};
    border-bottom: none;
    padding: 6px 14px;
    font-family: {FONT_INTERFACE};
}}
QTabBar::tab:selected {{
    background-color: {t['surface']};
    color: {t['text']};
    font-weight: 600;
    border-bottom: 2px solid {t['accent']};
}}
QTabBar::tab:hover {{
    color: {t['text']};
}}

QLabel#tuner-row-name {{
    font-family: {FONT_MONO};
    color: {t['text']};
}}
QLabel#tuner-row-name[changed="true"] {{
    color: {t['accent']};
    font-weight: 600;
    background-color: {t['accent-soft']};
    border-left: 3px solid {t['accent']};
    padding-left: 6px;
}}
QWidget#tuner-row-field[changed="true"] {{
    background-color: {t['accent-soft']};
    border-left: 3px solid {t['accent']};
    padding-left: 6px;
}}
QLabel#tuner-range {{
    font-family: {FONT_MONO};
    color: {t['text-3']};
}}
QLabel#tuner-dependents {{
    color: {t['text-3']};
}}
QLabel[role="tuner-head-value"] {{
    font-family: {FONT_MONO};
    color: {t['text-2']};
}}
QPushButton[role="tuner-revert"] {{
    color: {t['accent']};
    border: 1px solid {t['accent-line']};
    padding: 2px 8px;
}}
QPushButton[role="tuner-revert"]:hover {{
    background-color: {t['accent']};
    color: {t['accent-ink']};
}}

/* ============================================================
   Diff panel (tools/garage/panels/diff_view.py).
   ============================================================ */
QLabel#diff-status {{
    color: {t['text-2']};
}}
QLabel#diff-truncated-note, QLabel#diff-binary-note {{
    color: {t['text-2']};
}}
QLabel#diff-file-header {{
    font-family: {FONT_MONO};
    color: {t['text']};
}}
QLabel#diff-hunk-header {{
    font-family: {FONT_MONO};
    color: {t['text-2']};
}}
QLabel#diff-untracked-header {{
    color: {t['text']};
}}
QLabel#diff-untracked-file {{
    font-family: {FONT_MONO};
    color: {t['text-2']};
}}
QLabel#diff-line {{
    font-family: {FONT_MONO};
}}
QLabel[diffKind="add"] {{
    color: {t['pass']};
}}
QLabel[diffKind="remove"] {{
    color: {t['fail']};
}}
QLabel[diffKind="context"], QLabel[diffKind="meta"] {{
    color: {t['text-3']};
}}
"""
