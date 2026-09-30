"""Tier 1 translator: CTranslate2 running a quantized NLLB-200 model
locally (no network calls). See DECISIONS.md phase 3 for why this exact
model/format was chosen and how it was verified.

NLLB-200 tokenization (verified empirically against the real model, not
assumed — an earlier draft omitted the trailing EOS and got token-salad
output like "Hello Hello Hello, travel travel travel."):
  source tokens = [src_flores_code] + sentencepiece_pieces + ["</s>"]
  target_prefix = [tgt_flores_code]
  output        = hypothesis tokens with the leading tgt_flores_code dropped

CUDA note: like onnxruntime-gpu, ctranslate2's CUDA path needs cuBLAS/cuDNN
DLLs that aren't present via a system CUDA Toolkit install on this machine.
Unlike onnxruntime, `os.add_dll_directory()` does NOT make ctranslate2 find
them (its loader apparently doesn't honor AddDllDirectory-registered
paths) — prepending the pip-packaged nvidia-cublas-cu12/nvidia-cudnn-cu12
DLL folders to the PATH environment variable *does* work. Also,
`ctranslate2.get_cuda_device_count()` only checks the driver, not whether
cuBLAS actually loads, so device="auto" does a real (tiny) translate call
to verify CUDA works before trusting it, falling back to CPU on failure.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Sequence

logger = logging.getLogger("gametrans.translate_fast")

_LANG_TO_FLORES = {
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "th": "tha_Thai",
}

_translator_cache: dict[str, "object"] = {}
_tokenizer_cache: dict[str, "object"] = {}
_cuda_dll_path_added = False


def _ensure_cuda_dlls_on_path() -> None:
    """Prepend pip-packaged nvidia-cublas-cu12/nvidia-cudnn-cu12 DLL dirs to
    PATH, if those packages are installed, so ctranslate2's CUDA backend can
    find them without requiring a system-wide CUDA Toolkit install."""
    global _cuda_dll_path_added
    if _cuda_dll_path_added or sys.platform != "win32":
        return
    site_packages = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
    extra_dirs = [site_packages / "nvidia" / pkg / "bin" for pkg in ("cublas", "cudnn")]
    existing = [str(d) for d in extra_dirs if d.is_dir()]
    if existing:
        os.environ["PATH"] = os.pathsep.join(existing) + os.pathsep + os.environ.get("PATH", "")
    _cuda_dll_path_added = True


def _create_translator(model_dir: str, device: str):
    import ctranslate2

    return ctranslate2.Translator(model_dir, device=device)


def _cuda_actually_works(translator, tokenizer, source_flores: str, target_flores: str) -> bool:
    try:
        probe = [source_flores] + tokenizer.encode("test", out_type=str) + ["</s>"]
        translator.translate_batch([probe], target_prefix=[[target_flores]], beam_size=1)
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "cuda doesn't actually work"
        logger.warning("translate_fast: cuda probe failed (%s) — falling back to cpu", exc)
        return False


def _get_translator(model_dir: str, device: str, source_flores: str, target_flores: str):
    key = f"{model_dir}|{device}"
    if key in _translator_cache:
        return _translator_cache[key]

    import ctranslate2

    tokenizer = _get_tokenizer(model_dir)
    _ensure_cuda_dlls_on_path()

    if device == "auto":
        if ctranslate2.get_cuda_device_count() > 0:
            try:
                candidate = _create_translator(model_dir, "cuda")
                if _cuda_actually_works(candidate, tokenizer, source_flores, target_flores):
                    _translator_cache[key] = candidate
                    return candidate
            except Exception as exc:  # noqa: BLE001 - fall back to cpu
                logger.warning("translate_fast: cuda unavailable (%s) — using cpu", exc)
        translator = _create_translator(model_dir, "cpu")
    else:
        translator = _create_translator(model_dir, device)

    _translator_cache[key] = translator
    return translator


def _get_tokenizer(model_dir: str):
    import sentencepiece as spm

    if model_dir not in _tokenizer_cache:
        sp_path = Path(model_dir) / "tokenizer" / "sentencepiece.bpe.model"
        if not sp_path.exists():
            raise FileNotFoundError(f"sentencepiece model not found at {sp_path}")
        proc = spm.SentencePieceProcessor()
        proc.load(str(sp_path))
        _tokenizer_cache[model_dir] = proc
    return _tokenizer_cache[model_dir]


class NllbCTranslator:
    """Implements the Translator protocol from spec section 7:
    `translate(texts, context=()) -> list[str]`, same length as `texts`,
    or raises. Tier 1 ignores `context` (spec: "ชั้น 1 ไม่ใช้บริบทเพื่อความเร็ว")."""

    name = "nllb200-600m-int8"

    def __init__(
        self,
        model_dir: str = "models/fast/nllb200-600m-int8",
        source_lang: str = "en",
        target_lang: str = "th",
        device: str = "auto",
        beam_size: int = 1,
    ) -> None:
        self.model_dir = model_dir
        self.source_flores = _LANG_TO_FLORES.get(source_lang, "eng_Latn")
        self.target_flores = _LANG_TO_FLORES.get(target_lang, "tha_Thai")
        self.device = device
        self.beam_size = beam_size

    def translate(self, texts: Sequence[str], context: Sequence[str] = ()) -> list[str]:
        if not texts:
            return []
        tokenizer = _get_tokenizer(self.model_dir)
        translator = _get_translator(self.model_dir, self.device, self.source_flores, self.target_flores)

        source_tokens = []
        for text in texts:
            pieces = tokenizer.encode(text, out_type=str)
            source_tokens.append([self.source_flores] + pieces + ["</s>"])

        target_prefix = [[self.target_flores]] * len(texts)
        results = translator.translate_batch(
            source_tokens,
            target_prefix=target_prefix,
            beam_size=self.beam_size,
            max_batch_size=32,
        )

        outputs: list[str] = []
        for r in results:
            tokens = r.hypotheses[0][1:]  # drop the leading target-language token
            outputs.append(tokenizer.decode(tokens))
        return outputs
