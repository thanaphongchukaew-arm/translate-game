"""RapidOCR wrapper.

Verified against the installed rapidocr-onnxruntime==1.4.4 source
(utils/parse_parameters.py): GPU is enabled via the flat kwargs
`det_use_cuda` / `rec_use_cuda` (or `_use_dml` for DirectML) passed to
`RapidOCR(**kwargs)` — NOT a nested `Det.use_cuda=...` dict as an earlier
draft assumed. See DECISIONS.md phase 2.

Provider decision (measured on this machine, see DECISIONS.md phase 2):
onnxruntime-gpu's CUDAExecutionProvider failed to load even after
installing the pip-packaged CUDA 12 / cuDNN 9 runtime DLLs (missing
transitive dependency, WinError 126) — a full CUDA Toolkit install would
fix it but that's a large, invasive system change out of scope here.
onnxruntime-directml works immediately with just the existing GPU driver
and measured 76ms warm-run OCR (vs ~570-600ms on CPU), so DirectML is the
default GPU path for OCR specifically, independent of the CUDA path chosen
for the translation layers in later phases.

Also verified: the bundled default "ch" (Chinese) recognition model drops
spaces between English words on multi-word sentences (a known RapidOCR
issue — github.com/RapidAI/RapidOCR/discussions/638). Fixed by downloading
`en_PP-OCRv3_rec_infer.onnx` into models/ocr/en/ and passing it as
`rec_model_path`; the English detection model stays the bundled Chinese
one (detection is script-agnostic and was already finding correct boxes).

`use_cls=False` is passed on every call per spec section 8.2 (Persona-style
game text is essentially never rotated, and skipping the angle classifier
is a meaningful speed win).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from gametrans.layout import OcrLine

logger = logging.getLogger("gametrans.ocr")

_engine_cache: dict[str, Any] = {}

_DEFAULT_EN_REC_MODEL = "models/ocr/en/en_PP-OCRv3_rec_infer.onnx"
_STYLIZED_MIN_H = 40
_STYLIZED_MAX_SCORE = 0.85
_STYLIZED_MAX_CLUSTERS = 3
_CAP_MIN_H = 18
_CASE_AMBIGUOUS = frozenset("cosvwxz")
_ACCENT_MAX_HUES = 3
_ACCENT_MIN_PIXELS = 200
_ACCENT_MIN_SHARE = 0.15
_CAP_MAX_BLOBS = 40
_CAP_MAX_H = 200
_CAP_MIN_SCORE = 0.35
_STYLIZED_CACHE_DIFF = 1.5
_stylized_cache: dict[str, tuple] = {}


def _build_kwargs(provider: str, rec_model_path: Optional[str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if provider == "cuda":
        kwargs.update({"det_use_cuda": True, "rec_use_cuda": True})
    elif provider == "directml":
        kwargs.update({"det_use_dml": True, "rec_use_dml": True})
    if rec_model_path and Path(rec_model_path).exists():
        kwargs["rec_model_path"] = str(rec_model_path)
    return kwargs


def _create_engine(provider: str, rec_model_path: Optional[str]):
    from rapidocr_onnxruntime import RapidOCR

    kwargs = _build_kwargs(provider, rec_model_path)
    try:
        return RapidOCR(**kwargs), provider
    except Exception as exc:  # noqa: BLE001 - must fall back to CPU, never crash
        if provider != "cpu":
            logger.warning("ocr: provider %s failed (%s) — falling back to cpu", provider, exc)
            fallback_kwargs = _build_kwargs("cpu", rec_model_path)
            return RapidOCR(**fallback_kwargs), "cpu"
        raise


def get_engine(provider: str = "auto", rec_model_path: Optional[str] = _DEFAULT_EN_REC_MODEL):
    """Returns (engine, active_provider). `auto` tries DirectML, then CPU
    (see module docstring for why DirectML rather than CUDA is the default
    GPU path for OCR on this project)."""
    key = f"{provider}|{rec_model_path}"
    if key not in _engine_cache:
        if provider == "auto":
            try:
                engine, active = _create_engine("directml", rec_model_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ocr: directml unavailable (%s) — using cpu", exc)
                engine, active = _create_engine("cpu", rec_model_path)
        else:
            engine, active = _create_engine(provider, rec_model_path)
        _engine_cache[key] = (engine, active)
    return _engine_cache[key]


def get_active_provider(provider: str = "auto") -> str:
    _, active = get_engine(provider)
    return active


def run_ocr(image: "np.ndarray", cfg: Optional[dict] = None, provider: str = "auto") -> list[OcrLine]:
    """Run OCR on a BGR numpy image and return score/height-filtered OcrLine
    results, sorted by nothing in particular (layout.merge_lines sorts)."""
    cfg = cfg or {}
    ocr_cfg = cfg.get("ocr", {}) if isinstance(cfg, dict) else {}
    min_score = float(ocr_cfg.get("min_score", 0.6))
    min_box_h = float(ocr_cfg.get("min_box_h", 8))
    configured_provider = ocr_cfg.get("provider", provider) if isinstance(cfg, dict) else provider
    rec_model_path = ocr_cfg.get("rec_model_path", _DEFAULT_EN_REC_MODEL)

    engine, _active = get_engine(configured_provider, rec_model_path)
    lines = _ocr_once(engine, image, min_score, min_box_h)

    # Stylized display type (Persona-style title cards: mixed-size letters,
    # accent-colored (e.g. red) and white fills on black, jagged outlines) often makes the detector
    # skip whole words or just their big first letter. Re-read the frame
    # as grayscale (recovers missed words) and as an accent-color mask (recovers
    # the drop-capitals), glue each capital back onto the word it begins, and
    # keep only results that don't overlap what the first pass found. Only
    # worth the extra passes when the frame has big or shaky text.
    if ocr_cfg.get("stylized_pass", True) and lines and _looks_stylized(lines):
        # The extra passes cost several OCR calls; a static title card
        # re-reads identically every frame, so reuse the last result while
        # the frame and the first-pass text are unchanged.
        sig = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
        texts = tuple(sorted(ln.text for ln in lines))
        cooldown = float(ocr_cfg.get("stylized_cooldown_s", 1.0))
        cached = _stylized_cache.get("last")
        if cached and cached[1] == texts and cached[0].shape == sig.shape:
            # Same first-pass text: reuse while the frame is still, and --
            # for a title over an animated background, where the frame
            # never stays still -- for `cooldown` seconds after the last
            # full pass, so a moving scene can't cost ~1s of OCR per frame.
            still = float(np.abs(cached[0].astype(np.int16) - sig).mean()) < _STYLIZED_CACHE_DIFF
            if still or time.monotonic() - cached[3] < cooldown:
                return list(cached[2])
        extras = _ocr_once(engine, _gray_image(image), min_score, min_box_h)
        caps = _accent_drop_caps(engine, image)
        for x1, y1, x2, y2 in _stylized_clusters(lines, image.shape[1], image.shape[0]):
            crop = image[y1:y2, x1:x2]
            for variant in (crop, _gray_image(crop), _accent_mask_image(crop, keep_white=True), _white_mask_image(crop)):
                extras += [_shift(ln, x1, y1) for ln in _ocr_once(engine, variant, min_score, min_box_h)]
        lines = _pick_best(_attach_drop_caps(caps, lines + extras))
        _stylized_cache["last"] = (sig, texts, list(lines), time.monotonic())
    return lines


def _gray_image(image: "np.ndarray") -> "np.ndarray":
    return cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def _shift(ln: OcrLine, dx: float, dy: float) -> OcrLine:
    return OcrLine(ln.x1 + dx, ln.y1 + dy, ln.x2 + dx, ln.y2 + dy, ln.text, ln.score)


def _stylized_clusters(lines: list[OcrLine], width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Pixel crops (x1, y1, x2, y2) around groups of big lines. Re-reading a
    tight crop instead of the whole frame matters: the detector downsizes a
    full frame, which shrinks display type into noise and loses words."""
    big = [ln for ln in lines if ln.y2 - ln.y1 >= _STYLIZED_MIN_H]
    if not big:  # triggered by low scores only: re-read around the shaky lines
        big = [ln for ln in lines if ln.score < _STYLIZED_MAX_SCORE]
    boxes: list[list[float]] = []  # [x1, y1, x2, y2, max_h]
    for ln in big:
        boxes.append([ln.x1, ln.y1, ln.x2, ln.y2, ln.y2 - ln.y1])
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                m = 0.8 * max(a[4], b[4])
                if a[0] - m <= b[2] and b[0] - m <= a[2] and a[1] - m <= b[3] and b[1] - m <= a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), max(a[4], b[4])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    crops = []
    for x1, y1, x2, y2, h in boxes[:_STYLIZED_MAX_CLUSTERS]:
        m = 1.5 * h
        crops.append((
            int(max(0, x1 - m)), int(max(0, y1 - m)),
            int(min(width, x2 + m)), int(min(height, y2 + m)),
        ))
    return crops


def _ink_masks(image: "np.ndarray") -> tuple["np.ndarray", "np.ndarray"]:
    """(accent, white) ink masks. `accent` is whichever saturated hues
    dominate the crop's colored pixels (red for Persona-style type, gold,
    cyan, green... for other games), found from a hue histogram rather than
    hard-coded, so drop-capitals and highlighted words work in any color."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colored = (sat > 120) & (val > 100)
    # 12 hue bins of 15 degrees (OpenCV hue is 0..179), shifted so red,
    # which wraps around 0, falls in a single bin
    bins = ((h.astype(np.int32) + 7) // 15) % 12
    counts = np.bincount(bins[colored], minlength=12)
    total = int(counts.sum())
    chosen = [
        int(i) for i in np.argsort(counts)[::-1][:_ACCENT_MAX_HUES]
        if counts[i] >= _ACCENT_MIN_PIXELS and counts[i] >= _ACCENT_MIN_SHARE * total
    ]
    accent = colored & np.isin(bins, chosen) if chosen else np.zeros_like(colored)
    white = (sat < 60) & (val > 170)
    return accent, white


def _mask_to_image(mask: "np.ndarray") -> "np.ndarray":
    return cv2.cvtColor(255 - mask.astype(np.uint8) * 255, cv2.COLOR_GRAY2BGR)


def _accent_mask_image(image: "np.ndarray", keep_white: bool = False) -> "np.ndarray":
    """Black-on-white image of only the accent-colored pixels (and, with
    `keep_white`, the white fills too — the two inks of Persona-style type)."""
    accent, white = _ink_masks(image)
    return _mask_to_image(accent | white if keep_white else accent)


def _white_mask_image(image: "np.ndarray") -> "np.ndarray":
    return _mask_to_image(_ink_masks(image)[1])


def _accent_drop_caps(engine, image: "np.ndarray") -> list[OcrLine]:
    """Find the big accent-colored first letters of stylized words as
    connected blobs of colored ink and read each one alone (recognizer only, no detector). Far more
    reliable than hoping the detector isolates a single glyph."""
    accent, _ = _ink_masks(image)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(accent.astype(np.uint8), connectivity=8)
    caps: list[OcrLine] = []
    candidates = sorted(range(1, n), key=lambda i: -int(stats[i][3]))[:_CAP_MAX_BLOBS]
    for i in candidates:
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (_CAP_MIN_H <= h <= _CAP_MAX_H) or not (0.25 <= w / h <= 1.8) or area < 0.2 * w * h:
            continue
        pad = int(0.15 * h)
        blob = labels[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad] == i
        glyph = cv2.copyMakeBorder(_mask_to_image(blob), 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        result, _e = engine(glyph, use_det=False, use_cls=False, use_rec=True)
        if not result:
            continue
        text, score = result[0][0], float(result[0][1])
        if text in _CASE_AMBIGUOUS:  # a lone "S" and "s" are the same shape
            text = text.upper()
        if len(text) == 1 and text.isalpha() and text.isupper() and score >= _CAP_MIN_SCORE:
            caps.append(OcrLine(x1=float(x), y1=float(y), x2=float(x + w), y2=float(y + h), text=text, score=score))
    return caps


def _attach_drop_caps(caps: list[OcrLine], lines: list[OcrLine]) -> list[OcrLine]:
    """Return `lines` where each line that starts lowercase gets the nearest
    single-capital `cap` sitting immediately left of it (same row) prepended
    to its text. Order and length of `lines` are preserved."""
    out = list(lines)
    for i, ln in enumerate(out):
        if ln.text[:1].isupper():
            continue
        best: tuple[float, OcrLine] | None = None
        for cap in caps:
            ch = cap.y2 - cap.y1
            row_overlap = min(cap.y2, ln.y2) - max(cap.y1, ln.y1)
            gap = ln.x1 - cap.x2
            if row_overlap < 0.4 * ch or not (-0.6 * ch <= gap <= 0.8 * ch):
                continue
            if ln.text.lower().startswith(cap.text.lower()):
                continue
            if best is None or abs(gap) < best[0]:
                best = (abs(gap), cap)
        if best is not None:
            cap = best[1]
            out[i] = OcrLine(
                x1=min(cap.x1, ln.x1), y1=min(cap.y1, ln.y1),
                x2=ln.x2, y2=max(cap.y2, ln.y2),
                text=cap.text + ln.text, score=min(cap.score, ln.score),
            )
    return out


def _ocr_once(engine, image: "np.ndarray", min_score: float, min_box_h: float) -> list[OcrLine]:
    result, _elapse = engine(image, use_cls=False)
    lines: list[OcrLine] = []
    if not result:
        return lines
    for item in result:
        box, text, score = item[0], item[1], item[2]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x1, x2 = float(min(xs)), float(max(xs))
        y1, y2 = float(min(ys)), float(max(ys))
        score = float(score)
        if score < min_score:
            continue
        if (y2 - y1) < min_box_h:
            continue
        lines.append(OcrLine(x1=x1, y1=y1, x2=x2, y2=y2, text=text, score=score))
    return lines


def _looks_stylized(lines: list[OcrLine]) -> bool:
    return max(ln.y2 - ln.y1 for ln in lines) >= _STYLIZED_MIN_H or any(
        ln.score < _STYLIZED_MAX_SCORE for ln in lines
    )


def _pick_best(candidates: list[OcrLine]) -> list[OcrLine]:
    """Resolve overlapping readings of the same spot: longest, most confident
    reading wins, anything it covers is discarded."""
    chosen: list[OcrLine] = []
    for ln in sorted(candidates, key=lambda c: -(c.score * sum(ch.isalnum() for ch in c.text))):
        if not any(_overlap_frac(ln, kept) >= 0.3 for kept in chosen):
            chosen.append(ln)
    return chosen


def _overlap_frac(a: OcrLine, b: OcrLine) -> float:
    """Intersection area as a fraction of the smaller box's area."""
    iw = min(a.x2, b.x2) - max(a.x1, b.x1)
    ih = min(a.y2, b.y2) - max(a.y1, b.y1)
    area = min((a.x2 - a.x1) * (a.y2 - a.y1), (b.x2 - b.x1) * (b.y2 - b.y1))
    if iw <= 0 or ih <= 0 or area <= 0:
        return 0.0
    return iw * ih / area
