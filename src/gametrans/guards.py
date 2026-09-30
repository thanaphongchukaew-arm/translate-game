"""Post-translation sanity checks (spec section 8.6). Rejects empty output,
non-Thai output, wildly wrong length, repetition (NMT hallucination),
lost numbers/placeholders, and stray explanatory text some LLMs add.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_THAI_RE = re.compile(r"[฀-๿]")
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_TOKEN_RE = re.compile(r"\[P\d+\]")
_NUMBER_RE = re.compile(r"\d+")

_EXPLANATORY_PATTERNS = [
    re.compile(r"^\s*(here('?s| is)\b|translation\s*:|note\s*:|sure[,.]?\s*$)", re.IGNORECASE),
    re.compile(r"^\s*(the\s+thai\s+translation|i\s+translated)", re.IGNORECASE),
]


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""


def check_translation(src: str, out: str, *, max_ratio: float = 3.0, min_ratio: float = 0.15) -> GuardResult:
    if out is None or not out.strip():
        return GuardResult(False, "empty")

    src_has_letters = bool(_HAS_LETTER_RE.search(src))
    if src_has_letters and not _THAI_RE.search(out):
        return GuardResult(False, "not_thai")

    for pat in _EXPLANATORY_PATTERNS:
        if pat.search(out):
            return GuardResult(False, "explanatory_text")

    if len(src) >= 4:
        ratio = len(out) / max(len(src), 1)
        if ratio > max_ratio:
            return GuardResult(False, "too_long")
        if ratio < min_ratio:
            return GuardResult(False, "too_short")

    words = out.split()
    if len(words) >= 6:
        for n in (2, 3):
            grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
            if len(grams) < 4:
                continue
            counts: dict[tuple[str, ...], int] = {}
            for g in grams:
                counts[g] = counts.get(g, 0) + 1
            if max(counts.values()) / len(grams) > 0.5:
                return GuardResult(False, "repetition")

    if _TOKEN_RE.search(out):
        # textprep.restore() should have resolved every placeholder already;
        # a leftover token means restore was skipped or a bug lost one.
        return GuardResult(False, "unresolved_placeholder")

    src_numbers = set(_NUMBER_RE.findall(src))
    out_numbers = set(_NUMBER_RE.findall(out))
    if src_numbers and not src_numbers.issubset(out_numbers):
        return GuardResult(False, "lost_numbers")

    return GuardResult(True)
