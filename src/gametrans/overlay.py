"""Click-through, capture-excluded overlay window that draws translated
Thai text over the original English at the same screen position (display
mode A, spec section 3A). This module (along with app.py, ui_*.py,
platform_win.py) is exempt from the "no PySide6 in core modules" rule.

Coordinate math (spec section 8.8, the most commonly-botched part of this
kind of app): FrameResult block coordinates are in CAPTURE-pixel space
(the region that was actually grabbed). The overlay window covers the
monitor in its own pixel space, which can differ from the capture
resolution (DPI scaling, or the overlay window not being an exact 1:1
match). Every paint recomputes sx = overlay_width / capture_width,
sy = overlay_height / capture_height -- never assumes 1.0.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from gametrans.pipeline import FrameResult
from gametrans.platform_win import MonitorInfo, exclude_from_capture, make_click_through


def fit_font_and_rect(
    fit_cache: dict[int, tuple[str, int, QtCore.QRectF]],
    block_id: int,
    text: str,
    base_rect: QtCore.QRectF,
    font_name: str,
    min_font_px: int,
) -> tuple[int, QtCore.QRectF]:
    """Shrinks the font (down to min_font_px) so `text` word-wraps to fit
    base_rect's WIDTH; if it still doesn't fit the HEIGHT even at the
    minimum size, expands the rect downward instead of letting Qt silently
    clip the overflow (spec section 13: start at ~0.85x the original line
    height, shrink toward min_font_px, then grow the box). Shared by
    OverlayWindow (mode A) and MirrorWindow (mode B) -- both draw
    translated text into a rect sized for the ORIGINAL (usually shorter)
    English text, so both need this or they silently truncate Thai text
    that needs more room (a real bug found from a user's screenshot of a
    truncated translation, not a hypothetical). `fit_cache` is owned by
    the caller (one per window) so an unchanged block skips the
    QFontMetrics measurement work on every repaint."""
    cached = fit_cache.get(block_id)
    if cached is not None and cached[0] == text:
        return cached[1], cached[2]

    start_px = max(int(base_rect.height() * 0.85), min_font_px)
    font = QtGui.QFont(font_name)
    chosen_px = min_font_px
    chosen_bounds = None
    for px in range(start_px, min_font_px - 1, -1):
        font.setPixelSize(px)
        metrics = QtGui.QFontMetrics(font)
        bounds = metrics.boundingRect(
            QtCore.QRect(0, 0, max(int(base_rect.width()), 1), 100000),
            QtCore.Qt.TextWordWrap | QtCore.Qt.AlignCenter,
            text,
        )
        chosen_px = px
        chosen_bounds = bounds
        if bounds.height() <= base_rect.height():
            break  # fits at this size -- stop shrinking further

    rect = QtCore.QRectF(base_rect)
    if chosen_bounds is not None and chosen_bounds.height() > rect.height():
        # even the minimum font doesn't fit the original box -- grow the
        # box downward rather than clip (never shrinks below the original
        # OCR'd size, only ever grows it)
        rect.setHeight(float(chosen_bounds.height()))

    fit_cache[block_id] = (text, chosen_px, rect)
    return chosen_px, rect


class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, monitor: MonitorInfo, font_name: str = "Leelawadee UI", min_font_px: int = 11) -> None:
        super().__init__()
        self._monitor = monitor
        self._font_name = font_name
        self._min_font_px = min_font_px
        self._frame: FrameResult | None = None
        # Per-block cache of the fitted (font_px, expanded_rect) for the
        # last text drawn there, keyed by block id -- spec section 13:
        # "แคชผลคำนวณขนาดฟอนต์ต่อบล็อก" (recomputing a font-fit via
        # QFontMetrics on every repaint for every block would be wasteful;
        # only redo it when that block's text actually changes).
        self._fit_cache: dict[int, tuple[str, int, QtCore.QRectF]] = {}

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowTransparentForInput
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setGeometry(monitor.left, monitor.top, monitor.width, monitor.height)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        hwnd = int(self.winId())
        make_click_through(hwnd)
        if not exclude_from_capture(hwnd):
            # Caller should already have a fallback strategy in this case
            # (spec section 15) -- overlay.py just can't guarantee it here.
            pass

    def update_frame(self, frame: FrameResult) -> None:
        """Qt slot. MUST only be called on the GUI thread -- connect the
        pipeline's on_frame callback to this via a queued Qt signal, never
        call it directly from the capture/translate threads."""
        self._frame = frame
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override
        frame = self._frame
        if frame is None or not frame.blocks:
            return

        sx = self.width() / max(frame.capture_width, 1)
        sy = self.height() / max(frame.capture_height, 1)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        try:
            for tb in frame.blocks:
                self._draw_block(painter, tb, sx, sy)
        finally:
            painter.end()

    def _draw_block(self, painter: QtGui.QPainter, tb, sx: float, sy: float) -> None:
        b = tb.block
        x1, y1, x2, y2 = b.x1 * sx, b.y1 * sy, b.x2 * sx, b.y2 * sy
        base_rect = QtCore.QRectF(x1, y1, max(x2 - x1, 1.0), max(y2 - y1, 1.0))

        font_px, rect = fit_font_and_rect(self._fit_cache, b.id, tb.thai, base_rect, self._font_name, self._min_font_px)
        font = QtGui.QFont(self._font_name)
        font.setPixelSize(font_px)
        painter.setFont(font)

        painter.fillRect(rect, QtGui.QColor(12, 12, 18, 225))
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(rect, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, tb.thai)
