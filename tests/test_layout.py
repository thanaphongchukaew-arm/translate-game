from gametrans.layout import OcrLine, Block, merge_lines, track_blocks


def _line(x1, y1, x2, y2, text, score=0.9):
    return OcrLine(x1=x1, y1=y1, x2=x2, y2=y2, text=text, score=score)


def test_three_lines_merge_into_one_block():
    lines = [
        _line(10, 100, 200, 120, "Line one"),
        _line(10, 122, 200, 142, "Line two"),
        _line(10, 144, 200, 164, "Line three"),
    ]
    blocks = merge_lines(lines, cfg=None)
    assert len(blocks) == 1
    assert blocks[0].text == "Line one\nLine two\nLine three"


def test_two_side_by_side_columns_do_not_merge():
    lines = [
        _line(10, 100, 100, 120, "Left"),
        _line(300, 100, 400, 120, "Right"),
    ]
    blocks = merge_lines(lines, cfg=None)
    assert len(blocks) == 2


def test_very_different_font_size_does_not_merge():
    lines = [
        _line(10, 100, 200, 120, "Normal size"),   # h=20
        _line(10, 122, 400, 200, "Huge heading"),   # h=78, ratio way off
    ]
    blocks = merge_lines(lines, cfg=None)
    assert len(blocks) == 2


def test_result_is_deterministic_regardless_of_input_order():
    lines = [
        _line(10, 100, 200, 120, "Line one"),
        _line(10, 122, 200, 142, "Line two"),
    ]
    reversed_lines = list(reversed(lines))
    blocks_a = merge_lines(lines, cfg=None)
    blocks_b = merge_lines(reversed_lines, cfg=None)
    assert [b.text for b in blocks_a] == [b.text for b in blocks_b]


def test_vertical_menu_wide_gap_does_not_merge():
    lines = [
        _line(10, 100, 200, 120, "Menu item one"),
        _line(10, 300, 200, 320, "Menu item two"),  # gap way larger than 0.9h
    ]
    blocks = merge_lines(lines, cfg=None)
    assert len(blocks) == 2


def _block(id_, x1, y1, x2, y2, text, stable_cycles=0, stable_since=0.0, first_seen=0.0, last_seen=0.0, hold_left=2):
    return Block(
        id=id_, x1=x1, y1=y1, x2=x2, y2=y2, text=text, line_h=20.0,
        first_seen=first_seen, last_seen=last_seen,
        stable_cycles=stable_cycles, stable_since=stable_since, hold_left=hold_left,
    )


def test_tracking_keeps_id_and_increments_stable_cycles():
    prev = [_block(0, 10, 10, 100, 30, "Hello", stable_cycles=0, stable_since=1.0, first_seen=1.0, last_seen=1.0)]
    cur = [_block(-1, 10, 10, 100, 30, "Hello")]  # id is reassigned by track_blocks
    result = track_blocks(prev, cur, now=2.0, cfg=None)
    assert len(result) == 1
    assert result[0].id == 0
    assert result[0].stable_cycles == 1
    assert result[0].stable_since == 1.0


def test_tracking_resets_stable_cycles_when_text_changes():
    prev = [_block(0, 10, 10, 100, 30, "Hello", stable_cycles=3, stable_since=1.0, first_seen=1.0, last_seen=1.5)]
    cur = [_block(-1, 10, 10, 100, 30, "Goodbye")]
    result = track_blocks(prev, cur, now=2.0, cfg=None)
    assert result[0].stable_cycles == 0
    assert result[0].stable_since == 2.0


def test_hysteresis_holds_vanished_block_for_hold_cycles():
    cfg = {"layout": {"hold_cycles": 2}, "ocr": {"max_blocks": 60}}
    prev = [_block(0, 10, 10, 100, 30, "Hello", hold_left=2)]
    # block vanished this frame (cur is empty)
    result = track_blocks(prev, [], now=2.0, cfg=cfg)
    assert len(result) == 1
    assert result[0].id == 0
    assert result[0].hold_left == 1

    result2 = track_blocks(result, [], now=3.0, cfg=cfg)
    assert len(result2) == 0  # hold exhausted, dropped


def test_small_movement_under_3px_keeps_old_position():
    prev = [_block(0, 10.0, 10.0, 100.0, 30.0, "Hello")]
    cur = [_block(-1, 11.0, 10.5, 101.0, 30.5, "Hello")]  # moved < 3px
    result = track_blocks(prev, cur, now=2.0, cfg=None)
    assert result[0].x1 == 10.0 and result[0].y1 == 10.0


def test_movement_over_3px_updates_position():
    prev = [_block(0, 10.0, 10.0, 100.0, 30.0, "Hello")]
    cur = [_block(-1, 20.0, 10.0, 110.0, 30.0, "Hello")]  # moved 10px
    result = track_blocks(prev, cur, now=2.0, cfg=None)
    assert result[0].x1 == 20.0
