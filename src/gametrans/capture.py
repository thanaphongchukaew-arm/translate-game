"""Screen capture backends: dxcam (DXGI Desktop Duplication, fast) with an
mss fallback (slower, always works). A backend must be created and used
from the SAME thread — dxcam/mss capture objects are not safe to share
across threads (spec section 10/20).
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("gametrans.capture")


class CaptureBackend:
    name: str

    def grab(self, left: int, top: int, width: int, height: int) -> Optional["np.ndarray"]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DxcamBackend(CaptureBackend):
    name = "dxcam"

    def __init__(self, monitor_index: int = 0) -> None:
        import dxcam

        self._camera = dxcam.create(output_idx=monitor_index, output_color="BGR")
        if self._camera is None:
            raise RuntimeError("dxcam.create() returned None (no compatible adapter/output)")
        self._last_frame: Optional["np.ndarray"] = None

    def grab(self, left: int, top: int, width: int, height: int) -> Optional["np.ndarray"]:
        # dxcam's DXGI Desktop Duplication grab() legitimately returns None
        # whenever the desktop hasn't changed since the previous poll (very
        # common when polling faster than the content actually updates) —
        # that is NOT the same thing as a black/failed capture, so we return
        # the last known-good frame instead of None. A real black frame
        # (exclusive fullscreen, DRM) still comes through as actual pixel
        # data that is_frame_black() can correctly flag.
        region = (left, top, left + width, top + height)
        frame = self._camera.grab(region=region)
        if frame is None:
            return self._last_frame
        self._last_frame = frame
        return frame

    def close(self) -> None:
        try:
            del self._camera
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


class MssBackend(CaptureBackend):
    name = "mss"

    def __init__(self) -> None:
        import mss

        self._sct = mss.mss()

    def grab(self, left: int, top: int, width: int, height: int) -> Optional["np.ndarray"]:
        shot = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        arr = np.asarray(shot)  # BGRA
        return arr[:, :, :3]  # drop alpha -> BGR

    def close(self) -> None:
        self._sct.close()


_BACKEND_CLASSES = {"dxcam": DxcamBackend, "mss": MssBackend}


def create_backend(preferred: str = "auto", monitor_index: int = 0) -> CaptureBackend:
    """Create a capture backend, falling back from dxcam to mss on failure.
    Never raises unless *every* backend fails."""
    order = ["dxcam", "mss"] if preferred == "auto" else [preferred]
    last_exc: Optional[Exception] = None
    for name in order:
        cls = _BACKEND_CLASSES.get(name)
        if cls is None:
            continue
        try:
            if name == "dxcam":
                return cls(monitor_index)
            return cls()
        except Exception as exc:  # noqa: BLE001 - must try the next backend
            logger.warning("capture: backend %s unavailable (%s)", name, exc)
            last_exc = exc
    raise RuntimeError(f"no capture backend available: {last_exc}")


def is_frame_black(frame: Optional["np.ndarray"], threshold: float = 8.0) -> bool:
    """Heuristic for exclusive-fullscreen / DRM-protected black frames
    (spec section 15). Caller should require this to be true for ~1s of
    consecutive frames before showing the warning."""
    if frame is None:
        return True
    return float(frame.mean()) < threshold
