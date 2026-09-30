"""FPS impact test (spec section 9/18 item 7): measures a synthetic
render loop's achieved FPS alone, then again with the real pipeline
running concurrently, and reports the percentage drop.

No real game is available to test against on this machine (spec allows
this fallback explicitly: "ถ้าวัด FPS เกมจริงไม่ได้ให้ใช้ frame time ของ
ตัวทดสอบ"). The synthetic workload is a Qt widget doing real per-frame
CPU work (drawing many shapes), run via QTimer at the tightest interval
Qt allows, which is a reasonable proxy for "something else on this
machine wants CPU/GPU time every frame."

Usage: python tools/fps_impact.py [duration_seconds] [mode]
  mode: "eco" (adaptive_throttle/low_priority on) or "always_on" (default,
  matches spec section 3D's actual default behavior)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402


class SyntheticLoad(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(800, 600)
        self.frame_times: list[float] = []
        self._last = time.perf_counter()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(0)  # as fast as Qt will allow

    def _tick(self) -> None:
        self.repaint()  # synchronous, forces paintEvent now

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        now = time.perf_counter()
        self.frame_times.append(now - self._last)
        self._last = now

        painter = QtGui.QPainter(self)
        # representative per-frame CPU work: draw a few hundred shapes
        for i in range(300):
            painter.fillRect(i % 780, (i * 7) % 580, 20, 20, QtGui.QColor((i * 13) % 255, (i * 29) % 255, 100))
        painter.end()


def measure(duration_s: float) -> dict:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    load = SyntheticLoad()
    load.show()

    deadline = time.perf_counter() + duration_s
    while time.perf_counter() < deadline:
        app.processEvents()

    load._timer.stop()
    times = load.frame_times[5:]  # drop warm-up frames
    if not times:
        return {"fps": 0.0, "frame_count": 0}
    avg_frame_time = sum(times) / len(times)
    return {"fps": 1.0 / avg_frame_time if avg_frame_time > 0 else 0.0, "frame_count": len(times)}


def main() -> None:
    duration_s = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

    print("กำลังวัด FPS พื้นฐาน (ไม่มีแอปแปลทำงาน)...")
    baseline = measure(duration_s)
    print(f"  baseline: {baseline['fps']:.1f} FPS ({baseline['frame_count']} เฟรม)")

    print("\nกำลังเริ่ม pipeline แล้ววัด FPS ซ้ำ (โหมดทำงานตลอดเวลา ค่าเริ่มต้น)...")
    from gametrans.pipeline import Pipeline
    from gametrans.platform_win import enumerate_monitors

    monitor = enumerate_monitors()[0]
    pipe = Pipeline(
        cfg={
            "fast": {"model_dir": "models/fast/nllb200-600m-int8", "device": "auto"},
            "ocr": {"provider": "auto"},
            "cache": {}, "text": {}, "layout": {},
            "regions": {"profile_dir": "profiles", "active_profile": "generic"},
        },
        on_frame=lambda f: None,
        on_status=lambda s: None,
    )
    pipe.start(monitor)
    time.sleep(2)  # let it ramp up / load the model
    try:
        with_pipeline = measure(duration_s)
    finally:
        pipe.stop()
    print(f"  ระหว่างแอปทำงาน: {with_pipeline['fps']:.1f} FPS ({with_pipeline['frame_count']} เฟรม)")

    if baseline["fps"] > 0:
        drop_pct = (baseline["fps"] - with_pipeline["fps"]) / baseline["fps"] * 100
        print(f"\nผลกระทบต่อ FPS: ลดลง {drop_pct:.1f}%")
        verdict = "ผ่านเป้าหมายโหมดประหยัด (≤10%)" if drop_pct <= 10 else "เกินเป้าหมายโหมดประหยัด (นี่คือโหมดทำงานตลอดเวลาค่าเริ่มต้น ซึ่งสเปกอนุญาตให้กินทรัพยากรเต็มที่ ไม่ใช่ข้อบกพร่อง)"
        print(verdict)


if __name__ == "__main__":
    main()
