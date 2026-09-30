"""Integration tests for the tier-1 NLLB/CTranslate2 translator. Marked
`slow` because they need the real downloaded model (models/fast/nllb200-600m-int8,
~620MB) -- skipped automatically if it isn't present, and excluded from the
default `pytest -q` run (see pyproject.toml: run with `pytest -m slow` to
include them).
"""
import pytest

from gametrans.guards import check_translation

MODEL_DIR = "models/fast/nllb200-600m-int8"


def _model_available() -> bool:
    from pathlib import Path

    return (Path(MODEL_DIR) / "model.bin").exists()


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not _model_available(), reason=f"NLLB model not downloaded at {MODEL_DIR}"),
]


@pytest.fixture(scope="module")
def translator():
    from gametrans.translate_fast import NllbCTranslator

    return NllbCTranslator(model_dir=MODEL_DIR)


def test_translate_returns_same_length_as_input(translator):
    out = translator.translate(["Hello", "World", "Are you sure?"])
    assert len(out) == 3


def test_translate_empty_list_returns_empty(translator):
    assert translator.translate([]) == []


def test_translate_produces_thai_output_that_passes_guards(translator):
    out = translator.translate(["Hello, traveler."])
    result = check_translation("Hello, traveler.", out[0])
    assert result.ok, f"guard rejected {out[0]!r}: {result.reason}"


def test_translate_preserves_numeric_placeholder_round_trip(translator):
    from gametrans.textprep import prepare

    prepared = prepare("Deal {0} damage", glossary={})
    out = translator.translate([prepared.text])
    restored = prepared.restore(out[0])
    assert "{0}" in restored


def test_context_argument_does_not_raise_even_though_tier1_ignores_it(translator):
    out = translator.translate(["Hello"], context=["previous line one", "previous line two"])
    assert len(out) == 1


def test_guards_catch_a_real_placeholder_drop_from_the_model(translator):
    """Documents a real, observed failure mode (see DECISIONS.md phase 3):
    this 600M model sometimes drops a "[P0]"-style placeholder entirely
    depending on sentence context, rather than always copying it through.
    "You found [P0] gold." is a known-bad case for this exact model/prompt
    -- guards.check_translation MUST catch the resulting lost number so the
    pipeline can fall back instead of showing a translation with a missing
    quantity."""
    from gametrans.textprep import prepare

    original = "You found 50 gold."
    prepared = prepare(original, glossary={})
    out = translator.translate([prepared.text])[0]
    restored = prepared.restore(out)

    result = check_translation(original, restored)
    if "50" in restored:
        pytest.skip("model preserved the placeholder this run (not guaranteed) -- nothing to catch")
    assert result.ok is False
    assert result.reason == "lost_numbers"
