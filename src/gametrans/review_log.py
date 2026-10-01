"""Opt-in log of OCR reads worth a human look (low confidence, or text the
post-processor had to change), so a profile's `ocr_fixes`/glossary can be
filled in from real data. Contains game text, so it is OFF unless
cfg["log"]["ocr_review"] is true (privacy rule, see log.py).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("gametrans.review")

LOW_SCORE = 0.85


class ReviewLog:
    def __init__(self, path: str, enabled: bool, max_entries: int = 2000) -> None:
        self._path = path
        self._enabled = enabled
        self._max = max_entries
        self._seen: set[tuple[str, str]] = set()

    def record(self, raw: str, cleaned: str, score: float) -> None:
        if not self._enabled or len(self._seen) >= self._max:
            return
        if raw == cleaned and score >= LOW_SCORE:
            return
        key = (raw, cleaned)
        if key in self._seen:
            return
        self._seen.add(key)
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"raw": raw, "clean": cleaned, "score": round(score, 3)}, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("review: cannot write %s (%s) — disabling", self._path, exc)
            self._enabled = False
