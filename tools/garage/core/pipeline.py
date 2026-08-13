"""Which converter an asset feeds, and the command that runs it (R6, R10).

No Qt import belongs here (R12); nothing here writes a file of its own.

**Why this reads the game repository's Makefile.** R6 forbids copying
converter logic into this repository, and AC6 asks a run from Garage to
produce the same output file as the same converter run from a terminal.
The invocations are not uniform -- `png_to_tiles.py` takes `--bank 255`,
an output path and an array name; the track tileset also takes a rotation
manifest, a `.tsx`, an id-map output and a meta-header output; a `.tmx`
feeds several targets at once. Spelling those out here would be exactly
the copy R6 forbids, and would drift the first time the game repository
changed one. The Makefile already holds every one of them, so Garage reads
it and then asks `make` to do the work -- the terminal command, run from a
window.

**Why `make -W <asset> <targets>` and not `make -B`.** `make <target>`
alone does nothing when the asset is older than its output, and "I pressed
Convert and nothing ran" is not an outcome. `-B` would force *every*
prerequisite, including `assets/maps/tileset.png: assets/maps/tileset.
aseprite`, which needs a drawing program on PATH -- so a user who edited
the PNG directly would be told to install Aseprite. `-W <asset>` says
"treat this one file as new", which forces exactly the chain the user
asked for and leaves everything else alone.

**Music is the exception R11 states.** No Makefile rule reads a `.uge`:
the export to `src/music_data.c` happens inside the tracker. So the two
validators are named here, and only here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Set, Tuple

MAKEFILE_NAME = "Makefile"

# What marks a recipe line as running one of the game repository's own
# converters. Every converter rule in that Makefile is spelled this way
# ("python tools/png_to_tiles.py ...", "python tools/tmx_to_c.py ..."),
# and it is what separates them from the aseprite export rules and from
# the compile/link recipes.
CONVERTER_MARKER = "python tools/"

# The converters R6 names, for the panel to say which one a card would
# run. Read out of the recipe rather than assumed from the asset's kind:
# the Makefile is what decides, and a rule that changed tool would
# otherwise be reported wrongly.
KNOWN_CONVERTERS = (
    "png_to_tiles.py",
    "tmx_to_c.py",
    "overmap_to_c.py",
    "dialog_to_c.py",
    "tmx_to_array_c.py",
)

# Said beside a tileset built with a rotation manifest. Garage's tile cost
# is the base tile count (width/8 x height/8, which is png_to_tiles'
# `n_tiles`); that converter then generates a rotated variant per entry in
# the manifest and checks the *total* against 192. The total cannot be
# known without running it, so the panel says which number it is showing
# rather than implying the budget is safe.
ROTATION_NOTE = (
    "base tiles only — this tileset also generates rotated variants at "
    "conversion time, which count against the same 192-tile VRAM budget."
)

# The two music validators R11 names, and what each is run against.
MUSIC_SONG_VALIDATE = ("tools", "music_song_validate.py")
MUSIC_WIRE_CHECK = ("tools", "music_wire_check.py")
# music_song_validate.py validates the hUGETracker *C export*, not the
# .uge -- the .uge is the tracker's project file and nothing outside the
# tracker reads it. This is the file the export lands in.
MUSIC_EXPORT_RELATIVE = "src/music_data.c"

MAKE_EXECUTABLE = "make"

# A variable assignment, not a rule. `export ` is allowed in front of it
# because the game repository's Makefile has one (`export PYTHONUTF8 := 1`)
# and without it "export" and "PYTHONUTF8" parse as two targets.
_ASSIGNMENT = re.compile(r"^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*(:?=|\+=|\?=|::=)")


class PipelineError(Exception):
    """The active worktree cannot answer a question about converters --
    no Makefile, or none Garage can read. Carries a message that names the
    path and what the failure prevents.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Rule:
    """One Makefile rule: what it writes, what it reads, how it does it.

    `recipe` lines have their leading tab stripped and their continuations
    joined, so one entry is one command.
    """

    targets: Tuple[str, ...]
    prerequisites: Tuple[str, ...]
    recipe: Tuple[str, ...]
    phony: bool = False

    @property
    def is_converter(self) -> bool:
        """True when this rule runs one of the game repository's own tools
        to write a generated source. A rule whose target is another asset
        (the aseprite exports) is excluded: it produces an input, not an
        output, and needs a drawing program Garage must not require.

        A `.PHONY` rule is a command, not a file. The game repository has
        ten of them whose recipes run `python tools/...` -- `memory-check`,
        `bank-check`, `hooks`, `sync-docs`, `all` and the rest -- and
        without this they are classified as converter rules and their names
        end up in `generated_files()`, a set whose whole meaning is "paths
        a converter writes". Make already declares the answer, so this asks
        it rather than guessing from the shape of the name.
        """
        if self.phony or not self.recipe:
            return False
        if not any(CONVERTER_MARKER in line for line in self.recipe):
            return False
        return not any(t.startswith("assets/") for t in self.targets)

    def converter_names(self) -> Tuple[str, ...]:
        """The converter scripts this rule's recipe invokes, in order."""
        found = []
        for line in self.recipe:
            for name in KNOWN_CONVERTERS:
                if name in line and name not in found:
                    found.append(name)
        return tuple(found)


def _join_continuations(text: str) -> List[str]:
    """Fold `\\`-continued lines into one, keeping a leading tab on the
    result when the first line had one (that tab is what makes a line a
    recipe).
    """
    joined: List[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if buffer:
            buffer += " " + line.strip()
        else:
            buffer = line
        if buffer.endswith("\\"):
            buffer = buffer[:-1].rstrip()
            continue
        joined.append(buffer)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _is_rule_line(line: str) -> bool:
    if not line or line.startswith("\t") or line.lstrip().startswith("#"):
        return False
    if _ASSIGNMENT.match(line.strip()):
        return False
    return ":" in line


def _split_targets_and_prerequisites(line: str) -> Tuple[List[str], List[str]]:
    head, _, tail = line.partition(":")
    # Order-only prerequisites (after `|`) are ordering constraints, not
    # inputs: `| build` only says the build directory must exist first.
    tail = tail.split("|", 1)[0]
    return head.split(), tail.split()


def _usable(name: str) -> bool:
    """A target Garage can name on a make command line: a literal path.
    A pattern (`%`) and a variable (`$(TARGET)`) are neither.
    """
    return "%" not in name and "$" not in name


def _phony_targets(lines: List[str]) -> Set[str]:
    """Every name `.PHONY` declares.

    Collected in its own pass because Make lets `.PHONY` appear
    anywhere, including after the rules it names -- reading it as we go
    would classify a rule correctly or not depending on line order.
    """
    phony: Set[str] = set()
    for line in lines:
        if line.startswith("\t"):
            continue
        head, separator, tail = line.partition(":")
        if separator and head.strip() == ".PHONY":
            phony.update(tail.split())
    return phony


def parse_makefile(text: str) -> List[Rule]:
    """Every rule in `text` whose targets are literal paths.

    Deliberately not a Make implementation: no variable expansion, no
    conditionals, no includes. It answers one question -- which literal
    target lists this asset as a prerequisite -- and everything it cannot
    answer literally it drops, so a rule Garage misreads becomes a rule
    Garage does not offer rather than a wrong command run in the user's
    worktree.
    """
    lines = _join_continuations(text)
    phony_names = _phony_targets(lines)

    rules: List[Rule] = []
    targets: List[str] = []
    prerequisites: List[str] = []
    recipe: List[str] = []
    have_rule = False

    def flush() -> None:
        nonlocal have_rule, targets, prerequisites, recipe
        if have_rule and targets:
            rules.append(
                Rule(
                    targets=tuple(targets),
                    prerequisites=tuple(prerequisites),
                    recipe=tuple(recipe),
                    phony=any(t in phony_names for t in targets),
                )
            )
        have_rule, targets, prerequisites, recipe = False, [], [], []

    for line in lines:
        if line.startswith("\t"):
            if have_rule:
                recipe.append(line[1:].strip())
            continue
        if not line.strip():
            continue
        if not _is_rule_line(line):
            flush()
            continue
        flush()
        parsed_targets, parsed_prerequisites = _split_targets_and_prerequisites(line)
        parsed_targets = [t for t in parsed_targets if _usable(t)]
        if not parsed_targets or parsed_targets == [".PHONY"]:
            continue
        have_rule = True
        targets = parsed_targets
        prerequisites = [p for p in parsed_prerequisites if _usable(p)]
    flush()
    return rules


def makefile_path(binding) -> Path:
    """The active worktree's Makefile (R13)."""
    return binding.resolve(MAKEFILE_NAME)


def read_rules(binding) -> List[Rule]:
    """Parse the active worktree's Makefile."""
    path = makefile_path(binding)
    if not path.is_file():
        raise PipelineError(
            f"'{path}' does not exist. Garage reads the game repository's "
            f"own Makefile to learn which converter each asset feeds, so it "
            f"cannot offer a conversion until that file is there."
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PipelineError(f"'{path}' could not be read: {exc}") from exc
    return parse_makefile(text)


def targets_for_asset(rules: Sequence[Rule], relative_path: str) -> List[str]:
    """Every generated file that reads `relative_path`, sorted.

    All of them, not the first: `assets/maps/track.tmx` feeds the map
    source *and* the rotation manifest, and converting one without the
    other leaves the worktree half converted.
    """
    found: List[str] = []
    for rule in rules:
        if not rule.is_converter:
            continue
        if relative_path in rule.prerequisites:
            found.extend(t for t in rule.targets if t not in found)
    return sorted(found)


def generated_files(rules: Sequence[Rule]) -> Set[str]:
    """Every file a converter rule writes (R10).

    Derived from the Makefile, not listed here: the spec names three
    (`src/track_map.c`, the generated tile sources, `src/dialog_data.c`),
    and a list would go stale the first time the game repository added a
    fourth. Includes the recipe-less rules that declare a converter's
    side-effect outputs (`build/track_tile_id_map.json
    src/track_tileset_meta.h: src/track_tiles.c`), which are generated by
    the rule that writes their prerequisite.

    The second pass excludes `.PHONY` rules for the same reason the
    first one does, and it has to say so itself: `dialog_data:
    src/dialog_data.c src/hub_data.c` is a phony rule with no recipe
    whose prerequisites are both generated, so it satisfies the
    side-effect test exactly. Reading `is_converter` in the first pass
    is not enough -- this loop never consults it.
    """
    generated: Set[str] = set()
    for rule in rules:
        if rule.is_converter:
            generated.update(rule.targets)
    for rule in rules:
        if rule.phony or rule.recipe or not rule.prerequisites:
            continue
        if all(p in generated for p in rule.prerequisites):
            generated.update(rule.targets)
    return generated
