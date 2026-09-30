from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _cfg(tmp_path, run_in_tray=True):
    return {
        "overlay": {}, "fast": {}, "ocr": {}, "layout": {}, "display": {},
        "text": {"overrides_path": str(tmp_path / "o.json"), "glossary_path": str(tmp_path / "g.json")},
        "cache": {"path": str(tmp_path / "c.json")},
        "run_in_tray": run_in_tray,
    }


def _monitor_stub(index, is_primary, left=0):
    from gametrans.platform_win import MonitorInfo

    return MonitorInfo(index=index, left=left, top=0, width=1920, height=1080, dpi_scale=1.0, is_primary=is_primary, device_name=f"D{index}")


def test_tray_icon_constructs(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path))
    assert win.tray is not None
    win.close()


def test_run_in_tray_false_means_no_tray_icon(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path, run_in_tray=False))
    assert win.tray is None
    win._force_quit = True
    win.close()


def test_closing_window_hides_instead_of_quitting_when_tray_enabled(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path))
    win.show()
    assert win.isVisible()
    win.close()  # simulates the user clicking the X button
    assert win.isVisible() is False  # hidden, not destroyed
    assert win.tray is not None  # app is still "running"

    # explicit quit path must actually close it
    win._force_quit = True
    win.close()


def test_tray_toggle_show_hides_and_shows_main_window(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path))
    win.show()
    assert win.isVisible()

    win.tray._toggle_main_window()
    assert win.isVisible() is False

    win.tray._toggle_main_window()
    assert win.isVisible() is True

    win._force_quit = True
    win.close()


def test_tray_quit_action_forces_real_close(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path))
    win.show()
    win.tray._quit()
    assert win._force_quit is True


def test_autostart_true_starts_pipeline_once_event_loop_runs(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])

    class FakePipeline:
        def __init__(self, cfg, on_frame, on_status, watchdog=None, **kwargs):
            self.started = False

        def start(self, monitor):
            self.started = True

        def stop(self, timeout_s=3.0):
            pass

    monkeypatch.setattr(ui_main_mod, "Pipeline", FakePipeline)
    from gametrans.ui_main import MainWindow

    cfg = _cfg(tmp_path)
    cfg["autostart"] = True
    win = MainWindow(cfg)
    assert win._pipeline is None  # not yet -- the singleShot(0, ...) hasn't fired

    QtWidgets.QApplication.processEvents()  # let the deferred autostart timer fire

    assert win._pipeline is not None
    assert win._pipeline.started is True
    win._force_quit = True
    win.close()


def test_autostart_false_does_not_start_pipeline(qapp, tmp_path, monkeypatch):
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])

    class FakePipeline:
        def __init__(self, cfg, on_frame, on_status, watchdog=None, **kwargs):
            pass

        def start(self, monitor):
            pass

        def stop(self, timeout_s=3.0):
            pass

    monkeypatch.setattr(ui_main_mod, "Pipeline", FakePipeline)
    from gametrans.ui_main import MainWindow

    cfg = _cfg(tmp_path)
    cfg["autostart"] = False
    win = MainWindow(cfg)
    QtWidgets.QApplication.processEvents()
    assert win._pipeline is None
    win._force_quit = True
    win.close()


def test_hotkey_registration_failure_does_not_raise(qapp, tmp_path, monkeypatch):
    """spec 13.7: failing to register a hotkey must not crash startup."""
    import gametrans.ui_main as ui_main_mod

    monkeypatch.setattr(ui_main_mod, "enumerate_monitors", lambda: [_monitor_stub(0, True)])
    monkeypatch.setattr(ui_main_mod, "register_hotkey", lambda *a, **k: False)
    from gametrans.ui_main import MainWindow

    win = MainWindow(_cfg(tmp_path))
    win.show()  # triggers _register_hotkeys() via showEvent -- must not raise
    win._force_quit = True
    win.close()
