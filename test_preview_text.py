from openflow.engine.preview_text import merge_preview


def test_sliding_windows_grow_one_line():
    t = merge_preview("", "hello there how")
    t = merge_preview(t, "there how are you")
    t = merge_preview(t, "are you doing today")
    assert t == "hello there how are you doing today"


def test_tail_correction_replaces_instead_of_repeating():
    t = merge_preview("send the file to", "send the fire to rahul")
    assert t == "send the fire to rahul"
    t = merge_preview("we should meet at noon", "meet at noon tomorrow")
    assert t == "we should meet at noon tomorrow"


def test_same_or_empty_text_changes_nothing():
    assert merge_preview("hello world", "hello world") == "hello world"
    assert merge_preview("hello world", "") == "hello world"
    assert merge_preview("", " first words ") == "first words"


def test_window_with_no_overlap_continues_the_line():
    assert merge_preview("good morning team", "lets start") == "good morning team lets start"
