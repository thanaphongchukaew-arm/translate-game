from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from gametrans.platform_win import MonitorInfo
from gametrans.profiles import Profile
from gametrans.regions import Region


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _monitor():
    return MonitorInfo(index=0, left=0, top=0, width=1920, height=1080, dpi_scale=1.0, is_primary=True, device_name="TEST")


def _empty_profile():
    return Profile(
        id="test", display_name="Test Game", match_process=None, match_window_title=None,
        risk_level="low", source_lang="en", regions=(), glossary_path=None,
        capture_target_type="auto", display_mode_default="auto", notes="",
    )


def _profile_with_region():
    region = Region(name="dialogue_box", rect=(0.1, 0.7, 0.9, 0.95), preset="dialogue")
    return Profile(
        id="test", display_name="Test Game", match_process=None, match_window_title=None,
        risk_level="low", source_lang="en", regions=(region,), glossary_path=None,
        capture_target_type="auto", display_mode_default="auto", notes="",
    )


def test_editor_constructs_with_no_capture_backend_available(qapp, monkeypatch):
    """Capture may fail (no real screen in this test env) -- editor must
    fall back to a placeholder image, never crash."""
    import gametrans.ui_region_editor as mod

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: __import__("PySide6.QtGui", fromlist=["QImage"]).QImage(100, 100, __import__("PySide6.QtGui", fromlist=["QImage"]).QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_empty_profile(), _monitor())
    assert editor.regions == []
    editor.close()


def test_editor_shows_existing_regions_in_list(qapp, monkeypatch):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_profile_with_region(), _monitor())
    assert editor.region_list.count() == 1
    assert "dialogue_box" in editor.region_list.item(0).text()
    editor.close()


def test_dragging_a_rectangle_adds_a_region_with_correct_proportions(qapp, monkeypatch):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_empty_profile(), _monitor())

    # simulate the user answering the name/preset dialogs -- patched on the
    # editor instance, not PySide6's QInputDialog (its static methods are
    # C++-bound and can't be reliably monkeypatched; doing so left a real
    # dialog open and hung the test process).
    editor._prompt_new_region = lambda: ("my_region", "dialogue")

    # canvas pixmap is scaled to editor's display width; drag a rect
    # covering the left half, top half of the DISPLAYED pixmap
    pixmap = editor.canvas.pixmap()
    half_w, half_h = pixmap.width() // 2, pixmap.height() // 2
    widget_rect = QtCore.QRect(0, 0, half_w, half_h)

    editor._on_region_dragged(widget_rect)

    assert len(editor.regions) == 1
    region = editor.regions[0]
    assert region.name == "my_region"
    assert region.preset == "dialogue"
    # left/top half of the monitor -> proportional rect roughly (0,0,0.5,0.5)
    assert region.rect[0] == pytest.approx(0.0, abs=0.05)
    assert region.rect[1] == pytest.approx(0.0, abs=0.05)
    assert region.rect[2] == pytest.approx(0.5, abs=0.05)
    assert region.rect[3] == pytest.approx(0.5, abs=0.05)
    editor.close()


def test_cancelling_name_dialog_does_not_add_region(qapp, monkeypatch):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_empty_profile(), _monitor())
    editor._prompt_new_region = lambda: None  # user cancelled

    pixmap = editor.canvas.pixmap()
    editor._on_region_dragged(QtCore.QRect(0, 0, pixmap.width() // 2, pixmap.height() // 2))

    assert editor.regions == []
    editor.close()


def test_remove_selected_region(qapp, monkeypatch):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_profile_with_region(), _monitor())
    editor.region_list.setCurrentRow(0)
    editor._on_remove_selected()

    assert editor.regions == []
    assert editor.region_list.count() == 0
    editor.close()


def test_save_writes_profile_to_disk(qapp, monkeypatch, tmp_path):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage
    from gametrans.profiles import load_profile

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_profile_with_region(), _monitor())
    editor._show_info = lambda title, message: None
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profiles").mkdir()

    editor._on_save()

    reloaded = load_profile(tmp_path / "profiles" / "test.json")
    assert reloaded is not None
    assert len(reloaded.regions) == 1
    assert reloaded.regions[0].name == "dialogue_box"
    editor.close()


def _generic_profile_with_region():
    from gametrans.profiles import GENERIC_PROFILE
    from dataclasses import replace

    region = Region(name="dialogue_box", rect=(0.1, 0.7, 0.9, 0.95), preset="dialogue")
    return replace(GENERIC_PROFILE, regions=(region,))


def test_save_while_on_generic_profile_prompts_for_new_id_and_does_not_touch_generic_json(qapp, monkeypatch, tmp_path):
    """Regression test: GENERIC_PROFILE is the hardcoded, always-available
    zero-config fallback every unmatched game uses. Saving edited regions
    under id="generic" would write profiles/generic.json to disk, which
    load_all_profiles() would then load OVER the hardcoded default on
    every future run -- corrupting the shared fallback for every other
    unmatched game. Saving while on the generic profile must detour
    through a rename prompt instead of silently overwriting it."""
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage
    from gametrans.profiles import load_profile

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_generic_profile_with_region(), _monitor())
    editor._show_info = lambda title, message: None
    editor._prompt_new_profile_id = lambda: "my_new_game"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profiles").mkdir()

    editor._on_save()

    assert not (tmp_path / "profiles" / "generic.json").exists()
    reloaded = load_profile(tmp_path / "profiles" / "my_new_game.json")
    assert reloaded is not None
    assert reloaded.id == "my_new_game"
    assert len(reloaded.regions) == 1
    editor.close()


def test_save_while_on_generic_profile_cancelled_does_not_save_anything(qapp, monkeypatch, tmp_path):
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_generic_profile_with_region(), _monitor())
    editor._prompt_new_profile_id = lambda: None  # user cancelled the rename prompt
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profiles").mkdir()

    editor._on_save()

    assert list((tmp_path / "profiles").glob("*.json")) == []
    editor.close()


def test_invalid_dragged_rect_shows_warning_not_crash(qapp, monkeypatch):
    """A degenerate rect (e.g. dragged entirely outside 0..1 after
    rounding) must be rejected gracefully, not crash the editor."""
    import gametrans.ui_region_editor as mod
    from PySide6.QtGui import QImage

    monkeypatch.setattr(mod, "_capture_snapshot", lambda monitor: QImage(100, 100, QImage.Format_RGB32))
    editor = mod.RegionEditorWindow(_empty_profile(), _monitor())
    editor._prompt_new_region = lambda: ("zero_size", "dialogue")
    warnings = []
    editor._show_warning = lambda title, message: warnings.append((title, message))

    # a zero-width rect -> proportional rect with x1==x2 -> Region() raises
    # ValueError internally, which the editor must catch
    editor._on_region_dragged(QtCore.QRect(10, 10, 0, 0))

    assert editor.regions == []
    assert len(warnings) == 1
    editor.close()
