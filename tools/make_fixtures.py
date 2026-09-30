"""Generate synthetic OCR test images (spec Appendix B, items 1-10 — the
ones phase 2 needs; items 11-22 depend on features built in later phases
and on real P5X screenshots).

Usage: python tools/make_fixtures.py
Writes PNGs + a manifest.json (expected text per image, for accuracy
scoring) into tests/fixtures/synthetic/.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthetic"


def _font(size: int) -> ImageFont.FreeTypeFont:
    # Windows ships Arial/Segoe UI in this path on every real install.
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _save(img: Image.Image, name: str, expected: list[str], category: str, manifest: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    img.save(path)
    manifest.append({"file": path.name, "expected_text": expected, "category": category})


def gen_01_white_on_black_sizes(manifest: list[dict]) -> None:
    img = Image.new("RGB", (500, 220), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    texts = ["Small text sample", "Medium text sample", "Large Text"]
    sizes = [14, 20, 32]
    y = 10
    for text, size in zip(texts, sizes):
        draw.text((10, y), text, font=_font(size), fill=(255, 255, 255))
        y += size + 20
    _save(img, "01_white_on_black_sizes", texts, "font_size", manifest)


def gen_02_shadowed_gradient(manifest: list[dict]) -> None:
    w, h = 500, 120
    img = Image.new("RGB", (w, h))
    for x in range(w):
        t = x / w
        color = (int(30 + 100 * t), int(60 + 80 * t), int(120 + 60 * t))
        for y in range(h):
            img.putpixel((x, y), color)
    draw = ImageDraw.Draw(img)
    text = "Subtitle with shadow"
    font = _font(28)
    # drop shadow
    draw.text((22, 42), text, font=font, fill=(0, 0, 0))
    draw.text((20, 40), text, font=font, fill=(255, 255, 255))
    _save(img, "02_shadow_gradient", [text], "subtitle_shadow", manifest)


def gen_03_dialogue_box(manifest: list[dict]) -> None:
    img = Image.new("RGB", (700, 220), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 690, 210], outline=(200, 200, 200), width=2)
    speaker = "Aldric"
    lines = ["You shouldn't have come here, traveler.", "The forest remembers everything.", "Turn back while you still can."]
    draw.text((30, 20), speaker, font=_font(22), fill=(255, 210, 120))
    y = 60
    for line in lines:
        draw.text((30, y), line, font=_font(20), fill=(255, 255, 255))
        y += 30
    _save(img, "03_dialogue_box", [speaker] + lines, "dialogue", manifest)


def gen_04_menu_two_columns(manifest: list[dict]) -> None:
    img = Image.new("RGB", (500, 260), (25, 25, 35))
    draw = ImageDraw.Draw(img)
    left = ["Start Game", "Continue", "Options", "Inventory", "Save", "Quit"]
    right = ["Map", "Party", "Skills", "Items", "Status", "Help"]
    font = _font(20)
    y = 10
    for l, r in zip(left, right):
        draw.text((20, y), l, font=font, fill=(255, 255, 255))
        draw.text((270, y), r, font=font, fill=(255, 255, 255))
        y += 40
    _save(img, "04_menu_two_columns", left + right, "menu", manifest)


def gen_05_hud_numbers(manifest: list[dict]) -> None:
    img = Image.new("RGB", (400, 120), (10, 10, 10))
    draw = ImageDraw.Draw(img)
    font = _font(26)
    draw.text((10, 10), "HP 120/200", font=font, fill=(255, 60, 60))
    draw.text((10, 50), "MP 40/60", font=font, fill=(80, 160, 255))
    _save(img, "05_hud_numbers", ["HP 120/200", "MP 40/60"], "hud", manifest)


def gen_06_noisy_background(manifest: list[dict]) -> None:
    random.seed(42)
    w, h = 500, 150
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        for y in range(h):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    draw = ImageDraw.Draw(img)
    text = "Readable Text"
    draw.rectangle([10, 55, 260, 95], fill=(0, 0, 0, 180))
    draw.text((20, 60), text, font=_font(26), fill=(255, 255, 255))
    _save(img, "06_noisy_background", [text], "noisy", manifest)


def gen_07_empty(manifest: list[dict]) -> None:
    img = Image.new("RGB", (400, 200), (40, 60, 80))
    _save(img, "07_empty", [], "empty", manifest)


def gen_08_black(manifest: list[dict]) -> None:
    img = Image.new("RGB", (400, 200), (0, 0, 0))
    _save(img, "08_black", [], "black_frame", manifest)


def gen_09_tiny_font(manifest: list[dict]) -> None:
    img = Image.new("RGB", (400, 80), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = "Tiny caption text"
    draw.text((10, 10), text, font=_font(11), fill=(255, 255, 255))
    _save(img, "09_tiny_font", [text], "tiny_font", manifest)


def gen_10_confusable_chars(manifest: list[dict]) -> None:
    img = Image.new("RGB", (400, 80), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = "World Hello 100"
    draw.text((10, 10), text, font=_font(26), fill=(255, 255, 255))
    _save(img, "10_confusable_chars", [text], "confusable", manifest)


def main() -> None:
    manifest: list[dict] = []
    for fn in [
        gen_01_white_on_black_sizes,
        gen_02_shadowed_gradient,
        gen_03_dialogue_box,
        gen_04_menu_two_columns,
        gen_05_hud_numbers,
        gen_06_noisy_background,
        gen_07_empty,
        gen_08_black,
        gen_09_tiny_font,
        gen_10_confusable_chars,
    ]:
        fn(manifest)

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"เขียน {len(manifest)} ภาพ + manifest.json ไปที่ {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
