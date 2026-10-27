"""Đếm phiên thất bại và khóa tạm tăng dần; lưu DB có chữ ký nên khởi động lại không reset."""
import math
import time
from collections.abc import Callable

from config import settings
from security.crypto_utils import TamperError

_FIELDS = ("failed_count", "lockout_until", "lockout_level", "last_seen_time")


class LockoutService:
    """`prefix` tách bộ đếm: "" cho mở cửa, "admin_" cho đăng nhập admin.

    admin_after_last=False (admin): sai `max_failed` lần → khóa tăng dần, bộ đếm về 0.
    admin_after_last=True (cửa): bộ đếm KHÔNG về 0 khi hết khóa, nên sau mỗi lần hết khóa chỉ còn
    1 lần thử; hết các mức LOCKOUT_STEPS thì chỉ admin mở được
    (tổng max_failed + len(LOCKOUT_STEPS) lần sai, hiện 3 + 1 + 1 + 1 = 6).
    """

    def __init__(self, settings_repo, logger, prefix: str = "",
                 clock: Callable[[], float] = time.time,
                 max_failed: int = settings.MAX_FAILED, admin_after_last: bool = False) -> None:
        self._settings = settings_repo
        self._logger = logger
        self._prefix = prefix
        self._clock = clock  # giờ thực (time.time) vì phải giữ qua các lần khởi động lại
        self.max_failed = max_failed
        self._admin_after_last = admin_after_last

    @staticmethod
    def install(settings_repo, prefix: str = "", now: float | None = None) -> None:
        """Ghi trạng thái ban đầu lúc cài đặt; sau đó thiếu khóa nào cũng bị coi là can thiệp."""
        LockoutService(settings_repo, None, prefix)._save(0, 0.0, 0, now)

    def _load(self) -> tuple[int, float, int, float]:
        count, until, level, last = (self._settings.get(self._prefix + f) for f in _FIELDS)
        return int(count), float(until), int(level), float(last)

    def _save(self, count: int, until: float, level: int, now: float | None = None) -> None:
        """Ghi cả 4 giá trị trong một transaction: crash giữa chừng không để lại trạng thái lẫn lộn."""
        now = self._clock() if now is None else now
        self._settings.set_many({self._prefix + f: v for f, v in zip(_FIELDS, (count, until, level, now))})

    def _punish(self, event: str, now: float) -> int:
        """Bị can thiệp (sai chữ ký, lùi đồng hồ): áp mức khóa cao nhất và ký lại trạng thái."""
        self._logger.log(event)
        self._save(0, now + settings.LOCKOUT_STEPS[-1], len(settings.LOCKOUT_STEPS), now)
        return settings.LOCKOUT_STEPS[-1]

    def admin_only(self) -> bool:
        """Đã hết mọi mức khóa có thời hạn: chỉ admin gỡ được."""
        try:
            return math.isinf(self._load()[1])
        except (TamperError, ValueError):
            return False  # remaining() sẽ xử lý dữ liệu bị sửa

    def remaining(self) -> int:
        """Số giây còn bị khóa tạm (0 = không khóa)."""
        now = self._clock()
        try:
            count, until, level, last = self._load()
        except (TamperError, ValueError):
            return self._punish("TAMPER_DETECTED", now)
        if math.isinf(until):
            return 0  # chỉ admin mở; xem admin_only()
        if now + settings.CLOCK_TOLERANCE_SECONDS < last:
            # Đồng hồ bị lùi. Dời mốc theo giờ hiện tại để mọi thứ luôn có giới hạn trên
            # (đồng hồ từng chạy nhanh rồi được chỉnh lại thì không bị khóa vĩnh viễn).
            if until > last:  # đang khóa: giữ nguyên thời gian khóa còn lại
                left = until - last
                self._logger.log("CLOCK_TAMPER")
                self._save(count, now + left, level, now)
                return math.ceil(left)
            return self._punish("CLOCK_TAMPER", now)
        return max(0, math.ceil(until - now))

    def register_failure(self) -> bool:
        """Ghi một phiên thất bại; trả True nếu vừa bị khóa tạm."""
        now = self._clock()
        try:
            count, until, level, _ = self._load()
        except (TamperError, ValueError):
            self._punish("TAMPER_DETECTED", now)
            return True
        count += 1
        if count < self.max_failed:
            self._save(count, until, level, now)
            return False
        if not self._admin_after_last:
            step = settings.LOCKOUT_STEPS[min(level, len(settings.LOCKOUT_STEPS) - 1)]
            self._save(0, now + step, level + 1, now)
            self._logger.log("LOCKED_OUT")
            return True
        if level >= len(settings.LOCKOUT_STEPS):
            self._save(count, math.inf, level + 1, now)
            self._logger.log("ADMIN_ONLY_LOCKOUT")
        else:
            self._save(count, now + settings.LOCKOUT_STEPS[level], level + 1, now)
            self._logger.log(f"LOCKED_OUT_{level + 1}")
        return True

    def register_success(self) -> None:
        self._save(0, 0.0, 0)

    def failed_count(self) -> int:
        """Số lần sai trong lượt hiện tại (để hiển thị); dữ liệu hỏng thì coi như đã hết lượt."""
        try:
            return self._load()[0]
        except (TamperError, ValueError):
            return self.max_failed

    def clear(self) -> None:
        """Admin gỡ khóa tạm thủ công (chống việc người lạ cố tình làm sai để khóa chủ nhà)."""
        self.register_success()
        self._logger.log("ADMIN_CLEAR_LOCKOUT")


class FaceCounter:
    """Số lần sai khuôn mặt; đủ FACE_MAX_FAILED thì tắt Face ID tới khi mở cửa thành công.

    Dữ liệu bị sửa hoặc bị xóa → coi như đã đủ: cửa không mở bằng Face ID nữa mà chỉ còn đường
    vân tay (PIN), tức 1 yếu tố – giống khi người lạ sai mặt 3 lần (hạn chế đã ghi trong README).
    Chỉ ghi TAMPER_DETECTED một lần (count() được gọi mỗi frame).
    """
    KEY = "face_failed"

    def __init__(self, settings_repo, logger) -> None:
        self._settings = settings_repo
        self._logger = logger
        self._tamper_logged = False

    @staticmethod
    def install(settings_repo) -> None:
        settings_repo.set(FaceCounter.KEY, 0)

    def count(self) -> int:
        try:
            return int(self._settings.get(self.KEY))
        except (TamperError, ValueError):
            if not self._tamper_logged:
                self._logger.log("TAMPER_DETECTED")
                self._tamper_logged = True
            return settings.FACE_MAX_FAILED

    def disabled(self) -> bool:
        return self.count() >= settings.FACE_MAX_FAILED

    def register_failure(self) -> None:
        count = self.count() + 1
        self._settings.set(self.KEY, count)
        if count == settings.FACE_MAX_FAILED:
            self._logger.log("FACE_DISABLED")

    def reset(self) -> None:
        self._settings.set(self.KEY, 0)
