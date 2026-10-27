import itertools
from types import SimpleNamespace

import numpy as np
import pytest

from config import settings
from hardware.simulated_lock import SimulatedLock
from security.pin_auth import PinFactor, hash_pin
from services.auth_service import (FACE_DISABLED, FACE_FAIL, FALLBACK_FAIL, LOCKED, LOCKED_OUT, UNLOCKED,
                                   VERIFYING, AuthService)
from services.frame_result import FrameResult
from services.lockout_service import FaceCounter, LockoutService
from tests.conftest import make_landmarks, vector
from tests.test_liveness_checker import FixedOrder

BOX = [(100, 300, 300, 100)]
SEQ = itertools.count(1)
TILT = [[1, 0, 0], [0, 1, 0], [0.006, 0, 1]]


def frame(encoding=None, boxes=BOX, encoding_age=0, quality=True, **landmark_args):
    seq = next(SEQ)
    return FrameResult(frame=np.zeros((4, 4, 3), np.uint8), boxes=boxes, encoding=encoding, seq=seq,
                       encoding_seq=seq - encoding_age, encoding_quality=quality,
                       landmarks=make_landmarks(**landmark_args) if boxes else None)


def near(v, d):
    """Vector cách v đúng d (người có mặt giống)."""
    u = vector(8) - (vector(8) @ v) * v
    return v + d * u / np.linalg.norm(u)


def build(ctx, clock, factor=None):
    lockout = LockoutService(ctx.state, ctx.logger, "", clock, settings.LOCK_MAX_FAILED, admin_after_last=True)
    faces = FaceCounter(ctx.state, ctx.logger)
    lock = SimulatedLock(clock)
    auth = AuthService(ctx.users, lockout, faces, factor or PinFactor(ctx.users),
                       ctx.logger, lock, clock,
                       FixedOrder(["TURN_LEFT", "OPEN_MOUTH"]))
    return SimpleNamespace(auth=auth, lock=lock, lockout=lockout, faces=faces)


@pytest.fixture
def s(ctx, clock):
    owner = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    other = ctx.users.add_user("Bình", hash_pin("654321"), [vector(2)])
    return SimpleNamespace(**vars(build(ctx, clock)), owner=owner, other=other, ctx=ctx, clock=clock)


def events(ctx):
    return [row["event"] for row in ctx.logs.list()]


def liveness(auth, vec):
    """Mặt `vec` làm xong thử thách (quay trái, há miệng); mỗi frame có vector."""
    auth.feed(frame(vec))
    auth.feed(frame(vec, yaw_deg=25))
    return auth.feed(frame(vec, mouth_gap=25))


def look_straight(auth, vec, n=3):
    for _ in range(n):
        view = auth.feed(frame(vec))
    return view


def reach_fingerprint(s, vec=None):
    vec = vector(1) if vec is None else vec
    liveness(s.auth, vec)
    return look_straight(s.auth, vec)


def end_result(s):
    """Hết thời gian hiện kết quả và người rời camera."""
    s.clock.t += settings.RESULT_HOLD_SECONDS
    s.auth.feed(frame(boxes=[]))
    return s.auth.feed(frame(boxes=[]))


def fail_face_once(s):
    liveness(s.auth, vector(99))
    look_straight(s.auth, vector(99))
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    view = s.auth.feed(frame(vector(99)))
    end_result(s)
    return view


def disable_face(s):
    s.ctx.state.set(FaceCounter.KEY, settings.FACE_MAX_FAILED)
    return s.auth.feed(frame(boxes=[]))


def wrong_fallback(s, pin="000000"):
    view = s.auth.submit_fallback(pin, s.owner)
    s.clock.t += settings.RESULT_HOLD_SECONDS
    return view


# ---------- luồng thường ----------

def test_owner_unlocks(s):
    assert liveness(s.auth, vector(1)).state == VERIFYING
    view = look_straight(s.auth, vector(1))
    assert (view.state, view.step, view.user) == (VERIFYING, "FINGERPRINT", "An")
    view = s.auth.submit_fingerprint("123456")
    assert (view.state, view.tone) == (UNLOCKED, "ok")
    assert not s.lock.is_locked()
    assert "GRANTED" in events(s.ctx)


def test_liveness_runs_before_matching_for_any_face(s):
    """Người lạ cũng phải làm thử thách: màn hình không lộ ảnh đã khớp hay chưa."""
    view = s.auth.feed(frame(vector(99)))
    assert (view.state, view.step) == (VERIFYING, "FACE") and s.auth.challenge() is not None


def test_two_faces_start_a_session(s):
    assert s.auth.feed(frame(vector(1), boxes=BOX + [(0, 50, 50, 0)])).state == VERIFYING


# ---------- sai mặt và câu báo chung ----------

def test_stranger_counts_face_failure_with_generic_message(s):
    view = fail_face_once(s)
    assert (view.tone, view.message) == ("bad", FACE_FAIL)
    assert s.faces.count() == 1 and s.lockout.failed_count() == 0
    assert "FACE_MISMATCH" in events(s.ctx)


def test_spoof_has_same_message_as_mismatch(s):
    s.auth.feed(frame(vector(1), flat=True))
    s.auth.feed(frame(vector(1), flat=True, homography=TILT))
    s.clock.t += settings.CHALLENGE_TIMEOUT + 0.1
    view = s.auth.feed(frame(vector(1), flat=True, homography=TILT))
    assert (view.tone, view.message) == ("bad", FACE_FAIL)
    assert "SPOOF_DETECTED" in events(s.ctx)


def test_photo_swap_after_liveness_fails(s):
    """Mặt thật của kẻ phá qua thử thách, rồi giơ ảnh chủ nhà ở bước nhìn thẳng."""
    liveness(s.auth, vector(7))
    view = look_straight(s.auth, vector(1))
    assert view.step == "FACE"
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    assert s.auth.feed(frame(vector(1))).message == FACE_FAIL
    assert "FACE_MISMATCH" in events(s.ctx)


def test_lookalike_between_thresholds_fails(s):
    """Mặt kẻ phá cách ảnh chủ nhà 0,5 (giữa 0,45 và 0,60) vẫn làm phiên thất bại."""
    liveness(s.auth, near(vector(1), 0.5))
    assert look_straight(s.auth, vector(1)).step == "FACE"
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    assert s.auth.feed(frame(vector(1))).message == FACE_FAIL


def test_low_quality_encodings_are_ignored(s):
    liveness(s.auth, vector(1))
    view = s.auth.feed(frame(vector(99), quality=False))   # mờ: không tính vào tỉ lệ
    assert view.state == VERIFYING
    assert look_straight(s.auth, vector(1)).step == "FINGERPRINT"


# ---------- thời gian ----------

def test_passer_by_is_not_counted(s):
    s.auth.feed(frame(vector(99)))
    s.clock.t += 2
    s.auth.feed(frame(boxes=[]))
    s.clock.t += settings.FACE_LOST_SECONDS + 0.1
    view = s.auth.feed(frame(boxes=[]))
    assert (view.state, view.tone) == (LOCKED, "")
    assert s.faces.count() == 0 and events(s.ctx) == []


def test_covering_camera_after_5s_counts(s):
    s.auth.feed(frame(vector(99)))
    s.clock.t += 5.5
    s.auth.feed(frame(vector(99)))
    s.clock.t += settings.FACE_LOST_SECONDS + 0.1
    view = s.auth.feed(frame(boxes=[]))
    assert view.message == FACE_FAIL and "FACE_ABORTED" in events(s.ctx)


def test_restart_button_after_5s_counts(s):
    s.auth.feed(frame(vector(99)))
    s.clock.t += 5.5
    s.auth.feed(frame(vector(99)))
    s.auth.abort()
    assert s.faces.count() == 1 and "FACE_ABORTED" in events(s.ctx)


def test_restart_button_early_is_free(s):
    s.auth.feed(frame(vector(99)))
    s.auth.abort()
    assert s.faces.count() == 0 and events(s.ctx) == []


def test_liveness_timeout_while_present_counts(s):
    s.auth.feed(frame(vector(1)))
    s.clock.t += settings.CHALLENGE_TIMEOUT + 0.1
    assert s.auth.feed(frame(vector(1))).message == FACE_FAIL
    assert "FACE_TIMEOUT" in events(s.ctx)


def test_leaving_at_fingerprint_is_not_counted(s):
    reach_fingerprint(s)
    s.clock.t += settings.PIN_TIMEOUT + 1
    view = s.auth.feed(frame(boxes=[]))
    assert (view.state, view.tone) == (LOCKED, "")
    assert s.faces.count() == 0 and s.lockout.failed_count() == 0


# ---------- vân tay ----------

def test_wrong_pin_counts_lock_failure(s):
    reach_fingerprint(s)
    view = s.auth.submit_fingerprint("000000")
    assert view.tone == "bad" and s.lockout.failed_count() == 1
    assert "FINGERPRINT_FAILED" in events(s.ctx)


def test_fingerprint_of_another_user_is_rejected(ctx, clock):
    owner = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    other = ctx.users.add_user("Bình", hash_pin("654321"), [vector(2)])

    class OtherFinger:
        def identify(self, sample, claimed_user_id):
            return other

    b = build(ctx, clock, OtherFinger())
    liveness(b.auth, vector(1))
    assert look_straight(b.auth, vector(1)).user == "An"
    assert b.auth.submit_fingerprint("anything").tone == "bad"
    assert b.lock.is_locked() and b.lockout.failed_count() == 1 and owner != other


# ---------- FACE_DISABLED ----------

def test_max_face_failures_disable_face_id(s):
    for _ in range(settings.FACE_MAX_FAILED):
        fail_face_once(s)
    view = s.auth.feed(frame(vector(1)))
    assert view.state == FACE_DISABLED and s.auth.challenge() is None


def test_fallback_wrong_pin_counts_lock_failure(s):
    disable_face(s)
    view = wrong_fallback(s)
    assert (view.state, view.message) == (FACE_DISABLED, FALLBACK_FAIL)
    assert "FINGERPRINT_FAILED" in events(s.ctx) and s.lockout.failed_count() == 1


def test_fallback_needs_chosen_user(s):
    disable_face(s)
    assert s.auth.submit_fallback("123456", None).message == FALLBACK_FAIL


def test_fallback_success_resets_both_counters(s):
    disable_face(s)
    wrong_fallback(s)
    view = s.auth.submit_fallback("123456", s.owner)
    assert (view.state, view.user) == (UNLOCKED, "An")
    assert s.faces.count() == 0 and s.lockout.failed_count() == 0


def test_submit_ignored_while_result_is_shown(s):
    disable_face(s)
    s.auth.submit_fallback("000000", s.owner)
    s.auth.submit_fallback("000000", s.owner)   # chưa hết RESULT_HOLD_SECONDS
    assert s.lockout.failed_count() == 1


# ---------- LOCKED_OUT ----------

def test_six_failures_reach_admin_only(s):
    """3 lần sai PIN → khóa 30 giây; hết khóa chỉ 1 lần thử: tổng 3 + 1 + 1 + 1 = 6 lần."""
    disable_face(s)
    for _ in range(settings.LOCK_MAX_FAILED):
        wrong_fallback(s)
    assert s.auth.feed(frame(boxes=[])).state == LOCKED_OUT
    assert s.auth.submit_fallback("123456", s.owner).state == LOCKED_OUT   # đang khóa: bỏ qua
    for _ in range(len(settings.LOCKOUT_STEPS)):
        s.clock.t += s.lockout.remaining()
        assert s.auth.feed(frame(boxes=[])).state == FACE_DISABLED              # hết giờ: về FACE_DISABLED
        wrong_fallback(s)
    s.clock.t += 10 ** 6
    assert s.auth.feed(frame(boxes=[])).state == LOCKED_OUT and s.auth.admin_only


def test_locked_out_expiry_returns_to_locked_when_face_ok(s):
    for _ in range(settings.LOCK_MAX_FAILED):
        s.lockout.register_failure()
    assert s.auth.feed(frame(boxes=[])).state == LOCKED_OUT
    s.clock.t += settings.LOCKOUT_STEPS[0]
    assert s.auth.feed(frame(boxes=[])).state == LOCKED


# ---------- lưu trữ và dữ liệu bị sửa ----------

def test_state_survives_restart(s, ctx, clock):
    disable_face(s)
    for _ in range(settings.LOCK_MAX_FAILED):
        s.lockout.register_failure()
    restarted = build(ctx, clock).auth
    assert restarted.feed(frame(boxes=[])).state == LOCKED_OUT
    clock.t += settings.LOCKOUT_STEPS[0]
    assert restarted.feed(frame(boxes=[])).state == FACE_DISABLED


def test_tampered_face_counter_disables_face_id(s):
    s.ctx.db.conn.execute("UPDATE app_state SET value = '1' WHERE key = 'face_failed'")
    assert s.auth.feed(frame(vector(1))).state == FACE_DISABLED
    assert "TAMPER_DETECTED" in events(s.ctx)


# ---------- sửa sau review ----------

def test_blurred_real_face_during_liveness_then_photo_fails(s):
    """Rọi đèn/làm mờ mặt thật lúc làm thử thách (vector bị loại) rồi giơ ảnh chủ nhà: không được qua."""
    s.auth.feed(frame(vector(7), quality=False))
    s.auth.feed(frame(vector(7), quality=False, yaw_deg=25))
    s.auth.feed(frame(vector(7), quality=False, mouth_gap=25))
    assert look_straight(s.auth, vector(1), n=6).step == "FACE"
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    assert s.auth.feed(frame(vector(1))).message == FACE_FAIL


def test_restart_after_unlock_waits_for_person_to_leave(s):
    reach_fingerprint(s)
    s.auth.submit_fingerprint("123456")
    s.auth.abort()                                   # bấm "Bắt đầu lại" khi đang hiện ĐÃ MỞ
    s.clock.t += settings.RESULT_HOLD_SECONDS
    for _ in range(3):
        assert s.auth.feed(frame(vector(1))).state != VERIFYING   # chủ nhà còn đứng đó: chưa mở phiên mới


def test_abort_after_5s_shows_denied(s):
    s.auth.feed(frame(vector(99)))
    s.clock.t += 5.5
    s.auth.feed(frame(vector(99)))
    s.auth.abort()
    assert s.auth.feed(frame(vector(99))).message == FACE_FAIL   # người dùng thấy mình vừa bị tính sai


# ---------- sửa sau review toàn bộ mã nguồn ----------

def test_pin_after_timeout_without_frames_is_rejected(s):
    """Camera treo (không có frame) thì hạn nhập PIN vẫn phải được tôn trọng."""
    reach_fingerprint(s)
    s.clock.t += settings.PIN_TIMEOUT + 1
    assert s.auth.submit_fingerprint("123456").state == LOCKED
    assert s.lock.is_locked()


def test_lock_failures_keep_snapshot(s):
    reach_fingerprint(s)
    s.auth.submit_fingerprint("000000")
    end_result(s)
    disable_face(s)
    s.auth.submit_fallback("000000", s.owner, np.zeros((4, 4, 3), np.uint8))
    rows = [r for r in s.ctx.logs.list() if r["event"] == "FINGERPRINT_FAILED"]
    assert len(rows) == 2 and all(r["snapshot"] for r in rows)


def test_unusable_frames_are_logged_as_low_quality(s):
    """Mọi vector đều mờ/tối: vẫn tính sai (chặn cố làm mờ), nhưng ghi đúng lý do cho admin."""
    s.auth.feed(frame(vector(1), quality=False))
    s.auth.feed(frame(vector(1), quality=False, yaw_deg=25))
    s.auth.feed(frame(vector(1), quality=False, mouth_gap=25))
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    s.auth.feed(frame(vector(1), quality=False))
    assert "FACE_LOW_QUALITY" in events(s.ctx)


def test_blur_after_liveness_is_logged_as_low_quality(s):
    """Vector tốt lúc thử thách nhưng mọi vector nhìn thẳng đều mờ: lý do là ảnh, không phải mặt lạ."""
    s.auth.feed(frame(vector(1)))
    s.auth.feed(frame(vector(1)))
    liveness(s.auth, vector(1))                       # 5 vector tốt trong lúc làm thử thách
    for _ in range(3):
        s.auth.feed(frame(vector(1), quality=False))
    s.clock.t += settings.FACE_MATCH_TIMEOUT + 0.1
    s.auth.feed(frame(vector(1), quality=False))
    assert "FACE_LOW_QUALITY" in events(s.ctx)


def test_counter_above_threshold_shows_capped(s):
    """Bộ đếm mặt vượt FACE_MAX_FAILED: hiển thị không vượt ngưỡng."""
    s.ctx.state.set(FaceCounter.KEY, 4)
    assert s.auth.feed(frame(boxes=[])).state == FACE_DISABLED
    assert s.auth.face_failures == settings.FACE_MAX_FAILED


def test_fallback_failure_is_not_attributed_to_chosen_name(s):
    """Tên chọn ở chế độ dự phòng chưa chứng minh ai đứng ở cửa: nhật ký không gắn tên đó."""
    disable_face(s)
    wrong_fallback(s)
    row = next(r for r in s.ctx.logs.list() if r["event"] == "FINGERPRINT_FAILED")
    assert row["name"] is None
