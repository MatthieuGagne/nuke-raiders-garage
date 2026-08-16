"""The asset panel: find an asset, see it, learn what it costs, open it,
convert it (spec P2, issue #3).

Layout follows the prototype's Assets screen (`garage/index.html`): a row
of kind chips, a grid of cards — thumbnail, name, kind tag, verdict chip,
cost, actions — and a log underneath for what a converter printed.

R18/AC18: no colour literal here. The four Game Boy shades are read from
`tools.garage.theme.tokens` by name; every other colour is the
stylesheet's, selected through the object names and the `verdict` dynamic
property this module sets.

Threading: a converter run blocks on a subprocess pipe, so it goes through
`tools.garage.panels.runner.RunController` — the same worker the compile
bar and the commit panel use. Everything that touches a widget below runs
on the UI thread.

R10 is held twice. Structurally, the panel lists files under `assets/`
and nothing else, and a card's only reference to a generated file is a
text label naming where the converter writes — no control offers to open
one. `open()` also refuses a path in the generated set outright, so the
rule holds for any caller rather than only for a user clicking a button
that was never drawn.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tools.garage.core import assets as assets_core
from tools.garage.core import pipeline, preview
from tools.garage.core.project import Binding, BindingError
from tools.garage.panels.runner import RunController
from tools.garage.theme.tokens import TOKENS

# The four shades, darkest index last, in the order png_to_tiles' palette
# indices run (0 = lightest, 3 = darkest).
GB_TOKEN_KEYS = ("gb-0", "gb-1", "gb-2", "gb-3")

# How many screen pixels one image pixel takes in a card thumbnail, and
# the card's width. The prototype's grid is 168px columns with a 96px
# thumbnail strip.
THUMBNAIL_SCALE = 4
THUMBNAIL_MAX_WIDTH = 152
CARD_WIDTH = 168
GRID_COLUMNS = 4
LOG_VISIBLE_LINES = 8

# The most pixels `thumbnail_image` will walk. 192 tiles is 12,288
# pixels, so this leaves room for a legal image of any shape while
# still bounding one whose dimensions defeat the tile count -- see
# `_previewable`.
MAX_PREVIEW_PIXELS = 16384

# How often the panel re-stamps every asset it lists (milliseconds). R9
# asks Garage to notice a file changed after the user opened it, and the
# editor is another process that reports nothing when it saves. A poll is
# the only signal available; two seconds is short enough that returning
# from the editor shows the mark immediately and long enough that a
# directory of a hundred files costs nothing measurable.
POLL_INTERVAL_MS = 2000


def gb_shades() -> List[QColor]:
    """The four Game Boy shades as colours, read from the theme by name."""
    return [QColor(TOKENS[key]) for key in GB_TOKEN_KEYS]


def thumbnail_image(facts: preview.PngFacts, scale: int = THUMBNAIL_SCALE,
                    grid: bool = True) -> QImage:
    """An image of `facts.pixels` in the four Game Boy shades, with the
    8-pixel tile grid drawn over it (R2/AC2).

    The grid is drawn in the darkest shade rather than in a colour of its
    own: it must read as a rule over the art, and adding a fifth colour to
    a four-shade preview would be a lie about the palette.
    """
    shades = gb_shades()
    width = (facts.width or 0) * scale
    height = (facts.height or 0) * scale
    image = QImage(max(width, 1), max(height, 1), QImage.Format.Format_RGB32)
    image.fill(shades[0])
    if not facts.pixels or not facts.width:
        return image

    for y in range(facts.height):
        for x in range(facts.width):
            # `& 3` is defence, not conversion: png_to_tiles' own decoder
            # already guarantees 0-3 (it raises on a higher index, and
            # clamps when it quantises luminance). A converter that ever
            # returned something else would be an IndexError here, and a
            # preview is not where that should surface.
            colour = shades[facts.pixels[y * facts.width + x] & 3]
            for dy in range(scale):
                for dx in range(scale):
                    image.setPixelColor(x * scale + dx, y * scale + dy, colour)

    if grid:
        line = shades[3]
        step = preview.TILE_SIZE * scale
        for x in range(0, width, step):
            for y in range(height):
                image.setPixelColor(x, y, line)
        for y in range(0, height, step):
            for x in range(width):
                image.setPixelColor(x, y, line)
    return image


def _previewable(facts: preview.PngFacts) -> bool:
    """Is this image worth drawing a thumbnail of?

    `thumbnail_image` sets every pixel from Python, so its cost is the
    pixel count times the scale squared. An asset inside the tile budget
    is at most 192 tiles — 12,288 pixels, a few hundred thousand calls,
    imperceptible. An asset *over* the budget has no bound at all: the
    reference screenshots in this project are 2454×122, which is 4.8
    million calls and a window frozen for seconds — to preview art the
    converter is going to refuse anyway. Such a card already carries a
    fail chip naming its tile cost, which is the useful half.

    The pixel bound is not redundant with the tile bound. `tile_count`
    is `(width // 8) * (height // 8)`, which floors to zero the moment
    either side is under 8 -- so a 100000x7 strip costs "0 tiles" and
    would sail through a tile-only check straight into the freeze this
    function exists to prevent.
    """
    if not facts.pixels:
        return False
    if (facts.tile_count or 0) > preview.MAX_TILES:
        return False
    return len(facts.pixels) <= MAX_PREVIEW_PIXELS


def cost_text(asset: assets_core.Asset, verification: assets_core.Verification,
              rotation: bool = False) -> str:
    """The cost line under a card: tiles for an image, size for a map,
    bytes for anything else (R3).
    """
    if verification.png is not None and verification.png.tile_count is not None:
        count = verification.png.tile_count
        text = (
            f"{verification.png.width}×{verification.png.height} · "
            f"{count} tile{'' if count == 1 else 's'}"
        )
        return f"{text} · {pipeline.ROTATION_NOTE}" if rotation else text
    if verification.tmx is not None and verification.tmx.width is not None:
        return f"{verification.tmx.width} × {verification.tmx.height} tiles"
    return f"{asset.size_bytes:,} bytes"


class AssetCard(QWidget):
    """One asset: what it looks like, what it costs, what is wrong with
    it, and the two things the user can do to it.

    `convert_button` is disabled — with the refusal as its tooltip — when
    verification failed (R5/AC5). The plan it would run carries no command
    in that case either, so the refusal holds even if a caller reaches
    past the button.
    """

    open_requested = Signal(object)     # AssetCard
    convert_requested = Signal(object)  # AssetCard

    def __init__(self, asset, verification, plan, image: Optional[QImage],
                 parent=None):
        super().__init__(parent)
        self.setObjectName("assets-card")
        # Without this, every rule in the stylesheet's `#assets-card` block
        # is dead: a plain QWidget does not paint a background or a border
        # from a style sheet, so the card's fail and CHANGED borders would
        # simply never appear. `tools/garage/panels/tuner.py` carries the
        # same call for the same reason; `doctor.py` solves it by deriving
        # from QFrame instead.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_WIDTH)
        self.asset = asset
        self.verification = verification
        self.plan = plan
        self._changed = False
        self._busy = False

        layout = QVBoxLayout(self)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            if pixmap.width() > THUMBNAIL_MAX_WIDTH:
                pixmap = pixmap.scaledToWidth(
                    THUMBNAIL_MAX_WIDTH, Qt.TransformationMode.FastTransformation
                )
            self.thumbnail_label.setPixmap(pixmap)
        else:
            # A map, a song, a source file: no preview exists, and an empty
            # frame that looks like a failed one would be worse than words.
            self.thumbnail_label.setText("no preview")
        layout.addWidget(self.thumbnail_label)

        self.name_label = QLabel(asset.name)
        self.name_label.setObjectName("assets-name")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        row = QHBoxLayout()
        self.kind_label = QLabel(assets_core.KIND_LABELS[asset.kind])
        self.kind_label.setObjectName("assets-kind")
        row.addWidget(self.kind_label)
        row.addStretch(1)
        self.verdict_label = QLabel()
        self.verdict_label.setObjectName("assets-verdict")
        row.addWidget(self.verdict_label)
        layout.addLayout(row)

        self.cost_label = QLabel(cost_text(asset, verification, plan.rotation))
        self.cost_label.setObjectName("assets-cost")
        self.cost_label.setWordWrap(True)
        layout.addWidget(self.cost_label)

        # R10: where the converter writes. A label, never a button — a
        # generated file is read-only in Garage, and the way to make that
        # true is to offer no control that could open one.
        self.target_label = QLabel(
            "→ " + ", ".join(plan.targets) if plan.targets else "no converter"
        )
        self.target_label.setObjectName("assets-target")
        self.target_label.setWordWrap(True)
        self.target_label.setToolTip(
            "Generated — read-only in Garage. Edit the asset, not this file."
            if plan.targets
            else (plan.refusal or "")
        )
        layout.addWidget(self.target_label)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("assets-open")
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self))
        actions.addWidget(self.open_button)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("assets-convert")
        self.convert_button.clicked.connect(
            lambda: self.convert_requested.emit(self)
        )
        actions.addWidget(self.convert_button)
        layout.addLayout(actions)

        self._apply_verdict()

    def _apply_verdict(self) -> None:
        if not self.verification.ok:
            problem = self.verification.problems[0]
            self.verdict_label.setText(problem.chip.upper())
            self.verdict_label.setToolTip(self.verification.summary())
            self.convert_button.setEnabled(False)
            self.convert_button.setToolTip(self.plan.refusal or "")
            self._set_verdict_property("fail")
            return
        if self._changed:
            self.verdict_label.setText("CHANGED")
            self.convert_button.setText("Reconvert")
            self._set_verdict_property("changed")
        else:
            self.verdict_label.setText("OK")
            self.convert_button.setText("Convert")
            self._set_verdict_property("pass")
        # `and not self._busy`: this method is the single place that
        # decides whether Convert is offered, and it is reached from four
        # directions -- the card being built, a poll re-verifying it,
        # `convert()` re-verifying it, and `set_busy` below. Reading the
        # busy state here is what stops any of the first three from
        # re-enabling a button a run in flight disabled (issue #9,
        # defect 1). Before this, `_set_busy` and `_apply_verdict` both
        # wrote that button's enabled state and disagreed about it.
        self.convert_button.setEnabled(self.plan.can_run and not self._busy)
        if self._busy:
            tooltip = (
                "A converter is running. This is offered again when it "
                "finishes."
            )
        else:
            tooltip = "" if self.plan.can_run else (self.plan.refusal or "")
        self.convert_button.setToolTip(tooltip)

    def _set_verdict_property(self, value: str) -> None:
        for widget in (self, self.verdict_label):
            widget.setProperty("verdict", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def is_changed(self) -> bool:
        return self._changed

    def set_changed(self, changed: bool) -> None:
        """R9: the asset changed on disk since Garage last looked. The
        card says so and its action becomes Reconvert, which is the offer
        AC9 asks for."""
        if changed == self._changed:
            return
        self._changed = changed
        self._apply_verdict()

    def set_busy(self, busy: bool) -> None:
        """A converter is running somewhere in the panel (or has just
        stopped). While one is, this card offers neither action: two runs
        at once would interleave two tools' output in one log and race
        over the same generated file, and Open is withheld with it so the
        user is not editing an asset a converter is mid-way through
        reading.

        The state is remembered rather than applied straight to the
        buttons, because a card recomputes its own Convert button every
        time it is re-verified -- see `_apply_verdict`.
        """
        if busy == self._busy:
            return
        self._busy = busy
        self.open_button.setEnabled(not busy)
        self._apply_verdict()

    def apply_verification(self, verification, plan) -> None:
        """Replace this card's verification and plan with freshly computed
        ones, and redraw everything that depends on them -- the verdict
        chip, the cost line, the generated-target label and the Convert
        button's enabled state and tooltip.

        The card is built once, in `refresh()`, from the verification the
        asset happened to have at that moment. The file it describes can
        keep changing underneath it -- an edit made in the seconds between
        the panel drawing OK and the user reaching for Convert -- so that
        first verification goes stale the instant the file does. `convert()`
        and `check_for_changes()` both need to act on what the asset is
        *now*, not on whatever the card was last drawn with, which is what
        this method is for: it updates an existing widget in place rather
        than requiring a full `refresh()` (which would destroy and rebuild
        every card, including the one a running converter reports to).
        """
        self.verification = verification
        self.plan = plan
        self.cost_label.setText(cost_text(self.asset, verification, plan.rotation))
        self.target_label.setText(
            "→ " + ", ".join(plan.targets) if plan.targets else "no converter"
        )
        self.target_label.setToolTip(
            "Generated — read-only in Garage. Edit the asset, not this file."
            if plan.targets
            else (plan.refusal or "")
        )
        self._apply_verdict()


class AssetsPanel(QWidget):
    """R1's list, R2's previews, R3's costs, R4's verdicts, R5's refusal to
    convert a failed asset, R6/R7's converter runs (R11's two validators
    for music), R8's "open in the default app", R9's change detection and
    R10's read-only guard over every generated file.
    """

    run_finished = Signal(object)

    KIND_FILTER_ALL = "all"

    def __init__(self, binding: Optional[Binding],
                 binding_error: Optional[BindingError], parent=None):
        super().__init__(parent)
        self.setObjectName("assets-panel")
        self.binding = binding
        self.binding_error = binding_error
        self._cards: List[AssetCard] = []
        self._filter = self.KIND_FILTER_ALL

        layout = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setObjectName("assets-status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.filter_row = QHBoxLayout()
        self._filter_buttons: Dict[str, QPushButton] = {}
        for key, label in [(self.KIND_FILTER_ALL, "All")] + [
            (k, assets_core.KIND_LABELS[k]) for k in assets_core.KIND_ORDER
        ]:
            button = QPushButton(label)
            button.setObjectName("assets-filter")
            button.setCheckable(True)
            button.setChecked(key == self.KIND_FILTER_ALL)
            button.clicked.connect(
                lambda _checked=False, k=key: self.set_kind_filter(k)
            )
            self._filter_buttons[key] = button
            self.filter_row.addWidget(button)
        self.filter_row.addStretch(1)
        layout.addLayout(self.filter_row)

        self.grid_holder = QWidget()
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_holder)
        layout.addWidget(scroll, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("assets-log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(
            self.log_view.fontMetrics().lineSpacing() * LOG_VISIBLE_LINES
        )
        layout.addWidget(self.log_view)

        self._runs = RunController(self)
        self._runs.line.connect(self.append_line)
        self._runs.command_started.connect(self._append_command)
        self._runs.finished.connect(self._on_run_finished)
        self._running_card: Optional[AssetCard] = None

        # What each listed asset looked like when Garage last stamped it,
        # and which ones are known to have changed since. Both live on the
        # panel rather than on the cards, because `refresh()` destroys and
        # rebuilds every card. A successful conversion below is what clears
        # a mark.
        self._stamps: Dict[str, assets_core.Stamp] = {}
        self._changed_paths: set = set()
        # A second, independent baseline: what each asset looked like when
        # Garage last *verified* it. The two answer different questions and
        # move at different times. `_stamps` answers "has this changed since
        # Garage last watched it?", which drives the CHANGED mark, and it
        # must not move until a conversion answers the offer. `_verified`
        # answers "has this changed since Garage last decoded it?", which
        # decides whether `check_for_changes` needs to re-verify, and it
        # moves on every verify. One dict cannot do both: a marked asset
        # stays changed against `_stamps` until it is converted, so a single
        # baseline meant re-decoding the PNG and re-parsing the game
        # repository's Makefile on every tick, per marked card, forever
        # (issue #9, defect 2).
        self._verified: Dict[str, assets_core.Stamp] = {}
        # The active worktree's parsed Makefile rules, read once per
        # `refresh()` and handed to `plan_for` rather than letting it read
        # the file itself. `None` means they could not be read, which
        # `plan_for` treats as "read them yourself" -- that branch is what
        # reproduces the PipelineError as each card's refusal, so `None` and
        # `[]` are not interchangeable here.
        self._rules: Optional[List[pipeline.Rule]] = None

        self._generated: set = set()
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self.check_for_changes)
        self._poll.start()

        self.refresh()

    # -- building the grid -------------------------------------------------

    def cards(self) -> List[AssetCard]:
        return list(self._cards)

    def visible_cards(self) -> List[AssetCard]:
        return [c for c in self._cards
                if self._filter in (self.KIND_FILTER_ALL, c.asset.kind)]

    def refresh(self) -> None:
        """Re-read assets/ and rebuild every card."""
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        # Both describe the cards this method is about to build, so both
        # are rebuilt from scratch: an entry for a file that has since
        # vanished should not survive. `_stamps` and `_changed_paths` are
        # deliberately *not* reset -- see the `setdefault` below.
        self._verified = {}
        self._rules = None

        if self.binding is None:
            self.status_label.setText(
                self.binding_error.message if self.binding_error
                else "No game repository is bound, so there are no assets to show."
            )
            return

        try:
            rules = pipeline.read_rules(self.binding)
        except pipeline.PipelineError as exc:
            # `None`, not `[]`: `plan_for` treats `None` as "re-read the
            # rules yourself", and only that branch reproduces this same
            # PipelineError for each asset. An empty list is not the same
            # thing to `plan_for` -- it reads as a Makefile with no rules at
            # all, so every card's refusal would claim "no rule reads this
            # asset" instead of naming the real cause, which is that there
            # is no Makefile to read. This log line is the one place that
            # cause is stated once; every card should say it too.
            rules = None
            self.append_line(exc.message)
        self._rules = rules

        found = assets_core.discover(self.binding)
        if not found:
            self.status_label.setText(
                f"{assets_core.assets_dir(self.binding)} holds no files."
            )
            return

        problems = 0
        for asset in found:
            # Stamped *before* verifying, not after: if the file changes
            # while this loop runs, the older stamp is what makes the next
            # poll re-verify it, instead of trusting a verification of a
            # file that has already moved on.
            self._verified[asset.relative_path] = assets_core.stamp(asset.path)
            verification = assets_core.verify(self.binding, asset)
            plan = pipeline.plan_for(self.binding, asset, verification, rules)
            image = None
            if verification.png is not None and _previewable(verification.png):
                image = thumbnail_image(verification.png)
            card = AssetCard(asset, verification, plan, image, parent=self.grid_holder)
            card.open_requested.connect(self._open)
            card.convert_requested.connect(self._convert)
            self._cards.append(card)
            if not verification.ok:
                problems += 1

        # Every listed asset is stamped as it is built, so a change made
        # from anywhere -- the editor Garage started, or Explorer -- is
        # noticed by the next poll (R9).
        #
        # `setdefault`, not a fresh dict: a refresh must not act as an
        # acknowledgement. `refresh()` runs every time the dialog opens, and
        # re-baselining here would mean editing a sprite, seeing CHANGED,
        # closing the panel and reopening it silently withdrew the offer to
        # convert a file that is still unconverted. The baseline belongs to
        # the asset, not to this rebuild of the grid.
        for card in self._cards:
            self._stamps.setdefault(
                card.asset.relative_path, assets_core.stamp(card.asset.path)
            )
        # A rebuilt card is a new widget with default state, so the marks
        # the panel already knows about are re-applied to it.
        for card in self._cards:
            if card.asset.relative_path in self._changed_paths:
                card.set_changed(True)
        # A rebuilt card is a fresh widget that knows nothing of a run in
        # flight -- and a worktree switch, which is one of the things that
        # rebuilds this grid, can happen while one is.
        self._set_busy(self._runs.is_running())
        # R10's read-only set, derived from the Makefile rather than
        # listed: a converter rule added to the game repository is covered
        # the day it lands. `rules or []`: a missing Makefile (rules is
        # None here) means Garage knows of no generated file, which is the
        # truth -- it could not read the file that would have named one.
        self._generated = pipeline.generated_files(rules or [])

        self.status_label.setText(
            f"{assets_core.assets_dir(self.binding)} · {len(found)} files · "
            f"{problems} need attention"
        )
        self._relayout()

    def _relayout(self) -> None:
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for card in self._cards:
            card.setVisible(False)
        for index, card in enumerate(self.visible_cards()):
            self.grid_layout.addWidget(
                card, index // GRID_COLUMNS, index % GRID_COLUMNS
            )
            card.setVisible(True)

    def set_kind_filter(self, kind: str) -> None:
        self._filter = kind
        for key, button in self._filter_buttons.items():
            button.setChecked(key == kind)
        self._relayout()

    # -- the log -----------------------------------------------------------

    def append_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_text(self) -> str:
        return self.log_view.toPlainText()

    def is_running(self) -> bool:
        return self._runs.is_running()

    def stop_and_wait(self) -> None:
        """For the window closing: a QThread still running when Qt tears
        its parent down is a crash, and a timer that fires into a
        half-destroyed panel is the same failure with a different stack.
        """
        self._poll.stop()
        self._runs.stop_and_wait()

    def open(self, card: AssetCard) -> None:
        """Hand the asset to the Windows default application (R8/AC8).

        R10's guard lives here rather than only in the absence of a
        button: a generated file is read-only in Garage, and the refusal
        must hold for any caller.
        """
        relative = card.asset.relative_path
        if relative in self._generated:
            self.append_line(
                f"{relative} is generated by a converter — it is read-only in "
                f"Garage. A hand edit to it is overwritten on the next "
                f"compile; edit the asset it is generated from instead."
            )
            return
        try:
            assets_core.open_in_default_app(card.asset.path)
        except assets_core.OpenError as exc:
            self.append_line(exc.message)
            return
        self.append_line(
            f"Opened {card.asset.name} in the application Windows associates "
            f"with that file type."
        )
        # From here on the file is watched, so a save on the way back is
        # noticed (R9). It is watched before this too -- see refresh() --
        # because a user may edit from Explorer; opening only re-baselines.
        self._stamps[relative] = assets_core.stamp(card.asset.path)

    def _open(self, card: AssetCard) -> None:
        self.open(card)

    def check_for_changes(self) -> None:
        """Re-stamp every listed asset and mark the ones that moved
        (R9/AC9). Called by the poll timer, and directly by tests.

        A card whose file changed is re-verified and re-planned here, not
        only re-stamped: without that, a card would keep showing OK (or a
        problem the edit already fixed) about a file that is not the file
        it was built from, and a Reconvert pressed from it would run
        against a verdict the edit had already made false. Updated in
        place through `AssetCard.apply_verification` rather than by calling
        `refresh()`, which destroys and rebuilds every card -- a rebuild
        while a converter is running would delete the very widget the run
        reports its result to.

        That re-verify is gated on `_verified`, not on `_stamps`. The mark
        is sticky by design, so `_stamps` goes on reporting a change every
        tick until a conversion answers it; gating the decode on the same
        baseline meant re-decoding the file and re-parsing the Makefile
        every two seconds, forever, for each marked card. `_verified`
        moves on every verify, which collapses that to once per edit.
        Do not replace it with "skip whenever the path is already marked":
        an asset edited twice would keep the verification from the first
        edit.
        """
        for card in self._cards:
            relative = card.asset.relative_path
            before = self._stamps.get(relative)
            after = assets_core.stamp(card.asset.path)
            if before is None:
                # Defensive: `refresh()` stamps every card it builds, so a
                # listed asset always has a baseline by the time the timer
                # fires. A missing one would otherwise reach `has_changed`
                # as None. `_verified` is deliberately left alone -- this
                # card has not been verified against this state, and the
                # next tick that sees a change should say so.
                self._stamps[relative] = after
                continue
            if not assets_core.has_changed(before, after):
                continue
            # Remembered on the panel, not only on the card: the card is
            # thrown away and rebuilt by every `refresh()`.
            self._changed_paths.add(relative)
            verified = self._verified.get(relative)
            if verified is None or assets_core.has_changed(verified, after):
                verification = assets_core.verify(self.binding, card.asset)
                plan = pipeline.plan_for(
                    self.binding, card.asset, verification, self._rules
                )
                card.apply_verification(verification, plan)
                self._verified[relative] = after
            card.set_changed(True)

    def convert(self, card: AssetCard) -> None:
        """Run the converter for `card`'s asset (R6/R7).

        The verification behind `card.plan` can be stale: the acceptance
        flow is edit an asset, see CHANGED, press Reconvert, and an edit
        made in the seconds between the panel drawing the card and the user
        pressing this button is exactly what that flow exists to catch.
        Trusting `card.plan` here would mean running a converter against a
        verification computed before the edit -- so this re-verifies and
        re-plans the asset first, against what is on disk right now, and
        updates the card to match before doing anything else. A fresh
        refusal is written to the log and nothing runs; a fresh pass is
        what gets run.

        `plan.can_run` is still checked afterwards, even though the fresh
        plan already encodes the same refusal when there is one: R5's
        guard is deliberately held in three places (the button's enabled
        state, this check, and the fact that a refused `Plan` carries no
        command at all), and this is the second and third of them.
        """
        verification = assets_core.verify(self.binding, card.asset)
        plan = pipeline.plan_for(self.binding, card.asset, verification)
        card.apply_verification(verification, plan)

        if not plan.can_run:
            self.append_line(
                plan.refusal
                or f"{card.asset.name} cannot be converted."
            )
            return
        if self._runs.is_running():
            # Two converter runs at once would interleave two tools'
            # output in one log and race over the same generated file.
            self.append_line(
                f"A converter is already running; {card.asset.name} was not "
                f"started."
            )
            return

        self._running_card = card
        if not self._runs.start(
            list(plan.commands), self.binding.active_worktree.path
        ):
            self._running_card = None
            return
        self._set_busy(True)

    def _convert(self, card: AssetCard) -> None:
        self.convert(card)

    def _append_command(self, label: str, target: str) -> None:
        # `command_started` fires just before a command actually begins, so
        # this echoes only commands that are truly running -- not every
        # command in a plan up front. For a multi-command plan (music's two
        # validators) that matters: if the first fails, `run_sequence`
        # never starts the second, and echoing it anyway would attribute a
        # `$` line to a command that never ran. `target` is accepted to
        # match `RunController.command_started`'s signature; the panel has
        # no use for it the way the compile bar's budget parser does.
        self.append_line(f"$ {label}")

    def _set_busy(self, busy: bool) -> None:
        """Every card learns that a run started or finished.

        Pushed into the cards rather than applied to their buttons from
        here: a card that is re-verified while a run is in flight redraws
        its own Convert button, and this loop cannot reach forward in time
        to stop it (issue #9, defect 1). `AssetCard.set_busy` is where the
        two facts -- "a run is in flight" and "this asset's plan can run"
        -- are combined, in one place.
        """
        for card in self._cards:
            card.set_busy(busy)

    def _on_run_finished(self, results) -> None:
        card, self._running_card = self._running_card, None
        self._set_busy(False)
        if card is None:
            return
        if results and all(r.ok for r in results):
            self.append_line(
                f"{card.asset.name} converted — wrote "
                f"{', '.join(card.plan.targets)}"
            )
            # The asset and its outputs now agree, so whatever change
            # brought the user here is answered (R9).
            self._stamps[card.asset.relative_path] = assets_core.stamp(
                card.asset.path
            )
            # The offer is answered, so it is withdrawn -- from the panel's
            # own memory as well as from the card, or the next refresh
            # would put the mark back (see `refresh`).
            self._changed_paths.discard(card.asset.relative_path)
            card.set_changed(False)
        else:
            codes = ", ".join(str(r.exit_code) for r in results) or "no result"
            self.append_line(
                f"{card.asset.name} — the converter failed (exit {codes}). "
                f"The message above is the converter's own."
            )
        self.run_finished.emit(results)
