from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

from gametrans.layout import OcrLine
from gametrans.platform_win import MonitorInfo
from gametrans.profile_wizard_ui import WizardDialog


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _monitor():
    return MonitorInfo(index=0, left=0, top=0, width=800, height=600, dpi_scale=1.0, is_primary=True, device_name="TEST")


class _FakeCapture:
    def __init__(self, frame):
        self._frame = frame

    def grab(self, l, t, w, h):
        return self._frame

    def close(self):
        pass


def test_collect_sample_appends_a_frame(qapp, monkeypatch):
    frame = np.zeros((600, 800, 3), dtype="uint8")

    # create_backend is imported lazily inside _collect_one_sample -- patch
    # the real module it comes from, which the lazy import re-resolves
    # against at call time.
    import gametrans.capture as capture_mod
    monkeypatch.setattr(capture_mod, "create_backend", lambda *a, **k: _FakeCapture(frame))

    dialog = WizardDialog(_monitor())
    dialog._collect_one_sample()
    assert len(dialog.samples) == 1
    assert dialog.sample_count_label.text() == "เก็บแล้ว: 1 ภาพ"
    dialog.close()


def test_collect_sample_failure_does_not_crash(qapp, monkeypatch):
    import gametrans.capture as capture_mod

    def _raise(*a, **k):
        raise RuntimeError("no capture backend available")

    monkeypatch.setattr(capture_mod, "create_backend", _raise)
    dialog = WizardDialog(_monitor())
    dialog._collect_one_sample()  # must not raise
    assert len(dialog.samples) == 0
    dialog.close()


def test_analyze_with_no_samples_shows_info_and_does_not_crash(qapp):
    dialog = WizardDialog(_monitor())
    infos = []
    dialog._show_info = lambda title, message: infos.append((title, message))
    dialog._on_analyze()
    assert len(infos) == 1
    assert dialog.result is None
    dialog.close()


def test_analyze_with_samples_populates_result_and_label(qapp):
    dialog = WizardDialog(_monitor())
    dialog.samples = [np.zeros((600, 800, 3), dtype="uint8")]

    def fake_ocr(frame, cfg):
        return [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)]

    dialog._ocr_func = fake_ocr
    dialog._on_analyze()

    assert dialog.result is not None
    assert len(dialog.result.regions) == 1
    assert "region_0" in dialog.result_label.text()


def test_build_profile_returns_none_before_analysis(qapp):
    dialog = WizardDialog(_monitor())
    assert dialog.build_profile("test_id", "Test Game") is None
    dialog.close()


def test_build_profile_after_analysis(qapp, monkeypatch):
    import gametrans.profile_wizard_ui as mod

    # get_foreground_window_info is imported at module level in
    # profile_wizard_ui.py, so the local binding there must be patched
    # (patching gametrans.platform_win's copy wouldn't affect it).
    monkeypatch.setattr(mod, "get_foreground_window_info", lambda: ("Game.exe", "My Game Window"))

    dialog = WizardDialog(_monitor())
    dialog.samples = [np.zeros((600, 800, 3), dtype="uint8")]
    dialog._ocr_func = lambda frame, cfg: [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)]
    dialog._on_analyze()

    profile = dialog.build_profile("my_game", "My Game")
    assert profile is not None
    assert profile.id == "my_game"
    assert profile.match_process == "Game.exe"
    assert profile.match_window_title == "My Game Window"
    assert len(profile.regions) == 1
    assert profile.risk_level == "medium"
    dialog.close()


def test_create_profile_without_analysis_shows_info(qapp):
    dialog = WizardDialog(_monitor())
    infos = []
    dialog._show_info = lambda title, message: infos.append((title, message))
    dialog._on_create_profile()
    assert len(infos) == 1


def test_create_profile_cancelled_name_prompt_does_nothing(qapp):
    dialog = WizardDialog(_monitor())
    dialog.samples = [np.zeros((600, 800, 3), dtype="uint8")]
    dialog._ocr_func = lambda frame, cfg: [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)]
    dialog._on_analyze()

    dialog._prompt_profile_name = lambda: None  # user cancelled
    opened = []
    dialog._open_region_editor_for = lambda profile: opened.append(profile)

    dialog._on_create_profile()
    assert opened == []


def test_create_profile_saves_and_opens_region_editor(qapp, monkeypatch, tmp_path):
    import gametrans.profile_wizard_ui as mod
    from gametrans.profiles import load_profile

    monkeypatch.setattr(mod, "get_foreground_window_info", lambda: ("Game.exe", "My Game"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profiles").mkdir()

    dialog = WizardDialog(_monitor())
    dialog.samples = [np.zeros((600, 800, 3), dtype="uint8")]
    dialog._ocr_func = lambda frame, cfg: [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)]
    dialog._on_analyze()

    dialog._prompt_profile_name = lambda: ("my_game", "My Game")
    opened = []
    dialog._open_region_editor_for = lambda profile: opened.append(profile)

    dialog._on_create_profile()

    assert len(opened) == 1
    assert opened[0].id == "my_game"

    reloaded = load_profile(tmp_path / "profiles" / "my_game.json")
    assert reloaded is not None
    assert reloaded.match_process == "Game.exe"
    dialog.close()


def test_open_region_editor_for_calls_editor_exec(qapp, monkeypatch):
    """RegionEditorWindow.exec() is a real modal call -- must be
    substituted, same lesson as test_ui_region_editor.py."""
    import gametrans.profile_wizard_ui as mod

    exec_calls = []

    class FakeEditor:
        def __init__(self, profile, monitor, parent=None):
            pass

        def exec(self):
            exec_calls.append(True)

    monkeypatch.setattr("gametrans.ui_region_editor.RegionEditorWindow", FakeEditor)

    dialog = WizardDialog(_monitor())
    dialog.samples = [np.zeros((600, 800, 3), dtype="uint8")]
    dialog._ocr_func = lambda frame, cfg: [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)]
    dialog._on_analyze()
    profile = dialog.build_profile("test", "Test")

    dialog._open_region_editor_for(profile)
    assert exec_calls == [True]
    dialog.close()


def test_auto_collect_toggle_starts_and_stops_timer(qapp):
    dialog = WizardDialog(_monitor())
    assert not dialog._auto_timer.isActive()
    dialog._toggle_auto_collect()
    assert dialog._auto_timer.isActive()
    dialog._toggle_auto_collect()
    assert not dialog._auto_timer.isActive()
    dialog.close()
