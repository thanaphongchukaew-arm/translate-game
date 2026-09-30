"""Main control window (spec section 13). Owns the Pipeline lifecycle and
the display-mode window (A overlay / B mirror / C panel), and bridges
background-thread callbacks onto the Qt GUI thread via signals (Qt signal
emission is thread-safe and auto-queues across threads with the default
connection type -- this is the ONLY safe way to touch widgets from here).
"""
from __future__ import annotations

import logging
import sys

from PySide6 import QtCore, QtWidgets

from gametrans.overlay import OverlayWindow
from gametrans.pipeline import FrameResult, Pipeline, StatusUpdate
from gametrans.platform_win import MOD_ALT, MOD_CONTROL, enumerate_monitors, exclude_from_capture, register_hotkey, unregister_hotkey
from gametrans.store import Store
from gametrans.ui_second_screen import MirrorWindow, PanelWindow
from gametrans.watchdog import Watchdog

_HOTKEY_TOGGLE_OVERLAY_ID = 1
_HOTKEY_OPEN_MANAGER_ID = 2
_VK_T = 0x54
_VK_E = 0x45
_WM_HOTKEY = 0x0312


class _HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    """Forwards WM_HOTKEY messages to MainWindow. Registration/delivery is
    NOT verified live in this project (see tray.py docstring) -- coded per
    spec section 13.7 and must fail open (no hotkeys, no crash) if
    RegisterHotKey doesn't work on the user's machine."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self.main_window = main_window

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt override
        if sys.platform != "win32":
            return False, 0
        import ctypes.wintypes

        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == _WM_HOTKEY:
            if msg.wParam == _HOTKEY_TOGGLE_OVERLAY_ID:
                self.main_window._toggle_overlay_visibility()
                return True, 0
            if msg.wParam == _HOTKEY_OPEN_MANAGER_ID:
                self.main_window._open_manager()
                return True, 0
        return False, 0

logger = logging.getLogger("gametrans.ui_main")

_MODE_LABELS = {
    "A": "A — Overlay ทับเกม (จอเดียว)",
    "B": "B — จอสองแสดงภาพเกมแปล",
    "C": "C — แผงคำแปลจอสอง",
}


class _PipelineBridge(QtCore.QObject):
    frame_ready = QtCore.Signal(object)
    status_ready = QtCore.Signal(object)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Game Screen Translator")
        self.resize(420, 280)

        self._pipeline: Pipeline | None = None
        self._output_window: QtWidgets.QWidget | None = None  # OverlayWindow | MirrorWindow | PanelWindow
        self._manager_dialog: QtWidgets.QDialog | None = None
        self._active_capture_monitor = None

        watchdog_cfg = cfg.get("watchdog", {})
        self._watchdog = Watchdog(
            stall_seconds=float(watchdog_cfg.get("stall_seconds", 10)),
            max_restarts_per_min=int(watchdog_cfg.get("max_restarts_per_min", 6)),
        )
        self._watchdog_timer = QtCore.QTimer(self)
        self._watchdog_timer.timeout.connect(self._check_watchdog)
        self._watchdog_timer.start(2000)
        self._bridge = _PipelineBridge()
        self._bridge.frame_ready.connect(self._on_frame_main_thread, QtCore.Qt.QueuedConnection)
        self._bridge.status_ready.connect(self._on_status_main_thread, QtCore.Qt.QueuedConnection)

        self._monitors = enumerate_monitors()
        self._build_ui()
        self._apply_default_mode()

        self._force_quit = False
        self._hotkeys_registered = False
        self._hotkey_filter: _HotkeyFilter | None = None
        self.tray: QtWidgets.QSystemTrayIcon | None = None
        if bool(cfg.get("run_in_tray", True)):
            from gametrans.tray import TrayIcon

            self.tray = TrayIcon(self)
            self.tray.show()

        if bool(cfg.get("autostart", True)):
            # defer to the next event-loop iteration so the window is
            # already constructed/shown first (spec 3D: starts translating
            # on its own when the app opens).
            QtCore.QTimer.singleShot(0, self._start)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("จอที่จะแปล (จับภาพ):"))
        self.monitor_combo = QtWidgets.QComboBox()
        for m in self._monitors:
            self.monitor_combo.addItem(self._monitor_label(m))
        layout.addWidget(self.monitor_combo)

        layout.addWidget(QtWidgets.QLabel("โหมดแสดงผล:"))
        self.mode_combo = QtWidgets.QComboBox()
        for key in ("A", "B", "C"):
            self.mode_combo.addItem(_MODE_LABELS[key], userData=key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.output_monitor_combo = QtWidgets.QComboBox()
        for m in self._monitors:
            self.output_monitor_combo.addItem(self._monitor_label(m))
        layout.addWidget(self.output_monitor_combo)

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

        self.region_editor_button = QtWidgets.QPushButton("แก้ไข region")
        self.region_editor_button.clicked.connect(self._open_region_editor)
        layout.addWidget(self.region_editor_button)

        self.wizard_button = QtWidgets.QPushButton("สร้างโปรไฟล์จากเกมนี้")
        self.wizard_button.clicked.connect(self._open_wizard)
        layout.addWidget(self.wizard_button)

    def _monitor_label(self, m) -> str:
        label = f"จอ {m.index} — {m.width}x{m.height} @{int(m.dpi_scale*100)}%"
        if m.is_primary:
            label += " (หลัก)"
        return label

    def _apply_default_mode(self) -> None:
        """spec section 3A default: 2+ monitors -> mode B, capture monitor
        0 / output monitor 1; single monitor -> mode A."""
        if len(self._monitors) >= 2:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("B"))
            self.monitor_combo.setCurrentIndex(0)
            self.output_monitor_combo.setCurrentIndex(1)
        else:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("A"))
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        self.output_monitor_combo.setVisible(mode in ("B", "C"))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        exclude_from_capture(int(self.winId()))
        self._register_hotkeys()

    def _register_hotkeys(self) -> None:
        if self._hotkeys_registered or sys.platform != "win32":
            return
        hwnd = int(self.winId())
        ok1 = register_hotkey(hwnd, _HOTKEY_TOGGLE_OVERLAY_ID, MOD_CONTROL | MOD_ALT, _VK_T)
        ok2 = register_hotkey(hwnd, _HOTKEY_OPEN_MANAGER_ID, MOD_CONTROL | MOD_ALT, _VK_E)
        if not (ok1 and ok2):
            # spec 13.7: failing to register must not crash or block startup
            logger.warning("ui_main: global hotkey registration failed (ok1=%s ok2=%s)", ok1, ok2)
        self._hotkey_filter = _HotkeyFilter(self)
        QtWidgets.QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        self._hotkeys_registered = True

    def _unregister_hotkeys(self) -> None:
        if not self._hotkeys_registered:
            return
        hwnd = int(self.winId())
        unregister_hotkey(hwnd, _HOTKEY_TOGGLE_OVERLAY_ID)
        unregister_hotkey(hwnd, _HOTKEY_OPEN_MANAGER_ID)
        if self._hotkey_filter is not None:
            QtWidgets.QApplication.instance().removeNativeEventFilter(self._hotkey_filter)
            self._hotkey_filter = None
        self._hotkeys_registered = False

    def _toggle_overlay_visibility(self) -> None:
        if self._output_window is not None:
            self._output_window.setVisible(not self._output_window.isVisible())

    # ------------------------------------------------------------- control

    def _on_start_stop_clicked(self) -> None:
        if self._pipeline is None:
            self._start()
        else:
            self._stop()

    def _resolve_mode_and_monitors(self):
        cap_idx = self.monitor_combo.currentIndex()
        if cap_idx < 0 or cap_idx >= len(self._monitors):
            return None, None, None
        capture_monitor = self._monitors[cap_idx]

        mode = self.mode_combo.currentData()
        if mode in ("B", "C"):
            out_idx = self.output_monitor_combo.currentIndex()
            if out_idx < 0 or out_idx >= len(self._monitors):
                mode = "A"
            else:
                output_monitor = self._monitors[out_idx]
                if output_monitor.index == capture_monitor.index:
                    # spec 3A: output monitor must never be the capture
                    # monitor -- warn and fall back to mode A rather than
                    # create a feedback loop.
                    logger.warning("ui_main: output monitor == capture monitor, falling back to mode A")
                    mode = "A"
                else:
                    return mode, capture_monitor, output_monitor
        return mode, capture_monitor, None

    def _start(self) -> None:
        mode, capture_monitor, output_monitor = self._resolve_mode_and_monitors()
        if capture_monitor is None:
            self.status_label.setText("ไม่พบจอที่เลือก")
            return

        mirror_fps = int(self.cfg.get("display", {}).get("mirror_fps", 60))
        if mode == "A":
            self._output_window = OverlayWindow(
                capture_monitor,
                font_name=self.cfg.get("overlay", {}).get("font", "Leelawadee UI"),
                min_font_px=int(self.cfg.get("overlay", {}).get("min_font_px", 11)),
            )
            self._output_window.show()
        elif mode == "B":
            mirror = MirrorWindow(output_monitor, mirror_fps=mirror_fps)
            self._output_window = mirror
            mirror.show()
        else:  # C
            self._output_window = PanelWindow()
            self._output_window.show()

        self._pipeline = Pipeline(
            cfg=self.cfg,
            on_frame=lambda f: self._bridge.frame_ready.emit(f),
            on_status=lambda s: self._bridge.status_ready.emit(s),
            watchdog=self._watchdog,
        )
        if mode == "B" and isinstance(self._output_window, MirrorWindow):
            self._output_window.attach_pipeline(self._pipeline)
            self._pipeline.enable_raw_capture = True  # dedicated fast thread for a smooth mirror background
        self._active_capture_monitor = capture_monitor
        self._pipeline.start(capture_monitor)

        self.start_button.setText("■ หยุด")
        self.status_label.setText(f"กำลังทำงาน... (โหมด {mode})")

    def _stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._output_window is not None:
            self._output_window.close()
            self._output_window = None
        self._active_capture_monitor = None
        self.start_button.setText("▶ เริ่มแปล")
        self.status_label.setText("หยุดแล้ว")

    def _check_watchdog(self) -> None:
        """spec section 3D/15: if a pipeline thread has stalled beyond
        watchdog.stall_seconds, restart the whole pipeline (simpler and
        safer than trying to resurrect a single thread mid-flight given
        our threading model) with backoff, and say so via the status
        label -- never a popup that interrupts the user (spec section 3D:
        "ไม่มีหน้าต่างเด้งขัดจังหวะ")."""
        if self._pipeline is None or self._active_capture_monitor is None:
            return
        watched = ("capture_ocr", "fast_translate", "raw_capture") if self._pipeline.enable_raw_capture else ("capture_ocr", "fast_translate")
        for name in watched:
            if self._watchdog.should_restart(name):
                logger.warning("ui_main: watchdog restarting pipeline (stalled component: %s)", name)
                monitor = self._active_capture_monitor
                was_mirror = isinstance(self._output_window, MirrorWindow)
                self._pipeline.stop()
                self._pipeline = Pipeline(
                    cfg=self.cfg,
                    on_frame=lambda f: self._bridge.frame_ready.emit(f),
                    on_status=lambda s: self._bridge.status_ready.emit(s),
                    watchdog=self._watchdog,
                )
                if was_mirror:
                    self._output_window.attach_pipeline(self._pipeline)
                    self._pipeline.enable_raw_capture = True
                self._pipeline.start(monitor)
                self._watchdog.restarted(name)
                self.status_label.setText(f"รีสตาร์ทอัตโนมัติ ({name} ค้าง)")
                return

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

    def _open_region_editor(self) -> None:
        from gametrans.ui_region_editor import RegionEditorWindow

        idx = self.monitor_combo.currentIndex()
        if idx < 0 or idx >= len(self._monitors):
            self.status_label.setText("ไม่พบจอที่เลือก")
            return
        monitor = self._monitors[idx]

        # Prefer the profile the running pipeline actually picked; if the
        # pipeline isn't running, resolve it the same way it would.
        from gametrans.profiles import GENERIC_PROFILE

        if self._pipeline is not None and self._pipeline.active_profile is not None:
            profile = self._pipeline.active_profile
        else:
            from gametrans.pipeline import _default_profile_selector

            try:
                profile = _default_profile_selector(self.cfg) or GENERIC_PROFILE
            except Exception:  # noqa: BLE001 - editor must open even if detection fails
                profile = GENERIC_PROFILE

        editor = RegionEditorWindow(profile, monitor, presets_dir=self.cfg.get("regions", {}).get("preset_dir", "presets"), parent=self)
        editor.exec()

    def _open_wizard(self) -> None:
        from gametrans.profile_wizard_ui import WizardDialog

        idx = self.monitor_combo.currentIndex()
        if idx < 0 or idx >= len(self._monitors):
            self.status_label.setText("ไม่พบจอที่เลือก")
            return
        monitor = self._monitors[idx]

        wizard = WizardDialog(monitor, parent=self)
        wizard.exec()

    # ------------------------------------------------------ signal slots

    def _on_frame_main_thread(self, frame: FrameResult) -> None:
        if isinstance(self._output_window, (OverlayWindow, PanelWindow)):
            handler = getattr(self._output_window, "update_frame", None) or getattr(self._output_window, "on_frame", None)
            if handler is not None:
                handler(frame)
        # MirrorWindow pulls via its own QTimer + pipeline.snapshot() and
        # does not need this push signal (spec 3A: must not slow the OCR
        # loop down; decoupling the render rate achieves that).

    def _on_status_main_thread(self, status: StatusUpdate) -> None:
        self.status_label.setText(
            f"OCR {status.ocr_ms:.0f} ms · {status.block_count} ข้อความ · ชั้น {status.active_tier}"
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.tray is not None and not self._force_quit:
            # run_in_tray: closing the window (X button) minimizes to tray
            # instead of quitting -- the pipeline keeps running (spec
            # section 3D: autostart/always-on, the user presses "หยุด"
            # explicitly rather than the app stopping itself).
            event.ignore()
            self.hide()
            return
        self._unregister_hotkeys()
        self._stop()
        super().closeEvent(event)
