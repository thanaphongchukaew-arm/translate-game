"""Headless GUI smoke tests: construct every widget and drive its
update/paint/slot code paths using Qt's "offscreen" platform plugin, which
needs no real window station (sidesteps the window-station isolation that
makes on-screen visibility unverifiable from this tool environment -- see
DECISIONS.md phase 5). This does NOT prove the window is visible/usable on
a real desktop; it proves the widget code doesn't raise and produces the
data it's supposed to.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from gametrans.layout import Block
from gametrans.pipeline import FrameResult, TranslatedBlock
from gametrans.platform_win import MonitorInfo
from gametrans.store import Store


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _monitor():
    return MonitorInfo(index=0, left=0, top=0, width=800, height=600, dpi_scale=1.0, is_primary=True, device_name="TEST")


def _block(text="Hello"):
    return Block(id=0, x1=10, y1=10, x2=200, y2=40, text=text, line_h=20.0, first_seen=0.0, last_seen=0.0, stable_cycles=1, stable_since=0.0)


def test_overlay_window_constructs_and_shows(qapp):
    from gametrans.overlay import OverlayWindow

    win = OverlayWindow(_monitor())
    win.show()
    assert win.width() == 800
    assert win.height() == 600
    win.close()


def test_overlay_window_renders_a_frame_without_raising(qapp):
    from gametrans.overlay import OverlayWindow

    win = OverlayWindow(_monitor())
    win.show()
    frame = FrameResult(
        frame_id=1,
        blocks=(TranslatedBlock(block=_block(), thai="สวัสดี", final=True),),
        capture_width=800,
        capture_height=600,
    )
    win.update_frame(frame)
    win.repaint()  # forces paintEvent synchronously
    win.close()


def test_overlay_window_handles_empty_frame(qapp):
    from gametrans.overlay import OverlayWindow

    win = OverlayWindow(_monitor())
    win.show()
    win.update_frame(FrameResult(frame_id=1, blocks=(), capture_width=800, capture_height=600))
    win.repaint()
    win.close()


def test_overlay_scales_coordinates_when_window_size_differs_from_capture(qapp):
    """Regression guard for spec section 8.8: never assume 1:1 pixel
    mapping between capture resolution and overlay window size."""
    from gametrans.overlay import OverlayWindow

    win = OverlayWindow(_monitor())
    win.resize(400, 300)  # half the capture resolution
    win.show()
    frame = FrameResult(
        frame_id=1,
        blocks=(TranslatedBlock(block=_block(), thai="test", final=True),),
        capture_width=800,
        capture_height=600,
    )
    win.update_frame(frame)
    win.repaint()  # must not raise even though sx=sy=0.5
    win.close()


def test_main_window_constructs(qapp, tmp_path):
    from gametrans.ui_main import MainWindow

    cfg = {
        "overlay": {"font": "Arial", "min_font_px": 11},
        "text": {"overrides_path": str(tmp_path / "o.json"), "glossary_path": str(tmp_path / "g.json")},
        "cache": {"path": str(tmp_path / "c.json")},
        "fast": {}, "ocr": {}, "layout": {},
    }
    win = MainWindow(cfg)
    assert win.windowTitle() == "Game Screen Translator"
    assert win.start_button.text() == "▶ เริ่มแปล"
    win.close()


def test_main_window_open_manager_without_running_pipeline(qapp, tmp_path):
    from gametrans.ui_main import MainWindow

    cfg = {
        "overlay": {}, "fast": {}, "ocr": {}, "layout": {},
        "text": {"overrides_path": str(tmp_path / "o.json"), "glossary_path": str(tmp_path / "g.json")},
        "cache": {"path": str(tmp_path / "c.json")},
    }
    win = MainWindow(cfg)
    win._open_manager()
    assert win._manager_dialog is not None
    win.close()


def test_manager_dialog_shows_overrides_and_glossary(qapp, tmp_path):
    from gametrans.ui_manager import ManagerDialog

    store = Store(overrides_path=tmp_path / "o.json", glossary_path=tmp_path / "g.json", cache_path=tmp_path / "c.json")
    store.load()
    store.set_override("Hello", "สวัสดี")
    store.set_glossary_term("Potion", "ยา")

    dialog = ManagerDialog(store)
    dialog.refresh()
    assert dialog.cache_table.rowCount() == 1
    assert dialog.cache_table.item(0, 0).text() == "Hello"
    assert dialog.glossary_table.rowCount() == 1
    dialog.close()


def test_manager_dialog_save_override_from_selected_row(qapp, tmp_path):
    from gametrans.ui_manager import ManagerDialog

    store = Store(overrides_path=tmp_path / "o.json", glossary_path=tmp_path / "g.json", cache_path=tmp_path / "c.json")
    store.load()
    store.put("Hello", "ทดสอบ", tier=1, final=False)

    dialog = ManagerDialog(store)
    dialog.refresh()
    assert dialog.cache_table.rowCount() == 1
    dialog.cache_table.selectRow(0)
    dialog._on_save_override()

    assert store.get_overrides() == {"Hello": "ทดสอบ"}
    dialog.close()


def test_manager_dialog_add_glossary_term(qapp, tmp_path):
    from gametrans.ui_manager import ManagerDialog

    store = Store(overrides_path=tmp_path / "o.json", glossary_path=tmp_path / "g.json", cache_path=tmp_path / "c.json")
    store.load()

    dialog = ManagerDialog(store)
    dialog.term_input.setText("Sword")
    dialog.translation_input.setText("ดาบ")
    dialog._on_add_glossary_term()

    assert store.get_glossary() == {"Sword": "ดาบ"}
    dialog.close()


def _two_monitor_cfg(tmp_path):
    return {
        "overlay": {}, "fast": {}, "ocr": {}, "layout": {}, "display": {"mirror_fps": 30},
        "text": {"overrides_path": str(tmp_path / "o.json"), "glossary_path": str(tmp_path / "g.json")},
        "cache": {"path": str(tmp_path / "c.json")},
    }


def test_main_window_defaults_to_mode_b_with_two_monitors(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(
        ui_main_mod,
        "enumerate_monitors",
        lambda: [_monitor_stub(0, True), _monitor_stub(1, False, left=1920)],
    )
    from gametrans.ui_main import MainWindow

    win = MainWindow(_two_monitor_cfg(tmp_path))
    assert win.mode_combo.currentData() == "B"
    assert win.monitor_combo.currentIndex() == 0
    assert win.output_monitor_combo.currentIndex() == 1
    win.close()


def test_main_window_defaults_to_mode_a_with_one_monitor(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_two_monitor_cfg(tmp_path))
    assert win.mode_combo.currentData() == "A"
    win.close()


def test_main_window_falls_back_to_mode_a_when_output_equals_capture_monitor(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(
        ui_main_mod,
        "enumerate_monitors",
        lambda: [_monitor_stub(0, True), _monitor_stub(1, False, left=1920)],
    )
    from gametrans.ui_main import MainWindow

    win = MainWindow(_two_monitor_cfg(tmp_path))
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("B"))
    win.monitor_combo.setCurrentIndex(0)
    win.output_monitor_combo.setCurrentIndex(0)  # same as capture monitor

    mode, capture_monitor, output_monitor = win._resolve_mode_and_monitors()
    assert mode == "A"
    win.close()


def test_main_window_watchdog_restarts_stalled_pipeline(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    class FakePipeline:
        """Stands in for the real Pipeline (no GPU/screen/model needed):
        just enough surface (store, start/stop) for _check_watchdog()'s
        restart path to exercise, so this test proves the restart LOGIC
        works without needing real hardware."""

        instances: list = []

        def __init__(self, cfg, on_frame, on_status, watchdog=None, **kwargs):
            self.started_with = None
            FakePipeline.instances.append(self)

        def start(self, monitor):
            self.started_with = monitor

        def stop(self, timeout_s=3.0):
            pass

    monkeypatch.setattr(ui_main_mod, "Pipeline", FakePipeline)

    win = MainWindow(_two_monitor_cfg(tmp_path))
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("A"))
    win.monitor_combo.setCurrentIndex(0)
    win._start()

    assert isinstance(win._pipeline, FakePipeline)
    old_pipeline = win._pipeline

    # force the watchdog to believe capture_ocr stalled a long time ago
    win._watchdog.heartbeat("capture_ocr", now=0.0)
    import time as _time
    monkeypatch.setattr(_time, "monotonic", lambda: 100.0)

    win._check_watchdog()

    assert win._pipeline is not old_pipeline, "watchdog should have replaced the stalled pipeline"
    assert isinstance(win._pipeline, FakePipeline)
    assert win._pipeline.started_with is not None
    win._stop()


def _monitor_stub(index, is_primary, left=0):
    from gametrans.platform_win import MonitorInfo

    return MonitorInfo(index=index, left=left, top=0, width=1920, height=1080, dpi_scale=1.0, is_primary=is_primary, device_name=f"D{index}")


def test_manager_dialog_clear_cache_keeps_overrides(qapp, tmp_path):
    from gametrans.ui_manager import ManagerDialog

    store = Store(overrides_path=tmp_path / "o.json", glossary_path=tmp_path / "g.json", cache_path=tmp_path / "c.json")
    store.load()
    store.set_override("Hello", "สวัสดี")
    store.put("World", "โลก", tier=1, final=False)

    dialog = ManagerDialog(store)
    dialog._on_clear_cache()

    assert store.get_overrides() == {"Hello": "สวัสดี"}
    assert store.lookup("World") is None
    dialog.close()
