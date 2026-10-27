"""Đánh giá chất lượng ảnh: độ nét và độ sáng."""
import cv2
import numpy as np

from config import settings


def sharpness(gray: np.ndarray) -> float:
    """Phương sai của Laplacian: ảnh mờ ít cạnh nên giá trị nhỏ."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def brightness(gray: np.ndarray) -> float:
    return float(gray.mean())


def is_sharp(gray: np.ndarray) -> bool:
    return gray.size > 0 and sharpness(gray) >= settings.MIN_SHARPNESS


def brightness_ok(gray: np.ndarray) -> bool:
    return gray.size > 0 and settings.MIN_BRIGHTNESS <= brightness(gray) <= settings.MAX_BRIGHTNESS
