import numpy as np

from core.face_matcher import find_best_match
from tests.conftest import vector


def test_empty_known_never_matches():
    assert find_best_match(vector(1), {}) == (None, float("inf"))


def test_match_under_threshold():
    owner = vector(1)
    uid, dist = find_best_match(owner + 0.01, {7: [owner], 8: [vector(2)]})
    assert uid == 7 and dist < 0.45


def test_reject_over_threshold():
    assert find_best_match(vector(3), {7: [vector(1)]})[0] is None


def test_reject_when_two_users_too_close():
    a = vector(1)
    b = a + np.full(128, 0.002)          # người thứ hai gần như giống hệt
    uid, _ = find_best_match(a, {1: [a], 2: [b]})
    assert uid is None                   # không đủ biên an toàn MATCH_MARGIN
