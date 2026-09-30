from gametrans.textprep import prepare


def test_number_placeholder_round_trip():
    p = prepare("HP 120/200", glossary={})
    assert "120/200" not in p.text
    # simulate translator leaving placeholders untouched
    translated = p.text.replace("HP", "พลังชีวิต")
    restored = p.restore(translated)
    assert "120/200" in restored


def test_format_specifier_round_trip():
    p = prepare("Deal {0} damage", glossary={})
    assert "{0}" not in p.text
    restored = p.restore(p.text)
    assert "{0}" in restored


def test_percent_d_format_round_trip():
    p = prepare("You found %d gold.", glossary={})
    assert "%d" not in p.text
    restored = p.restore(p.text)
    assert "%d" in restored


def test_glossary_term_replaced_and_restored_as_thai():
    p = prepare("I need a Potion now", glossary={"Potion": "ยา"})
    assert "Potion" not in p.text
    restored = p.restore(p.text)
    assert "ยา" in restored
    assert "Potion" not in restored


def test_glossary_is_case_insensitive_and_whole_word_only():
    p = prepare("Potions and Potionmaker", glossary={"Potion": "ยา"})
    # "Potionmaker" must NOT be treated as containing the whole word "Potion"
    restored = p.restore(p.text)
    assert "Potionmaker" in restored


def test_all_caps_is_sentence_cased_before_protection():
    p = prepare("GAME OVER", glossary={})
    assert p.text != "GAME OVER"
    assert p.text.lower() == "game over"


def test_pure_number_text_is_marked_skip():
    p = prepare("120/200", glossary={})
    assert p.skip is True


def test_text_with_letters_is_not_skipped():
    p = prepare("Hello 120", glossary={})
    assert p.skip is False


def test_angle_bracket_placeholder_round_trip():
    p = prepare("Welcome, <name>!", glossary={})
    assert "<name>" not in p.text
    restored = p.restore(p.text)
    assert "<name>" in restored


def test_restore_is_idempotent_for_untouched_tokens():
    p = prepare("Deal {0} damage to <name>", glossary={})
    restored = p.restore(p.text)
    assert restored == "Deal {0} damage to <name>"
