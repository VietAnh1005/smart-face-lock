"""Tìm vị trí khuôn mặt (HOG + SVM của dlib) và 68 điểm landmark."""
import cv2
import face_recognition
import numpy as np

from config import settings
from core.face_types import Box, Landmarks


class FaceDetector:
    def __init__(self, scale: float = settings.DETECT_SCALE,
                 min_ratio: float = settings.MIN_FACE_RATIO) -> None:
        self.scale = scale
        self.min_ratio = min_ratio

    def detect(self, rgb: np.ndarray) -> list[Box]:
        """Phát hiện trên ảnh thu nhỏ cho nhanh, trả box theo tọa độ ảnh gốc.

        Bỏ các mặt nhỏ hơn MIN_FACE_RATIO (người/poster ở xa phía sau).
        """
        small = cv2.resize(rgb, (0, 0), fx=self.scale, fy=self.scale)
        min_side = self.min_ratio * rgb.shape[1]
        h, w = rgb.shape[:2]
        boxes = []
        for top, right, bottom, left in face_recognition.face_locations(small):
            box = (max(0, int(top / self.scale)), min(w, int(right / self.scale)),
                   min(h, int(bottom / self.scale)), max(0, int(left / self.scale)))
            if box[1] - box[3] >= min_side:
                boxes.append(box)
        return boxes

    @staticmethod
    def landmarks(rgb: np.ndarray, box: Box) -> Landmarks:
        """68 điểm landmark, nhóm theo bộ phận: chin, left_eye, nose_tip, top_lip..."""
        return face_recognition.face_landmarks(rgb, [box])[0]
