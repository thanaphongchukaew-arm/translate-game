"""Phase 2 benchmark: OCR accuracy + speed on synthetic fixtures, and real
screen-capture speed (dxcam vs mss) against the actual monitors on this
machine. Run: python tools/benchmark.py
"""
from __future__ import annotations

import difflib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from gametrans.capture import create_backend, is_frame_black  # noqa: E402
from gametrans.ocr import run_ocr, get_engine  # noqa: E402
from gametrans.ocr_post import clean_text  # noqa: E402
from gametrans.platform_win import enumerate_monitors  # noqa: E402

FIXTURES_DIR = ROOT / "tests" / "fixtures" / "synthetic"


def _char_accuracy(expected: str, actual: str) -> float:
    if not expected and not actual:
        return 1.0
    return difflib.SequenceMatcher(None, expected, actual).ratio()


def bench_ocr() -> None:
    manifest = json.loads((FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))

    # warm up (loads models / JITs the session) — excluded from timing
    engine, active_provider = get_engine("auto")
    warm_img = np.array(Image.open(FIXTURES_DIR / manifest[0]["file"]).convert("RGB"))[:, :, ::-1]
    run_ocr(warm_img, cfg={"ocr": {"min_score": 0.3, "min_box_h": 5}})

    print(f"OCR provider ที่ใช้จริง: {active_provider}\n")
    print(f"{'ไฟล์':30s} {'ms':>7s} {'accuracy':>9s}  หมวด")
    print("-" * 70)

    times: list[float] = []
    accuracies: list[float] = []
    for entry in manifest:
        path = FIXTURES_DIR / entry["file"]
        img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1]

        t0 = time.perf_counter()
        lines = run_ocr(img, cfg={"ocr": {"min_score": 0.3, "min_box_h": 5}})
        elapsed_ms = (time.perf_counter() - t0) * 1000
        times.append(elapsed_ms)

        detected_sorted = sorted(lines, key=lambda ln: (ln.y1, ln.x1))
        actual_text = " ".join(clean_text(ln.text) for ln in detected_sorted)
        expected_text = " ".join(entry["expected_text"])

        if entry["category"] in ("empty", "black_frame"):
            acc = 1.0 if not lines else 0.0
        else:
            acc = _char_accuracy(expected_text, actual_text)
        accuracies.append(acc)

        print(f"{entry['file']:30s} {elapsed_ms:7.1f} {acc*100:8.1f}%  {entry['category']}")
        if acc < 0.95 and entry["category"] not in ("empty", "black_frame"):
            print(f"    คาดหวัง: {expected_text!r}")
            print(f"    ได้จริง:  {actual_text!r}")

    avg_acc = sum(accuracies) / len(accuracies)
    avg_ms = sum(times) / len(times)
    print("-" * 70)
    print(f"ค่าเฉลี่ย accuracy: {avg_acc*100:.1f}%  |  ค่าเฉลี่ยเวลา: {avg_ms:.1f} ms")
    verdict = "ผ่าน ✅" if avg_acc >= 0.95 else "ไม่ผ่าน ❌"
    print(f"เกณฑ์เฟส 2 (≥95% accuracy บนภาพทดสอบสะอาด): {verdict}")


def bench_capture() -> None:
    print("\n=== ความเร็วการจับภาพหน้าจอจริง ===")
    monitors = enumerate_monitors()
    if not monitors:
        print("ไม่พบจอภาพ ข้ามการทดสอบนี้")
        return
    mon = monitors[0]

    for backend_name in ("dxcam", "mss"):
        try:
            backend = create_backend(backend_name, monitor_index=mon.index)
        except Exception as exc:  # noqa: BLE001
            print(f"{backend_name}: ใช้งานไม่ได้ ({exc})")
            continue

        # warm up
        for _ in range(3):
            backend.grab(mon.left, mon.top, mon.width, mon.height)

        times = []
        black_count = 0
        for _ in range(20):
            t0 = time.perf_counter()
            frame = backend.grab(mon.left, mon.top, mon.width, mon.height)
            times.append((time.perf_counter() - t0) * 1000)
            if is_frame_black(frame):
                black_count += 1
        backend.close()

        avg = sum(times) / len(times)
        p95 = sorted(times)[int(len(times) * 0.95) - 1]
        print(f"{backend_name}: avg={avg:.2f}ms p95={p95:.2f}ms black_frames={black_count}/20")


if __name__ == "__main__":
    bench_ocr()
    bench_capture()
