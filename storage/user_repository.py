"""Người dùng và vector khuôn mặt (mã hóa + chữ ký từng dòng)."""
import re
from datetime import datetime

import numpy as np

from security.crypto_utils import Crypto, InvalidToken, TamperError

NAME_PATTERN = re.compile(r"[\w .'-]{1,50}")
VECTOR_SIZE = 128


def validate_name(name: str) -> str:
    name = name.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Tên dài 1–50 ký tự, chỉ gồm chữ, số, khoảng trắng và . ' -")
    return name


class UserRepository:
    def __init__(self, db, crypto: Crypto) -> None:
        self._conn = db.conn
        self._crypto = crypto

    def _user_sig_ok(self, row) -> bool:
        return self._crypto.verify(row["signature"], "users", row["id"], row["name"],
                                   row["pin_hash"], row["is_active"], row["created_at"])

    def add_user(self, name: str, pin_hash: str, encodings: list[np.ndarray]) -> int:
        """Thêm người dùng và toàn bộ encoding trong một transaction."""
        name = validate_name(name)
        created = datetime.now().isoformat(timespec="seconds")
        with self._conn:
            uid = self._conn.execute(
                "INSERT INTO users (name, pin_hash, is_active, created_at, signature) VALUES (?, ?, 1, ?, '')",
                (name, pin_hash, created),
            ).lastrowid
            self._conn.execute("UPDATE users SET signature = ? WHERE id = ?",
                               (self._crypto.sign("users", uid, name, pin_hash, 1, created), uid))
            for vec in encodings:
                vec = np.asarray(vec, dtype=np.float64)
                if vec.shape != (VECTOR_SIZE,):
                    raise ValueError("Vector khuôn mặt phải có 128 phần tử.")
                blob = self._crypto.encrypt(vec.tobytes())
                self._conn.execute(
                    "INSERT INTO face_encodings (user_id, encoding, signature, created_at) VALUES (?, ?, ?, ?)",
                    (uid, blob, self._crypto.sign("face_encodings", uid, blob), created),
                )
        return uid

    def name_exists(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM users WHERE name = ?", (name.strip(),)).fetchone() is not None

    def get_user(self, uid: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:
            return None
        if not self._user_sig_ok(row):
            raise TamperError(f"Chữ ký sai ở người dùng {uid}")
        return dict(row)

    def list_users(self) -> list[dict]:
        """Mỗi dòng có thêm 'valid' = chữ ký đúng và 'photos' = số ảnh khuôn mặt đã lưu."""
        rows = self._conn.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM face_encodings f WHERE f.user_id = u.id) AS photos "
            "FROM users u ORDER BY u.id"
        ).fetchall()
        return [{**dict(r), "valid": self._user_sig_ok(r)} for r in rows]

    def load_known_encodings(self) -> tuple[dict[int, list[np.ndarray]], int]:
        """Trả ({user_id: [vector]}, số bản ghi bị bỏ vì sai chữ ký / hỏng).

        Chỉ lấy người dùng có chữ ký đúng và đang hoạt động.
        """
        users = self.list_users()
        known = {u["id"]: [] for u in users if u["valid"] and u["is_active"]}
        tampered = sum(not u["valid"] for u in users)
        for row in self._conn.execute("SELECT user_id, encoding, signature FROM face_encodings"):
            uid, blob = row["user_id"], row["encoding"]
            if uid not in known:
                continue
            if not self._crypto.verify(row["signature"], "face_encodings", uid, blob):
                tampered += 1
                continue
            try:
                vec = np.frombuffer(self._crypto.decrypt(blob), dtype=np.float64)
            except InvalidToken:
                tampered += 1
                continue
            if vec.shape != (VECTOR_SIZE,):
                tampered += 1
                continue
            known[uid].append(vec)
        return {uid: encs for uid, encs in known.items() if encs}, tampered

    def delete_user(self, uid: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM users WHERE id = ?", (uid,))  # encoding xóa theo nhờ CASCADE
