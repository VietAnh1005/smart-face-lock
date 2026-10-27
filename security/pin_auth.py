"""Yếu tố thứ hai: PIN 6 số (sẽ thay bằng vân tay). Chỉ lưu hash bcrypt."""
import re
from typing import Protocol

import bcrypt


def hash_pin(pin: str) -> str:
    if not re.fullmatch(r"\d{6}", pin):
        raise ValueError("PIN phải gồm đúng 6 chữ số.")
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def check_pin(pin: str, pin_hash: str) -> bool:
    if not re.fullmatch(r"\d{6}", pin):
        return False
    return bcrypt.checkpw(pin.encode(), pin_hash.encode())


class AuthFactor(Protocol):
    """Mọi yếu tố xác thực thứ hai (PIN hôm nay, vân tay sau này) phải có phương thức này.

    sample: dữ liệu người dùng đưa vào (chuỗi PIN, hoặc mẫu từ cảm biến vân tay).
    claimed_user_id: người đã biết trước (từ khuôn mặt hoặc bước chọn tên); vân tay thật có thể
    bỏ qua và tự so 1:N. Trả user_id nếu khớp, None nếu không.
    """

    def identify(self, sample, claimed_user_id: int | None) -> int | None: ...


class PinFactor:
    """PIN giữ chỗ cho vân tay: so 1:1 nên BẮT BUỘC biết trước người (so 1:N cho kẻ đoán N cơ hội)."""

    def __init__(self, user_repo) -> None:
        self._users = user_repo

    def identify(self, sample, claimed_user_id: int | None) -> int | None:
        if claimed_user_id is None:
            return None
        user = self._users.get_user(claimed_user_id)  # TamperError: để máy trạng thái xử lý
        return claimed_user_id if user is not None and check_pin(sample, user["pin_hash"]) else None
