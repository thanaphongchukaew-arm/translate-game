"""Display modes B (mirror) and C (panel) on a second monitor, spec
section 3A. Both pull from Pipeline.snapshot() on their own QTimer instead
of reacting to every on_frame signal, so their render rate (mirror_fps) is
decoupled from the OCR loop's rate and can never slow it down.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from gametrans.overlay import fit_font_and_rect
from gametrans.pipeline import FrameResult, Pipeline
from gametrans.platform_win import MonitorInfo, exclude_from_capture


def _median_fill_color(frame, x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int]:
    """Median color of a ring of pixels just outside the text box -- used
    to paint over the original text less jarringly than a flat black box
    (spec section 3A mode B detail)."""
    import numpy as np

    h, w = frame.shape[0], frame.shape[1]
    pad = max(3, (y2 - y1) // 4)
    rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)
    rx2, ry2 = min(w, x2 + pad), min(h, y2 + pad)
    if rx2 <= rx1 or ry2 <= ry1:
        return (12, 12, 18)
    ring = frame[ry1:ry2, rx1:rx2].reshape(-1, frame.shape[2])
    median = np.median(ring, axis=0)
    b, g, r = int(median[0]), int(median[1]), int(median[2])
    return (r, g, b)  # QColor wants RGB


def _frame_to_qimage(frame) -> QtGui.QImage:
    h, w, ch = frame.shape
    bytes_per_line = ch * w
    # frame is BGR (from capture.py); QImage.Format_BGR888 matches directly.
    return QtGui.QImage(frame.data, w, h, bytes_per_line, QtGui.QImage.Format_BGR888).copy()


class MirrorWindow(QtWidgets.QWidget):
    """Mode B: full copy of the captured game frame with original text
    painted over and replaced by the Thai translation, on a second
    monitor. Never the capture target itself (caller picks a different
    monitor than the one being captured -- see ui_main.py)."""

    def __init__(self, output_monitor: MonitorInfo, mirror_fps: int = 30) -> None:
        super().__init__()
        self._output_monitor = output_monitor
        self._pipeline: Pipeline | None = None
        self._latest: FrameResult | None = None

        self.setWindowTitle("Game Translator - Output")
        self.setGeometry(output_monitor.left, output_monitor.top, output_monitor.width, output_monitor.height)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._pull_and_repaint)
        interval_ms = max(1, int(1000 / max(mirror_fps, 1)))
        self._timer.start(interval_ms)

        self._fit_cache: dict[int, tuple[str, int, QtCore.QRectF]] = {}

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def attach_pipeline(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    def _pull_and_repaint(self) -> None:
        if self._pipeline is None:
            return
        frame = self._pipeline.snapshot()
        if frame is not None and frame.frame_image is not None:
            self._latest = frame
            self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override
        frame = self._latest
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        try:
            if frame is None or frame.frame_image is None:
                painter.fillRect(self.rect(), QtGui.QColor(10, 10, 14))
                painter.setPen(QtGui.QColor(180, 180, 180))
                painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "รอภาพจากเกม...")
                return

            img_array = frame.frame_image.copy()
            for tb in frame.blocks:
                b = tb.block
                x1, y1, x2, y2 = int(b.x1), int(b.y1), int(b.x2), int(b.y2)
                color = _median_fill_color(frame.frame_image, x1, y1, x2, y2)
                img_array[y1:y2, x1:x2] = (color[2], color[1], color[0])  # back to BGR for the array

            qimg = _frame_to_qimage(img_array)
            scaled = qimg.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            x_off = (self.width() - scaled.width()) // 2
            y_off = (self.height() - scaled.height()) // 2
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
            painter.drawImage(x_off, y_off, scaled)

            sx = scaled.width() / max(frame.capture_width, 1)
            sy = scaled.height() / max(frame.capture_height, 1)
            for tb in frame.blocks:
                b = tb.block
                base_rect = QtCore.QRectF(
                    x_off + b.x1 * sx, y_off + b.y1 * sy,
                    max((b.x2 - b.x1) * sx, 1.0), max((b.y2 - b.y1) * sy, 1.0),
                )
                # Same fit-then-grow logic as OverlayWindow (mode A) --
                # without it, Thai text longer than the original English
                # silently gets clipped by Qt instead of shown in full.
                font_px, rect = fit_font_and_rect(self._fit_cache, b.id, tb.thai, base_rect, "Leelawadee UI", 11)
                font = QtGui.QFont("Leelawadee UI")
                font.setPixelSize(font_px)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(rect, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, tb.thai)
        finally:
            painter.end()


class PanelWindow(QtWidgets.QWidget):
    """Mode C: a scrolling list of recent translated lines, newest at the
    bottom. A block is appended once it's had a stable text value (not
    re-added every frame for the same id+text)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Game Translator - Output")
        self.resize(420, 640)

        layout = QtWidgets.QVBoxLayout(self)
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setWordWrap(True)
        layout.addWidget(self.list_widget)

        self._seen: set[tuple[int, str]] = set()
        self._max_items = 200

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    def on_frame(self, frame: FrameResult) -> None:
        """Call from the GUI thread only (connect via a queued Qt signal,
        same as OverlayWindow.update_frame)."""
        for tb in frame.blocks:
            key = (tb.block.id, tb.thai)
            if key in self._seen:
                continue
            self._seen.add(key)
            item = QtWidgets.QListWidgetItem(tb.thai)
            self.list_widget.addItem(item)

        while self.list_widget.count() > self._max_items:
            self.list_widget.takeItem(0)
        self.list_widget.scrollToBottom()
