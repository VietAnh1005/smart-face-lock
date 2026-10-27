"""Mã hóa (Fernet) và chữ ký chống sửa dữ liệu (HMAC-SHA256)."""
import hashlib
import hmac
import struct

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401  (InvalidToken dùng ở nơi khác)


class TamperError(Exception):
    """Dữ liệu bị sửa/xóa trái phép: chữ ký sai hoặc thiếu bản ghi bắt buộc."""


def _pack(fields: tuple) -> bytes:
    """Ghép các trường kèm độ dài 4 byte phía trước để ("ab","c") khác ("a","bc")."""
    out = bytearray()
    for field in fields:
        data = bytes(field) if isinstance(field, (bytes, bytearray)) else str(field).encode()
        out += struct.pack(">I", len(data)) + data
    return bytes(out)


class Crypto:
    def __init__(self, fernet_key: bytes, hmac_key: bytes) -> None:
        self._fernet = Fernet(fernet_key)
        self._hmac_key = hmac_key

    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        """Ném InvalidToken nếu dữ liệu bị sửa hoặc sai khóa."""
        return self._fernet.decrypt(token)

    def sign(self, *fields) -> str:
        """Trường đầu tiên nên là tên bảng để chữ ký của bảng này không dùng được cho bảng khác."""
        return hmac.new(self._hmac_key, _pack(fields), hashlib.sha256).hexdigest()

    def verify(self, signature: str, *fields) -> bool:
        return hmac.compare_digest(signature or "", self.sign(*fields))
