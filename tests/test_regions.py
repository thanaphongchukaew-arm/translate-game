import pytest

from gametrans.regions import Region, rect_to_pixels, rect_from_pixels, regions_overlap


def test_rect_to_pixels_basic():
    assert rect_to_pixels((0.0, 0.0, 1.0, 1.0), 1920, 1080) == (0, 0, 1920, 1080)
    assert rect_to_pixels((0.5, 0.5, 1.0, 1.0), 1920, 1080) == (960, 540, 1920, 1080)


def test_rect_from_pixels_round_trip():
    rect = (0.25, 0.5, 0.75, 0.9)
    px = rect_to_pixels(rect, 1920, 1080)
    back = rect_from_pixels(px, 1920, 1080)
    assert back == pytest.approx(rect, abs=1e-3)


def test_rect_survives_resolution_change():
    rect = (0.05, 0.72, 0.95, 0.95)
    px_1080 = rect_to_pixels(rect, 1920, 1080)
    px_1440 = rect_to_pixels(rect, 2560, 1440)
    # proportionally equivalent even though pixel values differ
    assert px_1080[0] / 1920 == pytest.approx(px_1440[0] / 2560, abs=1e-6)


def test_region_rejects_out_of_range_rect():
    with pytest.raises(ValueError):
        Region(name="bad", rect=(0.0, 0.0, 1.5, 1.0), preset="dialogue")


def test_region_rejects_inverted_rect():
    with pytest.raises(ValueError):
        Region(name="bad", rect=(0.5, 0.5, 0.2, 0.8), preset="dialogue")


def test_regions_overlap_detects_overlap():
    a = Region(name="a", rect=(0.0, 0.0, 0.5, 0.5), preset="ui_heavy")
    b = Region(name="b", rect=(0.3, 0.3, 0.8, 0.8), preset="ui_heavy")
    assert regions_overlap(a, b) is True


def test_regions_overlap_detects_no_overlap():
    a = Region(name="a", rect=(0.0, 0.0, 0.3, 0.3), preset="ui_heavy")
    b = Region(name="b", rect=(0.5, 0.5, 0.8, 0.8), preset="ui_heavy")
    assert regions_overlap(a, b) is False


def test_regions_overlap_adjacent_not_overlapping():
    a = Region(name="a", rect=(0.0, 0.0, 0.5, 1.0), preset="ui_heavy")
    b = Region(name="b", rect=(0.5, 0.0, 1.0, 1.0), preset="ui_heavy")
    assert regions_overlap(a, b) is False
