"""Nhật ký truy cập và ảnh người lạ (file .enc trong data/snapshots)."""
import csv
from datetime import datetime, timedelta
from pathlib import Path


class LogRepository:
    def __init__(self, db, snapshot_dir: Path) -> None:
        self._conn = db.conn
        self.snapshot_dir = snapshot_dir

    def add(self, event: str, user_id: int | None = None, distance: float | None = None,
            snapshot: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO access_logs (user_id, timestamp, event, distance, snapshot) VALUES (?, ?, ?, ?, ?)",
                (user_id, datetime.now().isoformat(timespec="seconds"), event, distance, snapshot),
            )

    def list(self, limit: int = 500) -> list[dict]:
        rows = self._conn.execute(
            "SELECT l.id, l.timestamp, l.event, u.name, l.distance, l.snapshot "
            "FROM access_logs l LEFT JOIN users u ON u.id = l.user_id ORDER BY l.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def export_csv(self, path: Path) -> None:
        rows = self.list(limit=-1)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig để Excel đọc đúng tiếng Việt
            writer = csv.DictWriter(f, fieldnames=["id", "timestamp", "event", "name", "distance", "snapshot"])
            writer.writeheader()
            writer.writerows(rows)

    def _delete_snapshots(self, where: str, params: tuple) -> None:
        for (name,) in self._conn.execute(f"SELECT snapshot FROM access_logs WHERE snapshot IS NOT NULL AND {where}",
                                          params).fetchall():
            (self.snapshot_dir / Path(name).name).unlink(missing_ok=True)

    def delete_snapshots_of_user(self, user_id: int) -> None:
        """Xóa ảnh của một người (khi xóa người dùng); dòng log vẫn giữ."""
        self._delete_snapshots("user_id = ?", (user_id,))
        with self._conn:
            self._conn.execute("UPDATE access_logs SET snapshot = NULL WHERE user_id = ?", (user_id,))

    def purge_older_than(self, days: int) -> None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        self._delete_snapshots("timestamp < ?", (cutoff,))
        with self._conn:
            self._conn.execute("DELETE FROM access_logs WHERE timestamp < ?", (cutoff,))
