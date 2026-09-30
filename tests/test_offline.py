"""Verifies the app never makes an outbound network connection during
normal operation (spec section 16). Blocks every socket.connect() call
except to loopback (127.0.0.1/::1) and asserts real OCR + translation
still work -- proving they run fully offline, not just "should".

These tests need the real downloaded models (marked `slow`) since a mock
translator/OCR engine wouldn't actually exercise "does this library try
to phone home" the way the real ones do.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@pytest.fixture
def block_non_loopback_sockets(monkeypatch):
    original_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _ALLOWED_HOSTS:
            raise RuntimeError(f"blocked outbound connection attempt to {address!r} — offline guarantee violated")
        return original_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    yield


def test_requirements_lock_has_no_cloud_sdk():
    """spec section 1 rule 7: no anthropic/openai/etc SDKs, ever."""
    lock_path = Path(__file__).resolve().parent.parent / "requirements.lock"
    content = lock_path.read_text(encoding="utf-8").lower()
    forbidden = ["anthropic", "openai", "cohere", "google-generativeai", "google-cloud", "azure-ai"]
    hits = [name for name in forbidden if name in content]
    assert not hits, f"requirements.lock contains forbidden cloud SDK(s): {hits}"


def test_network_allow_outbound_defaults_to_false():
    from gametrans.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["network"]["allow_outbound"] is False


@pytest.mark.slow
def test_ocr_runs_fully_offline(block_non_loopback_sockets):
    import numpy as np
    from PIL import Image

    from gametrans.ocr import run_ocr

    fixture = Path(__file__).resolve().parent / "fixtures" / "synthetic" / "03_dialogue_box.png"
    img = np.array(Image.open(fixture).convert("RGB"))[:, :, ::-1]
    lines = run_ocr(img, cfg={"ocr": {"min_score": 0.3, "min_box_h": 5}})
    assert len(lines) > 0  # ran successfully with zero outbound connections


@pytest.mark.slow
def test_translation_runs_fully_offline(block_non_loopback_sockets):
    from gametrans.translate_fast import NllbCTranslator

    model_dir = Path(__file__).resolve().parent.parent / "models" / "fast" / "nllb200-600m-int8"
    if not (model_dir / "model.bin").exists():
        pytest.skip("NLLB model not downloaded")

    translator = NllbCTranslator(model_dir=str(model_dir))
    out = translator.translate(["Hello, traveler."])
    assert out and out[0]
