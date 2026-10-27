"""Khóa mô phỏng. Fail-secure: mặc định khóa, tự khóa lại khi hết giờ.

Dùng hạn chót thay cho timer/thread nên app treo hay tắt thì khóa vẫn được coi là đóng.
ArduinoLock (phần mở rộng) cần đủ 4 method: lock(), unlock(seconds) – PHẢI tự khóa lại sau `seconds`
(hẹn giờ trong firmware), is_locked(), seconds_open() – tính theo hạn chót của lần unlock (đồng hồ phần mềm),
không đọc relay. Ứng dụng dựa vào seconds_open() để gửi lock() khi hết giờ (ui/app.py: relock_if_expired).
"""
import time
from collections.abc import Callable


class SimulatedLock:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._open_until = 0.0

    def unlock(self, seconds: float) -> None:
        self._open_until = self._clock() + seconds

    def lock(self) -> None:
        self._open_until = 0.0

    def is_locked(self) -> bool:
        return self._clock() >= self._open_until

    def seconds_open(self) -> float:
        """Số giây cửa còn mở trước khi tự khóa lại (0 nếu đang khóa)."""
        return max(0.0, self._open_until - self._clock())
