"""Tests llm_server.py against a real local HTTP server standing in for
Ollama/llama-server's health endpoints, plus LlamaServerProcess's graceful
failure when the binary doesn't exist (it never has on this machine --
see module docstring in llm_server.py)."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gametrans.llm_server import LlamaServerProcess, check_ollama, is_server_running


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _HealthyHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


@pytest.fixture
def fake_healthy_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _HealthyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join(timeout=5)


def test_is_server_running_true_for_real_server(fake_healthy_server):
    assert is_server_running(port=fake_healthy_server) is True


def test_is_server_running_false_for_closed_port():
    assert is_server_running(port=1, timeout_s=0.5) is False


def test_check_ollama_true_for_real_server(fake_healthy_server):
    status = check_ollama(port=fake_healthy_server)
    assert status.running is True
    assert status.backend == "ollama"


def test_check_ollama_false_when_unreachable():
    status = check_ollama(port=1, timeout_s=0.5)
    assert status.running is False
    assert status.detail  # some reason recorded


def test_llama_server_process_start_fails_gracefully_when_binary_missing(tmp_path):
    proc = LlamaServerProcess(
        binary_path=str(tmp_path / "does-not-exist.exe"),
        model_path=str(tmp_path / "model.gguf"),
        port=_free_port(),
    )
    ok = proc.start(startup_timeout_s=1.0)
    assert ok is False
    assert proc.is_running is False


def test_llama_server_process_stop_is_safe_when_never_started():
    proc = LlamaServerProcess(binary_path="nope", model_path="nope")
    proc.stop()  # must not raise
