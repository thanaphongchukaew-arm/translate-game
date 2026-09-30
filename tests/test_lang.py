from gametrans.lang import detect_script, detect_source_language, resolve_source_lang, is_ocr_model_available


def test_detect_script_english():
    assert detect_script("Hello, traveler!") == "en"


def test_detect_script_japanese_with_kana():
    assert detect_script("セーブしますか？") == "ja"  # "Save?" in Japanese (katakana+hiragana)


def test_detect_script_korean():
    assert detect_script("저장하시겠습니까?") == "ko"


def test_detect_script_chinese_no_kana():
    assert detect_script("任务已完成") == "zh"  # "Quest complete" in Chinese, no kana present


def test_detect_script_numbers_only_is_other():
    assert detect_script("120/200") == "other"


def test_detect_script_empty_is_other():
    assert detect_script("") == "other"


def test_detect_source_language_majority_vote():
    texts = ["Hello there", "How are you", "120/200"]
    assert detect_source_language(texts) == "en"


def test_detect_source_language_empty_list_is_other():
    assert detect_source_language([]) == "other"


def test_resolve_source_lang_explicit_overrides_detection():
    assert resolve_source_lang("ja", ["Hello there"]) == "ja"


def test_resolve_source_lang_auto_uses_detection():
    assert resolve_source_lang("auto", ["Hello there", "General Kenobi"]) == "en"


def test_english_ocr_model_is_available():
    assert is_ocr_model_available("en") is True


def test_japanese_ocr_model_not_yet_downloaded():
    # Honest about current state: only English is downloaded (P5X is
    # English-only); ja/ko/zh model download is deferred, see lang.py.
    assert is_ocr_model_available("ja") is False
