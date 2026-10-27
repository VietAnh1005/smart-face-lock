import itertools

import numpy as np
import pytest

from config import settings
from services.enrollment_service import DONE, READY, RUNNING, EnrollmentError, EnrollmentService
from services.frame_result import FrameResult
from tests.conftest import make_landmarks, vector
from tests.test_liveness_checker import FixedOrder


class FakeAdmin:
    def __init__(self):
        self.active = True
        self.touches = 0

    def is_active(self):
        return self.active

    def touch(self):
        self.touches += 1


@pytest.fixture
def admin():
    return FakeAdmin()


@pytest.fixture
def service(ctx, clock, admin):
    svc = EnrollmentService(ctx.users, ctx.logs, admin, ctx.logger, clock,
                            FixedOrder(["OPEN_MOUTH", "TURN_LEFT"]))
    svc.start("An", "123456", "123456")
    for pose in ({"mouth_gap": 25}, {}, {"yaw_deg": 25}):  # qua 2 thử thách liveness
        svc.feed(frame(clock, **pose))
    assert svc.liveness_passed and svc.captured == 0
    return svc


SEQ = itertools.count(1)


def frame(clock, encoded_pose=None, encoding_age=None, encoding_quality=True, **pose):
    """Frame giả; vector mặc định thuộc chính frame này. encoded_pose: vector của frame cũ có tư thế khác."""
    clock.t += settings.ENROLL_CAPTURE_INTERVAL + 0.1
    seq = next(SEQ)
    landmarks = make_landmarks(**pose)
    age = encoding_age if encoding_age is not None else (0 if encoded_pose is None else 3)
    return FrameResult(None, boxes=[(100, 300, 300, 100)], landmarks=landmarks, quality_ok=True, seq=seq,
                       encoding=vector(1) + np.random.default_rng(int(clock.t)).normal(0, 0.005, 128),
                       encoding_seq=seq - age,
                       encoding_landmarks=landmarks if encoded_pose is None else make_landmarks(**encoded_pose),
                       encoding_quality=encoding_quality)


def captured(svc):
    return len(svc._captures)


def capture_front(service, clock):
    """Nhìn thẳng tới khi được chụp (cần đủ mẫu làm mốc pitch trước)."""
    before = captured(service)
    for _ in range(10):
        service.feed(frame(clock))
        if captured(service) > before:
            return
    raise AssertionError("không chụp được ảnh nhìn thẳng")


POSE_ARGS = {"front": {}, "left": {"yaw_deg": 20}, "right": {"yaw_deg": -20},
             "up": {"pitch_deg": 20}, "down": {"pitch_deg": -20}}


def test_encoding_from_liveness_frames_not_stored(service, clock):
    """Vector đến trễ của frame chụp lúc còn làm thử thách không được lưu."""
    for _ in range(10):
        service.feed(frame(clock, encoding_age=50))
    assert captured(service) == 0


def test_quality_checked_on_the_encoded_frame(service, clock):
    for _ in range(10):
        service.feed(frame(clock, encoding_quality=False))  # frame hiện tại nét, frame của vector bị mờ
    assert captured(service) == 0


def test_front_needs_several_frames_for_pitch_baseline(service, clock):
    for _ in range(4):
        service.feed(frame(clock))
    assert captured(service) == 0
    service.feed(frame(clock))
    assert captured(service) == 1


def test_up_and_down_poses_are_not_auto_passed(service, clock):
    capture_front(service, clock)
    for pose in ("left", "right"):
        service.feed(frame(clock, **POSE_ARGS[pose]))
    assert captured(service) == 3
    for _ in range(5):
        service.feed(frame(clock))                      # nhìn thẳng khi được yêu cầu ngẩng lên
    assert captured(service) == 3
    service.feed(frame(clock, **POSE_ARGS["down"]))     # cúi xuống khi được yêu cầu ngẩng lên
    assert captured(service) == 3
    service.feed(frame(clock, **POSE_ARGS["up"]))
    assert captured(service) == 4
    for _ in range(5):
        service.feed(frame(clock))                      # nhìn thẳng khi được yêu cầu cúi xuống
    assert captured(service) == 4
    service.feed(frame(clock, **POSE_ARGS["down"]))
    assert captured(service) == 5


def test_full_enrollment_waits_for_save(service, clock, ctx):
    capture_front(service, clock)
    state = RUNNING
    for pose in ["left", "right", "up", "down", "front", "left", "right", "up", "down"]:
        state, _, _ = service.feed(frame(clock, **POSE_ARGS[pose]))
    assert state == READY and service.ready
    assert ctx.users.list_users() == []           # chưa bấm Lưu thì chưa ghi DB
    assert service.feed(frame(clock))[0] == READY  # không chụp thêm
    assert service.save()[0] == DONE
    assert ctx.users.list_users()[0]["name"] == "An"


def test_pitch_noise_and_head_turn_do_not_count_as_up(service, clock):
    """Đo thật: nhìn thẳng pitch dao động ~0.06, quay đầu làm pitch lệch ~0.04 → không được tính là ngẩng."""
    for noise in (0, 0, 0, 0, -7):                     # frame mốc cuối bất thường không làm lệch trung vị
        service.feed(frame(clock, pitch_deg=noise))
    for pose in ("left", "right"):
        service.feed(frame(clock, **POSE_ARGS[pose]))
    assert captured(service) == 3
    for noise in (7, 7):                               # lắc nhẹ ~7° (Δpitch ~0.055): vượt ngưỡng cũ 0.05
        service.feed(frame(clock, pitch_deg=noise))
    service.feed(frame(clock, pitch_deg=20, yaw_deg=25))  # ngẩng nhưng đầu đang quay ngang
    assert captured(service) == 3
    service.feed(frame(clock, pitch_deg=20))
    assert captured(service) == 4


def test_pose_checked_on_the_frame_the_encoding_came_from(service, clock):
    """Vector đến từ frame cũ còn đang nhìn thẳng thì không được lưu thành ảnh 'ngẩng lên'."""
    capture_front(service, clock)
    for pose in ("left", "right"):
        service.feed(frame(clock, **POSE_ARGS[pose]))
    service.feed(frame(clock, encoded_pose={}, **POSE_ARGS["up"]))  # frame hiện tại ngẩng, vector của frame cũ
    assert captured(service) == 3
    service.feed(frame(clock, **POSE_ARGS["up"]))
    assert captured(service) == 4


def test_save_refused_before_ready(service):
    with pytest.raises(EnrollmentError):
        service.save()


def test_camera_frames_do_not_extend_admin_session(service, clock, admin):
    """Chỉ thao tác của admin mới gia hạn phiên; frame camera thì không."""
    before = admin.touches
    for _ in range(5):
        service.feed(frame(clock))
    assert admin.touches == before


def test_expired_admin_session_stops_enrollment(service, clock, admin):
    admin.active = False
    with pytest.raises(EnrollmentError):
        service.feed(frame(clock))
    assert not service.active
