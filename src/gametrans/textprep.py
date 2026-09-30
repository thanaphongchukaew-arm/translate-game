"""Protect text spans a translator must not touch (numbers, formats,
placeholders, glossary terms) before translation, and restore them
afterwards. See spec section 8.6.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping

_TOKEN_FMT = "⟦P{}⟧"  # ⟦ ⟧ = mathematical white square brackets: unlikely in game text
_TOKEN_RE = re.compile(r"⟦P(\d+)⟧")

# Combined into ONE alternation and matched in a single pass over the
# original text. This matters: chaining separate .sub() calls would let a
# later pattern (e.g. the plain-number catch-all) re-match digits that are
# part of a placeholder token an earlier pattern just inserted, producing
# corrupt nested tokens. Order within the alternation is significant —
# regex tries alternatives left-to-right at each position, so more specific
# patterns must come before the generic number catch-all.
_PROTECT_RE = re.compile(
    r"\{[^{}]*\}"                        # {0}, {name}
    r"|%[sd%]"                           # %s %d %%
    r"|<[^<>]+>"                         # <name>
    r"|\d+/\d+"                          # 120/200
    r"|[+-]\d+(?:\.\d+)?%"               # +3%, -5%
    r"|[+-]\d+(?:\.\d+)?"                # +3, -5
    r"|\bx\d+(?:\.\d+)?\b"               # x2
    r"|\d+(?:\.\d+)?%"                   # 50%
    r"|\d+(?:\.\d+)?",                   # plain numbers (catch-all, last)
    re.IGNORECASE,
)

_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass(frozen=True)
class Prepared:
    text: str
    restore: Callable[[str], str]
    skip: bool


def _sentence_case_if_all_caps(text: str) -> str:
    if len(text) > 3 and text.isupper() and _HAS_LETTER_RE.search(text):
        return text[0] + text[1:].lower()
    return text


def prepare(text: str, glossary: Mapping[str, str]) -> Prepared:
    mapping: dict[str, str] = {}
    counter = 0
    working = _sentence_case_if_all_caps(text)

    def _protect_sub(m: re.Match[str]) -> str:
        nonlocal counter
        token = _TOKEN_FMT.format(counter)
        mapping[token] = m.group(0)
        counter += 1
        return token

    working = _PROTECT_RE.sub(_protect_sub, working)

    for term in sorted(glossary, key=len, reverse=True):
        if not term:
            continue
        thai = glossary[term]
        pat = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)

        def _sub(m: re.Match[str], thai: str = thai) -> str:
            nonlocal counter
            token = _TOKEN_FMT.format(counter)
            mapping[token] = thai
            counter += 1
            return token

        working = pat.sub(_sub, working)

    stripped = _TOKEN_RE.sub("", working)
    skip = not _HAS_LETTER_RE.search(stripped)

    def restore(translated: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            return mapping.get(m.group(0), m.group(0))

        return _TOKEN_RE.sub(_sub, translated)

    return Prepared(text=working, restore=restore, skip=skip)
