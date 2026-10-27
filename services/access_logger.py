"""Ghi nhật ký sự kiện; ảnh người lạ được mã hóa trước khi lưu."""
import uuid

import cv2
import numpy as np

from security.crypto_utils import Crypto


class AccessLogger:
    def __init__(self, log_repo, crypto: Crypto) -> None:
        self._repo = log_repo
        self._crypto = crypto

    def log(self, event: str, user_id: int | None = None, distance: float | None = None,
            frame_bgr: np.ndarray | None = None) -> None:
        snapshot = None
        if frame_bgr is not None:
            ok, jpg = cv2.imencode(".jpg", frame_bgr)
            if ok:
                self._repo.snapshot_dir.mkdir(parents=True, exist_ok=True)
                snapshot = f"{uuid.uuid4().hex}.enc"
                (self._repo.snapshot_dir / snapshot).write_bytes(self._crypto.encrypt(jpg.tobytes()))
        if distance is not None and not np.isfinite(distance):
            distance = None
        self._repo.add(event, user_id, distance, snapshot)

    def load_snapshot(self, name: str) -> np.ndarray:
        data = self._crypto.decrypt((self._repo.snapshot_dir / name).read_bytes())
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
