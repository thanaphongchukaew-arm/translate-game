"""Tier-2 LLM server management: health-check and (for llama-server)
start/stop a local HTTP inference server, always on 127.0.0.1 only (spec
section 11.2: "เชื่อมผ่าน 127.0.0.1 เท่านั้น").

NOT exercised end-to-end in this project yet: the user chose to skip
installing Ollama/llama-server for now since tier 1 alone already meets
the speed/quality bar (see DECISIONS.md phase 4). This module is coded
and unit-tested against a fake local HTTP server standing in for the real
thing, but has not been run against an actual Ollama or llama-server
process. Report status honestly until that verification happens.
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("gametrans.llm_server")


@dataclass(frozen=True)
class ServerStatus:
    running: bool
    backend: str
    detail: str = ""


def is_server_running(host: str = "127.0.0.1", port: int = 8089, timeout_s: float = 1.0) -> bool:
    import urllib.request
    import urllib.error

    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def check_ollama(host: str = "127.0.0.1", port: int = 11434, timeout_s: float = 1.0) -> ServerStatus:
    import urllib.request
    import urllib.error

    url = f"http://{host}:{port}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            if resp.status == 200:
                return ServerStatus(running=True, backend="ollama")
            return ServerStatus(running=False, backend="ollama", detail=f"HTTP {resp.status}")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return ServerStatus(running=False, backend="ollama", detail=str(exc))


class LlamaServerProcess:
    """Starts/stops a `llama-server` binary as a subprocess. The binary
    itself (tools/bin/llama-server.exe, per spec section 11.2) is not
    bundled by this project yet -- start() will fail with FileNotFoundError
    until the user places one there, and callers must treat that as
    "tier 2 unavailable", not a crash (spec section 15's fallback table)."""

    def __init__(self, binary_path: str, model_path: str, host: str = "127.0.0.1", port: int = 8089) -> None:
        self.binary_path = binary_path
        self.model_path = model_path
        self.host = host
        self.port = port
        self._process: Optional[subprocess.Popen] = None

    def start(self, startup_timeout_s: float = 30.0) -> bool:
        args = [
            self.binary_path,
            "--model", self.model_path,
            "--host", self.host,
            "--port", str(self.port),
        ]
        try:
            self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, FileNotFoundError) as exc:
            logger.warning("llm_server: cannot start llama-server (%s)", exc)
            return False

        deadline = time.monotonic() + startup_timeout_s
        while time.monotonic() < deadline:
            if is_server_running(self.host, self.port, timeout_s=1.0):
                return True
            if self._process.poll() is not None:
                logger.warning("llm_server: llama-server exited early (code %s)", self._process.returncode)
                return False
            time.sleep(0.5)
        logger.warning("llm_server: llama-server did not become healthy within %.0fs", startup_timeout_s)
        return False

    def stop(self, timeout_s: float = 5.0) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
