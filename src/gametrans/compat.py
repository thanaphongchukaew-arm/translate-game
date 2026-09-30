"""Capture compatibility check (spec section 3F): which capture backends
actually work on this machine/monitor right now, how fast, whether frames
are coming back black (exclusive fullscreen / DRM), and a best-effort HDR
heuristic. Results are always shown to the user — this module never
silently picks a fallback without saying so (spec section 20).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from gametrans.capture import create_backend, is_frame_black


@dataclass(frozen=True)
class BackendResult:
    name: str
    available: bool
    avg_ms: float
    fps: float
    black_frame_ratio: float
    error: str = ""


@dataclass(frozen=True)
class CompatResult:
    backends: tuple[BackendResult, ...]
    chosen_backend: str
    hdr_suspected: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def _hdr_heuristic(frame) -> bool:
    """Very rough heuristic: HDR content displayed through an SDR capture
    path often looks washed out (low color saturation) at a mid-range
    brightness. This WILL have false positives/negatives — it exists only
    to prompt the user to look closer, never to silently change behavior."""
    if frame is None:
        return False
    # frame is BGR
    b = frame[:, :, 0].astype("float32")
    g = frame[:, :, 1].astype("float32")
    r = frame[:, :, 2].astype("float32")
    maxc = np_max3(r, g, b)
    minc = np_min3(r, g, b)
    brightness = (maxc + minc) / 2.0
    saturation = (maxc - minc) / (255.0 - abs(2 * brightness - 255.0) + 1e-6)
    mean_sat = float(saturation.mean())
    mean_bright = float(brightness.mean())
    return mean_sat < 0.12 and 60.0 < mean_bright < 180.0


def np_max3(a, b, c):
    import numpy as np

    return np.maximum(np.maximum(a, b), c)


def np_min3(a, b, c):
    import numpy as np

    return np.minimum(np.minimum(a, b), c)


def check_backend(name: str, monitor_index: int, left: int, top: int, width: int, height: int, duration_s: float = 2.0):
    """Returns (BackendResult, last_frame_or_None). Keeping the last frame
    lets the caller reuse it for the HDR heuristic instead of spinning up
    a second capture backend instance for the same output (dxcam only
    supports one live duplicator per output at a time)."""
    try:
        backend = create_backend(name, monitor_index=monitor_index)
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return BackendResult(name=name, available=False, avg_ms=0.0, fps=0.0, black_frame_ratio=0.0, error=str(exc)), None

    times: list[float] = []
    black_count = 0
    total = 0
    last_frame = None
    deadline = time.perf_counter() + duration_s
    try:
        # warm up
        for _ in range(3):
            last_frame = backend.grab(left, top, width, height)
        while time.perf_counter() < deadline:
            t0 = time.perf_counter()
            frame = backend.grab(left, top, width, height)
            last_frame = frame if frame is not None else last_frame
            times.append((time.perf_counter() - t0) * 1000)
            total += 1
            if is_frame_black(frame):
                black_count += 1
    finally:
        backend.close()

    avg_ms = sum(times) / len(times) if times else 0.0
    fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
    black_ratio = black_count / total if total else 1.0
    result = BackendResult(name=name, available=True, avg_ms=avg_ms, fps=fps, black_frame_ratio=black_ratio)
    return result, last_frame


def run_compat_check(monitor, duration_s: float = 2.0) -> CompatResult:
    results = []
    frames: dict[str, object] = {}
    for name in ("dxcam", "mss"):
        result, frame = check_backend(
            name, monitor.index, monitor.left, monitor.top, monitor.width, monitor.height, duration_s
        )
        results.append(result)
        frames[name] = frame

    notes: list[str] = []
    chosen = ""
    for r in sorted(results, key=lambda r: (-r.available, -r.fps)):
        if r.available and r.black_frame_ratio < 0.9:
            chosen = r.name
            break
    if not chosen:
        notes.append("ทุก backend ให้ภาพดำเกือบทั้งหมด — อาจเป็น exclusive fullscreen หรือเนื้อหาป้องกันการจับภาพ (DRM)")
        chosen = results[0].name if results else "mss"

    hdr_suspected = _hdr_heuristic(frames.get(chosen))

    if hdr_suspected:
        notes.append("ตรวจพบสัญญาณที่อาจบ่งชี้ HDR (heuristic, ไม่ยืนยัน 100%) — ถ้าสีภาพดูซีด แนะนำลองปิด HDR หรือใช้ tone-mapping ก่อน OCR")

    return CompatResult(
        backends=tuple(results),
        chosen_backend=chosen,
        hdr_suspected=hdr_suspected,
        notes=tuple(notes),
    )
