"""Các phép đo hình học trên 68 điểm landmark."""
import cv2
import numpy as np

from core.face_types import Landmarks


def _dist(a, b) -> float:
    return float(np.linalg.norm(np.subtract(a, b, dtype=float)))


def eye_aspect_ratio(eye: list[tuple[int, int]]) -> float:
    """EAR = (|p2-p6| + |p3-p5|) / (2|p1-p4|); mắt nhắm thì EAR giảm mạnh."""
    p = eye
    width = _dist(p[0], p[3])
    return 0.0 if width == 0 else (_dist(p[1], p[5]) + _dist(p[2], p[4])) / (2 * width)


def mouth_aspect_ratio(lm: Landmarks) -> float:
    """Độ mở miệng: khoảng cách môi trong trên-dưới chia bề rộng miệng.

    Theo thứ tự điểm của face_recognition: top_lip[8..10] là điểm 63,62,61,
    bottom_lip[8..10] là điểm 67,66,65; top_lip[0], top_lip[6] là hai khóe miệng.
    """
    t, b = lm["top_lip"], lm["bottom_lip"]
    width = _dist(t[0], t[6])
    gap = (_dist(t[10], b[8]) + _dist(t[9], b[9]) + _dist(t[8], b[10])) / 3
    return 0.0 if width == 0 else gap / width


def head_yaw(lm: Landmarks) -> float:
    """Độ lệch của chóp mũi so với giữa hai bên má, trong khoảng [-1, 1].

    Dương khi mũi lệch về phía phải của ảnh gốc (người quay sang trái của họ).
    """
    left, right = lm["chin"][0][0], lm["chin"][16][0]
    nose = lm["nose_tip"][2][0]
    width = right - left
    return 0.0 if width <= 0 else (2 * nose - left - right) / width


def head_pitch(lm: Landmarks) -> float:
    """Vị trí chóp mũi giữa đường ngang hai mắt (0) và đáy cằm (1).

    Ngẩng lên thì mũi nhô ra đi lên gần mắt → giá trị giảm; cúi xuống thì tăng.
    Giá trị tuyệt đối khác nhau giữa từng người, nên chỉ so với mốc nhìn thẳng của chính người đó.
    """
    eye_y = (np.mean(lm["left_eye"], axis=0)[1] + np.mean(lm["right_eye"], axis=0)[1]) / 2
    height = lm["chin"][8][1] - eye_y
    return 0.0 if height <= 0 else float((lm["nose_tip"][2][1] - eye_y) / height)


_RIGID = ("chin", "left_eyebrow", "right_eyebrow", "nose_bridge", "nose_tip", "left_eye", "right_eye")


def _rigid_points(lm: Landmarks) -> np.ndarray:
    return np.array([p for key in _RIGID for p in lm[key]], dtype=np.float32)


def planarity_residual(ref: Landmarks, cur: Landmarks) -> float:
    """Sai số khi coi khuôn mặt là một mặt phẳng.

    Ảnh in hay màn hình là mặt phẳng: dù nghiêng thế nào, landmark giữa hai frame
    vẫn liên hệ đúng bằng một phép biến đổi homography nên sai số gần 0. Mặt thật có
    chiều sâu (mũi nhô ra) nên khi quay đầu sai số lớn. Chuẩn hóa theo khoảng cách hai mắt.
    """
    a, b = _rigid_points(ref), _rigid_points(cur)
    h, _ = cv2.findHomography(a, b, 0)
    if h is None:
        return 0.0
    projected = cv2.perspectiveTransform(a.reshape(-1, 1, 2), h).reshape(-1, 2)
    eye_gap = _dist(np.mean(cur["left_eye"], axis=0), np.mean(cur["right_eye"], axis=0))
    return float(np.mean(np.linalg.norm(projected - b, axis=1)) / max(eye_gap, 1e-6))
