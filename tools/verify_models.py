"""Verify every model file listed in models/MANIFEST.json against its
recorded sha256 (spec section 11.2/15: "hash ของโมเดลไม่ตรง MANIFEST ->
แจ้งว่าไฟล์เสีย ไม่โหลด").

Usage: python tools/verify_models.py
Exit code 0 if all present files match; 1 if any mismatch (missing files
are reported but don't fail the run -- not every model is required, e.g.
ja/ko/zh OCR models are optional and usually absent).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "models" / "MANIFEST.json"


def sha256_of(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"ไม่พบ {MANIFEST_PATH}")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ok_count = 0
    missing_count = 0
    bad_count = 0

    for entry in manifest.get("models", []):
        path = ROOT / "models" / entry["file"]
        expected = entry["sha256"].upper()
        if not path.exists():
            print(f"ขาดหาย: {entry['file']} (ยังไม่ได้ดาวน์โหลด — อาจเป็นทางเลือก)")
            missing_count += 1
            continue
        actual = sha256_of(path)
        if actual == expected:
            print(f"ตรง: {entry['file']}")
            ok_count += 1
        else:
            print(f"ไม่ตรง! {entry['file']}")
            print(f"   คาดหวัง: {expected}")
            print(f"   ได้จริง:  {actual}")
            bad_count += 1

    print(f"\nสรุป: ตรง {ok_count} | ขาดหาย {missing_count} | ไม่ตรง {bad_count}")
    return 1 if bad_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
