"""Safe, conservative cleanup of raw OCR text (spec section 8.3).

Rules: only "fix" something when the fix is provably safer than leaving it
alone (e.g. a confusable-character substitution that turns a non-word into a
real dictionary word). Never touch digits, codes, or names aggressively.
"""
from __future__ import annotations

import re
import string

# Small bundled word list — enough to validate common English game/UI text.
# Not a full dictionary; expand as real OCR data (P5X fixtures, phase 2B)
# reveals more false positives/negatives. See DECISIONS.md.
_WORDLIST = frozenset(
    w.lower()
    for w in """
    a an the of to in on at by for with from into onto out over under
    is are was were be been being do does did have has had will would
    can could shall should may might must not no yes
    i you he she it we they me him her us them my your his its our their
    this that these those here there where when why how what who
    game start options continue save load quit exit menu settings
    inventory items item skill skills quest quests level levels
    health mana stamina damage attack defense speed critical
    hero heroes player players enemy enemies boss monster monsters
    sword shield armor potion potions gold silver coin coins gem gems
    key keys door doors chest chests map world village town city castle
    forest cave mountain river lake sea ocean sky ground road path
    traveler travelers wanderer merchant merchants guard guards king queen
    lord lady prince princess knight knights wizard witch mage priest
    story chapter chapters mission missions objective objectives
    online offline connect connection lost reconnect reconnecting
    party guild raid tonight anyone tomorrow today yesterday night day
    morning evening afternoon time turns turn build research complete
    granary iron working gold enough insufficient resources resource
    summon summons rate pity daily quest stamina battle pass banner limited
    tap skip auto log claim all hp mp xp exp
    hello world welcome goodbye thanks thank please sorry excuse
    remember forget remembers everything nothing something anything
    shouldn wouldn couldn didn doesn isn aren wasn weren havent hasnt
    come came coming go going went gone leave left arrive arrived
    meet meeting met old new young small big large tiny huge
    mill sunset sunrise dawn dusk moon sun star stars
    tell told say said speak spoke talk talked whisper whispered
    hear heard listen listened sound sounds voice voices
    wait waited stop stopped continue continued
    """.split()
)

_CONFUSABLE_GROUPS: list[tuple[str, ...]] = [
    ("0", "O", "o"),
    ("1", "l", "I", "|"),
    ("5", "S"),
    ("8", "B"),
    ("rn", "m"),
]

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "-",
})

_HYPHEN_BREAK_RE = re.compile(r"(\w+)-\s+(\w+)")


def _normalize_quotes(text: str) -> str:
    return text.translate(_QUOTE_MAP)


def _merge_hyphenation(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        left, right = m.group(1), m.group(2)
        joined = left + right
        if joined.lower() in _WORDLIST:
            return joined
        return m.group(0)

    return _HYPHEN_BREAK_RE.sub(_sub, text)


def _confusable_variants(word: str) -> list[str]:
    variants: list[str] = []
    for group in _CONFUSABLE_GROUPS:
        for i, sub in enumerate(group):
            if sub not in word:
                continue
            for repl in group:
                if repl == sub:
                    continue
                variants.append(word.replace(sub, repl, 1))
    return variants


def fix_confusables(word: str) -> str:
    """Fix commonly-confused OCR characters (0/O, 1/l/I, rn/m, ...) but only
    when doing so turns the word into a known dictionary word — never when
    the original word is already a plausible token (has digits, is a code,
    or is already a real word).

    The replacement casing is reconstructed from the *original* word's case
    pattern (all-caps / title-case / lowercase) rather than from whichever
    literal confusable character happened to be substituted, so "W0rld"
    resolves to "World" and not "WOrld"."""
    core = word.strip(string.punctuation)
    if not core:
        return word
    if core.lower() in _WORDLIST:
        return word
    for variant in _confusable_variants(core):
        lower_variant = variant.lower()
        if lower_variant in _WORDLIST and lower_variant != core.lower():
            if core.isupper():
                fixed_core = lower_variant.upper()
            elif core[:1].isupper():
                fixed_core = lower_variant.capitalize()
            else:
                fixed_core = lower_variant
            return word.replace(core, fixed_core, 1)
    return word


def clean_text(text: str) -> str:
    """Whitespace/quote normalization, safe hyphenation merge, and
    conservative confusable-character fixes. Never touches proper nouns
    (capitalized mid-sentence) or tokens containing digits unless the fix
    resolves to a dictionary word."""
    if not text:
        return text

    text = _normalize_quotes(text)
    text = _merge_hyphenation(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n")).strip()

    words = text.split(" ")
    fixed_words = []
    for idx, tok in enumerate(words):
        core = tok.strip(string.punctuation)
        if not core:
            fixed_words.append(tok)
            continue
        # Conservative: skip likely proper nouns (capitalized, not sentence-start,
        # not ALL-CAPS) to avoid mangling names.
        is_mid_sentence_capital = (
            idx > 0 and core[:1].isupper() and not core.isupper() and core.lower() not in _WORDLIST
        )
        if is_mid_sentence_capital:
            fixed_words.append(tok)
            continue
        new_core = fix_confusables(core)
        fixed_words.append(tok.replace(core, new_core, 1) if new_core != core else tok)
    return " ".join(fixed_words)
