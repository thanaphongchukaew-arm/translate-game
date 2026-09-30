"""Tier 2 translator: a local LLM (via llama-server's /completion or
Ollama's /api/generate, both on 127.0.0.1 only) refines a tier-1 result
using glossary + previous-lines context. Optional per spec section 3 --
the pipeline must work fully without it.

Status: coded and tested against a fake local HTTP server (see
tests/test_translate_refine.py), NOT run against a real Ollama/llama-server
process -- the user chose to skip installing one for now since tier 1
alone already clears the speed/quality bar (DECISIONS.md phase 4). Treat
"passes its tests" and "verified end-to-end with a real LLM" as different
claims; only the first is true today.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Mapping, Sequence

from gametrans.layout import Block

logger = logging.getLogger("gametrans.translate_refine")

# Verbatim from spec section 12. temperature=0, stop at newline / end tag.
PROMPT_TEMPLATE = """You are a professional game localizer translating English game text into natural Thai.
Rules:
- Output ONLY the Thai translation of the text between <src> and </src>. No quotes, notes, or explanations.
- Keep character names, place names and untranslatable game terms in English or common transliteration.
- Use the glossary translations exactly when the term appears.
- Preserve placeholders like [P0] and any numbers/symbols unchanged.
- UI text: short and natural. Dialogue: natural spoken Thai; keep the speaker's tone.
- Previous lines are context only. Do not translate them.
Glossary:
{glossary_lines}
Previous lines:
{context_lines}
<src>{text}</src>"""


def build_prompt(text: str, glossary: Mapping[str, str], context: Sequence[str]) -> str:
    glossary_lines = "\n".join(f"{k} = {v}" for k, v in glossary.items()) or "(none)"
    context_lines = "\n".join(context) or "(none)"
    return PROMPT_TEMPLATE.format(glossary_lines=glossary_lines, context_lines=context_lines, text=text)


def _call_ollama(host: str, port: int, model: str, prompt: str, timeout_s: float) -> str:
    url = f"http://{host}:{port}/api/generate"
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["response"]


def _call_llama_server(host: str, port: int, prompt: str, max_tokens: int, timeout_s: float) -> str:
    url = f"http://{host}:{port}/completion"
    payload = json.dumps({
        "prompt": prompt, "temperature": 0, "n_predict": max_tokens, "stop": ["</src>", "\n\n"],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["content"]


class RefineTranslator:
    """Implements the Translator protocol (spec section 7). Unlike tier 1,
    tier 2 DOES use `context` (previous lines) and the glossary."""

    name = "refine-llm"

    def __init__(
        self,
        backend: str = "ollama",
        model: str = "",
        host: str = "127.0.0.1",
        port: int = 8089,
        glossary: Mapping[str, str] | None = None,
        max_tokens: int = 200,
        timeout_s: float = 15.0,
    ) -> None:
        self.backend = backend
        self.model = model
        self.host = host
        self.port = port
        self.glossary = dict(glossary or {})
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def translate(self, texts: Sequence[str], context: Sequence[str] = ()) -> list[str]:
        outputs: list[str] = []
        if self.backend not in ("ollama", "llama-server"):
            raise RuntimeError(f"tier-2 refine call failed: unknown backend {self.backend!r}")

        for text in texts:
            prompt = build_prompt(text, self.glossary, context)
            try:
                if self.backend == "ollama":
                    raw = _call_ollama(self.host, self.port, self.model, prompt, self.timeout_s)
                else:
                    raw = _call_llama_server(self.host, self.port, prompt, self.max_tokens, self.timeout_s)
            except (urllib.error.URLError, OSError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"tier-2 refine call failed: {exc}") from exc
            outputs.append(raw.strip())
        return outputs


def refine_should_run(block: Block, now: float, cfg: Mapping) -> bool:
    """Should this block be sent to tier 2 right now? Requires BOTH enough
    consecutive stable cycles AND enough elapsed wall-clock time since the
    text last changed (spec section 3D: a cycle count alone is too short
    when OCR runs at full uncapped speed; a typewriter effect that briefly
    pauses mid-sentence must not be mistaken for "finished typing").
    Never fires twice for text that hasn't changed since the last refine
    -- callers should also track "already sent for this exact text" state,
    e.g. via store.Store (final entries aren't re-refined)."""
    layout_cfg = cfg.get("layout", {}) if isinstance(cfg, Mapping) else {}
    min_cycles = int(layout_cfg.get("stable_cycles_for_refine", 2))
    min_ms = float(layout_cfg.get("stable_ms_for_refine", 500))

    if block.stable_cycles < min_cycles:
        return False
    elapsed_ms = (now - block.stable_since) * 1000.0
    return elapsed_ms >= min_ms
