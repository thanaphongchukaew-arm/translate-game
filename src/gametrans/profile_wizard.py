"""Profile creation wizard (spec section 3E): given a handful of
screenshots (or frames from a short "learn for N seconds" capture) of a
game, proposes regions + presets + source language + a starter glossary,
which the user reviews/adjusts (typically via ui_region_editor.py) before
saving. This is explicitly a PROPOSAL, never claimed to be 100% accurate
(spec: "ผลลัพธ์เป็นข้อเสนอที่ผู้ใช้ตรวจแก้ได้ ห้ามอ้างว่าแม่น 100%").

Core algorithm (testable without any GUI):
  1. OCR every sample frame independently.
  2. Cluster OCR blocks across frames by position (IoU-based) into
     "slots" -- the same physical UI location appearing in >=1 frames.
  3. Classify each slot's behavior from how its text changed across the
     frames it appeared in:
       - appears in most frames, text never changes  -> static UI text
         (short -> "ui_heavy"; mostly digits/symbols -> "hud")
       - appears in most frames, text grows monotonically (each version
         is a prefix of the next) -> typewriter dialogue -> "dialogue"
       - appears in most frames, text changes but doesn't grow          -> "dialogue" (still a good default: story text changing between
         samples looks exactly like this)
       - appears in only a minority of frames -> transient -> "subtitle"
  4. The slot's proposed region rect is the union of its bounding boxes
     across frames (with a small padding margin), converted to
     proportional coordinates.
  5. Source language: majority-vote script detection (lang.py) over all
     OCR'd text.
  6. Starter glossary: capitalized words/phrases that repeat across >=2
     samples and aren't common English words -- likely proper nouns
     (character/item/place names). No translation is guessed; the user
     fills those in.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from gametrans.lang import detect_source_language
from gametrans.layout import OcrLine, merge_lines
from gametrans.ocr_post import _WORDLIST  # reuse the common-word list to filter glossary noise
from gametrans.regions import Region, rect_from_pixels

_MIN_PRESENCE_FOR_STATIC = 0.5  # a slot present in >=50% of samples is "regular", not transient


@dataclass
class ProposedRegion:
    region: Region
    sample_count: int
    behavior: str  # "static" | "typewriter" | "changing" | "transient"


@dataclass
class WizardResult:
    regions: list[ProposedRegion] = field(default_factory=list)
    source_lang: str = "other"
    glossary_candidates: list[str] = field(default_factory=list)
    frame_width: int = 0
    frame_height: int = 0


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class _Slot:
    """A location cluster: the same on-screen position across frames."""

    def __init__(self, box: tuple[float, float, float, float], text: str, frame_idx: int) -> None:
        self.box = box  # running union
        self.observations: list[tuple[int, str]] = [(frame_idx, text)]

    def matches(self, box: tuple[float, float, float, float], iou_threshold: float = 0.3) -> bool:
        return _iou(self.box, box) >= iou_threshold

    def add(self, box: tuple[float, float, float, float], text: str, frame_idx: int) -> None:
        x1 = min(self.box[0], box[0])
        y1 = min(self.box[1], box[1])
        x2 = max(self.box[2], box[2])
        y2 = max(self.box[3], box[3])
        self.box = (x1, y1, x2, y2)
        self.observations.append((frame_idx, text))


def _classify_behavior(observations: list[tuple[int, str]], total_frames: int) -> str:
    presence_ratio = len(observations) / total_frames if total_frames else 0.0
    texts = [t for _, t in observations]
    unique_texts = list(dict.fromkeys(texts))  # preserve order, dedupe

    if presence_ratio < _MIN_PRESENCE_FOR_STATIC:
        return "transient"

    if len(unique_texts) <= 1:
        return "static"

    # typewriter check: each later text is a prefix-extension of the one
    # before it (allowing repeats/no-ops between frames)
    growing = True
    prev = ""
    for t in unique_texts:
        if not t.startswith(prev):
            growing = False
            break
        prev = t
    return "typewriter" if growing else "changing"


def _preset_for_behavior(behavior: str, sample_text: str) -> str:
    digits_and_symbols_only = bool(sample_text) and not re.search(r"[^\W\d_]", sample_text, re.UNICODE)
    if behavior == "static":
        return "hud" if digits_and_symbols_only else "ui_heavy"
    if behavior == "typewriter":
        return "dialogue"
    if behavior == "changing":
        return "dialogue"
    return "subtitle"  # transient


def analyze_samples(
    frames: list,
    ocr_func: Callable,
    cfg: dict | None = None,
) -> WizardResult:
    """`frames` are BGR numpy arrays (e.g. from capture.py), all the same
    resolution. `ocr_func` matches pipeline.py's injectable OCR signature:
    `ocr_func(frame, cfg) -> list[OcrLine]`."""
    cfg = cfg or {}
    if not frames:
        return WizardResult()

    height, width = frames[0].shape[0], frames[0].shape[1]
    slots: list[_Slot] = []
    all_texts: list[str] = []

    for frame_idx, frame in enumerate(frames):
        lines = ocr_func(frame, cfg)
        blocks = merge_lines(lines, cfg)
        for block in blocks:
            all_texts.append(block.text)
            prop_box = (block.x1 / width, block.y1 / height, block.x2 / width, block.y2 / height)
            matched = None
            for slot in slots:
                if slot.matches(prop_box):
                    matched = slot
                    break
            if matched is None:
                slots.append(_Slot(prop_box, block.text, frame_idx))
            else:
                matched.add(prop_box, block.text, frame_idx)

    total_frames = len(frames)
    proposed: list[ProposedRegion] = []
    for i, slot in enumerate(slots):
        behavior = _classify_behavior(slot.observations, total_frames)
        preset = _preset_for_behavior(behavior, slot.observations[-1][1])
        x1, y1, x2, y2 = slot.box
        pad = 0.01
        rect = (max(0.0, x1 - pad), max(0.0, y1 - pad), min(1.0, x2 + pad), min(1.0, y2 + pad))
        try:
            region = Region(name=f"region_{i}", rect=rect, preset=preset)
        except ValueError:
            continue  # degenerate box (e.g. a single point) -- skip, not worth proposing
        proposed.append(ProposedRegion(region=region, sample_count=len(slot.observations), behavior=behavior))

    source_lang = detect_source_language(all_texts)
    glossary_candidates = _extract_glossary_candidates(all_texts)

    return WizardResult(
        regions=proposed,
        source_lang=source_lang,
        glossary_candidates=glossary_candidates,
        frame_width=width,
        frame_height=height,
    )


_CAPITALIZED_WORD_RE = re.compile(r"\b[A-Z][a-zA-Z']{2,}\b")


def _extract_glossary_candidates(texts: list[str], min_occurrences: int = 2) -> list[str]:
    """Capitalized words that repeat across samples and aren't common
    English words -- a reasonable proxy for proper nouns (character/item/
    place names) without any translation guessing or external service."""
    counts: Counter[str] = Counter()
    for text in texts:
        for word in _CAPITALIZED_WORD_RE.findall(text):
            if word.lower() in _WORDLIST:
                continue
            if word.lower() in ("i", "the", "a", "an"):
                continue
            counts[word] += 1
    return [word for word, n in counts.most_common() if n >= min_occurrences]
