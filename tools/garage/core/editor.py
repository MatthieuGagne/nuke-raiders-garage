"""Opening a directory of the game repository in VS Code (issue #43).

No Qt import belongs in this module or anywhere under tools/garage/core/
(R9): everything here is testable with no display and, through the two
seams below, with no editor.

**This module names an editor, and it is the only one that may.**
`core/assets.py::open_in_default_app` records the opposite rule -- which
program opens a `.png` or a `.uge` is the user's choice, recorded in
Windows -- and that rule is untouched. It holds for a *file* and breaks
for a *directory*: a directory has one association, Explorer, and Explorer
is not an editor. Naming the editor is the only way to hand a folder to
one, so #43 R3 makes this button the stated exception and
`tests/test_garage_editor.py::TestTheExceptionIsScoped` keeps the
exception one module wide.

**The name, not a path.** `code` is resolved on PATH rather than spelled
as an absolute path to the executable: the install location varies (user,
system, portable) and `code` is what an install puts on PATH and what
survives an upgrade. On Windows PATH holds `code.CMD`; `shutil.which`
finds it through PATHEXT and `subprocess.Popen` runs it without a shell.

**Two seams, not one** (R9). `_spawn` is "do not really launch";
`_find_editor` is "pretend PATH has no code", which the not-found test
(R4/AC2) needs on a developer machine where it does.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

# What the user is told, and what Garage looks for. Two constants because
# they are two different things: the product's name, and the command an
# install puts on PATH.
EDITOR_NAME = "VS Code"
EDITOR_COMMAND = "code"


class EditorError(Exception):
    """The editor could not be started. Carries `.message` so the panel
    shows a sentence rather than a traceback (R4).
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _find_editor() -> Optional[str]:
    """Where PATH says `code` is, or None. A seam (R9)."""
    return shutil.which(EDITOR_COMMAND)


def _spawn(argv: List[str]) -> None:
    """Start `argv` and return immediately (R5). A seam (R9).

    `Popen`, never `run`: Garage must not block until the editor is
    closed, and it never learns what the user does in it.

    CREATE_NO_WINDOW keeps the `code.CMD` shim from flashing a console
    window on Windows; the flag does not exist elsewhere, and 0 is the
    no-op value `Popen` accepts on every platform.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(argv, creationflags=creationflags)


def open_directory(path: Path) -> None:
    """Open `path` as a folder in the editor (R3).

    Raises `EditorError` when the directory is not there, when PATH holds
    no `code`, or when the launch itself fails. There is no fallback and
    no second editor: a machine without it gets the message, not another
    program (R4).
    """
    path = Path(path)
    if not path.is_dir():
        raise EditorError(
            f"'{path}' is not a directory, so there is nothing to open in "
            f"{EDITOR_NAME}."
        )
    executable = _find_editor()
    if executable is None:
        raise EditorError(
            f"{EDITOR_NAME} was not found on PATH: no '{EDITOR_COMMAND}' "
            f"command resolves there. Install {EDITOR_NAME}, or add its "
            f"bin directory to PATH — Garage opens no other editor."
        )
    try:
        _spawn([executable, str(path)])
    except OSError as exc:
        raise EditorError(
            f"{EDITOR_NAME} did not start from '{executable}': {exc}."
        ) from exc
