import json

from gametrans.presets import load_preset, load_all_presets, validate_preset, BUILTIN_PRESETS


def test_all_builtin_preset_names_from_spec_table_exist():
    for name in ("dialogue", "ui_heavy", "chat_log", "subtitle", "hud", "tooltip", "retro_pixel"):
        assert name in BUILTIN_PRESETS


def test_load_preset_from_real_files_on_disk():
    preset = load_preset("dialogue", presets_dir="presets")
    assert preset["id"] == "dialogue"
    assert preset["stable_ms_for_refine"] == 500
    assert preset["context_lines"] == 3


def test_load_preset_missing_file_falls_back_to_builtin(tmp_path):
    preset = load_preset("dialogue", presets_dir=tmp_path)
    assert preset["id"] == "dialogue"


def test_load_preset_unknown_name_falls_back_to_ui_heavy(tmp_path):
    preset = load_preset("totally_unknown_preset", presets_dir=tmp_path)
    assert preset["id"] == "ui_heavy"


def test_load_preset_corrupt_file_falls_back(tmp_path):
    (tmp_path / "dialogue.json").write_text("{not valid json", encoding="utf-8")
    preset = load_preset("dialogue", presets_dir=tmp_path)
    assert preset["id"] == "dialogue"  # fell back to built-in


def test_validate_preset_missing_required_key_falls_back():
    result = validate_preset({"id": "dialogue"}, "dialogue")  # missing merge_lines etc.
    assert result == BUILTIN_PRESETS["dialogue"]


def test_load_all_presets_from_directory(tmp_path):
    (tmp_path / "custom.json").write_text(
        json.dumps({
            "id": "custom", "merge_lines": True, "stable_ms_for_refine": 100,
            "context_lines": 0, "enable_refine": False, "translate_position": "in_place",
        }),
        encoding="utf-8",
    )
    presets = load_all_presets(tmp_path)
    assert "custom" in presets
    assert "dialogue" in presets  # built-ins still present
