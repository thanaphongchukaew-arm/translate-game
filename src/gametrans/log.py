"""Logging setup. OCR/translation text content is never logged at INFO or
above — only at DEBUG, and only when cfg['log']['log_text'] is true. This is
a privacy requirement (section 16), not a style preference.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

_CONFIGURED = False


def setup_logging(cfg: dict[str, Any]) -> logging.Logger:
    global _CONFIGURED
    root = logging.getLogger("gametrans")

    log_cfg = cfg.get("log", {}) if isinstance(cfg, dict) else {}
    level_name = str(log_cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    path = log_cfg.get("path", "gametrans.log")

    root.setLevel(level)

    if not _CONFIGURED:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

        try:
            file_handler = logging.handlers.RotatingFileHandler(
                Path(path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError:
            root.warning("log: cannot open log file %s — file logging disabled", path)

        _CONFIGURED = True
    else:
        for handler in root.handlers:
            handler.setLevel(level)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"gametrans.{name}")


def should_log_text(cfg: dict[str, Any]) -> bool:
    """Whether OCR/translation text content may be logged (DEBUG-level only)."""
    return bool(cfg.get("log", {}).get("log_text", False))
