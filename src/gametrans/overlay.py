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


class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, monitor: MonitorInfo, font_name: str = "Leelawadee UI", min_font_px: int = 11) -> None:
        super().__init__()
        self._monitor = monitor
        self._font_name = font_name
        self._min_font_px = min_font_px
        self._frame: FrameResult | None = None

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
        rect = QtCore.QRectF(x1, y1, max(x2 - x1, 1.0), max(y2 - y1, 1.0))

        font_px = max(int((y2 - y1) * 0.85), self._min_font_px)
        font = QtGui.QFont(self._font_name)
        font.setPixelSize(font_px)
        painter.setFont(font)

        painter.fillRect(rect, QtGui.QColor(12, 12, 18, 225))
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(rect, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, tb.thai)
