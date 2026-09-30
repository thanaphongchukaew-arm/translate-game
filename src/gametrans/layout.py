"""Merge OCR lines into text blocks, and track blocks across frames.

merge_lines(): groups OcrLine results from a single frame into Block(s)
following the rules in spec section 8.4 (vertical gap, height ratio, left/
center alignment, no horizontal overlap with other blocks' latest row).

track_blocks(): matches this frame's blocks against the previous frame's,
carrying over `id`, `stable_cycles` and `stable_since`, with a hold/hysteresis
window so a block that briefly disappears is not immediately dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, replace, field
from typing import Any

_POSITION_EPS_PX = 3.0


@dataclass(frozen=True)
class OcrLine:
    x1: float
    y1: float
    x2: float
    y2: float
    text: str
    score: float


@dataclass
class Block:
    id: int
    x1: float
    y1: float
    x2: float
    y2: float
    text: str
    line_h: float
    first_seen: float
    last_seen: float
    stable_cycles: int
    stable_since: float
    hold_left: int = 0  # internal: frames remaining before a vanished block is dropped


def _cfg_get(cfg: Any, *path: str, default: Any = None) -> Any:
    node = cfg
    for key in path:
        if node is None:
            return default
        if isinstance(node, dict):
            node = node.get(key)
        else:
            node = getattr(node, key, None)
    return default if node is None else node


def merge_lines(lines: list[OcrLine], cfg: Any = None) -> list[Block]:
    """Merge same-frame OCR lines into blocks. Deterministic regardless of
    input order (always sorts by (y1, x1) first)."""
    ordered = sorted(lines, key=lambda ln: (ln.y1, ln.x1))

    class _Open:
        __slots__ = ("x1", "y1", "x2", "y2", "texts", "line_h", "last_x1", "last_center", "last_y2")

        def __init__(self, ln: OcrLine) -> None:
            self.x1, self.y1, self.x2, self.y2 = ln.x1, ln.y1, ln.x2, ln.y2
            self.texts = [ln.text]
            self.line_h = max(ln.y2 - ln.y1, 1e-6)
            self.last_x1 = ln.x1
            self.last_center = (ln.x1 + ln.x2) / 2
            self.last_y2 = ln.y2

    open_blocks: list[_Open] = []

    for ln in ordered:
        h = max(ln.y2 - ln.y1, 1e-6)
        center = (ln.x1 + ln.x2) / 2
        best: _Open | None = None
        for ob in open_blocks:
            gap = ln.y1 - ob.last_y2
            if not (-0.3 * h <= gap <= 0.9 * h):
                continue
            ratio = h / ob.line_h
            if not (0.7 <= ratio <= 1.4):
                continue
            left_aligned = abs(ln.x1 - ob.last_x1) <= 1.5 * h
            center_aligned = abs(center - ob.last_center) <= 1.5 * h
            if not (left_aligned or center_aligned):
                continue
            # must not horizontally overlap a *different* open block in the
            # same row (side-by-side columns should stay separate)
            overlaps_other = False
            for other in open_blocks:
                if other is ob:
                    continue
                same_row = not (ln.y2 < other.y1 or ln.y1 > other.last_y2)
                h_overlap = not (ln.x2 < other.x1 or ln.x1 > other.x2)
                if same_row and h_overlap:
                    overlaps_other = True
                    break
            if overlaps_other:
                continue
            best = ob
            break

        if best is not None:
            best.texts.append(ln.text)
            best.x1 = min(best.x1, ln.x1)
            best.y1 = min(best.y1, ln.y1)
            best.x2 = max(best.x2, ln.x2)
            best.y2 = max(best.y2, ln.y2)
            best.last_x1 = ln.x1
            best.last_center = center
            best.last_y2 = ln.y2
        else:
            open_blocks.append(_Open(ln))

    blocks: list[Block] = []
    for i, ob in enumerate(open_blocks):
        blocks.append(
            Block(
                id=i,
                x1=ob.x1, y1=ob.y1, x2=ob.x2, y2=ob.y2,
                text="\n".join(ob.texts),
                line_h=ob.line_h,
                first_seen=0.0,
                last_seen=0.0,
                stable_cycles=0,
                stable_since=0.0,
            )
        )
    return sorted(blocks, key=lambda b: (b.y1, b.x1))


def _iou(a: Block, b: Block) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _find_match(cb: Block, candidates: list[Block]) -> Block | None:
    best: Block | None = None
    best_score = -1.0
    for pb in candidates:
        iou = _iou(cb, pb)
        close = abs(cb.x1 - pb.x1) < 4.0 and abs(cb.y1 - pb.y1) < 4.0
        same_text = cb.text == pb.text
        if iou >= 0.5:
            score = iou
        elif close and same_text:
            score = 0.5  # tie-broken below iou matches, above nothing
        else:
            continue
        if score > best_score:
            best_score = score
            best = pb
    return best


def track_blocks(prev: list[Block], cur: list[Block], now: float, cfg: Any = None) -> list[Block]:
    hold_cycles = int(_cfg_get(cfg, "layout", "hold_cycles", default=2))
    max_blocks = int(_cfg_get(cfg, "ocr", "max_blocks", default=60))

    used_prev_ids: set[int] = set()
    next_id = (max((b.id for b in prev), default=-1)) + 1
    result: list[Block] = []

    for cb in cur:
        available = [p for p in prev if p.id not in used_prev_ids]
        match = _find_match(cb, available)
        if match is not None:
            used_prev_ids.add(match.id)
            same_text = cb.text == match.text
            moved = max(
                abs(cb.x1 - match.x1), abs(cb.y1 - match.y1),
                abs(cb.x2 - match.x2), abs(cb.y2 - match.y2),
            )
            if moved < _POSITION_EPS_PX:
                x1, y1, x2, y2 = match.x1, match.y1, match.x2, match.y2
            else:
                x1, y1, x2, y2 = cb.x1, cb.y1, cb.x2, cb.y2

            if same_text:
                stable_cycles = match.stable_cycles + 1
                stable_since = match.stable_since
            else:
                stable_cycles = 0
                stable_since = now

            result.append(
                Block(
                    id=match.id, x1=x1, y1=y1, x2=x2, y2=y2,
                    text=cb.text, line_h=cb.line_h,
                    first_seen=match.first_seen, last_seen=now,
                    stable_cycles=stable_cycles, stable_since=stable_since,
                    hold_left=hold_cycles,
                )
            )
        else:
            result.append(
                Block(
                    id=next_id, x1=cb.x1, y1=cb.y1, x2=cb.x2, y2=cb.y2,
                    text=cb.text, line_h=cb.line_h,
                    first_seen=now, last_seen=now,
                    stable_cycles=0, stable_since=now,
                    hold_left=hold_cycles,
                )
            )
            next_id += 1

    # hysteresis: keep vanished prev blocks alive for `hold_cycles` frames
    for pb in prev:
        if pb.id in used_prev_ids:
            continue
        if pb.hold_left > 1:
            result.append(replace(pb, hold_left=pb.hold_left - 1))

    if len(result) > max_blocks:
        cx = sum((b.x1 + b.x2) / 2 for b in result) / len(result)
        cy = sum((b.y1 + b.y2) / 2 for b in result) / len(result)

        def _priority(b: Block) -> tuple[float, float]:
            area = (b.x2 - b.x1) * (b.y2 - b.y1)
            dist = ((b.x1 + b.x2) / 2 - cx) ** 2 + ((b.y1 + b.y2) / 2 - cy) ** 2
            return (-area, dist)

        result = sorted(result, key=_priority)[:max_blocks]

    return sorted(result, key=lambda b: (b.y1, b.x1))
