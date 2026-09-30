"""Source-language detection from OCR'd text scripts, and the registry of
which per-language OCR recognition models are actually downloaded on this
machine (spec section 3G). Target language is always Thai in this project.

Only English/Latin is downloaded/used by default (spec: "ดาวน์โหลดเฉพาะ
ภาษาที่ผู้ใช้เลือก") — the user's only test game (P5X) is English-only, so
ja/ko/zh model download + bake-off is deferred until a user actually
selects one of those languages. Detection logic works today for all of
them; only the *model* is missing.
"""
from __future__ import annotations

import re
from collections import Counter

# Unicode block ranges used to classify each character's script.
_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_HANGUL = (0xAC00, 0xD7A3)
_HANGUL_JAMO = (0x1100, 0x11FF)
_CJK_UNIFIED = (0x4E00, 0x9FFF)
_LATIN_BASIC = (0x0041, 0x007A)  # covers A-Za-z (with a few punctuation gaps, fine for detection)
_LATIN_EXT = (0x00C0, 0x024F)

SUPPORTED_LANGS = ("en", "ja", "ko", "zh", "other")

# Which languages have a downloaded OCR recognition model available. Kept
# as a plain module-level registry (not a class) so tools/tests can both
# read and, in future phases, extend it as more languages get downloaded.
DOWNLOADED_OCR_LANGS: set[str] = {"en"}


def _char_script(ch: str) -> str:
    cp = ord(ch)
    if _HIRAGANA[0] <= cp <= _HIRAGANA[1] or _KATAKANA[0] <= cp <= _KATAKANA[1]:
        return "ja"
    if _HANGUL[0] <= cp <= _HANGUL[1] or _HANGUL_JAMO[0] <= cp <= _HANGUL_JAMO[1]:
        return "ko"
    if _CJK_UNIFIED[0] <= cp <= _CJK_UNIFIED[1]:
        return "zh"  # kanji-only text with no kana is classified zh (ja needs kana to be distinguishable)
    if _LATIN_BASIC[0] <= cp <= _LATIN_BASIC[1] or _LATIN_EXT[0] <= cp <= _LATIN_EXT[1]:
        return "en"
    return "other"


def detect_script(text: str) -> str:
    """Classify a single string's dominant script. Presence of hiragana or
    katakana always wins as 'ja' even if kanji (CJK) characters are also
    present, since ja/zh share the CJK ideograph block and kana is the
    only unambiguous signal that separates them."""
    counts: Counter[str] = Counter()
    for ch in text:
        if ch.isspace() or not ch.isalpha():
            continue
        counts[_char_script(ch)] += 1

    if not counts:
        return "other"
    if counts["ja"] > 0:
        return "ja"
    return counts.most_common(1)[0][0]


def detect_source_language(texts: list[str]) -> str:
    """Majority-vote script detection across several OCR'd lines (more
    robust than a single line, which might be a name/number)."""
    votes: Counter[str] = Counter()
    for text in texts:
        script = detect_script(text)
        if script != "other":
            votes[script] += 1
    if not votes:
        return "other"
    return votes.most_common(1)[0][0]


def resolve_source_lang(configured: str, detected_texts: list[str]) -> str:
    """`configured` is the profile/region's `source_lang` setting: a
    specific code overrides detection; 'auto' falls back to detection."""
    if configured and configured != "auto":
        return configured
    return detect_source_language(detected_texts)


def is_ocr_model_available(lang: str) -> bool:
    return lang in DOWNLOADED_OCR_LANGS
