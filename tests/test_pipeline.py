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


def test_capture_backend_failure_does_not_crash_process(store):
    def failing_factory(monitor, cfg):
        raise RuntimeError("no capture backend available")

    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=store,
        capture_factory=failing_factory,
        ocr_func=FakeOcr([]),
        fast_translator_factory=lambda cfg: FakeTranslator(),
    )
    pipe.start(_monitor())
    time.sleep(0.1)
    pipe.stop()  # must not raise/hang
