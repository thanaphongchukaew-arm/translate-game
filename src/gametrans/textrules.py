"""Per-profile text rules applied around OCR/translation (profiles/*.json):

- `ocr_fixes`: whole-line OCR misreads to repair ("THEIPHANTOMX" -> "THE PHANTOM X")
- `skip_patterns`: regexes for text that must be left as-is (logos, brand names)
- `overrides`: fixed Thai for short UI labels whose literal machine
  translation is poor ("NEWS", "Support")

Matching ignores case, spaces and punctuation, so stylized renderings
("SCHOOL LIFE", "School Life", "SCHOOLLIFE") hit the same rule.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Long labels (title cards) are matched approximately: stylized type is
# never read the same way twice ("lave" for "Have", a missing "Thieves"),
# but a 30-character phrase is still unmistakable. Short labels stay exact.
_FUZZY_MIN_LEN = 14
_FUZZY_RATIO = 0.8

_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text).casefold()


@dataclass
class TextRules:
    overrides: dict[str, str] = field(default_factory=dict)
    ocr_fixes: dict[str, str] = field(default_factory=dict)
    skip: list[re.Pattern] = field(default_factory=list)

    @classmethod
    def from_profile(cls, profile: Any) -> "TextRules":
        if profile is None:
            return cls()
        skip = []
        for pat in getattr(profile, "skip_patterns", ()) or ():
            try:
                skip.append(re.compile(pat, re.IGNORECASE))
            except re.error:
                continue
        return cls(
            overrides={_norm(k): v for k, v in (getattr(profile, "overrides", None) or {}).items()},
            ocr_fixes={_norm(k): v for k, v in (getattr(profile, "ocr_fixes", None) or {}).items()},
            skip=skip,
        )

    @staticmethod
    def _lookup(table: dict[str, str], text: str) -> Optional[str]:
        key = _norm(text)
        if key in table:
            return table[key]
        if len(key) < _FUZZY_MIN_LEN:
            return None
        best, best_ratio = None, _FUZZY_RATIO
        for cand, value in table.items():
            if len(cand) < _FUZZY_MIN_LEN:
                continue
            ratio = difflib.SequenceMatcher(None, key, cand).ratio()
            if ratio >= best_ratio:
                best, best_ratio = value, ratio
        return best

    def fix(self, text: str) -> str:
        fixed = self._lookup(self.ocr_fixes, text)
        return text if fixed is None else fixed

    def should_skip(self, text: str) -> bool:
        flat = " ".join(text.split())
        return any(p.search(flat) for p in self.skip)

    def override(self, text: str) -> Optional[str]:
        return self._lookup(self.overrides, text)
