import numpy as np

from gametrans.layout import OcrLine
from gametrans.profile_wizard import analyze_samples, _extract_glossary_candidates, _classify_behavior


def _frame(w=800, h=600):
    return np.zeros((h, w, 3), dtype="uint8")


def _ocr_func_factory(lines_per_frame: list[list[OcrLine]]):
    """Returns an ocr_func that yields a different fixed set of lines per
    call, in order -- simulates a sequence of samples."""
    calls = {"i": 0}

    def _ocr(frame, cfg):
        i = calls["i"]
        calls["i"] += 1
        return lines_per_frame[i] if i < len(lines_per_frame) else []

    return _ocr


def test_empty_frames_returns_empty_result():
    result = analyze_samples([], ocr_func=lambda f, c: [], cfg={})
    assert result.regions == []


def test_static_short_text_proposes_ui_heavy_preset():
    line = OcrLine(x1=10, y1=10, x2=100, y2=30, text="Start Game", score=0.9)
    ocr = _ocr_func_factory([[line], [line], [line]])
    result = analyze_samples([_frame(), _frame(), _frame()], ocr, cfg={})
    assert len(result.regions) == 1
    assert result.regions[0].behavior == "static"
    assert result.regions[0].region.preset == "ui_heavy"


def test_static_numeric_text_proposes_hud_preset():
    line = OcrLine(x1=10, y1=10, x2=100, y2=30, text="120/200", score=0.9)
    ocr = _ocr_func_factory([[line], [line], [line]])
    result = analyze_samples([_frame(), _frame(), _frame()], ocr, cfg={})
    assert result.regions[0].behavior == "static"
    assert result.regions[0].region.preset == "hud"


def test_typewriter_growth_proposes_dialogue_preset():
    texts = ["H", "He", "Hel", "Hell", "Hello"]
    frames_lines = [[OcrLine(x1=10, y1=400, x2=200, y2=430, text=t, score=0.9)] for t in texts]
    ocr = _ocr_func_factory(frames_lines)
    result = analyze_samples([_frame() for _ in texts], ocr, cfg={})
    assert len(result.regions) == 1
    assert result.regions[0].behavior == "typewriter"
    assert result.regions[0].region.preset == "dialogue"


def test_changing_non_growing_text_proposes_dialogue_preset():
    texts = ["Hello there.", "Goodbye now."]
    frames_lines = [[OcrLine(x1=10, y1=400, x2=300, y2=430, text=t, score=0.9)] for t in texts]
    ocr = _ocr_func_factory(frames_lines)
    result = analyze_samples([_frame(), _frame()], ocr, cfg={})
    assert result.regions[0].behavior == "changing"
    assert result.regions[0].region.preset == "dialogue"


def test_transient_text_present_in_minority_of_frames_proposes_subtitle():
    # present in 1 of 4 frames -> below the 50% presence threshold
    frames_lines = [
        [OcrLine(x1=10, y1=10, x2=200, y2=30, text="They're coming.", score=0.9)],
        [],
        [],
        [],
    ]
    ocr = _ocr_func_factory(frames_lines)
    result = analyze_samples([_frame() for _ in range(4)], ocr, cfg={})
    assert len(result.regions) == 1
    assert result.regions[0].behavior == "transient"
    assert result.regions[0].region.preset == "subtitle"


def test_two_distinct_positions_produce_two_separate_regions():
    top = OcrLine(x1=10, y1=10, x2=100, y2=30, text="120/200", score=0.9)  # pure digits/symbol -> hud
    bottom = OcrLine(x1=10, y1=500, x2=300, y2=530, text="Welcome to the village.", score=0.9)
    ocr = _ocr_func_factory([[top, bottom], [top, bottom]])
    result = analyze_samples([_frame(), _frame()], ocr, cfg={})
    assert len(result.regions) == 2
    names_by_preset = {r.region.preset for r in result.regions}
    assert "hud" in names_by_preset
    assert "ui_heavy" in names_by_preset or "dialogue" in names_by_preset


def test_proposed_region_rect_is_proportional_and_within_bounds():
    line = OcrLine(x1=10, y1=10, x2=100, y2=30, text="Menu", score=0.9)
    ocr = _ocr_func_factory([[line]])
    result = analyze_samples([_frame(w=800, h=600)], ocr, cfg={})
    rect = result.regions[0].region.rect
    assert all(0.0 <= v <= 1.0 for v in rect)
    assert rect[2] > rect[0] and rect[3] > rect[1]


def test_source_language_detected_from_samples():
    line = OcrLine(x1=10, y1=10, x2=200, y2=30, text="Hello, traveler.", score=0.9)
    ocr = _ocr_func_factory([[line]])
    result = analyze_samples([_frame()], ocr, cfg={})
    assert result.source_lang == "en"


def test_glossary_candidates_extracted_from_repeated_capitalized_words():
    texts = [
        "Lord Aldric of Stormwatch greets you.",
        "You have angered Lord Aldric.",
        "The Whispering Caverns await.",
    ]
    candidates = _extract_glossary_candidates(texts, min_occurrences=2)
    assert "Aldric" in candidates
    # "The" is a common word and must be filtered out even though capitalized
    assert "The" not in candidates


def test_glossary_candidates_ignore_words_appearing_only_once():
    texts = ["Aldric appears once.", "Nothing else repeats here."]
    candidates = _extract_glossary_candidates(texts, min_occurrences=2)
    assert "Aldric" not in candidates


def test_classify_behavior_directly_static_vs_transient():
    assert _classify_behavior([(0, "A"), (1, "A"), (2, "A")], total_frames=3) == "static"
    assert _classify_behavior([(0, "A")], total_frames=10) == "transient"
