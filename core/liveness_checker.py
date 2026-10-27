"""Chuỗi thử thách ngẫu nhiên chống giả mạo bằng ảnh và video."""
import secrets
import statistics
import time
from collections import deque
from collections.abc import Callable

from config import settings
from core.face_types import Landmarks
from core.landmark_utils import eye_aspect_ratio, head_yaw, mouth_aspect_ratio, planarity_residual

PROMPTS = {
    "BLINK_TWICE": "Nháy mắt 2 lần",
    "TURN_LEFT": "Quay đầu sang TRÁI của bạn",
    "TURN_RIGHT": "Quay đầu sang PHẢI của bạn",
    "OPEN_MOUTH": "Há miệng",
}
TURNS = ("TURN_LEFT", "TURN_RIGHT")
OPEN_EAR_MIN_SAMPLES = 3  # số frame mắt mở tối thiểu trước khi bắt đầu nhận nháy mắt
PENDING, PASSED, FAILED = "PENDING", "PASSED", "FAILED"


class LivenessChecker:
    """Nhận landmark từng frame, trả PENDING / PASSED / FAILED.

    Mỗi phiên chọn ngẫu nhiên LIVENESS_STEPS thử thách khác nhau (thứ tự cũng ngẫu nhiên),
    mỗi thử thách có CHALLENGE_TIMEOUT giây. Bước quay đầu chỉ đạt khi landmark cho thấy
    khuôn mặt có chiều sâu (không phải ảnh phẳng bị nghiêng).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic, rng=secrets.SystemRandom()) -> None:
        self._clock = clock
        # Luôn có một bước quay đầu: chỉ bước này kiểm tra chiều sâu 3D, nên ảnh in khoét lỗ mắt/miệng
        # không thể qua được bằng chuỗi chỉ gồm nháy mắt + há miệng.
        turn = rng.sample(TURNS, 1)[0]
        others = rng.sample([s for s in PROMPTS if s != turn], settings.LIVENESS_STEPS - 1)
        self.steps: list[str] = [turn, *others]
        rng.shuffle(self.steps)
        self._index = 0
        self._frontal: Landmarks | None = None
        self.reason = ""
        self.spoof = False
        self._open_ears: deque[float] = deque(maxlen=15)
        self._ear = 0.0
        self._start_step()

    def _start_step(self) -> None:
        self._step_started = self._clock()
        self._blinks = 0
        self._eyes_closed = False
        self._saw_flat_turn = False

    @property
    def instruction(self) -> str:
        """Hướng dẫn của thử thách hiện tại, ví dụ "Há miệng"."""
        return PROMPTS[self.steps[self._index]] if self._index < len(self.steps) else ""

    @property
    def step_number(self) -> int:
        return min(self._index + 1, len(self.steps))

    @property
    def prompt(self) -> str:
        if self._index >= len(self.steps):
            return ""
        return f"Bước {self.step_number}/{len(self.steps)}: {self.instruction}"

    def open_ear(self) -> float | None:
        """EAR lúc mắt mở của chính người này (trung vị các frame gần nhất).

        Ngưỡng nhắm/mở tính theo tỉ lệ so với mức này: mắt mỗi người mở to nhỏ khác nhau
        (đo thật: mở 0.30–0.38, nháy nhanh chỉ xuống 0.21–0.23), ngưỡng cố định bỏ sót nhiều lần nháy.
        """
        return statistics.median(self._open_ears) if len(self._open_ears) >= OPEN_EAR_MIN_SAMPLES else None

    def seconds_left(self) -> float:
        """Thời gian còn lại của thử thách hiện tại."""
        return max(0.0, settings.CHALLENGE_TIMEOUT - (self._clock() - self._step_started))

    def update(self, lm: Landmarks | None) -> str:
        if self._index >= len(self.steps):
            return PASSED
        if self._clock() - self._step_started > settings.CHALLENGE_TIMEOUT:
            self.spoof = self._saw_flat_turn
            self.reason = ("Phát hiện khuôn mặt phẳng (ảnh in / màn hình)" if self.spoof
                           else "Hết thời gian làm theo hướng dẫn")
            return FAILED
        if lm is None:
            return PENDING
        self._ear = (eye_aspect_ratio(lm["left_eye"]) + eye_aspect_ratio(lm["right_eye"])) / 2
        ref = self.open_ear()
        if ref is None or self._ear >= ref * settings.EAR_CLOSED_RATIO:
            self._open_ears.append(self._ear)  # chỉ học từ frame mắt mở
        yaw = settings.YAW_SIGN * head_yaw(lm)
        if abs(yaw) < settings.FRONTAL_YAW:
            self._frontal = lm  # mốc nhìn thẳng để so khi quay đầu
        if self._step_done(self.steps[self._index], lm, yaw):
            self._index += 1
            if self._index == len(self.steps):
                return PASSED
            self._start_step()
        return PENDING

    def _step_done(self, step: str, lm: Landmarks, yaw: float) -> bool:
        if step == "BLINK_TWICE":
            ref = self.open_ear()
            if ref is None:
                return False
            if self._ear < ref * settings.EAR_CLOSED_RATIO:
                self._eyes_closed = True
            elif self._eyes_closed and self._ear > ref * settings.EAR_OPEN_RATIO:
                self._eyes_closed = False
                self._blinks += 1
            return self._blinks >= 2
        if step == "OPEN_MOUTH":
            return mouth_aspect_ratio(lm) > settings.MOUTH_OPEN_MAR
        turned = yaw > settings.TURN_YAW if step == "TURN_LEFT" else yaw < -settings.TURN_YAW
        if not turned or self._frontal is None:
            return False
        if planarity_residual(self._frontal, lm) >= settings.MIN_3D_RESIDUAL:
            return True
        self._saw_flat_turn = True
        return False
