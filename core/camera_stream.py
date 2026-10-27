"""Mở và đọc webcam."""
import sys

import cv2
import numpy as np

from config import settings


class CameraError(RuntimeError):
    """Không mở được hoặc mất tín hiệu camera."""


class CameraStream:
    """Bọc cv2.VideoCapture, dùng được với `with`."""

    def __init__(self, index: int = settings.CAMERA_INDEX) -> None:
        self.index = index
        self._cap: cv2.VideoCapture | None = None
        self._fails = 0

    def open(self) -> None:
        # CAP_DSHOW mở nhanh và ổn định trên Windows; macOS/Linux dùng backend mặc định
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Không mở được camera {self.index}. "
                "Cam có đang bị ứng dụng khác (Zoom, Teams...) dùng không?"
            )
        self._cap = cap
        self._fails = 0

    def read_frame(self) -> np.ndarray | None:
        """Trả frame BGR, hoặc None nếu frame này lỗi; lỗi liên tiếp quá nhiều thì báo CameraError."""
        ok, frame = self._cap.read()
        if ok:
            self._fails = 0
            return frame
        self._fails += 1
        if self._fails >= settings.CAMERA_FAIL_FRAMES:
            raise CameraError("Mất tín hiệu camera (bị rút hoặc bị ứng dụng khác chiếm).")
        return None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "CameraStream":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
