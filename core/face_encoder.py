"""Biến khuôn mặt thành vector 128 chiều.

Mạng ResNet của dlib được huấn luyện bằng triplet loss: ảnh cùng một người cho
vector gần nhau, khác người cho vector xa nhau (khoảng cách Euclid).
"""
import face_recognition
import numpy as np

from core.face_types import Box


def encode_face(rgb: np.ndarray, box: Box) -> np.ndarray:
    return face_recognition.face_encodings(rgb, [box])[0].astype(np.float64)
