"""List physical monitors with resolution, DPI scale, and primary flag.
Usage: python tools/list_monitors.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gametrans.platform_win import enumerate_monitors  # noqa: E402


def main() -> None:
    monitors = enumerate_monitors()
    if not monitors:
        print("ไม่พบจอภาพใด ๆ (ผิดปกติ)")
        return
    print(f"พบ {len(monitors)} จอ:\n")
    for m in monitors:
        primary = " (หลัก)" if m.is_primary else ""
        print(
            f"จอ {m.index}{primary}: {m.width}x{m.height} @ {int(m.dpi_scale * 100)}% "
            f"ตำแหน่ง=({m.left},{m.top}) device={m.device_name}"
        )


if __name__ == "__main__":
    main()
