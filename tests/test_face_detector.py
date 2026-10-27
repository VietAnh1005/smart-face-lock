from core.face_types import largest


def test_largest_box_by_area():
    small, big = (0, 50, 50, 0), (100, 400, 400, 100)   # (top, right, bottom, left)
    assert largest([small, big]) == big
    assert largest([big, small]) == big
