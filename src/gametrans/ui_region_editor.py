"""Region editor (spec section 3B/13): lets the user drag rectangles over
a real screenshot of the target monitor to define/edit a profile's
regions, instead of hand-editing profiles/*.json. Existing regions are
shown as labeled boxes; new ones are added by dragging, each tagged with
a preset from presets.py; any region can be removed from the list.
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from gametrans.platform_win import MonitorInfo
from gametrans.presets import load_all_presets
from gametrans.profiles import Profile, save_profile
from gametrans.regions import Region, rect_from_pixels, rect_to_pixels

logger = logging.getLogger("gametrans.ui_region_editor")


def _capture_snapshot(monitor: MonitorInfo):
    """One-shot screenshot of the target monitor to use as the editor's
    background. Falls back to a plain gray image if capture fails (must
    never crash the editor over this)."""
    try:
        from gametrans.capture import create_backend

        backend = create_backend("auto", monitor_index=monitor.index)
        try:
            frame = backend.grab(monitor.left, monitor.top, monitor.width, monitor.height)
            for _ in range(3):
                if frame is not None:
                    break
                frame = backend.grab(monitor.left, monitor.top, monitor.width, monitor.height)
        finally:
            backend.close()
        if frame is not None:
            h, w, ch = frame.shape
            return QtGui.QImage(frame.data, w, h, ch * w, QtGui.QImage.Format_BGR888).copy()
    except Exception as exc:  # noqa: BLE001 - fall back to a placeholder
        logger.warning("ui_region_editor: snapshot capture failed (%s)", exc)

    img = QtGui.QImage(monitor.width, monitor.height, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(40, 40, 45))
    return img


class _CanvasLabel(QtWidgets.QLabel):
    """Displays the screenshot and handles rubber-band region dragging in
    WIDGET pixel space; the editor converts to/from proportional rects."""

    region_dragged = QtCore.Signal(QtCore.QRect)

    def __init__(self) -> None:
        super().__init__()
        self._rubber_band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)
        self._origin = QtCore.QPoint()
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        self._origin = event.pos()
        self._rubber_band.setGeometry(QtCore.QRect(self._origin, QtCore.QSize()))
        self._rubber_band.show()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._rubber_band.isVisible():
            self._rubber_band.setGeometry(QtCore.QRect(self._origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._rubber_band.isVisible():
            rect = QtCore.QRect(self._origin, event.pos()).normalized()
            self._rubber_band.hide()
            if rect.width() >= 8 and rect.height() >= 8:
                self.region_dragged.emit(rect)


class RegionEditorWindow(QtWidgets.QDialog):
    def __init__(self, profile: Profile, monitor: MonitorInfo, presets_dir: str = "presets", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"แก้ไข region — {profile.display_name}")
        self.profile = profile
        self.monitor = monitor
        self.regions: list[Region] = list(profile.regions)
        self.presets = load_all_presets(presets_dir)

        self._snapshot = _capture_snapshot(monitor)
        self._scaled_size = QtCore.QSize(min(self._snapshot.width(), 1000), 0)

        self._build_ui()
        self._redraw()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)

        self.canvas = _CanvasLabel()
        self.canvas.region_dragged.connect(self._on_region_dragged)
        layout.addWidget(self.canvas, stretch=3)

        side = QtWidgets.QVBoxLayout()
        side.addWidget(QtWidgets.QLabel("ลากกรอบบนภาพเพื่อเพิ่ม region ใหม่"))

        self.region_list = QtWidgets.QListWidget()
        self.region_list.itemSelectionChanged.connect(self._redraw)
        side.addWidget(self.region_list)

        remove_button = QtWidgets.QPushButton("ลบ region ที่เลือก")
        remove_button.clicked.connect(self._on_remove_selected)
        side.addWidget(remove_button)

        save_button = QtWidgets.QPushButton("บันทึกโปรไฟล์")
        save_button.clicked.connect(self._on_save)
        side.addWidget(save_button)

        side.addStretch(1)
        layout.addLayout(side, stretch=1)

        self._refresh_region_list()

    def _refresh_region_list(self) -> None:
        self.region_list.clear()
        for r in self.regions:
            self.region_list.addItem(f"{r.name}  [{r.preset}]  {tuple(round(v, 3) for v in r.rect)}")

    def _scaled_pixmap(self) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap.fromImage(self._snapshot)
        target_w = self._scaled_size.width() or pixmap.width()
        return pixmap.scaledToWidth(target_w, QtCore.Qt.SmoothTransformation)

    def _redraw(self) -> None:
        pixmap = self._scaled_pixmap().copy()
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        sx = pixmap.width() / self.monitor.width
        sy = pixmap.height() / self.monitor.height

        selected_idx = self.region_list.currentRow()
        for i, r in enumerate(self.regions):
            px = rect_to_pixels(r.rect, self.monitor.width, self.monitor.height)
            rect = QtCore.QRectF(px[0] * sx, px[1] * sy, (px[2] - px[0]) * sx, (px[3] - px[1]) * sy)
            color = QtGui.QColor(255, 200, 0, 160) if i == selected_idx else QtGui.QColor(0, 200, 255, 120)
            painter.fillRect(rect, color)
            painter.setPen(QtGui.QColor(255, 255, 255))
            painter.drawRect(rect)
            painter.drawText(rect.adjusted(2, 2, 0, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, r.name)
        painter.end()

        self.canvas.setPixmap(pixmap)
        self.canvas.resize(pixmap.size())

    def _on_region_dragged(self, widget_rect: QtCore.QRect) -> None:
        pixmap = self.canvas.pixmap()
        if pixmap is None or pixmap.width() == 0:
            return
        sx = self.monitor.width / pixmap.width()
        sy = self.monitor.height / pixmap.height()
        px_rect = (
            int(widget_rect.left() * sx), int(widget_rect.top() * sy),
            int(widget_rect.right() * sx), int(widget_rect.bottom() * sy),
        )
        proportional = rect_from_pixels(px_rect, self.monitor.width, self.monitor.height)

        answer = self._prompt_new_region()
        if answer is None:
            self._redraw()
            return
        name, preset_name = answer

        try:
            region = Region(name=name, rect=proportional, preset=preset_name)
        except ValueError as exc:
            self._show_warning("region ไม่ถูกต้อง", str(exc))
            self._redraw()
            return

        self.regions.append(region)
        self._refresh_region_list()
        self._redraw()

    def _prompt_new_region(self) -> tuple[str, str] | None:
        """Asks for a region name + preset. A plain method (not a direct
        static Qt dialog call in the caller) so tests can substitute it
        without needing to monkeypatch PySide6's C++-bound QInputDialog
        static methods, which doesn't reliably work."""
        name, ok = QtWidgets.QInputDialog.getText(self, "ชื่อ region", "ตั้งชื่อ region นี้:")
        if not ok or not name.strip():
            return None
        preset_name, ok = QtWidgets.QInputDialog.getItem(
            self, "พรีเซ็ต", "เลือกพรีเซ็ตสำหรับ region นี้:", list(self.presets.keys()), editable=False
        )
        if not ok:
            return None
        return name.strip(), preset_name

    def _show_warning(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, message)

    def _show_info(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.information(self, title, message)

    def _on_remove_selected(self) -> None:
        row = self.region_list.currentRow()
        if 0 <= row < len(self.regions):
            del self.regions[row]
            self._refresh_region_list()
            self._redraw()

    def _on_save(self) -> None:
        from dataclasses import replace

        updated = replace(self.profile, regions=tuple(self.regions))
        save_profile(updated, profile_dir="profiles")
        self.profile = updated
        self._show_info("บันทึกแล้ว", f"บันทึกโปรไฟล์ {updated.id} แล้ว ({len(self.regions)} region)")
