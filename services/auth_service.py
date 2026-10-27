"""Máy trạng thái khóa cửa.

LOCKED ──thấy mặt──▶ VERIFYING ──đúng mặt + vân tay──▶ UNLOCKED ──5 giây──▶ LOCKED
  sai mặt 3 lần    → FACE_DISABLED (chỉ nhận vân tay / PIN)
  sai vân tay 3 lần → LOCKED_OUT (30 giây → 2 phút → 10 phút → chỉ admin)
FACE_DISABLED và LOCKED_OUT suy ra từ hai bộ đếm lưu trong DB, nên tắt/mở lại vẫn giữ.

Bên trong VERIFYING (giao diện chỉ thấy "Khuôn mặt" và "Vân tay"):
  LIVENESS    thử thách ngẫu nhiên cho MỌI khuôn mặt, trước khi so khớp → không lộ ảnh đã khớp chưa.
  MATCH       nhìn thẳng; danh tính quyết định từ mọi vector thu được từ đầu phiên.
  FINGERPRINT yếu tố thứ hai (PIN giữ chỗ cho vân tay), phải đúng người của khuôn mặt.
"""
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from config import settings
from core.face_matcher import distance_to, find_best_match
from core.liveness_checker import FAILED, PASSED, LivenessChecker
from security.crypto_utils import TamperError
from security.pin_auth import AuthFactor
from services.frame_result import FrameResult

LOCKED, VERIFYING, UNLOCKED, FACE_DISABLED, LOCKED_OUT = (
    "LOCKED", "VERIFYING", "UNLOCKED", "FACE_DISABLED", "LOCKED_OUT")
FACE_FAIL = "Không xác thực được khuôn mặt"   # chung cho không khớp / giả mạo / hết giờ
FALLBACK_FAIL = "Thông tin không đúng"         # chế độ dự phòng: sai PIN hoặc tên
WAITING = "Mời đứng trước camera"
# Bước con bên trong VERIFYING
LIVENESS, MATCH, FINGERPRINT = "LIVENESS", "MATCH", "FINGERPRINT"
FACE_PHASES = (LIVENESS, MATCH)


@dataclass
class AuthView:
    """Những gì giao diện cần hiển thị."""
    state: str
    message: str
    step: str | None = None   # VERIFYING: "FACE" hoặc "FINGERPRINT"
    user: str | None = None   # chỉ có từ bước vân tay trở đi
    tone: str = ""            # "ok" / "bad": đang hiện kết quả


class AuthService:
    def __init__(self, user_repo, lockout, face_counter, factor: AuthFactor,
                 logger, lock, clock: Callable[[], float] = time.monotonic,
                 rng=secrets.SystemRandom()) -> None:
        self._users = user_repo
        self._lockout = lockout
        self._faces = face_counter
        self._factor = factor
        self._logger = logger
        self._lock = lock
        self._clock = clock
        self._rng = rng
        self._tamper_logged = False
        self._need_clear = False
        self._hold_until = 0.0
        self._names: dict[int, str] = {}
        self._end_session()
        self._view = AuthView(LOCKED, WAITING)

    # ---------- cho giao diện ----------

    @property
    def state(self) -> str:
        return self._view.state

    @property
    def view(self) -> AuthView:
        return self._view

    @property
    def admin_only(self) -> bool:
        return self._lockout.admin_only()

    @property
    def face_failures(self) -> int:
        return min(self._faces.count(), settings.FACE_MAX_FAILED)  # bộ đếm có thể vượt ngưỡng, hiển thị tối đa FACE_MAX_FAILED

    @property
    def lock_failures(self) -> int:
        return min(self._lockout.failed_count(), self._lockout.max_failed)

    def user_names(self) -> dict[int, str]:
        return {u["id"]: u["name"] for u in self._users.list_users() if u["valid"]}

    def challenge(self) -> tuple[str, int, int] | None:
        """(hướng dẫn, bước hiện tại, tổng số bước) khi đang làm thử thách."""
        if self._phase != LIVENESS:
            return None
        return self._liveness.instruction, self._liveness.step_number, len(self._liveness.steps)

    def countdown(self) -> tuple[float, float | None] | None:
        """(số giây còn lại, tổng) của bước có giới hạn thời gian; tổng None = chỉ hiện số giây."""
        if self._phase == LIVENESS:
            return self._liveness.seconds_left(), settings.CHALLENGE_TIMEOUT
        if self._phase == FINGERPRINT:
            left = settings.PIN_TIMEOUT - (self._clock() - self._fp_started)
            return max(0.0, left), settings.PIN_TIMEOUT
        if self._view.state == UNLOCKED:
            return self._lock.seconds_open(), settings.UNLOCK_SECONDS
        if self._view.state == LOCKED_OUT and not self._lockout.admin_only():
            return float(self._lockout.remaining()), None
        return None

    # ---------- trạng thái nền ----------

    def _end_session(self) -> None:
        self._phase: str | None = None
        self._liveness: LivenessChecker | None = None
        self._encodings: list[tuple[int, object]] = []
        self._face_uid: int | None = None
        self._last_frame = None
        # Mốc thời gian / số thứ tự frame của phiên, khai báo hết ở đây để đọc một chỗ là biết đủ:
        self._known: dict = {}
        self._session_start = self._last_face = self._match_start = self._fp_started = 0.0
        self._session_seq = self._verify_seq = 0

    def _base_view(self, message: str | None = None, tone: str = "") -> AuthView:
        """Trạng thái khi không có phiên, suy ra từ hai bộ đếm (đã lưu, có chữ ký)."""
        if self._lockout.admin_only():
            return AuthView(LOCKED_OUT, message or "Sai quá nhiều lần. Liên hệ quản trị viên", tone=tone)
        wait = self._lockout.remaining()
        if wait:
            return AuthView(LOCKED_OUT, message or f"Tạm khóa do sai nhiều lần. Thử lại sau {wait} giây",
                            tone=tone)
        if self._faces.disabled():
            return AuthView(FACE_DISABLED, message or "Face ID tạm tắt. Mở bằng vân tay (PIN)",
                            tone=tone)
        return AuthView(LOCKED, message or WAITING, tone=tone)

    def _hold(self, view: AuthView) -> AuthView:
        """Kết thúc phiên và giữ kết quả trên màn hình RESULT_HOLD_SECONDS."""
        self._end_session()
        self._hold_until = self._clock() + settings.RESULT_HOLD_SECONDS
        self._view = view
        return view

    # ---------- xử lý từng frame ----------

    def feed(self, r: FrameResult) -> AuthView:
        now = self._clock()
        if self._hold_until:
            if now < self._hold_until:
                return self._view
            self._hold_until = 0.0
            self._need_clear = True  # chờ người vừa xong rời đi rồi mới mở phiên mới
        if self._phase is None:
            return self._idle(r, now)
        if self._phase == FINGERPRINT:
            if now - self._fp_started > settings.PIN_TIMEOUT:
                self._end_session()  # bỏ đi ở bước vân tay: không phải đoán sai, không tính
                self._view = self._base_view()
            return self._view
        return self._face_phase(r, now)

    def _idle(self, r: FrameResult, now: float) -> AuthView:
        self._view = self._base_view()
        if self._need_clear:
            if r.boxes:
                return self._view
            self._need_clear = False
        if self._view.state != LOCKED or not r.boxes:
            return self._view
        known, tampered = self._users.load_known_encodings()
        if tampered and not self._tamper_logged:
            self._logger.log("TAMPER_DETECTED")
            self._tamper_logged = True
        if not known:
            self._view = AuthView(LOCKED, "Chưa có người dùng nào được đăng ký")
            return self._view
        self._known = known
        self._names = self.user_names()
        self._phase = LIVENESS
        self._liveness = LivenessChecker(self._clock, self._rng)
        self._session_start = self._last_face = now
        self._session_seq = r.seq
        return self._face_phase(r, now)

    def _face_phase(self, r: FrameResult, now: float) -> AuthView:
        if r.encoding is not None and r.encoding_quality and r.encoding_seq >= self._session_seq:
            self._encodings.append((r.encoding_seq, r.encoding))
        if not r.boxes:
            if now - self._last_face <= settings.FACE_LOST_SECONDS:
                return self._view
            return self._abandon()
        self._last_face, self._last_frame = now, r.frame
        if self._phase == LIVENESS:
            status = self._liveness.update(r.landmarks)
            if status == FAILED:
                return self._fail_face("SPOOF_DETECTED" if self._liveness.spoof else "FACE_TIMEOUT")
            if status == PASSED:
                self._phase, self._match_start, self._verify_seq = MATCH, now, r.seq + 1
                self._view = AuthView(VERIFYING, "Nhìn thẳng vào camera", "FACE")
            else:
                self._view = AuthView(VERIFYING, self._liveness.prompt, "FACE")
            return self._view
        uid = self._session_identity()
        if uid is not None:
            self._face_uid, self._phase, self._fp_started = uid, FINGERPRINT, now
            self._view = AuthView(VERIFYING, "Đặt vân tay (nhập PIN 6 số)", "FINGERPRINT", self._names.get(uid))
            return self._view
        if now - self._match_start > settings.FACE_MATCH_TIMEOUT:
            # Vẫn tính sai khi không có vector dùng được (chặn cố làm mờ mặt), nhưng ghi đúng lý do cho admin.
            during = sum(seq < self._verify_seq for seq, _ in self._encodings)
            fresh = len(self._encodings) - during
            usable = (len(self._encodings) >= settings.REQUIRED_MATCH_FRAMES and fresh > 0
                      and during >= settings.LIVENESS_MIN_VECTORS)  # cùng điều kiện với _session_identity
            return self._fail_face("FACE_MISMATCH" if usable else "FACE_LOW_QUALITY")
        return self._view

    def _session_identity(self) -> int | None:
        """Người khớp, nếu ≥ SESSION_MATCH_RATIO vector CẢ PHIÊN đều dưới MATCH_THRESHOLD với người đó.

        Tính từ đầu phiên, không dùng cửa sổ trượt: vector mặt thật của kẻ phá lúc làm thử thách
        vẫn kéo tỉ lệ xuống dù sau đó giơ ảnh chủ nhà; FACE_MATCH_TIMEOUT giới hạn số vector ảnh
        có thể thêm vào để "pha loãng". Người được chọn lấy từ vector nhìn thẳng mới nhất (có biên
        với người gần nhì, xem find_best_match).
        """
        if len(self._encodings) < settings.REQUIRED_MATCH_FRAMES:
            return None
        fresh = [enc for seq, enc in self._encodings if seq >= self._verify_seq]
        during = [enc for seq, enc in self._encodings if seq < self._verify_seq]
        # Mặt làm thử thách phải có vector đạt chất lượng và chính nó phải khớp: nếu không, kẻ phá
        # rọi đèn / làm mờ mặt thật lúc làm thử thách (vector bị loại) rồi giơ ảnh chủ nhà là qua.
        if not fresh or len(during) < settings.LIVENESS_MIN_VECTORS:
            return None
        uid, _ = find_best_match(fresh[-1], self._known)
        if uid is None:
            return None
        for group in (during, [enc for _, enc in self._encodings]):
            matched = sum(distance_to(enc, self._known[uid]) < settings.MATCH_THRESHOLD for enc in group)
            if matched < settings.SESSION_MATCH_RATIO * len(group):
                return None
        return uid

    def _abandon(self) -> AuthView:
        """Mặt rời đi trước khi có kết quả: người đi ngang thì bỏ qua, đã đứng lâu thì tính sai.

        Không tính thì kẻ phá thử cách vượt chống giả mạo vài giây rồi che camera để làm lại miễn phí.
        """
        if self._last_face - self._session_start >= settings.FACE_ABORT_SECONDS:
            return self._fail_face("FACE_ABORTED")
        self._end_session()
        self._view = self._base_view()
        return self._view

    def _fail_face(self, event: str) -> AuthView:
        # Ảnh chụp là ảnh người đứng trước cửa, không gắn vào user nào (chưa biết là ai).
        self._logger.log(event, None, None, self._last_frame)
        self._faces.register_failure()
        return self._hold(self._base_view(FACE_FAIL, "bad"))

    # ---------- yếu tố thứ hai ----------

    def submit_fingerprint(self, sample) -> AuthView:
        if self._phase != FINGERPRINT:
            return self._view
        if self._clock() - self._fp_started > settings.PIN_TIMEOUT:
            # Hạn được kiểm cả ở đây: camera treo (không có frame gọi feed) không được giữ phiên mở mãi.
            self._end_session()
            self._view = self._base_view()
            return self._view
        try:
            uid = self._factor.identify(sample, self._face_uid)
        except TamperError:
            return self._fail_lock("TAMPER_DETECTED", self._face_uid, "Dữ liệu người dùng bị can thiệp",
                                   self._last_frame)
        if uid != self._face_uid:  # vân tay của người khác trong nhà cũng là sai
            return self._fail_lock("FINGERPRINT_FAILED", self._face_uid, "Vân tay (PIN) không đúng",
                                   self._last_frame)
        return self._grant(uid)

    def submit_fallback(self, sample, claimed_user_id: int | None = None, frame=None) -> AuthView:
        """FACE_DISABLED: mở bằng vân tay (PIN của người được chọn).

        frame: ảnh camera lúc gửi, lưu kèm nhật ký khi sai (bằng chứng cho chủ nhà).
        """
        if self._phase is not None or self._clock() < self._hold_until:
            return self._view
        if self._base_view().state != FACE_DISABLED:
            return self._view
        try:
            uid = self._factor.identify(sample, claimed_user_id)
        except TamperError:
            return self._fail_lock("TAMPER_DETECTED", None, FALLBACK_FAIL, frame)
        if uid is not None:
            return self._grant(uid)
        # Tên được chọn chưa chứng minh ai đứng ở cửa: không gắn lần sai vào người đó (ảnh chụp cho biết là ai).
        return self._fail_lock("FINGERPRINT_FAILED", None, FALLBACK_FAIL, frame)

    def _fail_lock(self, event: str, uid: int | None, message: str, frame=None) -> AuthView:
        self._logger.log(event, uid, None, frame)
        self._lockout.register_failure()
        return self._hold(self._base_view(message, "bad"))

    def _grant(self, uid: int) -> AuthView:
        self._lockout.register_success()
        self._faces.reset()
        self._lock.unlock(settings.UNLOCK_SECONDS)
        self._logger.log("GRANTED", uid)
        self._logger.log("UNLOCK", uid)
        name = self._names.get(uid) or self.user_names().get(uid, "")
        return self._hold(AuthView(UNLOCKED, f"Xin chào {name}! Cửa đã mở", user=name, tone="ok"))

    def abort(self) -> None:
        """Hủy phiên từ bên ngoài (nút bắt đầu lại, mở Admin, lỗi camera).

        Ở bước khuôn mặt, đã đứng ≥ FACE_ABORT_SECONDS thì vẫn tính sai (như khi che camera).
        """
        if self._phase in FACE_PHASES and self._last_face - self._session_start >= settings.FACE_ABORT_SECONDS:
            self._fail_face("FACE_ABORTED")  # giữ câu "bị từ chối" trên màn hình để người dùng biết
            return
        if self._hold_until:
            return  # đang hiện kết quả: không xóa, và vẫn chờ người vừa xong rời đi
        self._end_session()
        self._view = self._base_view()
