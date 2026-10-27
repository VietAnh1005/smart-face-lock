"""Mật khẩu admin (bcrypt) và phiên đăng nhập có hạn."""
import time
from collections.abc import Callable

import bcrypt

from config import settings
from security.crypto_utils import TamperError


def hash_password(password: str) -> str:
    data = password.encode()
    if len(password) < 8 or len(data) > 72:  # bcrypt chỉ dùng 72 byte đầu
        raise ValueError("Mật khẩu admin phải dài 8–72 ký tự.")
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode()


class AdminAuth:
    """Phiên hết hạn sau ADMIN_IDLE_SECONDS không thao tác, tối đa ADMIN_MAX_SECONDS."""

    def __init__(self, settings_repo, lockout, logger,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._settings = settings_repo
        self._lockout = lockout   # bộ đếm sai riêng cho admin
        self._logger = logger
        self._clock = clock
        self._login_at: float | None = None
        self._last_activity = 0.0

    def login(self, password: str) -> tuple[bool, str]:
        wait = self._lockout.remaining()
        if wait:
            return False, f"Đăng nhập admin đang bị khóa tạm, thử lại sau {wait} giây."
        try:
            admin_hash = self._settings.get("admin_hash")
        except TamperError:
            self._logger.log("TAMPER_DETECTED")
            return False, "Dữ liệu admin bị can thiệp. Chạy `python main.py --reset` để cài lại."
        data = password.encode()
        if len(data) <= 72 and bcrypt.checkpw(data, admin_hash.encode()):
            self._lockout.register_success()
            self._login_at = self._last_activity = self._clock()
            self._logger.log("ADMIN_LOGIN")
            return True, ""
        self._logger.log("ADMIN_LOGIN_FAILED")
        if self._lockout.register_failure():
            return False, f"Sai mật khẩu quá nhiều lần. Thử lại sau {self._lockout.remaining()} giây."
        left = settings.MAX_FAILED - self._lockout.failed_count()
        return False, f"Sai mật khẩu. Còn {left} lần thử."

    def seconds_left(self) -> int:
        """Số giây còn lại của phiên admin (phiên hết khi chạm hạn không thao tác hoặc hạn tối đa)."""
        if not self.is_active():
            return 0
        now = self._clock()
        return int(min(settings.ADMIN_IDLE_SECONDS - (now - self._last_activity),
                       settings.ADMIN_MAX_SECONDS - (now - self._login_at)))

    def is_active(self) -> bool:
        if self._login_at is None:
            return False
        now = self._clock()
        if (now - self._last_activity > settings.ADMIN_IDLE_SECONDS
                or now - self._login_at > settings.ADMIN_MAX_SECONDS):
            self.logout()
            return False
        return True

    def touch(self) -> None:
        """Gọi khi admin thao tác để gia hạn phiên."""
        if self.is_active():
            self._last_activity = self._clock()

    def logout(self) -> None:
        self._login_at = None
