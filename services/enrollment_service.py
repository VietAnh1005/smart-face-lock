"""Đăng ký và xóa người dùng (bắt buộc phiên admin)."""
import secrets
import statistics
import time
from collections.abc import Callable

import numpy as np

from config import settings
from core.face_matcher import distance_to
from core.landmark_utils import head_pitch, head_yaw
from core.liveness_checker import FAILED, PASSED, LivenessChecker
from security.pin_auth import hash_pin
from services.frame_result import FrameResult
from storage.user_repository import validate_name

POSES = (
    ("Nhìn thẳng vào camera", "front"),
    ("Hơi quay đầu sang trái", "left"),
    ("Hơi quay đầu sang phải", "right"),
    ("Hơi ngẩng lên", "up"),
    ("Hơi cúi xuống", "down"),
)  # tư thế "front" luôn đứng đầu mỗi vòng nên up/down luôn có mốc nhìn thẳng
FRONT_PITCH_SAMPLES = 15      # số frame nhìn thẳng gần nhất dùng làm mốc pitch
FRONT_PITCH_MIN_SAMPLES = 5   # số frame nhìn thẳng tối thiểu trước khi chụp ảnh "nhìn thẳng"
RUNNING, READY, DONE, FAILED_ENROLL = "RUNNING", "READY", "DONE", "FAILED"


class EnrollmentError(Exception):
    """Lỗi người dùng cần sửa (tên trùng, PIN sai định dạng, hết phiên admin...)."""


class EnrollmentService:
    def __init__(self, user_repo, log_repo, admin_auth, logger,
                 clock: Callable[[], float] = time.monotonic, rng=secrets.SystemRandom()) -> None:
        self._rng = rng
        self._users = user_repo
        self._logs = log_repo
        self._admin = admin_auth
        self._logger = logger
        self._clock = clock
        self.active = False
        self.liveness_passed = False
        self._captures: list[np.ndarray] = []

    @property
    def captured(self) -> int:
        return len(self._captures)

    @property
    def ready(self) -> bool:
        """Đủ ảnh và đã qua kiểm tra người thật: được phép bấm Lưu."""
        return self.active and self.liveness_passed and self.captured >= settings.ENROLL_CAPTURES

    def _require_admin(self, touch: bool = True) -> None:
        """touch=False cho frame camera: phiên chỉ được gia hạn khi admin thật sự thao tác."""
        if not self._admin.is_active():
            self.active = False
            raise EnrollmentError("Phiên admin đã hết hạn, hãy đăng nhập lại.")
        if touch:
            self._admin.touch()

    def start(self, name: str, pin: str, pin_again: str) -> None:
        self._require_admin()
        try:
            name = validate_name(name)
            if self._users.name_exists(name):
                raise ValueError(f"Tên '{name}' đã tồn tại.")
            if pin != pin_again:
                raise ValueError("Hai lần nhập PIN không khớp.")
            self._pin_hash = hash_pin(pin)
        except ValueError as exc:
            raise EnrollmentError(str(exc)) from exc
        self._name = name
        self._captures = []
        self._front_pitches: list[float] = []
        self._capture_seq = 0
        self._liveness = LivenessChecker(self._clock, self._rng)
        self.liveness_passed = False
        self._last_capture = 0.0
        self.active = True

    def feed(self, r: FrameResult) -> tuple[str, str, float]:
        """Trả (trạng thái, thông báo, tiến độ 0..1)."""
        self._require_admin(touch=False)
        progress = len(self._captures) / settings.ENROLL_CAPTURES
        if self.ready:
            return READY, "Đã chụp đủ ảnh. Bấm Lưu để hoàn tất", 1.0
        if len(r.boxes) != 1:
            return RUNNING, "Cần đúng một khuôn mặt trong khung hình", progress
        if self._liveness is not None:
            status = self._liveness.update(r.landmarks)
            if status == FAILED:
                return self._stop(f"Kiểm tra người thật thất bại: {self._liveness.reason}")
            if status != PASSED:
                return RUNNING, self._liveness.prompt, progress
            self._liveness = None
            self.liveness_passed = True
            self._capture_seq = r.seq + 1  # không lưu vector của frame chụp lúc còn làm thử thách
        hint, pose = POSES[len(self._captures) % len(POSES)]
        if pose == "front" and abs(settings.YAW_SIGN * head_yaw(r.landmarks)) < settings.FRONTAL_YAW:
            # Mốc nhìn thẳng = trung vị nhiều frame: pitch 1 frame dao động ~0.06, ngang cỡ ngưỡng ngẩng/cúi.
            self._front_pitches = (self._front_pitches + [head_pitch(r.landmarks)])[-FRONT_PITCH_SAMPLES:]
        # Vector thuộc một frame trước đó: tư thế và độ nét phải xét trên CHÍNH frame của vector.
        if r.encoding is None or r.encoding_landmarks is None or r.encoding_seq < self._capture_seq:
            return RUNNING, hint, progress
        if not r.encoding_quality:
            return RUNNING, f"{hint} — ảnh mờ hoặc thiếu sáng", progress
        yaw = settings.YAW_SIGN * head_yaw(r.encoding_landmarks)
        pitch = head_pitch(r.encoding_landmarks)
        front_pitch = statistics.median(self._front_pitches) if self._front_pitches else pitch
        # Ngẩng/cúi chỉ tính khi đầu không quay ngang: quay đầu cũng làm pitch lệch ~0.04.
        level = abs(yaw) < settings.ENROLL_PITCH_MAX_YAW
        pose_ok = {
            # Chỉ chụp ảnh nhìn thẳng khi đã có đủ mẫu làm mốc pitch cho bước ngẩng/cúi phía sau.
            "front": abs(yaw) < settings.FRONTAL_YAW and len(self._front_pitches) >= FRONT_PITCH_MIN_SAMPLES,
            "left": yaw > settings.ENROLL_POSE_YAW,
            "right": yaw < -settings.ENROLL_POSE_YAW,
            "up": level and pitch < front_pitch - settings.ENROLL_POSE_PITCH,
            "down": level and pitch > front_pitch + settings.ENROLL_POSE_PITCH,
        }[pose]
        now = self._clock()
        if not pose_ok or now - self._last_capture < settings.ENROLL_CAPTURE_INTERVAL:
            return RUNNING, hint, progress
        self._captures.append(r.encoding)
        self._last_capture = now
        if len(self._captures) < settings.ENROLL_CAPTURES:
            return RUNNING, hint, len(self._captures) / settings.ENROLL_CAPTURES
        return READY, "Đã chụp đủ ảnh. Bấm Lưu để hoàn tất", 1.0

    def save(self) -> tuple[str, str, float]:
        """Admin bấm Lưu: kiểm tra lần cuối rồi ghi vào DB."""
        self._require_admin()
        if not self.ready:
            raise EnrollmentError("Chưa chụp đủ ảnh hoặc chưa qua kiểm tra người thật.")
        captures = np.asarray(self._captures)
        mean = captures.mean(axis=0)
        if np.max(np.linalg.norm(captures - mean, axis=1)) > settings.MATCH_THRESHOLD:
            return self._stop("Các ảnh chụp không cùng một người, hãy làm lại.")
        known, _ = self._users.load_known_encodings()
        for encs in known.values():
            if min(distance_to(c, encs) for c in captures) < settings.MATCH_THRESHOLD:
                return self._stop("Khuôn mặt này đã được đăng ký cho người khác.")
        uid = self._users.add_user(self._name, self._pin_hash, list(captures))
        self._logger.log("ENROLL", uid)
        self.cancel()
        return DONE, f"Đã đăng ký {self._name}", 1.0

    def _stop(self, message: str) -> tuple[str, str, float]:
        self.cancel()
        return FAILED_ENROLL, message, 0.0

    def cancel(self) -> None:
        """Bỏ phiên đăng ký đang làm dở (rời màn hình, thất bại, hoặc đã lưu xong)."""
        self.active = False
        self.liveness_passed = False
        self._captures = []

    def delete_user(self, uid: int) -> None:
        self._require_admin()
        self._logs.delete_snapshots_of_user(uid)
        self._users.delete_user(uid)
        self._logger.log("DELETE_USER")
