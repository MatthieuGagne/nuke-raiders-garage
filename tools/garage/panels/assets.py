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

R10 is structural here rather than enforced: the panel lists files under
`assets/` and nothing else, and a card's only reference to a generated
file is a text label naming where the converter writes. There is no code
path that opens one.
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
            self.verdict_label.setText(problem.message.upper()[:40])
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
        self.convert_button.setEnabled(self.plan.can_run)
        self.convert_button.setToolTip(
            "" if self.plan.can_run else (self.plan.refusal or "")
        )

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


class AssetsPanel(QWidget):
    """R1's list, R2's previews, R3's costs, R4's verdicts."""

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
        self._runs.finished.connect(self._on_run_finished)
        self._running_card: Optional[AssetCard] = None

        # What each listed asset looked like when Garage last stamped it,
        # and which ones are known to have changed since. Both live on the
        # panel rather than on the cards, because `refresh()` destroys and
        # rebuilds every card. Task 9 is what fills them; a successful
        # conversion below is what clears a mark.
        self._stamps: Dict[str, assets_core.Stamp] = {}
        self._changed_paths: set = set()

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

        if self.binding is None:
            self.status_label.setText(
                self.binding_error.message if self.binding_error
                else "No game repository is bound, so there are no assets to show."
            )
            return

        try:
            rules = pipeline.read_rules(self.binding)
        except pipeline.PipelineError as exc:
            rules = []
            self.append_line(exc.message)

        found = assets_core.discover(self.binding)
        if not found:
            self.status_label.setText(
                f"{assets_core.assets_dir(self.binding)} holds no files."
            )
            return

        problems = 0
        for asset in found:
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
        # R10's read-only set, derived from the Makefile rather than
        # listed: a converter rule added to the game repository is covered
        # the day it lands.
        self._generated = pipeline.generated_files(rules)

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

    # -- the two actions (filled in by Task 8 and Task 9) ------------------

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
        (R9/AC9). Called by the poll timer, and directly by tests."""
        for card in self._cards:
            relative = card.asset.relative_path
            before = self._stamps.get(relative)
            after = assets_core.stamp(card.asset.path)
            if before is None:
                self._stamps[relative] = after
                continue
            if assets_core.has_changed(before, after):
                # Remembered on the panel, not only on the card: the card is
                # thrown away and rebuilt by every `refresh()`.
                self._changed_paths.add(relative)
                card.set_changed(True)

    def convert(self, card: AssetCard) -> None:
        """Run the converter for `card`'s asset (R6/R7).

        R5's refusal is here as well as on the button: the button is
        disabled when verification failed, and this is the guard behind
        it. A refused asset writes its reason to the log rather than
        failing silently — the user pressed something, and something must
        answer.
        """
        if not card.plan.can_run:
            self.append_line(
                card.plan.refusal
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
        for command in card.plan.commands:
            # The prototype's log echoes each command as a shell line, so
            # the output underneath is attributable to the call that
            # produced it.
            self.append_line(f"$ {command.label}")
        if not self._runs.start(
            list(card.plan.commands), self.binding.active_worktree.path
        ):
            self._running_card = None
            return
        self._set_busy(True)

    def _convert(self, card: AssetCard) -> None:
        self.convert(card)

    def _set_busy(self, busy: bool) -> None:
        for card in self._cards:
            card.convert_button.setEnabled(not busy and card.plan.can_run)
            card.open_button.setEnabled(not busy)

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
