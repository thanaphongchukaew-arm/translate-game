"""Persistent translation store: overrides (user-edited, permanent),
glossary (user-edited terms) and translation cache (LRU, final-only persisted).

Lookup priority: override > final cache > non-final cache.
A non-final `put` never overwrites an existing final entry for the same text.
All writes to disk are atomic (write temp file, then os.replace) and keep a
`.bak` of the previous version.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gametrans.store")

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Entry:
    text: str
    thai: str
    tier: int
    final: bool


def _atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            logger.warning("store: could not update backup %s", bak)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_json_with_backup(path: Path) -> Optional[dict]:
    path = Path(path)
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("store: cannot read %s (%s)", candidate, exc)
            continue
    return None


class Store:
    def __init__(
        self,
        overrides_path: str | Path = "overrides.json",
        glossary_path: str | Path = "glossary.json",
        cache_path: str | Path = "translation_cache.json",
        max_entries: int = 8000,
    ) -> None:
        self.overrides_path = Path(overrides_path)
        self.glossary_path = Path(glossary_path)
        self.cache_path = Path(cache_path)
        self.max_entries = max_entries

        self._lock = threading.Lock()
        self._overrides: dict[str, str] = {}
        self._glossary: dict[str, str] = {}
        self._cache: "OrderedDict[str, Entry]" = OrderedDict()

    # ---------------------------------------------------------------- I/O

    def load(self) -> None:
        with self._lock:
            ov = _load_json_with_backup(self.overrides_path)
            self._overrides = dict(ov.get("entries", {})) if ov else {}

            gl = _load_json_with_backup(self.glossary_path)
            self._glossary = dict(gl.get("entries", {})) if gl else {}

            cache_data = _load_json_with_backup(self.cache_path)
            self._cache = OrderedDict()
            if cache_data:
                for text, item in cache_data.get("entries", {}).items():
                    self._cache[text] = Entry(
                        text=text,
                        thai=item.get("thai", ""),
                        tier=int(item.get("tier", 0)),
                        final=bool(item.get("final", True)),
                    )

    def save(self) -> None:
        """Persist overrides, glossary and cache. Only `final` entries are
        written to the cache file — non-final (tier-1, transient) entries
        live in memory only."""
        with self._lock:
            _atomic_write_json(
                self.overrides_path,
                {"schema_version": SCHEMA_VERSION, "entries": dict(self._overrides)},
            )
            _atomic_write_json(
                self.glossary_path,
                {"schema_version": SCHEMA_VERSION, "entries": dict(self._glossary)},
            )
            final_entries = {
                text: {"thai": e.thai, "tier": e.tier, "final": True}
                for text, e in self._cache.items()
                if e.final
            }
            _atomic_write_json(
                self.cache_path,
                {"schema_version": SCHEMA_VERSION, "entries": final_entries},
            )

    # ------------------------------------------------------------ lookup

    def lookup(self, text: str) -> Optional[Entry]:
        with self._lock:
            if text in self._overrides:
                return Entry(text=text, thai=self._overrides[text], tier=-1, final=True)
            entry = self._cache.get(text)
            if entry is not None:
                self._cache.move_to_end(text)
            return entry

    def put(self, text: str, thai: str, tier: int, final: bool) -> None:
        with self._lock:
            existing = self._cache.get(text)
            if existing is not None and existing.final and not final:
                # final results are never overwritten by a lower tier
                self._cache.move_to_end(text)
                return
            self._cache[text] = Entry(text=text, thai=thai, tier=tier, final=final)
            self._cache.move_to_end(text)
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        """Clear the translation cache only — overrides and glossary are
        untouched (user data must never be silently deleted)."""
        with self._lock:
            self._cache.clear()

    def list_recent(self, limit: int = 200) -> list[Entry]:
        """Most-recently-used cache entries first (for the translation
        manager UI). Does not include overrides — those are listed
        separately via get_overrides()."""
        with self._lock:
            entries = list(self._cache.values())
        return list(reversed(entries))[:limit]

    # ---------------------------------------------------------- overrides

    def set_override(self, text: str, thai: str) -> None:
        with self._lock:
            self._overrides[text] = thai

    def remove_override(self, text: str) -> None:
        with self._lock:
            self._overrides.pop(text, None)

    def get_overrides(self) -> dict[str, str]:
        with self._lock:
            return dict(self._overrides)

    # ----------------------------------------------------------- glossary

    def get_glossary(self) -> dict[str, str]:
        with self._lock:
            return dict(self._glossary)

    def set_glossary_term(self, term: str, translation: str) -> None:
        with self._lock:
            self._glossary[term] = translation

    def remove_glossary_term(self, term: str) -> None:
        with self._lock:
            self._glossary.pop(term, None)
