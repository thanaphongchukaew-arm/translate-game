import json

from gametrans.profiles import (
    GENERIC_PROFILE, Profile, load_all_profiles, load_profile, parse_profile,
    profile_to_dict, save_profile, select_profile,
)
from gametrans.regions import Region


def test_generic_profile_has_no_regions():
    assert GENERIC_PROFILE.id == "generic"
    assert GENERIC_PROFILE.regions == ()


def test_select_profile_falls_back_to_generic():
    profiles = {"generic": GENERIC_PROFILE}
    assert select_profile(profiles, "notepad.exe", "Untitled - Notepad") == "generic"


def test_select_profile_matches_process_name():
    p5x = Profile(
        id="p5x", display_name="P5X", match_process="P5X|PhantomX", match_window_title=None,
        risk_level="medium", source_lang="en", regions=(), glossary_path=None,
        capture_target_type="auto", display_mode_default="auto", notes="",
    )
    profiles = {"generic": GENERIC_PROFILE, "p5x": p5x}
    assert select_profile(profiles, "PhantomX.exe", "") == "p5x"
    assert select_profile(profiles, "chrome.exe", "") == "generic"


def test_select_profile_matches_window_title():
    game = Profile(
        id="game", display_name="Game", match_process=None, match_window_title="My Cool Game",
        risk_level="low", source_lang="auto", regions=(), glossary_path=None,
        capture_target_type="auto", display_mode_default="auto", notes="",
    )
    profiles = {"generic": GENERIC_PROFILE, "game": game}
    assert select_profile(profiles, "game.exe", "My Cool Game - v1.2") == "game"


def test_parse_profile_missing_id_returns_none():
    assert parse_profile({"display_name": "no id here"}) is None


def test_parse_profile_invalid_risk_level_defaults_to_medium():
    profile = parse_profile({"id": "x", "risk_level": "extreme"})
    assert profile is not None
    assert profile.risk_level == "medium"


def test_parse_profile_with_regions():
    data = {
        "id": "x",
        "regions": [
            {"name": "dialogue_box", "rect": [0.05, 0.7, 0.95, 0.95], "preset": "dialogue"}
        ],
    }
    profile = parse_profile(data)
    assert len(profile.regions) == 1
    assert profile.regions[0].name == "dialogue_box"
    assert profile.regions[0].preset == "dialogue"


def test_parse_profile_skips_invalid_region_but_keeps_profile():
    data = {"id": "x", "regions": [{"name": "bad", "rect": [0.0, 0.0, 2.0, 1.0]}]}
    profile = parse_profile(data)
    assert profile is not None
    assert profile.regions == ()


def test_save_and_load_profile_round_trip(tmp_path):
    profile = Profile(
        id="p5x", display_name="P5X", match_process="P5X.exe", match_window_title=None,
        risk_level="medium", source_lang="en",
        regions=(Region(name="dialogue_box", rect=(0.05, 0.7, 0.95, 0.95), preset="dialogue"),),
        glossary_path="glossary.p5x.json", capture_target_type="auto",
        display_mode_default="auto", notes="test",
    )
    save_profile(profile, profile_dir=tmp_path)
    reloaded = load_profile(tmp_path / "p5x.json")
    assert reloaded == profile


def test_load_profile_missing_file_returns_none(tmp_path):
    assert load_profile(tmp_path / "nope.json") is None


def test_load_profile_corrupt_file_returns_none(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_profile(path) is None


def test_load_all_profiles_always_includes_generic(tmp_path):
    profiles = load_all_profiles(profile_dir=tmp_path)
    assert "generic" in profiles


def test_load_all_profiles_reads_real_p5x_profile_from_disk():
    profiles = load_all_profiles(profile_dir="profiles")
    assert "p5x" in profiles
    assert profiles["p5x"].risk_level == "medium"
    assert len(profiles["p5x"].regions) >= 1
