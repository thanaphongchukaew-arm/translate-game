"""Windows-only platform integration via ctypes (no pywin32 dependency):
multi-monitor enumeration with per-monitor DPI, screen-capture exclusion,
click-through overlay windows, and global hotkeys.

This module (plus ui_*.py, overlay.py, app.py) is exempt from the
"no PySide6 in core modules" rule in spec section 6 — it is exempt from
needing PySide6 in the first place since it only wraps Win32 APIs.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

logger = logging.getLogger("gametrans.platform_win")

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore

MDT_EFFECTIVE_DPI = 0
# WDA_EXCLUDEFROMCAPTURE requires Windows 10 2004+ (build 19041+); on older
# builds SetWindowDisplayAffinity silently no-ops or fails and callers must
# fall back to another anti-feedback-loop strategy (spec section 15).
WDA_EXCLUDEFROMCAPTURE = 0x00000011

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

MONITORINFOF_PRIMARY = 0x00000001


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int
    dpi_scale: float
    is_primary: bool
    device_name: str


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _get_dpi_scale(hmonitor) -> float:
    try:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        result = shcore.GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if result != 0 or dpi_x.value == 0:
            return 1.0
        return dpi_x.value / 96.0
    except OSError:
        return 1.0


def enumerate_monitors() -> list[MonitorInfo]:
    """Enumerate physical monitors in left/top order (deterministic), each
    with its real per-monitor DPI scale (section 8.8 — never assume 100%)."""
    monitors: list[MonitorInfo] = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(hmonitor, hdc, rect_ptr, lparam):  # noqa: ANN001
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcMonitor
            monitors.append(
                MonitorInfo(
                    index=-1,  # assigned after sorting, below
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                    dpi_scale=_get_dpi_scale(hmonitor),
                    is_primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    device_name=info.szDevice,
                )
            )
        return True

    callback = MonitorEnumProc(_callback)
    user32.EnumDisplayMonitors(0, 0, callback, 0)

    monitors.sort(key=lambda m: (m.top, m.left))
    return [
        MonitorInfo(
            index=i,
            left=m.left, top=m.top, width=m.width, height=m.height,
            dpi_scale=m.dpi_scale, is_primary=m.is_primary, device_name=m.device_name,
        )
        for i, m in enumerate(monitors)
    ]


def exclude_from_capture(hwnd: int) -> bool:
    """SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE). Returns False
    if unsupported — caller MUST fall back to another anti-feedback-loop
    strategy (e.g. hide overlay briefly before each capture), never assume
    success silently."""
    try:
        ok = user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE)
        return bool(ok)
    except OSError as exc:
        logger.warning("platform_win: exclude_from_capture failed (%s)", exc)
        return False


def make_click_through(hwnd: int) -> None:
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, style)


def register_hotkey(hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
    return bool(user32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, modifiers | MOD_NOREPEAT, vk))


def unregister_hotkey(hwnd: int, hotkey_id: int) -> bool:
    return bool(user32.UnregisterHotKey(wintypes.HWND(hwnd), hotkey_id))
