"""Tier-1 translation model bake-off (spec section 12).

Usage:
  python tools/bakeoff.py                 # run the bake-off
  python tools/bakeoff.py --add "src" "ref" "category"   # append a sentence

Scope note (see DECISIONS.md phase 3): the spec lists several tier-1
candidates (NLLB-200 600M/1.3B, MADLAD-400, Opus-MT). Given the ~5-10GB
disk budget the user approved and how much of it a *pair* of these models
already costs (600M-int8 alone is ~620MB; 1.3B and MADLAD are both
multiple GB), this run compares what's actually installed under
models/fast/ rather than downloading every candidate. Add more converted
models under models/fast/<name>/ and register them in CANDIDATES below to
extend the comparison later.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gametrans.guards import check_translation  # noqa: E402
from gametrans.translate_fast import NllbCTranslator  # noqa: E402

EVAL_PATH = ROOT / "tests" / "eval" / "en_th.jsonl"

CANDIDATES = {
    "nllb200-600m-int8": lambda: NllbCTranslator(model_dir=str(ROOT / "models" / "fast" / "nllb200-600m-int8")),
}


def load_eval_set() -> list[dict]:
    rows = []
    with EVAL_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def add_sentence(src: str, ref: str, category: str) -> None:
    with EVAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"src": src, "ref": ref, "category": category, "ref_source": "user"}, ensure_ascii=False) + "\n")
    print(f"เพิ่มประโยคแล้ว ({EVAL_PATH})")


def run_bakeoff() -> None:
    rows = load_eval_set()
    try:
        import sacrebleu
        have_sacrebleu = True
    except ImportError:
        have_sacrebleu = False
        print("หมายเหตุ: ไม่มี sacrebleu ติดตั้งอยู่ จะข้ามคะแนน chrF (ยังรายงานความเร็ว+guards ได้ตามปกติ)\n")

    for name, factory in CANDIDATES.items():
        print(f"=== {name} ===")
        try:
            translator = factory()
        except Exception as exc:  # noqa: BLE001
            print(f"  ข้าม: โหลดโมเดลไม่ได้ ({exc})\n")
            continue

        srcs = [r["src"] for r in rows]
        # warm up (model load / first CUDA call)
        translator.translate(srcs[:1])

        times_ms = []
        outputs = []
        for src in srcs:
            t0 = time.perf_counter()
            out = translator.translate([src])
            times_ms.append((time.perf_counter() - t0) * 1000)
            outputs.append(out[0])

        times_sorted = sorted(times_ms)
        p50 = times_sorted[len(times_sorted) // 2]
        p95 = times_sorted[int(len(times_sorted) * 0.95) - 1]

        guard_pass = 0
        for r, out in zip(rows, outputs):
            result = check_translation(r["src"], out)
            if result.ok:
                guard_pass += 1

        print(f"  ประโยคทั้งหมด: {len(rows)}")
        print(f"  เวลาแปล: p50={p50:.1f}ms  p95={p95:.1f}ms")
        print(f"  ผ่าน guards: {guard_pass}/{len(rows)} ({guard_pass/len(rows)*100:.1f}%)")

        if have_sacrebleu:
            refs = [r["ref"] for r in rows]
            chrf = sacrebleu.corpus_chrf(outputs, [refs])
            print(f"  chrF: {chrf.score:.1f}")

        print("\n  ตัวอย่างเทียบข้างกัน (10 รายการแรก):")
        print(f"  {'src':45s} {'ref (draft)':25s} {'output จริง':25s}")
        for r, out in list(zip(rows, outputs))[:10]:
            print(f"  {r['src'][:43]:45s} {r['ref'][:23]:25s} {out[:23]:25s}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", nargs=3, metavar=("SRC", "REF", "CATEGORY"))
    args = parser.parse_args()

    if args.add:
        add_sentence(*args.add)
        return

    run_bakeoff()


if __name__ == "__main__":
    main()
