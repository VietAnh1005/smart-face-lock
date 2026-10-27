"""Kiểu dữ liệu khuôn mặt dùng chung. Không import dlib: phần chỉ tính hình học không phải nạp model (~140 MB)."""

Box = tuple[int, int, int, int]  # (top, right, bottom, left) theo quy ước của face_recognition
Landmarks = dict[str, list[tuple[int, int]]]


def largest(boxes: list[Box]) -> Box:
    """Mặt to nhất = người đứng gần camera nhất."""
    return max(boxes, key=lambda b: (b[1] - b[3]) * (b[2] - b[0]))
