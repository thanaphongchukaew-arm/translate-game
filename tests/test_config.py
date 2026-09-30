import json
from pathlib import Path

from gametrans.config import DEFAULT_CONFIG, merge_config, load_config

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_missing_keys_fall_back_to_default():
    merged = merge_config(DEFAULT_CONFIG, {})
    assert merged == DEFAULT_CONFIG


def test_wrong_type_falls_back_with_default():
    merged = merge_config(DEFAULT_CONFIG, {"ocr": {"min_score": "not-a-number"}})
    assert merged["ocr"]["min_score"] == DEFAULT_CONFIG["ocr"]["min_score"]


def test_out_of_range_falls_back_to_default():
    merged = merge_config(DEFAULT_CONFIG, {"ocr": {"min_score": 5.0}})
    assert merged["ocr"]["min_score"] == DEFAULT_CONFIG["ocr"]["min_score"]

    merged2 = merge_config(DEFAULT_CONFIG, {"layout": {"hold_cycles": -1}})
    assert merged2["layout"]["hold_cycles"] == DEFAULT_CONFIG["layout"]["hold_cycles"]


def test_valid_user_value_is_applied():
    merged = merge_config(DEFAULT_CONFIG, {"ocr": {"min_score": 0.8}})
    assert merged["ocr"]["min_score"] == 0.8
    # sibling defaults preserved
    assert merged["ocr"]["min_box_h"] == DEFAULT_CONFIG["ocr"]["min_box_h"]


def test_enum_field_rejects_invalid_value():
    merged = merge_config(DEFAULT_CONFIG, {"display": {"mode": "Z"}})
    assert merged["display"]["mode"] == DEFAULT_CONFIG["display"]["mode"]

    merged2 = merge_config(DEFAULT_CONFIG, {"display": {"mode": "B"}})
    assert merged2["display"]["mode"] == "B"


def test_bool_is_not_coerced_from_int():
    # bool is a subclass of int in Python; make sure `1` is not silently
    # accepted where a bool is expected.
    merged = merge_config(DEFAULT_CONFIG, {"autostart": 1})
    assert merged["autostart"] == DEFAULT_CONFIG["autostart"]

    merged2 = merge_config(DEFAULT_CONFIG, {"autostart": False})
    assert merged2["autostart"] is False


def test_non_dict_user_config_falls_back_entirely():
    merged = merge_config(DEFAULT_CONFIG, ["not", "a", "dict"])  # type: ignore[arg-type]
    assert merged == DEFAULT_CONFIG


def test_load_config_missing_files_returns_defaults(tmp_path):
    cfg = load_config(user_path=tmp_path / "nope.json", default_path=tmp_path / "also-nope.json")
    assert cfg == DEFAULT_CONFIG


def test_load_config_corrupt_user_file_falls_back(tmp_path):
    user_path = tmp_path / "config.user.json"
    user_path.write_text("{not valid json", encoding="utf-8")
    cfg = load_config(user_path=user_path)
    assert cfg == DEFAULT_CONFIG


def test_load_config_merges_valid_user_file(tmp_path):
    user_path = tmp_path / "config.user.json"
    user_path.write_text(json.dumps({"mode": "fastest", "cache": {"max_entries": 500}}), encoding="utf-8")
    cfg = load_config(user_path=user_path)
    assert cfg["mode"] == "fastest"
    assert cfg["cache"]["max_entries"] == 500
    assert cfg["cache"]["path"] == DEFAULT_CONFIG["cache"]["path"]


def test_real_config_default_json_fast_model_dir_points_to_an_existing_tokenizer():
    """Regression test for a real deployment bug: config.default.json's
    fast.model_dir was "models/fast" instead of
    "models/fast/nllb200-600m-int8" -- every real run (loaded through
    load_config(), the path app.py actually uses) silently picked up the
    wrong path and every single tier-1 translate() call failed forever,
    reported by a user as "no Thai translation appears, and severe lag."
    No prior test caught this because every other test/tool built its cfg
    dict inline without setting fast.model_dir, so they all fell through
    to pipeline.py's own correct hardcoded default and never touched the
    real config.default.json file at all. This test loads the REAL file
    the app loads, the way app.py actually loads it."""
    cfg = load_config(
        user_path=_PROJECT_ROOT / "config.user.json",  # usually absent -- load_config handles that
        default_path=_PROJECT_ROOT / "config.default.json",
    )
    model_dir_str = cfg["fast"]["model_dir"]

    # Cheap, always-runnable guard: this exact wrong value is what broke
    # translation for real, so a direct regression check on it never
    # depends on whether the (gitignored, ~620MB) model happens to be
    # downloaded on the machine running the test.
    assert model_dir_str != "models/fast", "fast.model_dir regressed to the bug's exact wrong value"

    model_dir = Path(model_dir_str)
    if not model_dir.is_absolute():
        model_dir = _PROJECT_ROOT / model_dir
    if not model_dir.exists():
        import pytest

        pytest.skip(f"model not downloaded at {model_dir} -- run scripts/download_models.ps1 to fully verify this")

    tokenizer_path = model_dir / "tokenizer" / "sentencepiece.bpe.model"
    assert tokenizer_path.exists(), (
        f"config.default.json's fast.model_dir ({model_dir_str}) does not contain a "
        f"tokenizer at the expected path ({tokenizer_path}) -- every real translate() call would fail"
    )
