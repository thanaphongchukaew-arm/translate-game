from gametrans.ocr_post import clean_text, fix_confusables


def test_collapses_repeated_whitespace():
    assert clean_text("Hello    world") == "Hello world"


def test_normalizes_curly_quotes():
    assert clean_text("‘Hello’") == "'Hello'"
    assert clean_text("“Hello”") == '"Hello"'


def test_merges_safe_hyphen_break_into_dictionary_word():
    assert clean_text("trav- eler") == "traveler"


def test_does_not_merge_hyphen_break_into_nonsense():
    # "sun-set" is a real compound but "xk-qz" is not a dictionary word,
    # must be left alone rather than force-merged.
    assert clean_text("xk- qz") == "xk- qz"


def test_fixes_confusable_zero_to_o_when_it_becomes_a_word():
    assert fix_confusables("W0rld") == "World"


def test_fixes_confusable_one_to_l_when_it_becomes_a_word():
    assert fix_confusables("He1lo") == "Hello"


def test_does_not_touch_proper_noun_like_codes():
    # A pure alphanumeric code should not be "fixed" into a dictionary word
    # if it isn't actually meant to be one.
    assert fix_confusables("XK47") == "XK47"


def test_does_not_touch_plain_numbers():
    assert clean_text("HP 100 / MP 50") == "HP 100 / MP 50"


def test_does_not_touch_names_mid_sentence():
    text = "Lord Aldric of Stormwatch"
    assert clean_text(text) == text


def test_empty_string_is_safe():
    assert clean_text("") == ""


def test_already_clean_word_is_unchanged():
    assert fix_confusables("hello") == "hello"


def test_inserts_missing_space_after_comma():
    assert clean_text("here,traveler.") == "here, traveler."


def test_does_not_insert_space_in_decimal_numbers():
    assert clean_text("Price: 3.14 gold") == "Price: 3.14 gold"
