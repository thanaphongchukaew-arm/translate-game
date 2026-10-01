import cv2
from pathlib import Path

import pytest

from gametrans.layout import Block, OcrLine, group_display_type
from gametrans.profiles import load_all_profiles, parse_profile
from gametrans.review_log import ReviewLog
from gametrans.textrules import TextRules

FIXTURES = Path(__file__).parent / "fixtures"


def _rules(**kw):
    p = parse_profile({"id": "x", **kw})
    return TextRules.from_profile(p)


def test_override_matches_ignoring_case_and_spacing():
    r = _rules(overrides={"SCHOOL LIFE": "ชีวิตนักเรียน"})
    assert r.override("SchoolLife") == "ชีวิตนักเรียน"
    assert r.override("school  life") == "ชีวิตนักเรียน"
    assert r.override("other") is None


def test_skip_and_ocr_fix():
    r = _rules(skip_patterns=[r"^PERSONA\s*5"], ocr_fixes={"THEIPHANTOMX": "THE PHANTOM X"})
    assert r.should_skip("PERSONA5 THE PHANTOM X")
    assert not r.should_skip("Start")
    assert r.fix("THEIPHANTOMX") == "THE PHANTOM X"


def test_invalid_skip_regex_is_ignored():
    assert not _rules(skip_patterns=["("]).should_skip("anything")


def test_real_p5x_profile_has_rules_and_regions():
    p = load_all_profiles("profiles")["p5x"]
    assert {"title_banner", "menu_bar", "dialogue_box"} <= {r.name for r in p.regions}
    assert p.overrides and p.skip_patterns and p.ocr_fixes


def test_group_display_type_leaves_small_lines_alone():
    lines = [OcrLine(0, 0, 80, 20, "Start", 0.9), OcrLine(0, 30, 80, 50, "Quit", 0.9)]
    assert group_display_type(lines, 900) == lines


def test_review_log_is_off_by_default_and_dedupes(tmp_path):
    path = tmp_path / "r.jsonl"
    ReviewLog(str(path), enabled=False).record("a", "b", 0.1)
    assert not path.exists()
    log = ReviewLog(str(path), enabled=True)
    log.record("TheNew", "The New", 0.97)
    log.record("TheNew", "The New", 0.97)
    log.record("fine", "fine", 0.99)  # nothing to review
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.skipif(not Path("models/ocr/en/en_PP-OCRv3_rec_infer.onnx").exists(), reason="OCR model missing")
def test_full_home_screen_reads_title_as_one_phrase():
    from gametrans.ocr import run_ocr
    from gametrans.ocr_post import clean_text

    img = cv2.imread(str(FIXTURES / "p5x_home.png"))
    lines = [OcrLine(l.x1, l.y1, l.x2, l.y2, clean_text(l.text), l.score) for l in run_ocr(img, {})]
    texts = [l.text for l in group_display_type(lines, img.shape[0])]
    assert "The New Phantom Thieves! Have Arrived!" in texts or any(
        t.startswith("The New Phantom") and t.endswith("Arrived!") for t in texts
    )
    for word in ("NEWS", "CHARACTERS", "FEATURE", "Support", "FAQ", "Google Play"):
        assert word in texts


def test_long_labels_match_approximately_but_short_ones_do_not():
    r = _rules(overrides={"The New Phantom Thieves Have Arrived!": "ok", "NEWS": "ข่าว"})
    assert r.override("The New Phantom lave Arrived!") == "ok"
    assert r.override("NEW") is None


def test_shipped_p5x_skip_patterns_match_logo():
    # regression: "\b" written unescaped in JSON became a backspace char,
    # so the "PERSONA 5" logo pattern could never match
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent.parent / "profiles" / "p5x.json").read_text(encoding="utf-8"))
    assert not any("\x08" in p for p in data["skip_patterns"])
    from gametrans.profiles import parse_profile
    from gametrans.textrules import TextRules

    rules = TextRules.from_profile(parse_profile(data))
    assert rules.should_skip("PERSONA 5 The Phantom X")
    assert not rules.should_skip("School Life")
