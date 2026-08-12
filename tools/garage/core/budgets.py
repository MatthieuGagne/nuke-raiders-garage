"""Reads the hardware budgets out of what the game repository's own tools
print (R12), and decides whether the emulator may start (R13).

AC12 says the panel must show *the same numbers as* `make memory-check`.
The cheapest way to be sure of that is to show nothing else: this module
parses the text those targets already produce, rather than reimplementing
their arithmetic against the map files. If `memory_check.py` changes how it
counts, Garage cannot silently disagree with it -- it either parses the new
line or reports that it could not read the report at all.

Two producers, two formats, both real (captured from a full build):

    === GB Memory Validation Report ===
    WRAM:  1,534 / 8,192 bytes   (18%)  PASS
    VRAM:  76 / 384 tiles   (19%)  PASS
    OAM:   32 / 40 sprites  (80%)  WARN  [busiest scene: Playing]
           per-scene peak OAM:
             Title      0 / 40   (-)
             Playing   32 / 40   (player=4, projectiles=8, ...)

    === Bank Post-Build Report ===
    ROM_1: 100%  [WARN]
    ROM capacity: OK - 32 banks (cartridge header 0x148), highest bank in use 31

No Qt here, and no subprocess either: the compile bar already ran the
targets and captured their output, so this module is a pure function from
text to numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
# A budget that could not be measured at all -- the report was never
# produced (romusage missing, nothing built yet). Distinct from FAIL,
# which is a measurement that came back over budget: R13 gates the
# emulator on FAIL, and a check that could not run has not failed.
BLOCKED = "BLOCKED"

# BLOCKED sits below WARN on purpose. A measured WARN is a fact about the
# ROM; BLOCKED is the absence of a fact. When one line has to name the worst
# thing, "OAM is at 80%" beats "three rows were not measured" -- and the
# unmeasured ones are counted separately rather than dropped (see summary).
_SEVERITY = {PASS: 0, BLOCKED: 1, WARN: 2, FAIL: 3}

# "WRAM:  1,534 / 8,192 bytes   (18%)  PASS" and the OAM line's trailing
# "[busiest scene: Playing]".
_BUDGET_RE = re.compile(
    r"^(?P<name>WRAM|VRAM|OAM):\s+"
    r"(?P<used>[\d,]+)\s*/\s*(?P<limit>[\d,]+)\s+"
    r"(?P<unit>\w+)\s+"
    r"\((?P<percent>\d+)%\)\s+"
    r"(?P<status>PASS|WARN|FAIL)"
    r"(?:\s+\[(?P<hint>[^\]]+)\])?"
)

# "         Playing   32 / 40   (player=4, projectiles=8)"
_SCENE_RE = re.compile(
    r"^\s+(?P<name>[A-Za-z][\w-]*)\s+(?P<used>\d+)\s*/\s*(?P<limit>\d+)\s*"
    r"(?:\((?P<detail>.*)\))?\s*$"
)
_SCENE_HEADER = "per-scene peak OAM:"

# "ROM_1: 100%  [WARN]"
_BANK_RE = re.compile(r"^ROM_(?P<bank>\d+):\s+(?P<percent>\d+)%\s+\[(?P<status>PASS|WARN|FAIL)\]")

# "ROM capacity: OK - 32 banks (cartridge header 0x148), highest bank in use 31"
_CAPACITY_RE = re.compile(
    r"^ROM capacity:.*?(?P<limit>\d+)\s+banks.*?highest bank in use\s+(?P<used>\d+)",
    re.IGNORECASE,
)


@dataclass
class Budget:
    key: str
    name: str
    status: str
    used: Optional[int] = None
    limit: Optional[int] = None
    unit: str = ""
    percent: Optional[int] = None
    hint: str = ""

    @property
    def measured(self) -> bool:
        return self.used is not None and self.limit is not None

    def value_text(self) -> str:
        """The numbers, exactly as the tool reported them -- AC12 is about
        agreeing with `make memory-check`, so the panel renders this and
        never a recomputed figure.
        """
        if not self.measured:
            return "—"
        return f"{self.used:,} / {self.limit:,} {self.unit}".strip()


@dataclass
class ScenePeak:
    name: str
    used: int
    limit: int
    detail: str = ""

    @property
    def is_peak(self) -> bool:
        return False  # set by BudgetReport, which can compare across scenes


@dataclass
class BudgetReport:
    budgets: List[Budget] = field(default_factory=list)
    scenes: List[ScenePeak] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.budgets:
            return BLOCKED
        return max((b.status for b in self.budgets), key=lambda s: _SEVERITY.get(s, 0))

    @property
    def failures(self) -> List[Budget]:
        return [b for b in self.budgets if b.status == FAIL]

    @property
    def has_fail(self) -> bool:
        return bool(self.failures)

    def budget(self, key: str) -> Optional[Budget]:
        for entry in self.budgets:
            if entry.key == key:
                return entry
        return None

    def peak_scene(self) -> Optional[ScenePeak]:
        return max(self.scenes, key=lambda s: s.used, default=None)

    def summary(self) -> str:
        """One clause for the compile bar's status line and the aside's
        heading: the worst *measured* result, named, plus a count of the
        rows nothing measured.

        Measured and unmeasured are reported separately because they answer
        different questions. Rolling them together let a run that measured
        one budget report only the ones it had not measured -- pressing
        Bank check said "budgets BLOCKED: WRAM, VRAM, OAM" and never
        mentioned the banks it had just read.
        """
        if not self.budgets:
            return "budgets unknown"
        measured = [b for b in self.budgets if b.status != BLOCKED]
        unmeasured = [b for b in self.budgets if b.status == BLOCKED]
        if not measured:
            return "budgets not measured yet"

        worst = max((b.status for b in measured), key=lambda s: _SEVERITY.get(s, 0))
        if worst == PASS:
            clause = "budgets all PASS"
        else:
            named = [b.name for b in measured if b.status == worst]
            clause = f"budgets {worst}: {', '.join(named)}"
        if unmeasured:
            clause += f" · {len(unmeasured)} not measured"
        return clause


def parse_memory_check(text: str) -> BudgetReport:
    """WRAM, VRAM and OAM, plus the per-scene OAM peaks, out of
    `make memory-check` output. Unparseable or absent lines simply do not
    appear -- a partial report is better than a wrong one, and
    `build_report` marks what is missing as BLOCKED.
    """
    report = BudgetReport()
    in_scenes = False
    for line in (text or "").splitlines():
        match = _BUDGET_RE.match(line.strip())
        if match:
            in_scenes = False
            name = match.group("name")
            report.budgets.append(
                Budget(
                    key=name.lower(),
                    name=name,
                    status=match.group("status"),
                    used=int(match.group("used").replace(",", "")),
                    limit=int(match.group("limit").replace(",", "")),
                    unit=match.group("unit"),
                    percent=int(match.group("percent")),
                    hint=(match.group("hint") or "").strip(),
                )
            )
            continue
        if _SCENE_HEADER in line:
            in_scenes = True
            continue
        if in_scenes:
            scene = _SCENE_RE.match(line.rstrip())
            if scene:
                detail = (scene.group("detail") or "").strip()
                report.scenes.append(
                    ScenePeak(
                        name=scene.group("name"),
                        used=int(scene.group("used")),
                        limit=int(scene.group("limit")),
                        detail="" if detail in ("-", "—") else detail,
                    )
                )
            elif line.strip():
                in_scenes = False
    return report


def parse_bank_report(text: str) -> Optional[Budget]:
    """The ROM bank budget, out of `make bank-post-build` output.

    The banks are one budget, not thirty-two: the meter shows how much of
    the cartridge is in use (highest bank in use, against the capacity the
    cartridge header declares), and the status is the worst any individual
    bank reported -- one bank at 100% is the problem, whatever the others
    are doing. `hint` names that bank so the number is actionable.
    """
    banks = []
    used = limit = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        bank = _BANK_RE.match(line)
        if bank:
            banks.append(
                (int(bank.group("bank")), int(bank.group("percent")), bank.group("status"))
            )
            continue
        capacity = _CAPACITY_RE.match(line)
        if capacity:
            used = int(capacity.group("used"))
            limit = int(capacity.group("limit"))

    if not banks and used is None:
        return None

    status = PASS
    hint = ""
    if banks:
        status = max((b[2] for b in banks), key=lambda s: _SEVERITY.get(s, 0))
        worst = max(banks, key=lambda b: (_SEVERITY.get(b[2], 0), b[1]))
        hint = f"busiest ROM_{worst[0]} {worst[1]}%"

    percent = None
    if used is not None and limit:
        percent = round(used * 100 / limit)

    return Budget(
        key="rom-banks",
        name="ROM banks",
        status=status,
        used=used,
        limit=limit,
        unit="banks",
        percent=percent,
        hint=hint,
    )


def build_report(
    memory_text: Optional[str] = None, bank_text: Optional[str] = None
) -> BudgetReport:
    """The four budgets R12 names, from the two reports.

    A budget whose report never arrived is BLOCKED with no numbers rather
    than absent: "romusage could not run" is information the panel should
    show, and silently dropping the row would read as "no ROM bank problem".
    """
    report = parse_memory_check(memory_text or "")
    measured = {b.key for b in report.budgets}
    for key, name, unit in (("wram", "WRAM", "bytes"), ("vram", "VRAM", "tiles"), ("oam", "OAM", "sprites")):
        if key not in measured:
            report.budgets.append(
                Budget(key=key, name=name, status=BLOCKED, unit=unit, hint="not measured")
            )
    report.budgets.sort(key=lambda b: ["wram", "vram", "oam"].index(b.key))

    banks = parse_bank_report(bank_text or "")
    if banks is None:
        banks = Budget(
            key="rom-banks",
            name="ROM banks",
            status=BLOCKED,
            unit="banks",
            hint="not measured",
        )
    report.budgets.append(banks)
    return report
