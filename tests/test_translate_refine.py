"""Tests translate_refine.py against a REAL local HTTP server (stdlib
http.server, not urllib mocks) standing in for Ollama/llama-server, so the
request/response wiring is genuinely exercised end-to-end -- just with a
fake "brain" instead of a real LLM. See module docstring for what is and
isn't verified here.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gametrans.layout import Block
from gametrans.translate_refine import build_prompt, refine_should_run, RefineTranslator


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence test server logging
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        assert body["model"] == "test-model"
        # echo something that looks like a Thai translation of whatever
        # was inside <src>...</src>, so tests can assert on it.
        prompt = body["prompt"]
        src = prompt.rsplit("<src>", 1)[1].rsplit("</src>", 1)[0]
        response = {"response": f"[TH]{src}"}
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


class _FakeLlamaServerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        prompt = body["prompt"]
        src = prompt.rsplit("<src>", 1)[1].rsplit("</src>", 1)[0]
        response = {"content": f"[TH]{src}"}
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def fake_ollama_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _FakeOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def fake_llama_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _FakeLlamaServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join(timeout=5)


def test_build_prompt_contains_required_sections():
    prompt = build_prompt("Hello", {"Potion": "ยา"}, ["prev line"])
    assert "<src>Hello</src>" in prompt
    assert "Potion = ยา" in prompt
    assert "prev line" in prompt
    assert "Output ONLY the Thai translation" in prompt


def test_build_prompt_empty_glossary_and_context_shows_none():
    prompt = build_prompt("Hi", {}, [])
    assert "(none)" in prompt


def test_ollama_backend_real_http_round_trip(fake_ollama_server):
    translator = RefineTranslator(backend="ollama", model="test-model", port=fake_ollama_server)
    out = translator.translate(["Hello there"])
    assert out == ["[TH]Hello there"]


def test_llama_server_backend_real_http_round_trip(fake_llama_server):
    translator = RefineTranslator(backend="llama-server", port=fake_llama_server)
    out = translator.translate(["Hello there"])
    assert out == ["[TH]Hello there"]


def test_translate_multiple_texts_same_length_output(fake_ollama_server):
    translator = RefineTranslator(backend="ollama", model="test-model", port=fake_ollama_server)
    out = translator.translate(["A", "B", "C"])
    assert len(out) == 3


def test_unreachable_server_raises_runtime_error():
    translator = RefineTranslator(backend="ollama", model="test-model", port=1, timeout_s=0.5)
    with pytest.raises(RuntimeError):
        translator.translate(["Hello"])


def test_unknown_backend_raises_runtime_error(fake_ollama_server):
    translator = RefineTranslator(backend="not-a-real-backend", port=fake_ollama_server)
    with pytest.raises(RuntimeError):
        translator.translate(["Hello"])


def _block(stable_cycles, stable_since, id_=0):
    return Block(
        id=id_, x1=0, y1=0, x2=10, y2=10, text="x", line_h=10.0,
        first_seen=0.0, last_seen=0.0, stable_cycles=stable_cycles, stable_since=stable_since,
    )


def test_refine_should_run_false_when_not_enough_cycles():
    cfg = {"layout": {"stable_cycles_for_refine": 2, "stable_ms_for_refine": 500}}
    block = _block(stable_cycles=1, stable_since=0.0)
    assert refine_should_run(block, now=10.0, cfg=cfg) is False


def test_refine_should_run_false_when_not_enough_time_elapsed():
    cfg = {"layout": {"stable_cycles_for_refine": 2, "stable_ms_for_refine": 500}}
    block = _block(stable_cycles=5, stable_since=1.0)
    assert refine_should_run(block, now=1.1, cfg=cfg) is False  # only 100ms elapsed


def test_refine_should_run_true_when_both_conditions_met():
    cfg = {"layout": {"stable_cycles_for_refine": 2, "stable_ms_for_refine": 500}}
    block = _block(stable_cycles=5, stable_since=1.0)
    assert refine_should_run(block, now=1.6, cfg=cfg) is True  # 600ms elapsed


def test_typewriter_simulation_does_not_fire_refine_until_text_settles():
    """Simulates OCR running fast (uncapped, spec 3D) against a typewriter
    dialogue effect: text grows every "frame" for a while, then holds
    steady. refine_should_run must stay False while text is still growing,
    even though stable_cycles alone would eventually pass 2 during a brief
    pause -- only the stable_ms wall-clock gate should let it through."""
    from gametrans.layout import merge_lines, track_blocks, OcrLine

    cfg = {"layout": {"stable_cycles_for_refine": 2, "stable_ms_for_refine": 500}, "ocr": {"max_blocks": 60}}

    growing_texts = ["You", "You should", "You shouldn't", "You shouldn't have come here."]
    prev_blocks: list[Block] = []
    now = 0.0
    fired = False
    for text in growing_texts:
        now += 0.05  # OCR loop runs every 50ms while typewriter is animating
        cur = merge_lines([OcrLine(x1=0, y1=0, x2=100, y2=20, text=text, score=0.9)], cfg)
        prev_blocks = track_blocks(prev_blocks, cur, now, cfg)
        if refine_should_run(prev_blocks[0], now, cfg):
            fired = True
    assert fired is False, "refine fired while text was still being typed out"

    # now the text stops changing and enough wall-clock time passes
    final_text = growing_texts[-1]
    for _ in range(3):
        now += 0.2
        cur = merge_lines([OcrLine(x1=0, y1=0, x2=100, y2=20, text=final_text, score=0.9)], cfg)
        prev_blocks = track_blocks(prev_blocks, cur, now, cfg)

    assert refine_should_run(prev_blocks[0], now, cfg) is True
