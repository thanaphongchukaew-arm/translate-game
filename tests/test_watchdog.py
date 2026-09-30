import time

from gametrans.watchdog import Watchdog


def test_not_stalled_right_after_heartbeat():
    wd = Watchdog(stall_seconds=10)
    wd.heartbeat("capture_ocr", now=100.0)
    assert wd.is_stalled("capture_ocr", now=105.0) is False


def test_stalled_after_stall_seconds_with_no_heartbeat():
    wd = Watchdog(stall_seconds=10)
    wd.heartbeat("capture_ocr", now=100.0)
    assert wd.is_stalled("capture_ocr", now=111.0) is True


def test_unknown_component_is_not_stalled():
    wd = Watchdog(stall_seconds=10)
    assert wd.is_stalled("never_registered", now=1000.0) is False


def test_should_restart_true_when_stalled_and_under_rate_limit():
    wd = Watchdog(stall_seconds=10, max_restarts_per_min=6)
    wd.heartbeat("x", now=0.0)
    assert wd.should_restart("x", now=11.0) is True


def test_should_restart_false_when_not_stalled():
    wd = Watchdog(stall_seconds=10)
    wd.heartbeat("x", now=0.0)
    assert wd.should_restart("x", now=5.0) is False


def test_restarted_resets_heartbeat_and_records_timestamp():
    wd = Watchdog(stall_seconds=10)
    wd.heartbeat("x", now=0.0)
    wd.restarted("x", now=11.0)
    assert wd.is_stalled("x", now=11.5) is False  # heartbeat was just reset


def test_backoff_prevents_immediate_second_restart():
    wd = Watchdog(stall_seconds=10)
    wd.heartbeat("x", now=0.0)
    wd.restarted("x", now=11.0)  # resets heartbeat to 11.0; backoff_seconds=2.0, backoff_until=13.0

    # still broken: no further heartbeats arrive. By now=12.0 it LOOKS
    # stalled again relative to stall_seconds (would be, if not for the
    # backoff window still being active).
    assert wd.is_stalled("x", now=21.5) is True  # 21.5 - 11.0 > 10
    assert wd.should_restart("x", now=13.5) is False  # stall_seconds not elapsed yet (only 2.5s since reset)
    assert wd.should_restart("x", now=22.0) is True  # both stall_seconds AND backoff window have passed


def test_backoff_doubles_on_repeated_restarts():
    wd = Watchdog(stall_seconds=1)
    wd.heartbeat("x", now=0.0)
    wd.restarted("x", now=1.0)
    state1 = wd._components["x"].backoff_seconds
    wd.restarted("x", now=100.0)
    state2 = wd._components["x"].backoff_seconds
    assert state2 == state1 * 2


def test_rate_limit_blocks_after_max_restarts_per_min():
    wd = Watchdog(stall_seconds=1, max_restarts_per_min=2)
    now = 0.0
    wd.heartbeat("x", now=now)
    for i in range(2):
        now += 2.0
        assert wd.should_restart("x", now=now) is True
        wd.restarted("x", now=now)
        # force it to look stalled again immediately after restart+backoff
        wd._components["x"].last_heartbeat = now - 100
        wd._components["x"].backoff_until = now  # bypass backoff for this test

    now += 2.0
    assert wd.should_restart("x", now=now) is False  # hit the 2-per-minute cap


def test_reset_backoff_returns_to_fast_restart():
    wd = Watchdog(stall_seconds=1)
    wd.heartbeat("x", now=0.0)
    wd.restarted("x", now=1.0)
    assert wd._components["x"].backoff_seconds > 1.0
    wd.reset_backoff("x")
    assert wd._components["x"].backoff_seconds == 1.0
    assert wd._components["x"].backoff_until == 0.0


def test_pipeline_reports_heartbeats_for_both_threads():
    """Real integration: Pipeline actually calls watchdog.heartbeat() from
    its background threads, not just a documented intent."""
    from gametrans.layout import OcrLine
    from gametrans.pipeline import Pipeline
    from gametrans.platform_win import MonitorInfo
    from gametrans.store import Store

    class FakeCapture:
        def grab(self, l, t, w, h):
            return object()

        def close(self):
            pass

    class FakeTranslator:
        def translate(self, texts, context=()):
            return [f"ทดสอบ:{t}" for t in texts]

    wd = Watchdog(stall_seconds=10)

    def make_store(tmp):
        s = Store(overrides_path=tmp / "o.json", glossary_path=tmp / "g.json", cache_path=tmp / "c.json")
        s.load()
        return s

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    pipe = Pipeline(
        cfg={"fast": {}, "cache": {}, "text": {}},
        on_frame=lambda f: None,
        on_status=lambda s: None,
        store=make_store(tmp),
        capture_factory=lambda monitor, cfg: FakeCapture(),
        ocr_func=lambda frame, cfg: [OcrLine(x1=0, y1=0, x2=10, y2=10, text="Hi", score=0.9)],
        fast_translator_factory=lambda cfg: FakeTranslator(),
        watchdog=wd,
    )
    mon = MonitorInfo(index=0, left=0, top=0, width=100, height=100, dpi_scale=1.0, is_primary=True, device_name="T")
    pipe.start(mon)
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not wd.is_stalled("capture_ocr") and not wd.is_stalled("fast_translate"):
                break
            time.sleep(0.02)
    finally:
        pipe.stop()

    assert wd.is_stalled("capture_ocr", now=time.monotonic()) is False
    assert wd.is_stalled("fast_translate", now=time.monotonic()) is False
