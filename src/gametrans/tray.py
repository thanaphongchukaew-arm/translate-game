"""System tray icon (spec section 3D/13.7): lets the app keep running
minimized (`run_in_tray`), with a menu to show/hide the control window,
start/stop translation, and quit. Global hotkeys (Ctrl+Alt+T toggle
overlay, Ctrl+Alt+E open manager) are registered via platform_win but
their actual WM_HOTKEY delivery is NOT verified in this project's test
environment -- see DECISIONS.md phase 5B (the same window-station
isolation that blocked visually verifying the overlay applies here too).
If registration fails, the app must keep working without hotkeys (spec
section 13.7: "ถ้าลงทะเบียน hotkey ไม่ได้ให้แจ้งแล้วทำงานต่อ").
"""
from __future__ import annotations

import logging

from PySide6 import QtGui, QtWidgets

logger = logging.getLogger("gametrans.tray")


def _build_icon() -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(32, 32)
    pixmap.fill(QtGui.QColor(30, 30, 40))
    painter = QtGui.QPainter(pixmap)
    painter.setPen(QtGui.QColor(255, 255, 255))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(20)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0084, "T")  # Qt.AlignCenter value, avoid extra import
    painter.end()
    return QtGui.QIcon(pixmap)


class TrayIcon(QtWidgets.QSystemTrayIcon):
    def __init__(self, main_window: QtWidgets.QWidget) -> None:
        super().__init__(_build_icon(), main_window)
        self.main_window = main_window
        self.setToolTip("Game Screen Translator")

        menu = QtWidgets.QMenu()
        self.toggle_show_action = menu.addAction("แสดง/ซ่อนหน้าต่างควบคุม")
        self.toggle_show_action.triggered.connect(self._toggle_main_window)

        self.toggle_run_action = menu.addAction("เริ่ม/หยุด แปล")
        self.toggle_run_action.triggered.connect(self._toggle_run)

        menu.addSeparator()
        quit_action = menu.addAction("ออกจากโปรแกรม")
        quit_action.triggered.connect(self._quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self._toggle_main_window()

    def _toggle_main_window(self) -> None:
        if self.main_window.isVisible():
            self.main_window.hide()
        else:
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _toggle_run(self) -> None:
        self.main_window._on_start_stop_clicked()

    def _quit(self) -> None:
        self.main_window._force_quit = True
        self.main_window.close()
        QtWidgets.QApplication.instance().quit()
