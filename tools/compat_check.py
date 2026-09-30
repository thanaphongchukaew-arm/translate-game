"""Capture compatibility check CLI (spec section 3F).
Usage: python tools/compat_check.py [monitor_index] [duration_seconds]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gametrans.compat import run_compat_check  # noqa: E402
from gametrans.platform_win import enumerate_monitors  # noqa: E402


def main() -> None:
    monitor_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    monitors = enumerate_monitors()
    if not monitors or monitor_index >= len(monitors):
        print("ไม่พบจอภาพตามที่ระบุ")
        return
    monitor = monitors[monitor_index]

    print(f"ตรวจสอบจอ {monitor.index}: {monitor.width}x{monitor.height} (ใช้เวลา ~{duration*2:.0f} วินาที)\n")
    result = run_compat_check(monitor, duration_s=duration)

    print(f"{'backend':10s} {'ใช้ได้':8s} {'avg ms':>8s} {'fps':>8s}  ภาพดำ")
    print("-" * 55)
    for b in result.backends:
        status = "ได้" if b.available else f"ไม่ได้ ({b.error})"
        print(f"{b.name:10s} {status:8s} {b.avg_ms:8.2f} {b.fps:8.1f}  {b.black_frame_ratio*100:.0f}%")

    print(f"\nbackend ที่เลือกใช้: {result.chosen_backend}")
    for note in result.notes:
        print(f"หมายเหตุ: {note}")
    if not result.notes:
        print("ไม่พบปัญหาความเข้ากันได้ที่ตรวจจับได้")


if __name__ == "__main__":
    main()
