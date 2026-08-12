"""The dark token set (R18), copied from the `:root[data-theme="dark"]`
block of `garage/index.html` -- the design source for Garage's appearance
(https://matthieugagne.github.io/nuke-raiders-garage/garage/). The user
decided Garage ships dark and nothing else, so only that set is taken; the
prototype's light tokens are reference material with no obligation here
(see the spec's "Out of Scope": "A light theme").

Every value below is named once. `tools/garage/theme/qss.py` builds the
whole stylesheet by looking values up in `TOKENS`, never by repeating a
hex literal -- and nothing outside this package may hold a colour literal
at all (AC18).

No Qt import here, and none belongs here: this module is data, read by
`qss.py` (Qt-adjacent, but still no widgets) and, for the two colour
lookups the header line needs, by `tools/garage/app.py`.
"""
from __future__ import annotations

TOKENS = {
    "bg": "#0E120F",
    "surface": "#171C18",
    "surface-2": "#1E241F",
    "surface-3": "#272E28",
    "line": "#343C35",
    "line-soft": "#242B25",
    "text": "#E6EAE2",
    "text-2": "#A6AFA5",
    "text-3": "#79837A",
    "accent": "#D2683F",
    "accent-ink": "#1A0E08",
    "accent-soft": "#2C1D15",
    "accent-line": "#573224",
    "pass": "#86B45A",
    "warn": "#D9AE3C",
    "fail": "#E0647C",
    "pass-soft": "#1D2717",
    "warn-soft": "#2C2412",
    "fail-soft": "#2E1720",
}

# The prototype's typography split (garage/index.html `body` / `.mono`):
# a proportional interface face for prose and labels, a monospace face for
# values, paths, counts and status. Qt Style Sheets accept a comma
# separated font-family list the same way CSS does.
FONT_INTERFACE = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
FONT_MONO = '"Cascadia Mono", "Cascadia Code", Consolas, monospace'
