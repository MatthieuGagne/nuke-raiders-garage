"""Toolchain verification (R14). Pure and Qt-free, like every module under
tools/garage/core/: it resolves executables through `shutil.which`, reads a
couple of environment variables, looks at the filesystem, and runs each
found tool once with a version flag. Nothing here builds, writes or starts
anything.

R14 names the items to verify: `make`, `gcc`, `GBDK_HOME`, `romusage`, Git
`bin` and `usr\\bin`, `java`, and the Emulicious jar. R17's last sentence
adds one more -- "a binding that no longer resolves" is reported here as a
toolchain failure rather than only inside the panels that trip over it --
so `run_checks` takes the binding (or the error that replaced it) and
reports it as the first check.

Two rules shape every check below.

**A missing item is a failure, never a degradation.** R14 exists because
`make bank-post-build` resolves `romusage` through `shutil.which` and exits
2 with a FileNotFoundError when it is absent: the gate cannot run, so it
never fails, so a real bank overflow stays invisible. That condition hid
gmb-nuke-raider#461 for months. Nothing here therefore returns a "probably
fine" status -- a check either passes or fails.

**A failure names what it prevents.** A report that says `romusage: FAIL`
tells the user a string is missing from PATH; `prevents` tells them which
part of their own loop just stopped working, which is the thing they
actually need to decide whether to fix it now (AC14).

The seams (`which`, `environ`, `probe_version`) exist so the whole module
is testable on a machine that has none of these tools -- or all of them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from tools.garage.core import config_io, project
from tools.garage.core.project import Binding, BindingError
from tools.garage.core.schema import Schema, SchemaError, find_drift

PASS = "PASS"
FAIL = "FAIL"

# Where Emulicious lives unless the user says otherwise. Overridden by
# `emulicious_jar` in garage.local.json, then by the EMULICIOUS_JAR
# environment variable -- see `resolve_emulicious_jar`.
DEFAULT_EMULICIOUS_JAR = "C:/Tools/Emulicious/Emulicious.jar"
EMULICIOUS_JAR_ENV = "EMULICIOUS_JAR"
EMULICIOUS_JAR_SETTING = "emulicious_jar"

# How long any single `--version` call may take before it is treated as no
# answer at all. A version string is decoration on a check that has already
# passed (the executable was resolved), so a hung probe must never hold the
# window shut -- it just loses the version.
VERSION_TIMEOUT_S = 5

# The first dotted-number token of a version banner: "GNU Make 4.4.1",
# 'openjdk version "25.0.3"', "version 1.3.2, by bbbbbr".
_VERSION_RE = re.compile(r"\b(\d+(?:\.\d+)+)")


@dataclass
class CheckResult:
    """One line of the report.

    `key` is stable and machine-readable (tests and panels select on it);
    `name` is what the user reads. `detail` carries the resolved path when
    the check passed and the reason when it failed -- the thing to fix.
    `prevents` is empty on a pass and names the lost capability on a
    failure. `tag` is the short right-hand annotation (a version, "on
    PATH"), decoration only, and may be empty.
    """

    key: str
    name: str
    status: str
    detail: str
    prevents: str = ""
    tag: str = ""

    @property
    def failed(self) -> bool:
        return self.status == FAIL


@dataclass
class Report:
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if c.failed]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def pass_count(self) -> int:
        return self.total - len(self.failures)

    def summary(self) -> str:
        """One line, the same shape whether it passes or fails, with the
        failing check names appended so the summary alone is actionable
        (the window shows it without the report open).
        """
        head = f"{self.pass_count} of {self.total} checks passing"
        failures = self.failures
        if not failures:
            return head
        return head + " · failing: " + ", ".join(c.key for c in failures)


# -- probes ------------------------------------------------------------------


def probe_version(command: List[str]) -> str:
    """Run `command` and return the first dotted-number token of its
    output, or "" when the tool cannot be run, is too slow, or prints no
    version. Java writes its banner to stderr, GNU tools to stdout, so
    both streams are read.

    Never raises: a version is decoration on a check that already passed.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    match = _VERSION_RE.search(text)
    return match.group(1) if match else ""


VersionProbe = Callable[[List[str]], str]
Which = Callable[[str], Optional[str]]


# -- individual checks -------------------------------------------------------


def check_binding(
    binding: Optional[Binding], binding_error: Optional[BindingError]
) -> CheckResult:
    """R17: a recorded game repository that no longer resolves is a
    toolchain failure, not a silent re-detection. Everything else Garage
    does resolves against this path, so it is reported first.
    """
    if binding is not None:
        return CheckResult(
            key="game-repo",
            name="Game repository — every path Garage resolves",
            status=PASS,
            detail=str(binding.active_worktree.path),
            tag=binding.game_repo_source,
        )
    detail = (
        f"{binding_error.key}: {binding_error.message}"
        if binding_error is not None
        else "No game repository is bound."
    )
    return CheckResult(
        key="game-repo",
        name="Game repository — every path Garage resolves",
        status=FAIL,
        detail=detail,
        prevents=(
            "Everything. The Tuner cannot read src/config.h, the diff has "
            "no worktree to read, and no make call or emulator start has a "
            "directory to run in."
        ),
        tag="blocked",
    )


def check_classification(
    binding: Optional[Binding], schema: Optional[Schema] = None
) -> CheckResult:
    """R8/AC9: the classification file is the single source of truth, and
    Garage reports its drift when it starts.

    The same comparison fails this repository's test suite
    (`tools/garage_lint.py`), which is the half that catches drift in CI.
    This half catches it in the one place the user is standing when it
    matters — a `#define` added to the game repository since Garage last
    ran is a value the Tuner silently does not offer, and silence is
    exactly what R8 exists to end.
    """
    name = "tunables.json — the classification of src/config.h"
    if binding is None:
        return CheckResult(
            key="classification",
            name=name,
            status=FAIL,
            detail="no game repository is bound, so the header cannot be read",
            prevents=(
                "The drift check. Garage cannot tell whether tunables.json "
                "still describes src/config.h."
            ),
            tag="blocked",
        )
    try:
        # `schema` is a seam for the tests: a real run reads the one
        # classification file this repository ships.
        schema = schema if schema is not None else Schema.load()
        config = config_io.read(binding, schema)
    except (SchemaError, config_io.ConfigIOError, OSError) as exc:
        return CheckResult(
            key="classification",
            name=name,
            status=FAIL,
            detail=str(exc),
            prevents=(
                "Every tunable. The Tuner has no classification to work "
                "from, so it can offer nothing."
            ),
            tag="blocked",
        )

    drift = find_drift(schema, config.defines.keys())
    if drift.clean:
        return CheckResult(
            key="classification",
            name=name,
            status=PASS,
            detail=f"{len(config.defines)} #defines, all classified",
            tag="in step",
        )

    details = []
    if drift.unclassified:
        details.append("unclassified in tunables.json: " + ", ".join(drift.unclassified))
    if drift.stale:
        details.append("gone from src/config.h: " + ", ".join(drift.stale))
    return CheckResult(
        key="classification",
        name=name,
        status=FAIL,
        detail=" · ".join(details),
        prevents=(
            "The Tuner does not offer an unclassified #define, and says "
            "nothing about it — the drift has to be fixed in tunables.json "
            "before that value can be tuned. This repository's test suite "
            "fails until it is."
        ),
        tag=drift.summary(),
    )


def check_make(which: Which, probe: VersionProbe) -> CheckResult:
    path = which("make")
    if path:
        return CheckResult(
            key="make",
            name="make — every build target",
            status=PASS,
            detail=path,
            tag=probe([path, "--version"]),
        )
    return CheckResult(
        key="make",
        name="make — every build target",
        status=FAIL,
        detail="not found on PATH",
        prevents=(
            "Every target: the compile, make clean, make memory-check and "
            "make bank-post-build. Garage's compile panel has nothing to run."
        ),
        tag="blocked",
    )


def check_gcc(which: Which, probe: VersionProbe) -> CheckResult:
    path = which("gcc")
    if path:
        return CheckResult(
            key="gcc",
            name="gcc — host test suite",
            status=PASS,
            detail=path,
            tag=probe([path, "--version"]),
        )
    return CheckResult(
        key="gcc",
        name="gcc — host test suite",
        status=FAIL,
        detail="not found on PATH",
        prevents=(
            "The game repository's host tests (make test), which compile "
            "with gcc rather than the GBDK toolchain. The pre-commit "
            "verification runs them."
        ),
        tag="blocked",
    )


def check_gbdk_home(environ) -> CheckResult:
    """GBDK_HOME must name a directory holding `bin/lcc` -- the compiler
    driver the game repository's Makefile calls as `$(GBDK_HOME)/bin/lcc`.
    A variable that is set but points somewhere without lcc fails the same
    way an unset one does, and says which of the two it is.
    """
    name = "GBDK_HOME — the Game Boy compiler"
    raw = environ.get("GBDK_HOME")
    prevents = (
        "The ROM compile. The Makefile calls $(GBDK_HOME)/bin/lcc, so make "
        "stops at the first source file."
    )
    if not raw:
        return CheckResult(
            key="gbdk-home",
            name=name,
            status=FAIL,
            detail="not set",
            prevents=prevents,
            tag="blocked",
        )
    root = Path(raw)
    lcc = _first_existing(root / "bin" / "lcc", root / "bin" / "lcc.exe")
    if lcc is None:
        return CheckResult(
            key="gbdk-home",
            name=name,
            status=FAIL,
            detail=f"{raw} holds no bin/lcc",
            prevents=prevents,
            tag="blocked",
        )
    if "\\" in raw:
        # Found by building, not by this check: `C:\gbdk` passes every test
        # above -- Python resolves either separator, so bin/lcc is right
        # there -- and still cannot compile a single file. The Makefile
        # interpolates the variable as `$(GBDK_HOME)/bin/lcc` and runs the
        # recipe under `SHELL := bash`, where `\g` is an escape sequence:
        # bash reads `C:gbdk/bin/lcc` and exits 127. Verifying that a tool
        # exists is not the same as verifying the build can use it.
        return CheckResult(
            key="gbdk-home",
            name=name,
            status=FAIL,
            detail=(
                f"{raw} uses backslashes — set it to "
                f"{raw.replace(chr(92), '/')} instead"
            ),
            prevents=(
                "Every compile. The Makefile expands this into "
                "$(GBDK_HOME)/bin/lcc and runs it under bash, which reads a "
                "backslash as an escape: the compile resolves a mangled "
                "path and exits 127 on the first source file."
            ),
            tag="blocked",
        )
    return CheckResult(
        key="gbdk-home", name=name, status=PASS, detail=str(lcc), tag=raw
    )


def check_romusage(which: Which, environ, probe: VersionProbe) -> CheckResult:
    """AC14. `tools/bank_post_build.py` in the game repository resolves
    romusage through `shutil.which`, so PATH -- not GBDK_HOME -- is what
    decides whether the bank budget can be measured. When it is missing and
    GBDK_HOME does hold it, the detail names that directory, since adding
    it to PATH is the whole fix.
    """
    name = "romusage — ROM bank budgets"
    path = which("romusage")
    if path:
        return CheckResult(
            key="romusage",
            name=name,
            status=PASS,
            detail=path,
            tag=probe([path]),
        )
    detail = "not found on PATH"
    gbdk_home = environ.get("GBDK_HOME")
    if gbdk_home:
        shipped = _first_existing(
            Path(gbdk_home) / "bin" / "romusage",
            Path(gbdk_home) / "bin" / "romusage.exe",
        )
        if shipped is not None:
            detail += f" — add {shipped.parent}"
    return CheckResult(
        key="romusage",
        name=name,
        status=FAIL,
        detail=detail,
        prevents=(
            "The ROM bank budget check. make bank-post-build exits 2 with a "
            "FileNotFoundError instead of reporting a result, so a bank "
            "overflow is never reported — the condition that hid "
            "gmb-nuke-raider#461 for months."
        ),
        tag="blocked",
    )


def check_git_unix_tools(which: Which) -> CheckResult:
    """Git for Windows ships bash in `bin` and the GNU coreutils in
    `usr\\bin`. The game repository's Makefile sets `SHELL := bash` and its
    recipes call those utilities, so both directories have to be on PATH --
    `bash` and `sed` are the two representatives resolved here, one per
    directory.
    """
    name = "Git bash + coreutils — every make recipe"
    prevents = (
        "Every make recipe. The game repository's Makefile sets SHELL := "
        "bash and its recipes call the GNU coreutils; without them make "
        "fails before it compiles anything."
    )
    bash = which("bash")
    sed = which("sed")
    missing = [n for n, p in (("bash", bash), ("sed", sed)) if not p]
    if missing:
        return CheckResult(
            key="git-unix-tools",
            name=name,
            status=FAIL,
            detail=f"not found on PATH: {', '.join(missing)}",
            prevents=prevents,
            tag="blocked",
        )
    directories = _unique_parents([bash, sed])
    return CheckResult(
        key="git-unix-tools",
        name=name,
        status=PASS,
        detail=";".join(directories),
        tag="on PATH",
    )


def check_java(which: Which, probe: VersionProbe) -> CheckResult:
    path = which("java")
    if path:
        return CheckResult(
            key="java",
            name="java — runs Emulicious",
            status=PASS,
            detail=path,
            tag=probe([path, "-version"]),
        )
    return CheckResult(
        key="java",
        name="java — runs Emulicious",
        status=FAIL,
        detail="not found on PATH",
        prevents=(
            "Starting the emulator. Emulicious is a jar, so a compiled ROM "
            "cannot be run from Garage."
        ),
        tag="blocked",
    )


def resolve_emulicious_jar(settings: Optional[dict], environ) -> Path:
    """Where the jar is expected: garage.local.json's `emulicious_jar`
    first (the file the user owns and can edit), then EMULICIOUS_JAR, then
    the default install path.
    """
    if settings:
        recorded = settings.get(EMULICIOUS_JAR_SETTING)
        if recorded:
            return Path(recorded)
    from_env = environ.get(EMULICIOUS_JAR_ENV)
    if from_env:
        return Path(from_env)
    return Path(DEFAULT_EMULICIOUS_JAR)


def check_emulicious(settings: Optional[dict], environ) -> CheckResult:
    name = "Emulicious — the emulator"
    jar = resolve_emulicious_jar(settings, environ)
    if jar.is_file():
        return CheckResult(
            key="emulicious", name=name, status=PASS, detail=str(jar), tag="ok"
        )
    return CheckResult(
        key="emulicious",
        name=name,
        status=FAIL,
        detail=(
            f"no jar at {jar} — set '{EMULICIOUS_JAR_SETTING}' in "
            f"garage.local.json"
        ),
        prevents=(
            "Starting the emulator. A ROM can still be compiled; it cannot "
            "be run from Garage."
        ),
        tag="blocked",
    )


# -- the run -----------------------------------------------------------------


def run_checks(
    binding: Optional[Binding] = None,
    binding_error: Optional[BindingError] = None,
    *,
    which: Which = shutil.which,
    environ=None,
    settings: Optional[dict] = None,
    probe: VersionProbe = probe_version,
) -> Report:
    """Every check R14 asks for, in the order the user should read them:
    the binding first (nothing else resolves without it), then the build
    chain, then the emulator.

    The seams default to the real environment; a caller that passes its own
    `which`/`environ`/`probe` gets a report about that environment instead,
    which is how this is tested without depending on the host's PATH.

    `settings` defaults to the bound repository's own garage.local.json, so
    a caller that has a binding never has to load that file itself just to
    let the user record where the Emulicious jar lives.
    """
    if environ is None:
        environ = os.environ
    if settings is None:
        settings = load_binding_settings(binding)
    return Report(
        checks=[
            check_binding(binding, binding_error),
            check_classification(binding),
            check_make(which, probe),
            check_gcc(which, probe),
            check_gbdk_home(environ),
            check_romusage(which, environ, probe),
            check_git_unix_tools(which),
            check_java(which, probe),
            check_emulicious(settings, environ),
        ]
    )


# -- helpers -----------------------------------------------------------------


def load_binding_settings(binding: Optional[Binding]) -> Optional[dict]:
    """The bound repository's garage.local.json, or None when there is no
    binding or the file cannot be read. A settings file that is missing or
    malformed is not itself a toolchain failure -- every key it can carry
    has a default -- so this never raises.
    """
    if binding is None:
        return None
    try:
        return project.load_settings(binding.settings_path.parent)
    except (OSError, ValueError):
        return None


def _first_existing(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _unique_parents(paths: List[str]) -> List[str]:
    """The directories the given executables were resolved from, in order,
    without repeating one (bash and sed can live in the same directory).
    """
    seen: List[str] = []
    for path in paths:
        parent = str(Path(path).parent)
        if parent not in seen:
            seen.append(parent)
    return seen
