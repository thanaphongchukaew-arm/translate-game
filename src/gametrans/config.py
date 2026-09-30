"""Load, merge and validate config.default.json + config.user.json.

Every value has a default. A missing key, wrong type or out-of-range value
falls back to the default and logs a warning — this module never raises on
malformed user config.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("gametrans.config")

DEFAULT_CONFIG: dict[str, Any] = {
    "mode": "max_accuracy",
    "autostart": True,
    "run_in_tray": True,
    "capture": {"backend": "auto", "max_ocr_fps": 0, "diff_threshold": 0},
    "capture_target": {"type": "auto", "window_title": ""},
    "ocr": {
        "provider": "auto",
        "min_score": 0.6,
        "min_box_h": 8,
        "max_blocks": 60,
        "upscale_small_text": True,
        "rec_model_path": "models/ocr/en/en_PP-OCRv3_rec_infer.onnx",
    },
    "layout": {"hold_cycles": 2, "stable_cycles_for_refine": 2, "stable_ms_for_refine": 500, "context_lines": 3},
    "fast": {"model_dir": "models/fast/nllb200-600m-int8", "beam_size": 1, "max_batch": 16, "device": "auto", "intra_threads": 0},
    "refine": {
        "enabled": "auto",
        "backend": "llama-server",
        "model_path": "",
        "host": "127.0.0.1",
        "port": 8089,
        "idle_unload_s": 0,
        "max_vram_mb": 0,
    },
    "text": {"keep_names": True, "glossary_path": "glossary.json", "overrides_path": "overrides.json"},
    "overlay": {"font": "Leelawadee UI", "min_font_px": 11, "bg_rgba": [12, 12, 18, 225], "fg_rgb": [255, 255, 255]},
    "display": {"mode": "auto", "output_monitor": "auto", "mirror_fps": 60, "visible_to_stream": False},
    "regions": {"profile_dir": "profiles", "active_profile": "auto", "preset": "auto", "auto_discover_interval_s": 1.0, "profile_select_delay_s": 2.5},
    "watchdog": {"stall_seconds": 10, "max_restarts_per_min": 6},
    "language": {"source": "auto", "target": "th", "cjk_pivot_via_english": "auto"},
    "resources": {"low_priority": False, "adaptive_throttle": False, "gpu_for_game_first": False},
    "cache": {"path": "translation_cache.json", "max_entries": 8000},
    "log": {"level": "INFO", "path": "gametrans.log", "log_text": False},
    "network": {"allow_outbound": False},
}

# dotted-path -> (min, max) inclusive, for numeric fields worth range-checking
_RANGES: dict[str, tuple[float, float]] = {
    "capture.max_ocr_fps": (0, 240),
    "capture.diff_threshold": (0, 255),
    "ocr.min_score": (0.0, 1.0),
    "ocr.min_box_h": (1, 200),
    "ocr.max_blocks": (1, 500),
    "layout.hold_cycles": (0, 50),
    "layout.stable_cycles_for_refine": (0, 50),
    "layout.stable_ms_for_refine": (0, 60000),
    "layout.context_lines": (0, 20),
    "fast.beam_size": (1, 16),
    "fast.max_batch": (1, 256),
    "fast.intra_threads": (0, 64),
    "refine.port": (1, 65535),
    "refine.idle_unload_s": (0, 86400),
    "refine.max_vram_mb": (0, 262144),
    "overlay.min_font_px": (6, 96),
    "display.mirror_fps": (1, 240),
    "regions.auto_discover_interval_s": (0.05, 3600),
    "regions.profile_select_delay_s": (0, 30),
    "watchdog.stall_seconds": (1, 3600),
    "watchdog.max_restarts_per_min": (1, 1000),
    "cache.max_entries": (10, 1000000),
}

_ENUMS: dict[str, tuple[Any, ...]] = {
    "mode": ("fastest", "balanced", "max_accuracy", "eco"),
    "capture.backend": ("auto", "dxcam", "mss"),
    "capture_target.type": ("auto", "monitor", "window"),
    "ocr.provider": ("auto", "cuda", "directml", "cpu"),
    "fast.device": ("auto", "cuda", "cpu"),
    "refine.enabled": ("auto", True, False),
    "display.mode": ("auto", "A", "B", "C"),
    "language.cjk_pivot_via_english": ("auto", True, False),
    "log.level": ("DEBUG", "INFO", "WARNING", "ERROR"),
}


def _get_path(d: dict, dotted: str) -> Any:
    node = d
    for part in dotted.split("."):
        node = node[part]
    return node


def _set_path(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = d
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _merge_and_validate(default: dict, user: Any, prefix: str = "") -> dict:
    """Recursively merge user config onto default, validating types/ranges.

    Any mismatch falls back to the default value for that leaf and logs a
    warning. Returns a brand-new dict; never mutates inputs.
    """
    if not isinstance(user, dict):
        if prefix:
            logger.warning("config: %s expected object, got %r — using defaults", prefix, user)
        return copy.deepcopy(default)

    result: dict[str, Any] = {}
    for key, default_value in default.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in user:
            result[key] = copy.deepcopy(default_value)
            continue
        user_value = user[key]
        if isinstance(default_value, dict):
            result[key] = _merge_and_validate(default_value, user_value, path)
            continue
        result[key] = _validate_leaf(path, default_value, user_value)
    return result


def _validate_leaf(path: str, default_value: Any, user_value: Any) -> Any:
    # bool must be exactly bool (bool is a subclass of int, check first)
    if isinstance(default_value, bool):
        if isinstance(user_value, bool):
            candidate = user_value
        else:
            logger.warning("config: %s expected bool, got %r — using default %r", path, user_value, default_value)
            return default_value
    elif isinstance(default_value, (int, float)):
        if isinstance(user_value, bool) or not isinstance(user_value, (int, float)):
            logger.warning("config: %s expected number, got %r — using default %r", path, user_value, default_value)
            return default_value
        candidate = user_value
    elif isinstance(default_value, str):
        if not isinstance(user_value, str):
            logger.warning("config: %s expected string, got %r — using default %r", path, user_value, default_value)
            return default_value
        candidate = user_value
    elif isinstance(default_value, list):
        if not isinstance(user_value, list):
            logger.warning("config: %s expected list, got %r — using default %r", path, user_value, default_value)
            return default_value
        candidate = user_value
    else:
        candidate = user_value

    if path in _ENUMS and candidate not in _ENUMS[path]:
        logger.warning(
            "config: %s value %r not in allowed set %r — using default %r",
            path, candidate, _ENUMS[path], default_value,
        )
        return default_value

    if path in _RANGES and isinstance(candidate, (int, float)):
        lo, hi = _RANGES[path]
        if not (lo <= candidate <= hi):
            logger.warning(
                "config: %s value %r out of range [%r, %r] — using default %r",
                path, candidate, lo, hi, default_value,
            )
            return default_value

    return candidate


def merge_config(default: dict, user: dict) -> dict:
    """Merge user config onto default with validation. Pure function."""
    return _merge_and_validate(default, user)


def load_config(
    user_path: str | Path = "config.user.json",
    default_path: str | Path | None = None,
) -> dict:
    """Load config.default.json (or built-in DEFAULT_CONFIG) merged with
    config.user.json. Never raises — malformed/missing files fall back to
    defaults with a logged warning.
    """
    if default_path is not None:
        default_path = Path(default_path)
        try:
            default = json.loads(default_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("config: cannot read %s (%s) — using built-in defaults", default_path, exc)
            default = copy.deepcopy(DEFAULT_CONFIG)
    else:
        default = copy.deepcopy(DEFAULT_CONFIG)

    user_path = Path(user_path)
    user: dict[str, Any] = {}
    if user_path.exists():
        try:
            user = json.loads(user_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("config: cannot read %s (%s) — using defaults only", user_path, exc)
            user = {}

    return merge_config(default, user)
