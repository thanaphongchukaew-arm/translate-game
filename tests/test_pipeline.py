"""Pipeline tests use fully injected fake capture/OCR/translator
dependencies -- no GPU, no real screen, no downloaded model needed. This
exercises the real threading/queueing/store-integration logic, just with
a fake "world" underneath it.
"""
from __future__ import annotations

import threading
import time

import pytest

from gametrans.layout import OcrLine
from gametrans.pipeline import Pipeline
from gametrans.platform_win import MonitorInfo
from gametrans.store import Store


class FakeCapture:
    def __init__(self):
        self.closed = False

    def grab(self, left, top, width, height):
        return object()  # OCR is faked too, so the "frame" content doesn't matter

    def close(self):
        self.closed = True


class FakeOcr:
    """Returns a fixed set of lines every call, tracking how many times it
    was invoked."""

    def __init__(self, lines_per_call):
        self.lines_per_call = lines_per_call
        self.call_count = 0

    def __call__(self, frame, cfg):
        self.call_count += 1
        return self.lines_per_call


class FakeTranslator:
    """Deterministic 'translation': prefixes with a Thai marker so guards'
    not_thai check passes. Tracks every batch it was asked to translate."""

    def __init__(self):
        self.batches: list[list[str]] = []

    def translate(self, texts, context=()):
        self.batches.append(list(texts))
        return [f"ทดสอบ:{t}" for t in texts]


class BadTranslator:
    """Always returns English (fails the not_thai guard) to test fallback."""

    def translate(self, texts, context=()):
        return list(texts)  # unchanged -> no Thai characters -> guard rejects


def _monitor(tmp_path=None):
    return MonitorInfo(index=0, left=0, top=0, width=800, height=600, dpi_scale=1.0, is_primary=True, device_name="TEST")


def _wait_until(predicate, timeout_s=3.0, interval_s=0.02):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


@pytest.fixture
def store(tmp_path):
    s = Store(
        overrides_path=tmp_path / "overrides.json",
        glossary_path=tmp_path / "glossary.json",
        cache_path=tmp_path / "cache.json",
    )
    s.load()
    return s


def test_pipeline_produces_frames_with_translated_blocks(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    translator = FakeTranslator()
    frames = []

    pipe = Pipeline(
        cfg={"fast": {"max_batch": 16}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    try:
        # tier-1 results are stored as final=False by design (only tier 2,
        # which is disabled in this project, ever sets final=True) -- so
        # wait for the translated VALUE to arrive, not for final=True.
        assert _wait_until(
            lambda: any(f.blocks and f.blocks[0].thai != "Hello" for f in frames)
        ), "translation never arrived"
    finally:
        pipe.stop()

    translated_blocks = [f for f in frames if f.blocks and f.blocks[0].thai != "Hello"]
    assert translated_blocks[-1].blocks[0].thai == "ทดสอบ:Hello"
    assert translated_blocks[-1].blocks[0].final is False


def test_pipeline_stop_joins_within_budget(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    time.sleep(0.2)
    t0 = time.monotonic()
    pipe.stop()
    assert time.monotonic() - t0 <= 3.0


def test_override_is_used_without_calling_translator(store):
    store.set_override("Hello", "คำแปลที่ผู้ใช้แก้เอง")
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    translator = FakeTranslator()
    frames = []

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: len(frames) >= 3)
    finally:
        pipe.stop()

    assert all(f.blocks[0].thai == "คำแปลที่ผู้ใช้แก้เอง" for f in frames)
    assert translator.batches == [], "translator should never be called when an override exists"


def test_duplicate_text_across_frames_is_translated_once(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    translator = FakeTranslator()
    frames = []

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: ocr.call_count >= 10)
        assert _wait_until(lambda: any(f.blocks and f.blocks[0].thai != "Hello" for f in frames))
        time.sleep(0.1)  # let a few more frames flow through post-translation
    finally:
        pipe.stop()

    total_texts_sent = sum(len(b) for b in translator.batches)
    assert total_texts_sent == 1, f"expected exactly 1 translate call for the repeated text, got {total_texts_sent}"


def test_bad_translation_falls_back_to_original_text_and_stops_retrying(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    translator = BadTranslator()
    frames = []

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: any(f.blocks and f.blocks[0].final for f in frames))
        time.sleep(0.1)
    finally:
        pipe.stop()

    final_blocks = [f for f in frames if f.blocks and f.blocks[0].final]
    assert final_blocks[-1].blocks[0].thai == "Hello"  # fell back to original, not junk

    entry = store.lookup("Hello")
    assert entry.final is True and entry.thai == "Hello"


def test_pure_number_text_skips_translation_entirely(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="120", score=0.9)])
    translator = FakeTranslator()
    frames = []

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: len(frames) >= 3)
    finally:
        pipe.stop()

    assert translator.batches == []
    assert frames[-1].blocks[0].thai == "120"
    assert frames[-1].blocks[0].final is True


def test_snapshot_returns_latest_frame(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    assert pipe.snapshot() is None
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: pipe.snapshot() is not None)
    finally:
        pipe.stop()


def test_raw_capture_thread_updates_much_faster_than_ocr_results(store):
    """Regression test for a real user request ("อยากให้หน้าจอแปล เป็น
    30fps+"): with a slow OCR function (simulating a real ~400-600ms
    full-screen scan), the dedicated raw-capture thread (enable_raw_capture)
    must keep grabbing frames at its own pace, not get stuck waiting for
    each slow OCR cycle -- proving MirrorWindow can redraw a fresh
    background at full capture speed instead of being capped at OCR's
    pace. A first version of this fix just published the raw frame
    earlier within the existing (still OCR-paced) loop iteration, which
    this test would correctly have failed -- the fix needed a genuinely
    separate thread, which is what's being verified here."""

    class SlowOcr:
        def __call__(self, frame, cfg):
            time.sleep(0.15)  # simulate a slow full-screen OCR pass
            return [OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)]

    class CountingCapture:
        def __init__(self):
            self.grab_count = 0

        def grab(self, l, t, w, h):
            self.grab_count += 1
            return object()

        def close(self):
            pass

    ocr_side_capture = CountingCapture()
    raw_capture = CountingCapture()
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}, "display": {"mirror_fps": 30}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: ocr_side_capture,
        raw_capture_factory=lambda monitor, cfg: raw_capture,
        ocr_func=SlowOcr(),
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.enable_raw_capture = True
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: pipe.snapshot_raw_frame() is not None)
        raw_count_at_start = raw_capture.grab_count
        ocr_count_at_start = ocr_side_capture.grab_count
        time.sleep(0.5)
        raw_count_after = raw_capture.grab_count
        ocr_count_after = ocr_side_capture.grab_count
    finally:
        pipe.stop()

    raw_grabs = raw_count_after - raw_count_at_start
    ocr_grabs = ocr_count_after - ocr_count_at_start
    # at 30fps target the raw thread should manage close to ~15 grabs in
    # 0.5s (generous lower bound to avoid timing flakiness); the OCR loop,
    # gated by the 150ms sleep, manages only ~3
    assert raw_grabs > 10, f"expected the dedicated raw-capture thread to run near 30fps, got {raw_grabs} grabs in 0.5s"
    assert raw_grabs > ocr_grabs * 2, f"raw capture ({raw_grabs}) should far outpace OCR-gated capture ({ocr_grabs})"


def _profile_with_region(name="dialogue_box", rect=(0.0, 0.7, 1.0, 1.0), preset="dialogue"):
    from gametrans.profiles import Profile
    from gametrans.regions import Region

    return Profile(
        id="test-profile", display_name="Test", match_process=None, match_window_title=None,
        risk_level="low", source_lang="en",
        regions=(Region(name=name, rect=rect, preset=preset),),
        glossary_path=None, capture_target_type="auto", display_mode_default="auto", notes="",
    )


def test_region_based_capture_crops_and_offsets_coordinates(store):
    """OCR lines detected inside a region crop must come back with
    coordinates in FULL-FRAME space (region pixel offset added), not
    crop-relative -- otherwise the overlay would draw in the wrong place."""
    profile = _profile_with_region(rect=(0.0, 0.5, 1.0, 1.0))  # bottom half of an 800x600 frame -> offset_y=300

    captured_regions = []

    def fake_ocr(crop_or_frame, cfg):
        # record what the OCR function actually received (should be the
        # CROPPED region, not the full frame) and return a line at a fixed
        # position relative to that crop.
        captured_regions.append(crop_or_frame)
        return [OcrLine(x1=10, y1=10, x2=100, y2=30, text="Hello", score=0.9)]

    frames = []
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: profile,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=fake_ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    # FakeCapture.grab returns a plain object(), not a real numpy frame --
    # crop_frame() needs a real array with .shape, so use a real one here.
    import numpy as np

    class NumpyCapture:
        def grab(self, l, t, w, h):
            return np.zeros((600, 800, 3), dtype="uint8")

        def close(self):
            pass

    pipe._capture_factory = lambda monitor, cfg: NumpyCapture()

    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: len(frames) >= 1 and frames[-1].blocks)
    finally:
        pipe.stop()

    block = frames[-1].blocks[0].block
    # region top-left in pixels is (0, 300); OCR reported (10,10) relative
    # to the crop, so full-frame coordinates must be (10, 310).
    assert block.y1 == 310.0
    assert block.x1 == 10.0


def test_region_based_capture_tracks_each_region_independently(store):
    """Two regions with the same text at different positions must not be
    matched against each other's tracking history."""
    from gametrans.profiles import Profile
    from gametrans.regions import Region

    profile = Profile(
        id="two-region", display_name="Two", match_process=None, match_window_title=None,
        risk_level="low", source_lang="en",
        regions=(
            Region(name="top", rect=(0.0, 0.0, 1.0, 0.5), preset="hud"),
            Region(name="bottom", rect=(0.0, 0.5, 1.0, 1.0), preset="dialogue"),
        ),
        glossary_path=None, capture_target_type="auto", display_mode_default="auto", notes="",
    )

    import numpy as np

    class NumpyCapture:
        def grab(self, l, t, w, h):
            return np.zeros((600, 800, 3), dtype="uint8")

        def close(self):
            pass

    def fake_ocr(crop, cfg):
        return [OcrLine(x1=5, y1=5, x2=50, y2=25, text="Same", score=0.9)]

    frames = []
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: profile,
        capture_factory=lambda monitor, cfg: NumpyCapture(),
        ocr_func=fake_ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: len(frames) >= 1 and len(frames[-1].blocks) == 2)
    finally:
        pipe.stop()

    ys = sorted(b.block.y1 for b in frames[-1].blocks)
    assert ys == [5.0, 305.0]  # top region's block stays near y=5, bottom region's near y=305


def test_no_regions_falls_back_to_full_screen_scan(store):
    """profile_selector returning a profile with no regions (or None)
    must behave exactly like the pre-regions generic full-screen path."""
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    frames = []
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=frames.append,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    try:
        assert _wait_until(lambda: len(frames) >= 1 and frames[-1].blocks)
    finally:
        pipe.stop()
    assert frames[-1].blocks[0].block.text == "Hello"


def test_max_ocr_fps_throttles_the_capture_loop(store):
    """spec section 9 (eco mode): a configured max_ocr_fps caps the loop
    rate. 0 (the default) must stay uncapped."""
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}, "capture": {"max_ocr_fps": 20}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    time.sleep(1.0)
    pipe.stop()

    # 20 fps for ~1s should give roughly 20 calls, NOT the tens of
    # thousands an uncapped loop produces in the same window (seen
    # elsewhere in this file with a FakeCapture that returns instantly).
    assert 10 <= ocr.call_count <= 35, f"expected ~20 OCR calls at 20fps cap, got {ocr.call_count}"


def test_max_ocr_fps_zero_stays_uncapped(store):
    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}, "capture": {"max_ocr_fps": 0}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    time.sleep(0.3)
    pipe.stop()
    assert ocr.call_count > 500, "uncapped loop should run far faster than a 20fps cap would allow"


def test_persistent_translate_failure_backs_off_instead_of_hammering(store):
    """Regression test for a real bug: a wrong model_dir in
    config.default.json made every real translate() call fail, and the
    loop retried every batch with zero backoff -- hundreds of failures
    per second, visible as severe lag in a real user report. This proves
    the circuit breaker actually engages."""

    class AlwaysFailingTranslator:
        def __init__(self):
            self.call_count = 0

        def translate(self, texts, context=()):
            self.call_count += 1
            raise RuntimeError("model file not found")

    ocr = FakeOcr([OcrLine(x1=0, y1=0, x2=100, y2=20, text="Hello", score=0.9)])
    translator = AlwaysFailingTranslator()
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=ocr,
        fast_translator_factory=lambda cfg: translator,
    )
    pipe.start(_monitor())
    time.sleep(1.5)
    pipe.stop()

    # without backoff this would be in the thousands (queue.get(timeout=0.05)
    # alone allows ~20/s minimum, but batching from an uncapped OCR loop
    # pushes it far higher); with the circuit breaker it should be small.
    assert translator.call_count < 50, f"expected backoff to sharply limit retries, got {translator.call_count} calls in 1.5s"


def test_capture_backend_failure_does_not_crash_process(store):
    def failing_factory(monitor, cfg):
        raise RuntimeError("no capture backend available")

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        profile_selector=lambda cfg: None,
        capture_factory=failing_factory,
        ocr_func=FakeOcr([]),
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    time.sleep(0.1)
    pipe.stop()  # must not raise/hang
