from gametrans.text_handlers import ChatLogTracker


def test_first_call_reports_all_lines_as_new():
    tracker = ChatLogTracker()
    new = tracker.new_lines(["Alice: hi", "Bob: hello"])
    assert new == ["Alice: hi", "Bob: hello"]


def test_scroll_by_one_line_reports_only_the_new_line():
    tracker = ChatLogTracker()
    tracker.new_lines(["Alice: hi", "Bob: hello", "Alice: how are you"])
    new = tracker.new_lines(["Bob: hello", "Alice: how are you", "Bob: good thanks"])
    assert new == ["Bob: good thanks"]


def test_scroll_by_multiple_lines_at_once():
    tracker = ChatLogTracker()
    tracker.new_lines(["L1", "L2", "L3"])
    new = tracker.new_lines(["L4", "L5", "L6"])
    assert new == ["L4", "L5", "L6"]


def test_no_change_reports_no_new_lines():
    tracker = ChatLogTracker()
    tracker.new_lines(["L1", "L2", "L3"])
    new = tracker.new_lines(["L1", "L2", "L3"])
    assert new == []


def test_genuine_duplicate_line_that_scrolled_is_not_re_reported():
    tracker = ChatLogTracker()
    tracker.new_lines(["Alice: lol", "Bob: what"])
    # "Alice: lol" scrolled up (still present, same content) — should NOT
    # be treated as new again, only "Bob: lol" is new.
    new = tracker.new_lines(["Bob: what", "Bob: lol"])
    assert new == ["Bob: lol"]


def test_two_identical_consecutive_new_lines_both_reported():
    tracker = ChatLogTracker()
    tracker.new_lines(["Alice: hi"])
    # a genuinely repeated message arrives as a brand new second line
    new = tracker.new_lines(["Alice: hi", "Alice: hi"])
    assert new == ["Alice: hi"]


def test_reset_clears_history():
    tracker = ChatLogTracker()
    tracker.new_lines(["L1", "L2"])
    tracker.reset()
    new = tracker.new_lines(["L1", "L2"])
    assert new == ["L1", "L2"]


def test_completely_different_content_treats_all_as_new():
    tracker = ChatLogTracker()
    tracker.new_lines(["L1", "L2", "L3"])
    new = tracker.new_lines(["X1", "X2"])
    assert new == ["X1", "X2"]
