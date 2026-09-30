"""Region = a named rectangle (in 0..1 proportional coordinates, so it
survives resolution/window-size changes) bound to a preset. Proportional
coordinates are the format stored in profiles/*.json; pixel coordinates are
what capture/OCR actually operate on — this module is the only place that
converts between the two (spec section 8.8).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    rect: tuple[float, float, float, float]  # (x1, y1, x2, y2), each 0..1
    preset: str
    min_score: float | None = None
    typewriter: bool = False
    translate_position: str = "in_place"  # "in_place" | "fixed"

    def __post_init__(self) -> None:
        x1, y1, x2, y2 = self.rect
        for v in (x1, y1, x2, y2):
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"region {self.name!r}: rect values must be in 0..1, got {self.rect}")
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"region {self.name!r}: rect must have x2>x1 and y2>y1, got {self.rect}")


def rect_to_pixels(rect: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = rect
    return (
        round(x1 * width),
        round(y1 * height),
        round(x2 * width),
        round(y2 * height),
    )


def rect_from_pixels(px_rect: tuple[int, int, int, int], width: int, height: int) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    x1, y1, x2, y2 = px_rect
    return (x1 / width, y1 / height, x2 / width, y2 / height)


def regions_overlap(a: Region, b: Region) -> bool:
    ax1, ay1, ax2, ay2 = a.rect
    bx1, by1, bx2, by2 = b.rect
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


def crop_frame(frame, rect: tuple[float, float, float, float]):
    """Crop a HxWxC numpy frame to a proportional region rect."""
    height, width = frame.shape[0], frame.shape[1]
    x1, y1, x2, y2 = rect_to_pixels(rect, width, height)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    return frame[y1:y2, x1:x2]
