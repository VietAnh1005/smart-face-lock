"""Bảng app_state: hash admin, trạng thái khóa tạm. Mọi giá trị đều có chữ ký HMAC."""
from security.crypto_utils import Crypto, TamperError


class SettingsRepository:
    def __init__(self, db, crypto: Crypto) -> None:
        self._conn = db.conn
        self._crypto = crypto

    def get(self, key: str) -> str:
        """Thiếu khóa hoặc chữ ký sai đều là dấu hiệu bị can thiệp, không bao giờ trả mặc định."""
        row = self._conn.execute("SELECT value, signature FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise TamperError(f"Thiếu trạng thái '{key}'")
        if not self._crypto.verify(row["signature"], "app_state", key, row["value"]):
            raise TamperError(f"Chữ ký sai ở trạng thái '{key}'")
        return row["value"]

    def set(self, key: str, value) -> None:
        self.set_many({key: value})

    def set_many(self, items: dict) -> None:
        """Ghi nhiều giá trị trong một transaction."""
        rows = [(key, str(value), self._crypto.sign("app_state", key, str(value))) for key, value in items.items()]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO app_state (key, value, signature) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, signature = excluded.signature",
                rows,
            )
