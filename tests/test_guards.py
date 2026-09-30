from gametrans.guards import check_translation


def test_rejects_empty_output():
    result = check_translation("Hello there", "")
    assert result.ok is False
    assert result.reason == "empty"


def test_rejects_whitespace_only_output():
    result = check_translation("Hello there", "   ")
    assert result.ok is False
    assert result.reason == "empty"


def test_rejects_output_with_no_thai_characters():
    result = check_translation("Hello there, traveler", "Hello there, traveler")
    assert result.ok is False
    assert result.reason == "not_thai"


def test_accepts_good_thai_translation():
    result = check_translation("Hello there", "สวัสดีครับ")
    assert result.ok is True


def test_rejects_wildly_too_long_output():
    src = "Hi there"
    out = "สวัสดี" * 20
    result = check_translation(src, out)
    assert result.ok is False
    assert result.reason == "too_long"


def test_rejects_repetition_hallucination():
    src = "The old mill by the river at sunset"
    out = " ".join(["ดีดี ดีดี"] * 6)
    result = check_translation(src, out)
    assert result.ok is False
    assert result.reason == "repetition"


def test_does_not_falsely_reject_natural_repetition():
    src = "Run run run as fast as you can"
    out = "วิ่ง วิ่ง เร็วที่สุดเท่าที่จะทำได้"
    result = check_translation(src, out)
    assert result.ok is True


def test_rejects_lost_numbers():
    result = check_translation("You found 50 gold.", "คุณเจอทองคำ")
    assert result.ok is False
    assert result.reason == "lost_numbers"


def test_accepts_when_numbers_preserved():
    result = check_translation("You found 50 gold.", "คุณเจอทองคำ 50 ชิ้น")
    assert result.ok is True


def test_rejects_unresolved_placeholder_token():
    result = check_translation("Deal damage", "โจมตี ⟦P0⟧")
    assert result.ok is False
    assert result.reason == "unresolved_placeholder"


def test_rejects_explanatory_preamble():
    result = check_translation("Hello", "Here is the translation: สวัสดี")
    assert result.ok is False
    assert result.reason == "explanatory_text"


def test_accepts_short_names_without_over_rejecting():
    result = check_translation("Aldric", "อัลดริก")
    assert result.ok is True
