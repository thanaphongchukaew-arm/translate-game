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
from pathlib import Path
from typing import Any, Optional

import numpy as np

from gametrans.layout import OcrLine

logger = logging.getLogger("gametrans.ocr")

_engine_cache: dict[str, Any] = {}

_DEFAULT_EN_REC_MODEL = "models/ocr/en/en_PP-OCRv3_rec_infer.onnx"


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
