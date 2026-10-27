"""Dữ liệu giả cho test: khuôn mặt 3D tổng hợp, đồng hồ giả, DB tạm."""
import math
from types import SimpleNamespace

import numpy as np
import pytest
from cryptography.fernet import Fernet

from config import settings
from security.crypto_utils import Crypto
from services.access_logger import AccessLogger
from services.lockout_service import FaceCounter, LockoutService
from storage.database import Database
from storage.log_repository import LogRepository
from storage.settings_repository import SettingsRepository
from storage.user_repository import UserRepository


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _face_points(eye_open: float, mouth_gap: float) -> dict[str, list[tuple[float, float, float]]]:
    """Khuôn mặt 3D thô (x, y, z), z dương hướng về camera; thứ tự điểm giống face_recognition."""
    chin = []
    for i in range(17):
        x = -60 + 120 * i / 16
        chin.append((x, 20 + 50 * math.sqrt(max(0.0, 1 - (x / 60) ** 2)), -40 * (x / 60) ** 2))

    def eye(cx):
        h = 4 * eye_open
        return [(cx - 12, -20, -5), (cx - 4, -20 - h, -5), (cx + 4, -20 - h, -5),
                (cx + 12, -20, -5), (cx + 4, -20 + h, -5), (cx - 4, -20 + h, -5)]

    top_inner, bottom_inner = 35, 35 + mouth_gap
    top_lip = [(-25, 35, 5), (-15, 30, 8), (-5, 29, 10), (0, 30, 10), (5, 29, 10), (15, 30, 8), (25, 35, 5),
               (20, 35, 6), (8, top_inner, 8), (0, top_inner, 9), (-8, top_inner, 8), (-20, 35, 6)]
    bottom_lip = [(25, 35, 5), (15, 42, 7), (5, 45, 8), (0, 46, 8), (-5, 45, 8), (-15, 42, 7), (-25, 35, 5),
                  (-20, 35, 6), (-8, bottom_inner, 8), (0, bottom_inner, 9), (8, bottom_inner, 8), (20, 35, 6)]
    return {
        "chin": chin,
        "left_eyebrow": [(-45 + 7.5 * i, -35, -5) for i in range(5)],
        "right_eyebrow": [(15 + 7.5 * i, -35, -5) for i in range(5)],
        "nose_bridge": [(0, -25, 5), (0, -17, 12), (0, -9, 18), (0, -1, 24)],
        "nose_tip": [(-10, 12, 15), (-5, 14, 22), (0, 15, 30), (5, 14, 22), (10, 12, 15)],
        "left_eye": eye(-30),
        "right_eye": eye(30),
        "top_lip": top_lip,
        "bottom_lip": bottom_lip,
    }


def make_landmarks(yaw_deg: float = 0.0, eye_open: float = 1.0, mouth_gap: float = 0.0,
                   flat: bool = False, homography=None, pitch_deg: float = 0.0) -> dict:
    """Chiếu khuôn mặt lên ảnh. flat=True: ảnh in (z=0). homography: nghiêng tấm ảnh phẳng.

    pitch_deg > 0: ngẩng lên (mũi nhô ra nên đi lên trong ảnh).
    """
    a, p = math.radians(yaw_deg), math.radians(pitch_deg)
    out = {}
    for key, pts in _face_points(eye_open, mouth_gap).items():
        projected = []
        for x, y, z in pts:
            if flat:
                z = 0.0
            y, z = y * math.cos(p) - z * math.sin(p), y * math.sin(p) + z * math.cos(p)
            xr, zr = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
            depth = 400 - zr
            u, v = 500 * xr / depth, 500 * y / depth
            if homography is not None:
                w = homography[2][0] * u + homography[2][1] * v + homography[2][2]
                u, v = ((homography[0][0] * u + homography[0][1] * v + homography[0][2]) / w,
                        (homography[1][0] * u + homography[1][1] * v + homography[1][2]) / w)
            projected.append((u + 320, v + 240))
        out[key] = projected
    return out


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ctx(tmp_path, clock):
    crypto = Crypto(Fernet.generate_key(), b"k" * 32)
    db = Database(tmp_path / "test.db")
    state = SettingsRepository(db, crypto)
    logs = LogRepository(db, tmp_path / "snapshots")
    logger = AccessLogger(logs, crypto)
    LockoutService.install(state, "", now=clock())
    FaceCounter.install(state)
    yield SimpleNamespace(
        crypto=crypto, db=db, state=state, logs=logs, logger=logger,
        users=UserRepository(db, crypto),
        lockout=LockoutService(state, logger, "", clock),
        door=LockoutService(state, logger, "", clock, settings.LOCK_MAX_FAILED, admin_after_last=True),
        faces=FaceCounter(state, logger),
    )
    db.close()


def vector(seed: int) -> np.ndarray:
    """Vector 128 chiều ngẫu nhiên, hai seed khác nhau cách nhau khoảng 1.4."""
    v = np.random.default_rng(seed).normal(size=128)
    return v / np.linalg.norm(v)
