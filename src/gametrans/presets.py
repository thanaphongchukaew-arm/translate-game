"""Text-style presets (spec section 1A): per-region defaults for how to
merge/track/translate text, keyed by the genre of text a region contains
(dialogue box, dense UI, scrolling chat, subtitle, HUD, tooltip, retro
pixel font). Presets are data (presets/*.json) — adding a new one never
requires touching code.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("gametrans.presets")

SCHEMA_VERSION = 1

# Built-in fallback for every preset named in spec section 1A's table, used
# when presets/<name>.json is missing or fails validation — presets, like
# config, must never crash the app.
BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "dialogue": {
        "schema_version": SCHEMA_VERSION,
        "id": "dialogue",
        "merge_lines": True,
        "stable_ms_for_refine": 500,
        "context_lines": 3,
        "enable_refine": True,
        "translate_position": "in_place",
        "max_blocks_hint": 10,
    },
    "ui_heavy": {
        "schema_version": SCHEMA_VERSION,
        "id": "ui_heavy",
        "merge_lines": False,
        "stable_ms_for_refine": 300,
        "context_lines": 0,
        "enable_refine": False,
        "translate_position": "in_place",
        "max_blocks_hint": 60,
    },
    "chat_log": {
        "schema_version": SCHEMA_VERSION,
        "id": "chat_log",
        "merge_lines": False,
        "stable_ms_for_refine": 200,
        "context_lines": 0,
        "enable_refine": False,
        "translate_position": "in_place",
        "only_new_lines": True,
        "max_blocks_hint": 30,
    },
    "subtitle": {
        "schema_version": SCHEMA_VERSION,
        "id": "subtitle",
        "merge_lines": True,
        "stable_ms_for_refine": 250,
        "context_lines": 1,
        "enable_refine": True,
        "translate_position": "in_place",
        "max_blocks_hint": 4,
    },
    "hud": {
        "schema_version": SCHEMA_VERSION,
        "id": "hud",
        "merge_lines": False,
        "stable_ms_for_refine": 200,
        "context_lines": 0,
        "enable_refine": False,
        "translate_position": "in_place",
        "skip_pure_numbers": True,
        "max_blocks_hint": 20,
    },
    "tooltip": {
        "schema_version": SCHEMA_VERSION,
        "id": "tooltip",
        "merge_lines": True,
        "stable_ms_for_refine": 150,
        "context_lines": 0,
        "enable_refine": False,
        "translate_position": "in_place",
        "max_blocks_hint": 6,
    },
    "retro_pixel": {
        "schema_version": SCHEMA_VERSION,
        "id": "retro_pixel",
        "merge_lines": True,
        "stable_ms_for_refine": 400,
        "context_lines": 1,
        "enable_refine": False,
        "translate_position": "in_place",
        "upscale_factor": 3.0,
        "upscale_nearest_neighbor": True,
        "max_blocks_hint": 10,
    },
}

_REQUIRED_KEYS = {"id", "merge_lines", "stable_ms_for_refine", "context_lines", "enable_refine", "translate_position"}


def validate_preset(data: Any, name: str) -> dict[str, Any]:
    """Return a valid preset dict, falling back to the built-in default (or
    a generic safe default) on any structural problem. Never raises."""
    fallback = BUILTIN_PRESETS.get(name, BUILTIN_PRESETS["ui_heavy"])
    if not isinstance(data, dict):
        logger.warning("presets: %s is not an object — using built-in default", name)
        return copy.deepcopy(fallback)
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        logger.warning("presets: %s missing keys %s — using built-in default", name, missing)
        return copy.deepcopy(fallback)
    return data


def load_preset(name: str, presets_dir: str | Path = "presets") -> dict[str, Any]:
    path = Path(presets_dir) / f"{name}.json"
    if not path.exists():
        if name in BUILTIN_PRESETS:
            return copy.deepcopy(BUILTIN_PRESETS[name])
        logger.warning("presets: unknown preset %r and no file at %s — using ui_heavy default", name, path)
        return copy.deepcopy(BUILTIN_PRESETS["ui_heavy"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("presets: cannot read %s (%s) — using built-in default", path, exc)
        return copy.deepcopy(BUILTIN_PRESETS.get(name, BUILTIN_PRESETS["ui_heavy"]))
    return validate_preset(data, name)


def load_all_presets(presets_dir: str | Path = "presets") -> dict[str, dict[str, Any]]:
    presets = {name: copy.deepcopy(data) for name, data in BUILTIN_PRESETS.items()}
    presets_path = Path(presets_dir)
    if presets_path.is_dir():
        for file in presets_path.glob("*.json"):
            presets[file.stem] = load_preset(file.stem, presets_dir)
    return presets
