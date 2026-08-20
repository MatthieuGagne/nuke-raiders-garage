"""Read and write the game repository's `src/config.h` through a Binding.

No Qt import belongs in this module or anywhere under tools/garage/core/.

R7 / R10: Garage may only ever change the value token of a `tunable`
#define, and must otherwise leave `src/config.h` byte-identical -- same
comments, same order, same blank lines, same indentation, same trailing-
comment column. A write of zero changes must reproduce the original file
exactly. Writing a `structural`, `derived` or `marker` entry is refused
(raises), never silently skipped.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .project import Binding
from .schema import Schema, SchemaError

# Matches a #define line that carries a literal integer value (decimal or
# hex), optionally suffixed with a 'u'/'U', followed by whatever else is on
# the line (whitespace and/or a trailing comment). Lines whose value is an
# expression (derived #defines) or that carry no value at all (markers)
# simply do not match this and are left untouched.
#
# re.DOTALL so the trailing "$" group ("tail") captures a line's own
# closing "\n" too: raw_line is always a single line (as split by
# str.splitlines(keepends=True)), so without DOTALL "." stops just before
# that final "\n" and $ matches ahead of it, silently dropping the
# newline from every edited line -- apply_changes would then run the
# edited line into the next one instead of preserving line breaks.
_DEFINE_VALUE_RE = re.compile(
    r"^(?P<prefix>#define[ \t]+(?P<name>\w+)[ \t]+)"
    r"(?P<value>0[xX][0-9a-fA-F]+|\d+)"
    r"(?P<suffix>[uU]?)"
    r"(?P<tail>.*)$",
    re.DOTALL,
)

# Matches any #define line, value or not, to find its name.
_DEFINE_NAME_RE = re.compile(r"^#define[ \t]+(?P<name>\w+)\b")

# A two-sided range guard: the `#if` a header uses to fail its own build
# when a #define leaves its legal range, e.g. (src/config.h:40)
#
#   #if (PLAYER_HANDLING) < 0 || (PLAYER_HANDLING) > 7
#   #error "PLAYER_HANDLING must be 0-7 (it indexes ...)"
#   #endif
#
# Recognized with or without parentheses, in either order, with `<`/`<=`
# and `>`/`>=`, and with decimal or hex literals carrying an optional u/U
# suffix. Anything else -- `#if defined(...)`, a one-sided comparison, a
# condition naming two different #defines -- is not a range guard and is
# left unparsed: #18 R4 asks an unrecognized guard to be skipped in
# silence rather than reported.
#
# `#ifdef`/`#ifndef` do not match: the pattern requires whitespace right
# after `if`, so the include guard is never mistaken for a range guard.
_GUARD_IF_RE = re.compile(r"^[ \t]*#[ \t]*if[ \t]+(?P<condition>.+?)[ \t]*$")
_GUARD_HALF_RE = re.compile(
    r"^\(?[ \t]*(?P<name>\w+)[ \t]*\)?[ \t]*"
    r"(?P<op><=?|>=?)[ \t]*"
    r"\(?[ \t]*(?P<literal>-?(?:0[xX][0-9a-fA-F]+|\d+))[uU]?[ \t]*\)?$"
)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/")


@dataclass(frozen=True)
class GuardRange:
    """The legal range a `#if ... #error` guard in config.h permits.

    `min` and `max` are inclusive and already normalized: `#if X <= -1`
    records min 0, because -1 is what the guard rejects.
    """

    name: str
    min: int
    max: int
    line_no: int  # 1-based, the `#if` line
    raw_line: str


def _strip_balanced_outer_parens(text: str) -> str:
    """Strip one balanced outer parenthesis pair from `text`, if it has
    one: `text` starts with `(`, ends with `)`, and that opening paren is
    the one the closing paren matches.

    Not just `text[0] == "(" and text[-1] == ")"` -- that would also
    strip (and mangle) something like `"(A) < (B)"`, whose leading `(`
    closes well before the end of the string. Scanning depth is what
    tells the two apart.
    """
    if len(text) < 2 or text[0] != "(" or text[-1] != ")":
        return text
    depth = 0
    for idx, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                # The opening paren at index 0 closes here. Only a strip
                # when that close is also the final character -- i.e. the
                # parens truly wrap the whole string.
                return text[1:-1] if idx == len(text) - 1 else text
    return text


def _parse_guard_half(half: str) -> Optional[Tuple[str, str, int]]:
    """`(name, operator, literal)` for one side of the `||`, or None."""
    stripped = _strip_balanced_outer_parens(half.strip())
    match = _GUARD_HALF_RE.match(stripped)
    if match is None:
        return None
    text = match.group("literal")
    base = 16 if "x" in text.lower() else 10
    return match.group("name"), match.group("op"), int(text, base)


def parse_guard_condition(condition: str) -> Optional[Tuple[str, int, int]]:
    """Read `(name, min, max)` out of a two-sided range-guard condition.

    Returns None for anything that is not one -- see `_GUARD_IF_RE`. An
    empty legal range (`X < 8 || X > 7`) is treated as unreadable rather
    than reported: a header that says that is broken in its own right,
    and this check's job is to compare ranges, not to review C.
    """
    condition = _BLOCK_COMMENT_RE.sub(" ", condition).split("//")[0]
    halves = condition.split("||")
    if len(halves) != 2:
        return None

    name: Optional[str] = None
    lower: Optional[int] = None
    upper: Optional[int] = None
    for half in halves:
        parsed = _parse_guard_half(half)
        if parsed is None:
            return None
        half_name, op, value = parsed
        if name is None:
            name = half_name
        elif half_name != name:
            return None
        if op.startswith("<"):
            if lower is not None:
                return None
            # `< L` rejects everything below L, so L is legal; `<= L`
            # rejects L itself, so the first legal value is L + 1.
            lower = value if op == "<" else value + 1
        else:
            if upper is not None:
                return None
            upper = value if op == ">" else value - 1

    if name is None or lower is None or upper is None or lower > upper:
        return None
    return name, lower, upper


class ConfigIOError(Exception):
    """Raised on a refused write (non-tunable target) or an I/O failure."""


@dataclass(frozen=True)
class DefineLine:
    """One `#define` as found in `src/config.h`."""

    name: str
    line_no: int  # 1-based
    raw_line: str  # the exact original line text, including its terminator
    cls: Optional[str]  # classification from the schema, or None if unclassified
    has_value: bool  # True when the line carries a parseable literal value
    value: Optional[int] = None  # the literal's integer value, if has_value
    value_text: Optional[str] = None  # e.g. "4u", "0xDF80U", "32" -- as written


@dataclass
class ConfigFile:
    """A parsed `src/config.h`: the exact original lines plus an index of
    every #define found in it. `lines` joined back together always
    reproduces the original text exactly when nothing has changed.

    `guards` indexes the two-sided `#if ... #error` range guards the
    header declares, by the #define name each one constrains. Most
    #defines have none; those simply do not appear (#18 R4).
    """

    path: Path
    lines: List[str]
    defines: Dict[str, DefineLine]
    guards: Dict[str, GuardRange] = field(default_factory=dict)

    def text(self) -> str:
        return "".join(self.lines)


def parse(text: str, schema: Optional[Schema] = None, path: Optional[Path] = None) -> ConfigFile:
    """Parse `text` (the content of a config.h) into a ConfigFile.

    Pure and testable without touching disk. `schema`, when given, supplies
    each define's classification; unclassified names get cls=None.
    """
    lines = text.splitlines(keepends=True)
    defines: Dict[str, DefineLine] = {}
    guards: Dict[str, GuardRange] = {}

    for idx, line in enumerate(lines):
        line_no = idx + 1

        guard_match = _GUARD_IF_RE.match(line.rstrip("\r\n"))
        if guard_match:
            parsed = parse_guard_condition(guard_match.group("condition"))
            if parsed is not None:
                guard_name, low, high = parsed
                # First guard wins. A header with two guards over one name
                # is already contradicting itself; the first is the one the
                # preprocessor reaches first, so it is the one reported.
                guards.setdefault(
                    guard_name,
                    GuardRange(
                        name=guard_name,
                        min=low,
                        max=high,
                        line_no=line_no,
                        raw_line=line,
                    ),
                )
            continue

        name_match = _DEFINE_NAME_RE.match(line)
        if not name_match:
            continue
        name = name_match.group("name")

        cls = None
        if schema is not None:
            try:
                cls = schema.classify(name)
            except SchemaError:
                cls = None

        value_match = _DEFINE_VALUE_RE.match(line)
        if value_match:
            raw_value = value_match.group("value")
            suffix = value_match.group("suffix")
            base = 16 if raw_value.lower().startswith("0x") else 10
            defines[name] = DefineLine(
                name=name,
                line_no=line_no,
                raw_line=line,
                cls=cls,
                has_value=True,
                value=int(raw_value, base),
                value_text=raw_value + suffix,
            )
        else:
            defines[name] = DefineLine(
                name=name,
                line_no=line_no,
                raw_line=line,
                cls=cls,
                has_value=False,
            )

    return ConfigFile(path=path, lines=lines, defines=defines, guards=guards)


def _format_value(original_value_text: str, new_value: int) -> str:
    """Render `new_value` preserving the radix and suffix of
    `original_value_text` (e.g. "0xDF80U" -> hex, uppercase suffix).
    """
    m = re.match(r"^(0[xX])?([0-9a-fA-F]+)([uU]?)$", original_value_text)
    if not m:  # pragma: no cover - defensive; _DEFINE_VALUE_RE already matched
        raise ConfigIOError(f"cannot re-render value token '{original_value_text}'")
    hex_prefix, _digits, suffix = m.groups()
    if hex_prefix:
        # Preserve the hex prefix's case ("0x" vs "0X") and render digits
        # uppercase to match this codebase's existing style (e.g. DF80).
        rendered = f"{hex_prefix}{new_value:X}"
    else:
        rendered = str(new_value)
    return rendered + suffix


def apply_changes(config: ConfigFile, schema: Schema, changes: Dict[str, int]) -> str:
    """Return the full text of `config` with `changes` applied.

    `changes` maps a #define name to its new integer value. Every name in
    `changes` must classify as "tunable" in `schema`, or this raises
    ConfigIOError naming the offending entry -- R7's write-side refusal.
    Values are clamped to the tunable's declared [min, max] before being
    written. Comments, order, blank lines, indentation and the trailing-
    comment column are all preserved: only the value token itself changes.
    An empty `changes` reproduces the original text exactly.
    """
    if not changes:
        return config.text()

    for name in changes:
        cls = schema.classify(name) if name in schema else None
        if cls != "tunable":
            reported = cls or "unclassified"
            raise ConfigIOError(
                f"refusing to write '{name}': classified as '{reported}', not 'tunable'"
            )
        if name not in config.defines or not config.defines[name].has_value:
            raise ConfigIOError(
                f"refusing to write '{name}': no parseable #define value found in config.h"
            )

    lines = list(config.lines)
    for name, new_value in changes.items():
        define = config.defines[name]
        clamped = schema.clamp(name, new_value)
        value_match = _DEFINE_VALUE_RE.match(define.raw_line)
        assert value_match is not None  # guaranteed by has_value check above
        new_value_text = _format_value(define.value_text, clamped)
        new_line = (
            value_match.group("prefix")
            + new_value_text
            + value_match.group("tail")
        )
        lines[define.line_no - 1] = new_line

    return "".join(lines)


def read(binding: Binding, schema: Optional[Schema] = None) -> ConfigFile:
    """Read and parse `binding.config_h`."""
    path = binding.config_h
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    return parse(text, schema=schema, path=path)


def write(binding: Binding, schema: Schema, changes: Dict[str, int]) -> None:
    """Apply `changes` to `binding.config_h` and write the result back.

    Refuses (raises ConfigIOError) if any name in `changes` is not
    classified "tunable". Preserves everything else in the file exactly.
    """
    config = read(binding, schema)
    new_text = apply_changes(config, schema, changes)
    with open(binding.config_h, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)


def read_config_at_head(binding: Binding, schema: Optional[Schema] = None) -> ConfigFile:
    """Return the whole of `src/config.h` as it exists at git HEAD of the
    active worktree, parsed exactly like `read()` parses the working copy.

    R9 / AC10: the Tuner needs the HEAD value of every changed row on a
    single refresh. `git show HEAD:src/config.h` returns the entire file
    in one process, so callers should read HEAD once per refresh with this
    function and look up as many names as they need from the result --
    never call this (or read_value_at_head) once per row.

    Raises ConfigIOError, distinguishing the two ways this can fail so the
    caller can explain itself rather than crash:
      - no git HEAD to read from at all (a fresh repository with no
        commit yet);
      - HEAD exists but has no `src/config.h` (e.g. a brand-new repo whose
        first commit hasn't landed the file yet).
    """
    result = subprocess.run(
        ["git", "-C", str(binding.active_worktree.path), "show", "HEAD:src/config.h"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        lowered = stderr.lower()
        if "invalid object name" in lowered or "unknown revision" in lowered or "bad revision" in lowered:
            raise ConfigIOError(
                "could not read src/config.h at HEAD: this repository has "
                f"no commits yet ({stderr})"
            )
        if "does not exist" in lowered:
            raise ConfigIOError(
                "could not read src/config.h at HEAD: src/config.h does "
                f"not exist at HEAD ({stderr})"
            )
        raise ConfigIOError(f"could not read src/config.h at HEAD: {stderr}")
    return parse(result.stdout, schema=schema)


def read_value_at_head(binding: Binding, name: str, schema: Optional[Schema] = None) -> int:
    """Return the integer value of #define `name` in `src/config.h` at git
    HEAD of the active worktree.

    Convenience wrapper around `read_config_at_head` for a single name.
    Reading several names for the same refresh (as the Tuner's revert
    feature does) should call `read_config_at_head` once instead of this
    once per name -- each call here re-runs `git show` from scratch.

    Raises ConfigIOError if `name` has no parseable literal value at HEAD,
    or if `read_config_at_head` fails (see its docstring).
    """
    head_config = read_config_at_head(binding, schema=schema)
    define = head_config.defines.get(name)
    if define is None or not define.has_value:
        raise ConfigIOError(f"'{name}' has no parseable value in src/config.h at HEAD")
    return define.value
