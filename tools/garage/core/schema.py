"""Load and validate tunables.json: the classification of every `#define`
in the game repository's `src/config.h`.

No Qt import belongs in this module or anywhere under tools/garage/core/.

R7 / R8: tunables.json is the single source of truth for which #defines
Garage may edit. Every entry is classified as exactly one of:
  - "tunable"    -- a literal a human may edit; carries "min", "max" and
                     "category".
  - "structural" -- a literal the correctness of the code depends on.
  - "derived"    -- a value the header computes from another #define.
  - "marker"     -- a #define that declares no value.
Garage must clamp every edit to [min, max] and must never write a
structural, derived or marker line (config_io.py enforces the write-side
half of that; this module enforces the classification and the clamp).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

VALID_CLASSES = {"tunable", "structural", "derived", "marker"}

DEFAULT_TUNABLES_PATH = Path(__file__).resolve().parent.parent / "tunables.json"


class SchemaError(Exception):
    """Raised when tunables.json is missing, malformed, or self-inconsistent.

    The message always names the offending entry (or the file, when the
    problem is not attributable to one entry).
    """


@dataclass(frozen=True)
class TunableEntry:
    name: str
    category: str
    min: int
    max: int
    reason: str


@dataclass(frozen=True)
class _Entry:
    name: str
    cls: str
    reason: str
    category: Optional[str] = None
    min: Optional[int] = None
    max: Optional[int] = None


def _fail(name: Optional[str], detail: str) -> None:
    if name is None:
        raise SchemaError(f"tunables.json: {detail}")
    raise SchemaError(f"tunables.json entry '{name}': {detail}")


def _parse_entry(name: str, raw: object) -> _Entry:
    if not isinstance(raw, dict):
        _fail(name, "must be a JSON object")

    cls = raw.get("class")
    if cls not in VALID_CLASSES:
        _fail(
            name,
            f"has class {cls!r}; must be one of {sorted(VALID_CLASSES)}",
        )

    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        _fail(name, "is missing a non-empty 'reason'")

    extra_keys = set(raw.keys()) - {"class", "reason", "category", "min", "max"}
    if extra_keys:
        _fail(name, f"has unrecognized field(s): {sorted(extra_keys)}")

    if cls == "tunable":
        category = raw.get("category")
        if not isinstance(category, str) or not category.strip():
            _fail(name, "is 'tunable' but is missing a non-empty 'category'")

        lo = raw.get("min")
        hi = raw.get("max")
        if not isinstance(lo, int) or isinstance(lo, bool):
            _fail(name, "is 'tunable' but 'min' is not an integer")
        if not isinstance(hi, int) or isinstance(hi, bool):
            _fail(name, "is 'tunable' but 'max' is not an integer")
        if lo > hi:
            _fail(name, f"has min ({lo}) greater than max ({hi})")

        return _Entry(name=name, cls=cls, reason=reason, category=category, min=lo, max=hi)

    # structural / derived / marker: min, max, category must be absent.
    for field in ("category", "min", "max"):
        if field in raw:
            _fail(name, f"is '{cls}' but declares '{field}' (only 'tunable' entries may)")

    return _Entry(name=name, cls=cls, reason=reason)


class Schema:
    """The parsed, validated contents of tunables.json."""

    def __init__(self, entries: Dict[str, _Entry], path: Path):
        self._entries = entries
        self.path = path

    # -- loading ------------------------------------------------------

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Schema":
        if path is None:
            path = DEFAULT_TUNABLES_PATH
        path = Path(path)

        if not path.is_file():
            raise SchemaError(f"tunables.json: file not found at '{path}'")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise SchemaError(f"tunables.json: not valid JSON ({e})") from e

        if not isinstance(raw, dict) or "entries" not in raw:
            _fail(None, "must be a JSON object with an 'entries' key")

        raw_entries = raw["entries"]
        if not isinstance(raw_entries, dict):
            _fail(None, "'entries' must be a JSON object")

        entries: Dict[str, _Entry] = {}
        for name, record in raw_entries.items():
            entries[name] = _parse_entry(name, record)

        return cls(entries, path)

    # -- classification -------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def names(self) -> List[str]:
        """All classified #define names, in tunables.json order."""
        return list(self._entries.keys())

    def classify(self, name: str) -> str:
        """Return "tunable" / "structural" / "derived" / "marker" for `name`.

        Raises SchemaError when `name` is not classified at all.
        """
        entry = self._entries.get(name)
        if entry is None:
            raise SchemaError(f"'{name}' is not classified in tunables.json")
        return entry.cls

    def is_tunable(self, name: str) -> bool:
        entry = self._entries.get(name)
        return entry is not None and entry.cls == "tunable"

    # -- tunables ---------------------------------------------------------

    def tunables(self) -> List[TunableEntry]:
        """All tunable entries, in tunables.json order."""
        result = []
        for entry in self._entries.values():
            if entry.cls == "tunable":
                result.append(
                    TunableEntry(
                        name=entry.name,
                        category=entry.category,
                        min=entry.min,
                        max=entry.max,
                        reason=entry.reason,
                    )
                )
        return result

    def tunable(self, name: str) -> TunableEntry:
        entry = self._entries.get(name)
        if entry is None or entry.cls != "tunable":
            raise SchemaError(f"'{name}' is not a tunable entry in tunables.json")
        return TunableEntry(
            name=entry.name,
            category=entry.category,
            min=entry.min,
            max=entry.max,
            reason=entry.reason,
        )

    def clamp(self, name: str, value: int) -> int:
        """Clamp `value` to the declared [min, max] of tunable `name`.

        Raises SchemaError if `name` is not a tunable entry.
        """
        entry = self.tunable(name)
        if value < entry.min:
            return entry.min
        if value > entry.max:
            return entry.max
        return value
