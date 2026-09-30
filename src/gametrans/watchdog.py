"""Watchdog (spec section 3D/15): detects a stalled thread (no heartbeat
within `stall_seconds`) and reports it so the caller can restart that
part, with exponential backoff capped at `max_restarts_per_min` to avoid a
restart storm if something is persistently broken.

This module only detects and decides *when* a restart is allowed; it does
not itself know how to restart a Pipeline (that's app-level orchestration,
kept in ui_main.py, since only it owns the Pipeline's lifecycle).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("gametrans.watchdog")


@dataclass
class _ComponentState:
    last_heartbeat: float
    restart_timestamps: list = field(default_factory=list)
    backoff_until: float = 0.0
    backoff_seconds: float = 1.0


class Watchdog:
    def __init__(self, stall_seconds: float = 10.0, max_restarts_per_min: int = 6) -> None:
        self.stall_seconds = stall_seconds
        self.max_restarts_per_min = max_restarts_per_min
        self._lock = threading.Lock()
        self._components: dict[str, _ComponentState] = {}

    def heartbeat(self, name: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            state = self._components.get(name)
            if state is None:
                self._components[name] = _ComponentState(last_heartbeat=now)
            else:
                state.last_heartbeat = now

    def register(self, name: str, now: float | None = None) -> None:
        """Explicitly start tracking a component before its first
        heartbeat (so check() doesn't false-positive on a component that
        hasn't started yet in this exact instant)."""
        self.heartbeat(name, now)

    def is_stalled(self, name: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            state = self._components.get(name)
            if state is None:
                return False
            return (now - state.last_heartbeat) > self.stall_seconds

    def should_restart(self, name: str, now: float | None = None) -> bool:
        """True if `name` is stalled AND we haven't exceeded the restart
        rate limit / aren't still in a backoff window. Call restarted()
        after actually restarting to record it and advance backoff."""
        now = time.monotonic() if now is None else now
        if not self.is_stalled(name, now):
            return False
        with self._lock:
            state = self._components[name]
            if now < state.backoff_until:
                return False
            recent = [t for t in state.restart_timestamps if now - t < 60.0]
            state.restart_timestamps = recent
            return len(recent) < self.max_restarts_per_min

    def restarted(self, name: str, now: float | None = None) -> None:
        """Record that a restart just happened: resets the heartbeat,
        logs the restart, and doubles the backoff window (capped) so a
        persistently-broken component doesn't spin-restart forever."""
        now = time.monotonic() if now is None else now
        with self._lock:
            state = self._components.setdefault(name, _ComponentState(last_heartbeat=now))
            state.last_heartbeat = now
            state.restart_timestamps.append(now)
            state.backoff_seconds = min(state.backoff_seconds * 2, 60.0)
            state.backoff_until = now + state.backoff_seconds
        logger.warning("watchdog: restarted %r (next backoff %.0fs)", name, state.backoff_seconds)

    def reset_backoff(self, name: str) -> None:
        """Call after a component has run healthily for a while, so a
        one-off blip long ago doesn't keep inflating future backoff."""
        with self._lock:
            state = self._components.get(name)
            if state is not None:
                state.backoff_seconds = 1.0
                state.backoff_until = 0.0
