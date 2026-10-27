from config import settings
from core.landmark_utils import head_yaw, planarity_residual
from core.liveness_checker import FAILED, PASSED, PENDING, LivenessChecker
from tests.conftest import make_landmarks


class FixedOrder:
    """rng giả: luôn chọn và xếp các thử thách theo đúng thứ tự cho trước."""

    def __init__(self, steps):
        self.steps = steps

    def sample(self, population, k):
        return [s for s in self.steps if s in population][:k]

    def shuffle(self, items):
        items.sort(key=self.steps.index)


def checker(clock, *steps):
    return LivenessChecker(clock, FixedOrder(list(steps)))


def test_real_face_passes_blink_and_turn(clock):
    c = checker(clock, "BLINK_TWICE", "TURN_LEFT")
    frames = [make_landmarks()] * 3 + [make_landmarks(eye_open=0.2), make_landmarks(),
                                       make_landmarks(eye_open=0.2), make_landmarks()]
    assert [c.update(f) for f in frames][-1] == PENDING  # xong bước 1, sang bước 2
    assert c.update(make_landmarks(yaw_deg=25)) == PASSED


def blinks_counted(clock, open_level, closed_level):
    c = checker(clock, "BLINK_TWICE", "TURN_LEFT")
    seq = [open_level] * 5 + [closed_level, open_level] * 2
    for level in seq:
        c.update(make_landmarks(eye_open=level))
    return c.step_number == 2  # đã qua bước nháy mắt


def test_blink_threshold_adapts_to_each_persons_eyes(clock):
    """Đo thật: mắt mở 0.30–0.38, nháy nhanh chỉ xuống 0.21–0.23 → ngưỡng cố định 0.21 bỏ sót."""
    assert blinks_counted(clock, open_level=1.0, closed_level=0.66)   # EAR 0.33 → 0.22: nháy nhanh, mắt to
    assert blinks_counted(clock, open_level=0.7, closed_level=0.45)   # mắt nhỏ: EAR 0.23 → 0.15


def test_small_eye_jitter_is_not_a_blink(clock):
    assert not blinks_counted(clock, open_level=1.0, closed_level=0.85)  # dao động nhẹ, không nhắm thật


def test_open_mouth_and_turn_right(clock):
    c = checker(clock, "OPEN_MOUTH", "TURN_RIGHT")
    assert c.update(make_landmarks(mouth_gap=25)) == PENDING
    c.update(make_landmarks())
    assert c.update(make_landmarks(yaw_deg=-25)) == PASSED


def test_tilted_photo_rejected(clock):
    """Ảnh in nghiêng mạnh làm yaw vượt ngưỡng, nhưng vẫn là mặt phẳng nên bị từ chối."""
    tilt = [[1, 0, 0], [0, 1, 0], [0.006, 0, 1]]
    tilted = make_landmarks(flat=True, homography=tilt)
    assert settings.YAW_SIGN * head_yaw(tilted) > settings.TURN_YAW  # tiền đề: yaw đã bị lừa
    assert planarity_residual(make_landmarks(flat=True), tilted) < settings.MIN_3D_RESIDUAL
    assert planarity_residual(make_landmarks(), make_landmarks(yaw_deg=25)) >= settings.MIN_3D_RESIDUAL

    c = checker(clock, "TURN_LEFT", "OPEN_MOUTH")
    c.update(make_landmarks(flat=True))
    assert c.update(tilted) == PENDING
    clock.t += settings.CHALLENGE_TIMEOUT + 1
    assert c.update(tilted) == FAILED
    assert "phẳng" in c.reason


def test_spoof_flag(clock):
    tilted = make_landmarks(flat=True, homography=[[1, 0, 0], [0, 1, 0], [0.006, 0, 1]])
    c = checker(clock, "TURN_LEFT", "OPEN_MOUTH")
    c.update(make_landmarks(flat=True))
    c.update(tilted)
    clock.t += settings.CHALLENGE_TIMEOUT + 1
    assert c.update(tilted) == FAILED and c.spoof
    plain = checker(clock, "TURN_LEFT", "OPEN_MOUTH")
    clock.t += settings.CHALLENGE_TIMEOUT + 1
    assert plain.update(make_landmarks()) == FAILED and not plain.spoof


def test_timeout(clock):
    c = checker(clock, "BLINK_TWICE", "TURN_LEFT")
    clock.t += settings.CHALLENGE_TIMEOUT + 1
    assert c.update(make_landmarks()) == FAILED


def test_random_challenges_are_distinct_and_include_a_turn():
    """Mọi phiên phải có bước quay đầu (bước duy nhất kiểm tra chiều sâu 3D)."""
    seen = set()
    for _ in range(200):
        steps = LivenessChecker().steps
        assert len(steps) == settings.LIVENESS_STEPS == len(set(steps))
        assert any(s in ("TURN_LEFT", "TURN_RIGHT") for s in steps)
        seen.add(tuple(steps))
    assert len(seen) > 4  # vẫn ngẫu nhiên cả lựa chọn lẫn thứ tự
