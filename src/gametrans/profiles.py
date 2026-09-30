"""Game profiles (spec section 3E): everything specific to one game lives
in a data file (profiles/<id>.json), never in code. `generic` is the
always-available zero-config fallback (full-screen scan, no regions).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from gametrans.regions import Region

logger = logging.getLogger("gametrans.profiles")

SCHEMA_VERSION = 1
VALID_RISK_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class Profile:
    id: str
    display_name: str
    match_process: Optional[str]  # regex against process name, or None
    match_window_title: Optional[str]  # regex against window title, or None
    risk_level: str
    source_lang: str
    regions: tuple[Region, ...]
    glossary_path: Optional[str]
    capture_target_type: str
    display_mode_default: str
    notes: str


GENERIC_PROFILE = Profile(
    id="generic",
    display_name="ทั่วไป (zero-config)",
    match_process=None,
    match_window_title=None,
    risk_level="medium",
    source_lang="auto",
    regions=(),  # no regions -> full-screen scan
    glossary_path=None,
    capture_target_type="auto",
    display_mode_default="auto",
    notes="โปรไฟล์เริ่มต้นสำหรับเกมที่ยังไม่มีโปรไฟล์เฉพาะ สแกนทั้งจอ ไม่ต้องตั้งค่า",
)


def _parse_regions(raw: Any, profile_id: str) -> tuple[Region, ...]:
    if not raw:
        return ()
    regions: list[Region] = []
    for item in raw:
        try:
            regions.append(
                Region(
                    name=item["name"],
                    rect=tuple(item["rect"]),
                    preset=item.get("preset", "ui_heavy"),
                    min_score=item.get("min_score"),
                    typewriter=bool(item.get("typewriter", False)),
                    translate_position=item.get("translate_position", "in_place"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("profiles: %s has an invalid region (%s) — skipping it", profile_id, exc)
    return tuple(regions)


def parse_profile(data: dict[str, Any]) -> Optional[Profile]:
    """Parse+validate a profile dict. Returns None (and logs) rather than
    raising on any structural problem — one bad profile file must never
    crash the app."""
    try:
        profile_id = data["id"]
    except (KeyError, TypeError):
        logger.warning("profiles: profile missing required 'id' field — skipping")
        return None

    risk_level = data.get("risk_level", "medium")
    if risk_level not in VALID_RISK_LEVELS:
        logger.warning("profiles: %s has invalid risk_level %r — defaulting to medium", profile_id, risk_level)
        risk_level = "medium"

    match = data.get("match", {}) or {}
    try:
        return Profile(
            id=profile_id,
            display_name=data.get("display_name", profile_id),
            match_process=match.get("process_name"),
            match_window_title=match.get("window_title"),
            risk_level=risk_level,
            source_lang=data.get("source_lang", "auto"),
            regions=_parse_regions(data.get("regions"), profile_id),
            glossary_path=data.get("glossary_path"),
            capture_target_type=data.get("capture_target", {}).get("type", "auto"),
            display_mode_default=data.get("display_mode_default", "auto"),
            notes=data.get("notes", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("profiles: %s failed to parse (%s) — skipping", profile_id, exc)
        return None


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": profile.id,
        "display_name": profile.display_name,
        "match": {"process_name": profile.match_process, "window_title": profile.match_window_title},
        "risk_level": profile.risk_level,
        "source_lang": profile.source_lang,
        "regions": [
            {
                "name": r.name, "rect": list(r.rect), "preset": r.preset,
                "min_score": r.min_score, "typewriter": r.typewriter,
                "translate_position": r.translate_position,
            }
            for r in profile.regions
        ],
        "glossary_path": profile.glossary_path,
        "capture_target": {"type": profile.capture_target_type},
        "display_mode_default": profile.display_mode_default,
        "notes": profile.notes,
    }


def load_profile(path: str | Path) -> Optional[Profile]:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("profiles: cannot read %s (%s)", path, exc)
        return None
    return parse_profile(data)


def save_profile(profile: Profile, profile_dir: str | Path = "profiles") -> None:
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / f"{profile.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(profile_to_dict(profile), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_all_profiles(profile_dir: str | Path = "profiles") -> dict[str, Profile]:
    profiles: dict[str, Profile] = {"generic": GENERIC_PROFILE}
    profile_path = Path(profile_dir)
    if not profile_path.is_dir():
        return profiles
    for file in sorted(profile_path.glob("*.json")):
        profile = load_profile(file)
        if profile is not None:
            profiles[profile.id] = profile
    return profiles


def select_profile(
    profiles: dict[str, Profile], process_name: str = "", window_title: str = ""
) -> str:
    """Pick the best-matching profile id for a running process/window,
    falling back to 'generic'. First match wins; 'generic' itself is
    never matched by process/window (it has no match rules)."""
    for profile_id, profile in profiles.items():
        if profile_id == "generic":
            continue
        if profile.match_process and re.search(profile.match_process, process_name, re.IGNORECASE):
            return profile_id
        if profile.match_window_title and re.search(profile.match_window_title, window_title, re.IGNORECASE):
            return profile_id
    return "generic"
