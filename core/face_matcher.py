"""So khớp vector khuôn mặt với danh sách đã đăng ký."""
import math

import numpy as np

from config import settings


def distance_to(vec: np.ndarray, encodings: list[np.ndarray]) -> float:
    """Khoảng cách nhỏ nhất từ vec tới các encoding của một người."""
    if not encodings:
        return math.inf
    return float(np.min(np.linalg.norm(np.asarray(encodings) - vec, axis=1)))


def find_best_match(vec: np.ndarray, known: dict[int, list[np.ndarray]],
                    threshold: float = settings.MATCH_THRESHOLD,
                    margin: float = settings.MATCH_MARGIN) -> tuple[int | None, float]:
    """Trả (user_id, khoảng cách); user_id là None nếu không đủ chắc chắn.

    Chấp nhận khi người gần nhất dưới ngưỡng VÀ cách người gần nhì ít nhất `margin`,
    để hai người giống nhau không bị nhận nhầm sang nhau.
    """
    ranked = sorted((distance_to(vec, encs), uid) for uid, encs in known.items())
    if not ranked:
        return None, math.inf
    best, best_uid = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else math.inf
    if best < threshold and second - best >= margin:
        return best_uid, best
    return None, best
