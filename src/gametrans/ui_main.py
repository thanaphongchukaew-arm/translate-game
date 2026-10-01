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


_STYLE = """
QWidget { background: #313338; color: #dbdee1; font-size: 14px; }
#topbar { background: #2b2d31; border-bottom: 1px solid #1e1f22; }
#title { font-size: 16px; font-weight: bold; color: #f2f3f5; background: transparent; }
#gear { background: transparent; border: none; font-size: 22px; color: #b5bac1; padding: 2px 8px; border-radius: 4px; }
#gear:hover { background: #3f4147; color: #f2f3f5; }
#sidebar { background: #2b2d31; }
#nav { background: transparent; border: none; outline: none; }
#nav::item { padding: 8px 10px; border-radius: 4px; color: #949ba4; }
#nav::item:hover { background: #35373c; color: #dbdee1; }
#nav::item:selected { background: #404249; color: #ffffff; }
#feed { background: #313338; border: none; }
#feed::item { padding: 8px 10px; border-radius: 4px; }
#feed::item:hover { background: #2e3035; }
#hint { color: #949ba4; font-size: 12px; background: transparent; }
#status { color: #b5bac1; background: transparent; }
#section { color: #b5bac1; font-size: 12px; font-weight: bold; margin-top: 10px; background: transparent; }
QPushButton { background: #4e5058; color: #ffffff; border: none; border-radius: 4px; padding: 8px 14px; }
QPushButton:hover { background: #6d6f78; }
QPushButton#primary { background: #5865f2; font-size: 15px; font-weight: bold; }
QPushButton#primary:hover { background: #4752c4; }
QComboBox, QLineEdit { background: #1e1f22; border: 1px solid #1e1f22; border-radius: 4px; padding: 7px 10px; color: #dbdee1; }
QComboBox QAbstractItemView { background: #2b2d31; selection-background-color: #404249; }
QTableWidget { background: #2b2d31; gridline-color: #3f4147; border: none; }
QHeaderView::section { background: #1e1f22; color: #b5bac1; border: none; padding: 6px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; padding: 8px 14px; color: #949ba4; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #5865f2; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #1a1b1e; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class _PipelineBridge(QtCore.QObject):
    frame_ready = QtCore.Signal(object)
    status_ready = QtCore.Signal(object)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Game Screen Translator")
        self.resize(760, 520)

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
        self.setStyleSheet(_STYLE)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- top bar: title on the left, settings gear in the corner
        bar = QtWidgets.QFrame()
        bar.setObjectName("topbar")
        bar_l = QtWidgets.QHBoxLayout(bar)
        bar_l.setContentsMargins(16, 8, 8, 8)
        self.title_label = QtWidgets.QLabel("Game Screen Translator")
        self.title_label.setObjectName("title")
        bar_l.addWidget(self.title_label)
        bar_l.addStretch(1)
        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setObjectName("gear")
        self.settings_button.setText("⚙")
        self.settings_button.setToolTip("ตั้งค่า")
        self.settings_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self._toggle_settings)
        bar_l.addWidget(self.settings_button)
        root.addWidget(bar)

        self.pages = QtWidgets.QStackedWidget()
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_home_page())
        self.pages.addWidget(self._build_settings_page())

    def _build_home_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(page)
        v.setContentsMargins(16, 12, 16, 12)

        self.feed = QtWidgets.QListWidget()
        self.feed.setObjectName("feed")
        self.feed.setWordWrap(True)
        self.feed.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.feed.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.feed.setFocusPolicy(QtCore.Qt.NoFocus)
        self._feed_items: dict[str, QtWidgets.QListWidgetItem] = {}
        v.addWidget(self.feed, 1)

        self.feed_hint = QtWidgets.QLabel("คำแปลล่าสุดจะแสดงที่นี่")
        self.feed_hint.setObjectName("hint")
        self.feed_hint.setAlignment(QtCore.Qt.AlignCenter)
        v.addWidget(self.feed_hint)

        self.start_button = QtWidgets.QPushButton("▶ เริ่มแปล")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumHeight(48)
        self.start_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.start_button.clicked.connect(self._on_start_stop_clicked)
        v.addWidget(self.start_button)

        self.status_label = QtWidgets.QLabel("ยังไม่เริ่มทำงาน")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        v.addWidget(self.status_label)

        self.offline_label = QtWidgets.QLabel("ทำงานออฟไลน์ ไม่ส่งข้อมูลออกนอกเครื่อง")
        self.offline_label.setObjectName("hint")
        self.offline_label.setAlignment(QtCore.Qt.AlignCenter)
        v.addWidget(self.offline_label)
        return page

    def _build_settings_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QtWidgets.QFrame()
        side.setObjectName("sidebar")
        side_l = QtWidgets.QVBoxLayout(side)
        side_l.setContentsMargins(8, 12, 8, 12)
        self.settings_nav = QtWidgets.QListWidget()
        self.settings_nav.setObjectName("nav")
        self.settings_nav.setFocusPolicy(QtCore.Qt.NoFocus)
        for name in ("จอและโหมด", "คำแปล", "เครื่องมือ"):
            self.settings_nav.addItem(name)
        side_l.addWidget(self.settings_nav, 1)
        back = QtWidgets.QPushButton("✕ กลับ")
        back.setCursor(QtCore.Qt.PointingHandCursor)
        back.clicked.connect(self._toggle_settings)
        side_l.addWidget(back)
        side.setFixedWidth(170)
        h.addWidget(side)

        self.settings_stack = QtWidgets.QStackedWidget()
        h.addWidget(self.settings_stack, 1)

        # -- general: monitors + mode
        general = QtWidgets.QWidget()
        g = QtWidgets.QVBoxLayout(general)
        g.setContentsMargins(24, 20, 24, 20)
        g.addWidget(self._section("จอที่จะแปล (จับภาพ)"))
        self.monitor_combo = QtWidgets.QComboBox()
        for m in self._monitors:
            self.monitor_combo.addItem(self._monitor_label(m))
        g.addWidget(self.monitor_combo)
        g.addWidget(self._section("โหมดแสดงผล"))
        self.mode_combo = QtWidgets.QComboBox()
        for key in ("A", "B", "C"):
            self.mode_combo.addItem(_MODE_LABELS[key], userData=key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        g.addWidget(self.mode_combo)
        self.output_section = self._section("จอที่แสดงผลคำแปล")
        g.addWidget(self.output_section)
        self.output_monitor_combo = QtWidgets.QComboBox()
        for m in self._monitors:
            self.output_monitor_combo.addItem(self._monitor_label(m))
        g.addWidget(self.output_monitor_combo)
        note = QtWidgets.QLabel("การเปลี่ยนค่าจะมีผลตอนกดเริ่มแปลครั้งถัดไป")
        note.setObjectName("hint")
        g.addWidget(note)
        g.addStretch(1)
        self.settings_stack.addWidget(general)

        # -- translations manager (embedded, filled in by _ensure_manager)
        self._manager_holder = QtWidgets.QWidget()
        self._manager_layout = QtWidgets.QVBoxLayout(self._manager_holder)
        self._manager_layout.setContentsMargins(16, 16, 16, 16)
        self.settings_stack.addWidget(self._manager_holder)

        # -- tools
        tools = QtWidgets.QWidget()
        t = QtWidgets.QVBoxLayout(tools)
        t.setContentsMargins(24, 20, 24, 20)
        self.region_editor_button = QtWidgets.QPushButton("แก้ไข region")
        self.region_editor_button.clicked.connect(self._open_region_editor)
        t.addWidget(self.region_editor_button)
        self.wizard_button = QtWidgets.QPushButton("สร้างโปรไฟล์จากเกมนี้")
        self.wizard_button.clicked.connect(self._open_wizard)
        t.addWidget(self.wizard_button)
        t.addStretch(1)
        self.settings_stack.addWidget(tools)

        self.settings_nav.currentRowChanged.connect(self._on_settings_nav)
        self.settings_nav.setCurrentRow(0)
        return page

    def _section(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("section")
        return label

    def _toggle_settings(self) -> None:
        in_settings = self.pages.currentIndex() == 1
        self.pages.setCurrentIndex(0 if in_settings else 1)
        self.settings_button.setText("⚙" if in_settings else "✕")

    def _show_settings_page(self, row: int) -> None:
        self.pages.setCurrentIndex(1)
        self.settings_button.setText("✕")
        self.settings_nav.setCurrentRow(row)

    def _on_settings_nav(self, row: int) -> None:
        if row < 0:
            return
        if row == 1:
            self._ensure_manager()
        self.settings_stack.setCurrentIndex(row)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == QtCore.Qt.Key_Escape and self.pages.currentIndex() == 1:
            self._toggle_settings()
            return
        super().keyPressEvent(event)

    def _add_feed(self, frame: FrameResult) -> None:
        for tb in frame.blocks:
            src, thai = tb.block.text, tb.thai
            if not src or not thai:
                continue
            item = self._feed_items.get(src)
            is_new = item is None
            if is_new:
                item = QtWidgets.QListWidgetItem()
                self.feed.addItem(item)
                self._feed_items[src] = item
                while self.feed.count() > 100:
                    old = self.feed.takeItem(0)
                    for k, v in list(self._feed_items.items()):
                        if v is old:
                            del self._feed_items[k]
                self.feed_hint.hide()
            item.setText(thai + "\n" + src)
            if is_new:
                self.feed.scrollToBottom()

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
        visible = mode in ("B", "C")
        self.output_monitor_combo.setVisible(visible)
        self.output_section.setVisible(visible)

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
        watched = ("capture", "ocr", "fast_translate")
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
                self._pipeline.start(monitor)
                self._watchdog.restarted(name)
                self.status_label.setText(f"รีสตาร์ทอัตโนมัติ ({name} ค้าง)")
                return

    def _ensure_manager(self) -> None:
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
            self._manager_dialog = ManagerDialog(store)
            self._manager_layout.addWidget(self._manager_dialog)
        self._manager_dialog.store = store
        self._manager_dialog.refresh()

    def _open_manager(self) -> None:
        self._ensure_manager()
        self._show_settings_page(1)
        self.show()
        self.raise_()

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
        self._add_feed(frame)
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
