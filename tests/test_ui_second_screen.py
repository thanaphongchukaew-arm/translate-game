from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

from gametrans.layout import Block
from gametrans.pipeline import FrameResult, Pipeline, TranslatedBlock
from gametrans.platform_win import MonitorInfo
from gametrans.ui_second_screen import MirrorWindow, PanelWindow, _median_fill_color, _frame_to_qimage


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _monitor(index=1, left=1920):
    return MonitorInfo(index=index, left=left, top=0, width=800, height=600, dpi_scale=1.0, is_primary=False, device_name="TEST2")


def _block(x1=10, y1=10, x2=100, y2=40):
    return Block(id=0, x1=x1, y1=y1, x2=x2, y2=y2, text="Hello", line_h=20.0, first_seen=0.0, last_seen=0.0, stable_cycles=1, stable_since=0.0)


def test_median_fill_color_uniform_region_returns_that_color():
    frame = np.full((100, 100, 3), (50, 100, 200), dtype=np.uint8)  # BGR
    r, g, b = _median_fill_color(frame, 20, 20, 60, 60)
    assert (r, g, b) == (200, 100, 50)  # returned as RGB


def test_median_fill_color_handles_edge_box_without_crashing():
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    color = _median_fill_color(frame, 0, 0, 5, 5)
    assert len(color) == 3


def test_frame_to_qimage_has_correct_dimensions():
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    img = _frame_to_qimage(frame)
    assert img.width() == 80
    assert img.height() == 60


def test_mirror_window_constructs_on_second_monitor(qapp):
    win = MirrorWindow(_monitor())
    assert win.windowTitle() == "Game Translator - Output"
    assert win.x() == 1920
    win.close()


def test_mirror_window_renders_without_a_pipeline_attached(qapp):
    win = MirrorWindow(_monitor())
    win.show()
    win.repaint()  # must show the "waiting" placeholder, not crash
    win.close()


def test_mirror_window_renders_a_real_frame_with_blocks(qapp):
    win = MirrorWindow(_monitor())
    win.show()

    frame = np.full((600, 800, 3), (40, 40, 40), dtype=np.uint8)
    result = FrameResult(
        frame_id=1,
        blocks=(TranslatedBlock(block=_block(), thai="สวัสดี", final=True),),
        capture_width=800, capture_height=600, frame_image=frame,
    )

    class _FakePipeline:
        def snapshot(self):
            return result

    win.attach_pipeline(_FakePipeline())
    win._pull_and_repaint()
    win.repaint()
    win.close()


def test_mirror_window_does_not_mutate_the_shared_frame_image(qapp):
    """frame_image is a shared reference (spec 3A: no re-capture) --
    painting over it for display must never corrupt the original array
    other consumers (e.g. a future OCR pass) might still be reading."""
    win = MirrorWindow(_monitor())
    win.show()

    frame = np.full((600, 800, 3), (40, 40, 40), dtype=np.uint8)
    original = frame.copy()
    result = FrameResult(
        frame_id=1,
        blocks=(TranslatedBlock(block=_block(), thai="test", final=True),),
        capture_width=800, capture_height=600, frame_image=frame,
    )

    class _FakePipeline:
        def snapshot(self):
            return result

    win.attach_pipeline(_FakePipeline())
    win._pull_and_repaint()
    win.repaint()
    win.close()

    assert np.array_equal(frame, original), "MirrorWindow must copy frame_image before drawing on it"


def test_panel_window_appends_new_lines_and_dedupes(qapp):
    win = PanelWindow()
    win.show()

    frame1 = FrameResult(
        frame_id=1,
        blocks=(TranslatedBlock(block=_block(), thai="สวัสดี", final=True),),
        capture_width=800, capture_height=600,
    )
    win.on_frame(frame1)
    assert win.list_widget.count() == 1

    # same block id + same text again -> must NOT duplicate
    win.on_frame(frame1)
    assert win.list_widget.count() == 1

    # same block id, DIFFERENT text (typewriter progressed) -> new entry
    frame2 = FrameResult(
        frame_id=2,
        blocks=(TranslatedBlock(block=_block(), thai="สวัสดีครับ", final=True),),
        capture_width=800, capture_height=600,
    )
    win.on_frame(frame2)
    assert win.list_widget.count() == 2
    win.close()


def test_panel_window_caps_history_length(qapp):
    win = PanelWindow()
    win._max_items = 5
    win.show()

    for i in range(10):
        b = Block(id=i, x1=0, y1=0, x2=10, y2=10, text=f"t{i}", line_h=10.0, first_seen=0.0, last_seen=0.0, stable_cycles=1, stable_since=0.0)
        frame = FrameResult(frame_id=i, blocks=(TranslatedBlock(block=b, thai=f"line{i}", final=True),), capture_width=100, capture_height=100)
        win.on_frame(frame)

    assert win.list_widget.count() == 5
    assert win.list_widget.item(4).text() == "line9"
    win.close()
