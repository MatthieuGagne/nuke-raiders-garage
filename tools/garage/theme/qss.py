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
- `#garage-toolchain-status` -- the one-line toolchain failure notice under
  the header (`tools/garage/app.py`), shown only when a check failed.
- `#worktrees-row`, `#worktrees-row-label`, `#worktrees-status`,
  `#worktrees-branch-field` -- the worktrees panel
  (`tools/garage/panels/worktrees.py`); `[active="true"]` is the active
  row's accent stripe.
- `#budgets-panel`, `#budgets-title`, `#budgets-status`, `#budgets-name`,
  `#budgets-value`, `#budgets-meter`, `#budgets-verdict`, `#budgets-hint`,
  `#budgets-scene`, `#budgets-scenes-title` -- the budgets aside
  (`tools/garage/panels/budgets.py`). `[status="pass"|"warn"|"fail"|
  "blocked"]` colours the meter's chunk and the verdict chip;
  `[peak="true"]` marks the scene that decides the OAM verdict.
- `#compile-controls`, `#compile-dot`, `#compile-status`, `#compile-log`
  and the `[role="primary"|"danger"]` buttons -- the compile bar
  (`tools/garage/panels/compile_bar.py`). `[state="busy"|"pass"|"fail"]` on
  the dot is the run's state; the status line beside it says the same in
  words, so the dot is never the only signal.
- `#doctor-summary`, `#doctor-check-row`, `#doctor-verdict`,
  `#doctor-check-name`, `#doctor-check-detail`, `#doctor-check-tag`,
  `#doctor-check-prevents` -- the Doctor panel
  (`tools/garage/panels/doctor.py`). `[verdict="pass"|"fail"]` carries the
  PASS/FAIL colour vocabulary the prototype's `.check` rows declare; the
  chip also spells the word out, so colour is never the only signal.
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
/* The prototype is a web page and never declares a scrollbar, so these
   take the surface/line tokens directly. Without them Qt paints the native
   light Windows scrollbar, which is the one bright rectangle in an
   otherwise dark window -- visible in any panel long enough to scroll (the
   Doctor, the diff, a long Tuner tab). */
QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {t['bg']};
    border: none;
    margin: 0;
}}
QScrollBar:vertical {{
    width: 10px;
}}
QScrollBar:horizontal {{
    height: 10px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: {t['surface-3']};
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    min-height: 24px;
}}
QScrollBar::handle:horizontal {{
    min-width: 24px;
}}
QScrollBar::handle:hover {{
    background-color: {t['line']};
}}
/* No stepper buttons: the arrows would need their own painted glyphs, and
   a 10px track has no room for them. Zeroing both the buttons and the
   page-area background leaves the track and the handle, nothing else. */
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background-color: transparent;
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
   Worktrees panel (tools/garage/panels/worktrees.py). One row
   per worktree, the active one carrying the prototype's left
   accent stripe (`table.grid tr.active-wt`).
   ============================================================ */
QFrame#worktrees-row {{
    background-color: {t['surface']};
    border: 1px solid {t['line-soft']};
    border-radius: 4px;
}}
QFrame#worktrees-row[active="true"] {{
    background-color: {t['accent-soft']};
    border-left: 3px solid {t['accent']};
}}
QLabel#worktrees-row-label {{
    font-family: {FONT_MONO};
    color: {t['text-2']};
}}
QFrame#worktrees-row[active="true"] QLabel#worktrees-row-label {{
    color: {t['text']};
}}
QLabel#worktrees-status {{
    color: {t['text-2']};
}}
QLineEdit#worktrees-branch-field {{
    background-color: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    border-radius: 3px;
    padding: 4px 8px;
    font-family: {FONT_MONO};
}}
QLineEdit#worktrees-branch-field:focus {{
    border-color: {t['accent']};
}}

/* ============================================================
   Budgets aside (tools/garage/panels/budgets.py). The
   prototype's meter: name and numbers, a 6px bar coloured by
   result, then the verdict chip and a hint.
   ============================================================ */
QWidget#budgets-panel {{
    background-color: {t['surface']};
    border-left: 1px solid {t['line']};
}}
QLabel#budgets-title, QLabel#budgets-scenes-title {{
    color: {t['text-3']};
    font-weight: 600;
    /* The prototype's section label: small, spaced, upper case. */
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel#budgets-status {{
    color: {t['text-2']};
}}
QLabel#budgets-name {{
    color: {t['text']};
    font-weight: 600;
}}
QLabel#budgets-value, QLabel#budgets-hint {{
    font-family: {FONT_MONO};
    color: {t['text-3']};
}}
QProgressBar#budgets-meter {{
    background-color: {t['surface-3']};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar#budgets-meter::chunk {{
    border-radius: 3px;
    background-color: {t['text-3']};
}}
QProgressBar#budgets-meter[status="pass"]::chunk {{
    background-color: {t['pass']};
}}
QProgressBar#budgets-meter[status="warn"]::chunk {{
    background-color: {t['warn']};
}}
QProgressBar#budgets-meter[status="fail"]::chunk {{
    background-color: {t['fail']};
}}
QProgressBar#budgets-meter[status="blocked"]::chunk {{
    background-color: {t['line']};
}}
QLabel#budgets-verdict {{
    font-family: {FONT_MONO};
    font-size: 10px;
    letter-spacing: 1px;
    border-radius: 2px;
    padding: 1px 6px;
}}
QLabel#budgets-verdict[status="pass"] {{
    color: {t['pass']};
    background-color: {t['pass-soft']};
}}
QLabel#budgets-verdict[status="warn"] {{
    color: {t['warn']};
    background-color: {t['warn-soft']};
}}
QLabel#budgets-verdict[status="fail"] {{
    color: {t['fail']};
    background-color: {t['fail-soft']};
}}
QLabel#budgets-verdict[status="blocked"] {{
    color: {t['text-3']};
    background-color: {t['surface-3']};
}}
QLabel#budgets-scene {{
    font-family: {FONT_MONO};
    color: {t['text-3']};
}}
QLabel#budgets-scene[peak="true"] {{
    color: {t['warn']};
    font-weight: 600;
}}

/* ============================================================
   Compile bar (tools/garage/panels/compile_bar.py). The
   prototype's build bar: a controls row on `surface-2` above a
   log on `bg`, both pinned to the bottom of the window.
   ============================================================ */
QWidget#compile-controls {{
    background-color: {t['surface-2']};
    border-top: 1px solid {t['line']};
}}
QPushButton[role="primary"] {{
    background-color: {t['accent']};
    border-color: {t['accent']};
    color: {t['accent-ink']};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background-color: {t['accent-line']};
    border-color: {t['accent']};
    color: {t['text']};
}}
QPushButton[role="danger"] {{
    color: {t['fail']};
    border-color: {t['fail']};
}}
QPushButton[role="danger"]:hover {{
    background-color: {t['fail-soft']};
}}
QPushButton[role="primary"]:disabled, QPushButton[role="danger"]:disabled {{
    background-color: {t['surface']};
    color: {t['text-3']};
    border-color: {t['line-soft']};
}}
/* The status dot: a fixed 8px square with a full radius. Qt has no
   aspect-ratio rule, so both dimensions are pinned rather than left to the
   label's (empty) text to size. */
QLabel#compile-dot {{
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background-color: {t['text-3']};
}}
QLabel#compile-dot[state="busy"] {{
    background-color: {t['accent']};
}}
QLabel#compile-dot[state="pass"] {{
    background-color: {t['pass']};
}}
QLabel#compile-dot[state="fail"] {{
    background-color: {t['fail']};
}}
QLabel#compile-status {{
    font-family: {FONT_MONO};
    color: {t['text-2']};
}}
QPlainTextEdit#compile-log {{
    background-color: {t['bg']};
    color: {t['text-2']};
    font-family: {FONT_MONO};
    border: none;
    border-top: 1px solid {t['line']};
    padding: 6px 10px;
}}

/* ============================================================
   Toolchain notice under the header (tools/garage/app.py).
   ============================================================ */
QLabel#garage-toolchain-status {{
    color: {t['fail']};
    background-color: {t['fail-soft']};
    border-bottom: 1px solid {t['line']};
    padding: 6px 12px;
    font-family: {FONT_MONO};
}}

/* ============================================================
   Doctor panel (tools/garage/panels/doctor.py). Follows the
   prototype's `.checks` list: one surface row per check, a soft
   fail background on a failing row, a PASS/FAIL chip on the left
   and the resolved path in the monospace face underneath.
   ============================================================ */
QLabel#doctor-summary {{
    color: {t['text-2']};
    padding: 2px 0 6px 0;
}}
QFrame#doctor-check-row {{
    background-color: {t['surface']};
    border: 1px solid {t['line']};
    border-radius: 5px;
}}
QFrame#doctor-check-row[verdict="fail"] {{
    background-color: {t['fail-soft']};
    border-color: {t['fail']};
}}
QLabel#doctor-verdict {{
    font-family: {FONT_MONO};
    font-weight: 600;
    border-radius: 3px;
    padding: 2px 6px;
    /* The chip is the same width for PASS and FAIL, so the names beside
       it line up down the column. */
    min-width: 34px;
    qproperty-alignment: AlignCenter;
}}
QLabel#doctor-verdict[verdict="pass"] {{
    color: {t['pass']};
    background-color: {t['pass-soft']};
}}
QLabel#doctor-verdict[verdict="fail"] {{
    color: {t['fail']};
    background-color: {t['fail-soft']};
}}
QLabel#doctor-check-name {{
    color: {t['text']};
    font-weight: 600;
}}
QLabel#doctor-check-detail {{
    font-family: {FONT_MONO};
    color: {t['text-3']};
}}
QLabel#doctor-check-detail[verdict="fail"] {{
    color: {t['fail']};
}}
QLabel#doctor-check-tag {{
    font-family: {FONT_MONO};
    color: {t['text-3']};
}}
QLabel#doctor-check-tag[verdict="fail"] {{
    color: {t['fail']};
}}
QLabel#doctor-check-prevents {{
    color: {t['text-2']};
    border-left: 3px solid {t['fail']};
    padding-left: 8px;
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
