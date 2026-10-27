"""Kết quả xử lý một frame, được tiến trình xử lý ảnh gửi sang các service."""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class FrameResult:
    frame: np.ndarray | None                 # ảnh BGR gốc (chưa lật)
    boxes: list = field(default_factory=list)
    landmarks: dict | None = None            # của mặt lớn nhất (khi có mặt)
    quality_ok: bool = False                 # vùng mặt đủ nét và đủ sáng
    dark: bool = False                       # cả khung hình quá tối (cam bị che / thiếu sáng)
    error: str | None = None                 # lỗi camera hoặc lỗi xử lý ảnh kéo dài
    seq: int = 0                             # số thứ tự frame, tăng dần
    # Vector 128 chiều được tạo ở tiến trình riêng nên thuộc một frame TRƯỚC đó (trễ tới ~0.8 s).
    # Đi kèm số thứ tự, landmark và độ nét của chính frame đó để không đem vector cũ ghép với frame hiện tại.
    encoding: np.ndarray | None = None
    encoding_seq: int = 0
    encoding_landmarks: dict | None = None
    encoding_quality: bool = False
