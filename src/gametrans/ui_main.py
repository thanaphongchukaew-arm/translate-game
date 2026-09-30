"""Main control window (spec section 13, MVP scope: display mode A only --
modes B/C are phase 5B). Owns the Pipeline lifecycle and bridges its
background-thread callbacks onto the Qt GUI thread via signals (Qt signal
emission is thread-safe and auto-queues across threads with the default
connection type -- this is the ONLY safe way to touch widgets from here).
"""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

from gametrans.overlay import OverlayWindow
from gametrans.pipeline import FrameResult, Pipeline, StatusUpdate
from gametrans.platform_win import enumerate_monitors, exclude_from_capture
from gametrans.store import Store

logger = logging.getLogger("gametrans.ui_main")


class _PipelineBridge(QtCore.QObject):
    frame_ready = QtCore.Signal(object)
    status_ready = QtCore.Signal(object)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Game Screen Translator")
        self.resize(420, 220)

        self._pipeline: Pipeline | None = None
        self._overlay: OverlayWindow | None = None
        self._manager_dialog: QtWidgets.QDialog | None = None
        self._bridge = _PipelineBridge()
        self._bridge.frame_ready.connect(self._on_frame_main_thread, QtCore.Qt.QueuedConnection)
        self._bridge.status_ready.connect(self._on_status_main_thread, QtCore.Qt.QueuedConnection)

        self._monitors = enumerate_monitors()
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.monitor_combo = QtWidgets.QComboBox()
        for m in self._monitors:
            label = f"จอ {m.index} — {m.width}x{m.height} @{int(m.dpi_scale*100)}%"
            if m.is_primary:
                label += " (หลัก)"
            self.monitor_combo.addItem(label)
        layout.addWidget(self.monitor_combo)

        self.start_button = QtWidgets.QPushButton("▶ เริ่มแปล")
        self.start_button.setMinimumHeight(52)
        self.start_button.clicked.connect(self._on_start_stop_clicked)
        layout.addWidget(self.start_button)

        self.status_label = QtWidgets.QLabel("ยังไม่เริ่มทำงาน")
        layout.addWidget(self.status_label)

        self.offline_label = QtWidgets.QLabel("ทำงานออฟไลน์ ไม่ส่งข้อมูลออกนอกเครื่อง")
        layout.addWidget(self.offline_label)

        self.manage_button = QtWidgets.QPushButton("จัดการคำแปล")
        self.manage_button.clicked.connect(self._open_manager)
        layout.addWidget(self.manage_button)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))

    # ------------------------------------------------------------- control

    def _on_start_stop_clicked(self) -> None:
        if self._pipeline is None:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        idx = self.monitor_combo.currentIndex()
        if idx < 0 or idx >= len(self._monitors):
            self.status_label.setText("ไม่พบจอที่เลือก")
            return
        monitor = self._monitors[idx]

        self._overlay = OverlayWindow(
            monitor,
            font_name=self.cfg.get("overlay", {}).get("font", "Leelawadee UI"),
            min_font_px=int(self.cfg.get("overlay", {}).get("min_font_px", 11)),
        )
        self._overlay.show()

        self._pipeline = Pipeline(
            cfg=self.cfg,
            on_frame=lambda f: self._bridge.frame_ready.emit(f),
            on_status=lambda s: self._bridge.status_ready.emit(s),
        )
        self._pipeline.start(monitor)

        self.start_button.setText("■ หยุด")
        self.status_label.setText("กำลังทำงาน...")

    def _stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self.start_button.setText("▶ เริ่มแปล")
        self.status_label.setText("หยุดแล้ว")

    def _open_manager(self) -> None:
        from gametrans.ui_manager import ManagerDialog

        if self._pipeline is None:
            store = Store(
                overrides_path=self.cfg.get("text", {}).get("overrides_path", "overrides.json"),
                glossary_path=self.cfg.get("text", {}).get("glossary_path", "glossary.json"),
                cache_path=self.cfg.get("cache", {}).get("path", "translation_cache.json"),
            )
            store.load()
        else:
            store = self._pipeline.store

        if self._manager_dialog is None:
            self._manager_dialog = ManagerDialog(store, parent=self)
        self._manager_dialog.refresh()
        self._manager_dialog.show()
        self._manager_dialog.raise_()

    # ------------------------------------------------------ signal slots

    def _on_frame_main_thread(self, frame: FrameResult) -> None:
        if self._overlay is not None:
            self._overlay.update_frame(frame)

    def _on_status_main_thread(self, status: StatusUpdate) -> None:
        self.status_label.setText(
            f"OCR {status.ocr_ms:.0f} ms · {status.block_count} ข้อความ · ชั้น {status.active_tier}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._stop()
        super().closeEvent(event)
