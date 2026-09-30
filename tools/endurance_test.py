"""Endurance test (spec section 17/18 item 10, 21): run the real pipeline
continuously and sample RSS, thread count, and (if available) VRAM every
N seconds, watching for a leak (RSS climbing without bound), stuck
threads, or OCR cycle time degrading over the run.

Usage: python tools/endurance_test.py [duration_minutes] [sample_interval_s]
Writes a CSV to endurance_log.csv and prints a verdict at the end.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import psutil  # noqa: E402

from gametrans.pipeline import Pipeline  # noqa: E402
from gametrans.platform_win import enumerate_monitors  # noqa: E402


def get_vram_used_mb() -> float:
    try:
        import subprocess

        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            timeout=5,
        )
        return float(out.decode().strip().splitlines()[0])
    except Exception:  # noqa: BLE001 - VRAM sampling is best-effort only
        return -1.0


def main() -> None:
    duration_min = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    interval_s = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0

    monitors = enumerate_monitors()
    monitor = monitors[0]

    proc = psutil.Process()
    samples: list[dict] = []
    frame_count = 0
    ocr_ms_samples: list[float] = []

    def on_frame(f):
        nonlocal frame_count
        frame_count += 1
        ocr_ms_samples.append(f.ocr_ms)

    def on_status(s):
        pass

    pipe = Pipeline(
        cfg={
            "fast": {"model_dir": "models/fast/nllb200-600m-int8", "device": "auto"},
            "ocr": {"provider": "auto"},
            "cache": {}, "text": {}, "layout": {},
            "regions": {"profile_dir": "profiles", "active_profile": "generic"},
        },
        on_frame=on_frame,
        on_status=on_status,
    )
    pipe.start(monitor)

    print(f"เริ่มทดสอบความทนทาน {duration_min:.0f} นาที (เก็บตัวอย่างทุก {interval_s:.0f} วินาที)")
    start = time.monotonic()
    deadline = start + duration_min * 60

    try:
        while time.monotonic() < deadline:
            time.sleep(interval_s)
            elapsed_min = (time.monotonic() - start) / 60
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            n_threads = proc.num_threads()
            vram_mb = get_vram_used_mb()
            recent_ocr_ms = ocr_ms_samples[-50:] if ocr_ms_samples else [0.0]
            avg_ocr_ms = sum(recent_ocr_ms) / len(recent_ocr_ms)

            sample = {
                "elapsed_min": round(elapsed_min, 2),
                "rss_mb": round(rss_mb, 1),
                "threads": n_threads,
                "vram_mb": vram_mb,
                "frame_count": frame_count,
                "avg_ocr_ms_recent": round(avg_ocr_ms, 1),
            }
            samples.append(sample)
            print(
                f"[{elapsed_min:6.2f} min] RSS={rss_mb:8.1f}MB threads={n_threads:3d} "
                f"VRAM={vram_mb:7.1f}MB frames={frame_count:6d} avg_ocr={avg_ocr_ms:6.1f}ms"
            )
    finally:
        pipe.stop()

    out_path = ROOT / "endurance_log.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(samples[0].keys()) if samples else [])
        writer.writeheader()
        writer.writerows(samples)

    print(f"\nบันทึกผลไปที่ {out_path}")

    if len(samples) >= 3:
        rss_start = samples[0]["rss_mb"]
        rss_end = samples[-1]["rss_mb"]
        growth_pct = (rss_end - rss_start) / rss_start * 100 if rss_start else 0
        print(f"\nRSS เริ่มต้น: {rss_start:.1f}MB -> สิ้นสุด: {rss_end:.1f}MB ({growth_pct:+.1f}%)")
        thread_counts = [s["threads"] for s in samples]
        print(f"จำนวน thread: min={min(thread_counts)} max={max(thread_counts)}")
        ocr_times = [s["avg_ocr_ms_recent"] for s in samples if s["avg_ocr_ms_recent"] > 0]
        if len(ocr_times) >= 2:
            print(f"เวลา OCR เฉลี่ย: เริ่ม={ocr_times[0]:.1f}ms จบ={ocr_times[-1]:.1f}ms")
        verdict_leak = "น่าสงสัยว่ารั่ว ❌" if growth_pct > 50 else "ไม่พบสัญญาณรั่วชัดเจน ✅"
        verdict_threads = "thread ค้างเพิ่มขึ้นเรื่อยๆ ❌" if max(thread_counts) - min(thread_counts) > 5 else "จำนวน thread คงที่ ✅"
        print(f"\nสรุป RSS: {verdict_leak}")
        print(f"สรุป thread: {verdict_threads}")


if __name__ == "__main__":
    main()
