"""Tham số cấu hình của Smart Face Lock.

Các giá trị ghi chú "(đo)" phải chỉnh lại theo webcam và ánh sáng thực tế,
dùng `python main.py --calibrate` để xem số đo trực tiếp.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "smart_lock.db"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ENV_PATH = BASE_DIR / ".env"

# --- Nhận diện ---
MATCH_THRESHOLD = 0.45          # khoảng cách tối đa để coi là khớp
MATCH_MARGIN = 0.06             # chênh tối thiểu giữa người gần nhất và người gần nhì
REQUIRED_MATCH_FRAMES = 5       # số vector tối thiểu cả phiên trước khi quyết định danh tính
DETECT_SCALE = 0.5              # thu nhỏ ảnh khi phát hiện mặt cho nhanh
MIN_FACE_RATIO = 0.15           # cạnh mặt tối thiểu so với chiều rộng frame

# --- Phiên xác thực ---
FACE_LOST_SECONDS = 1.0
PIN_TIMEOUT = 20
RESULT_HOLD_SECONDS = 3
FACE_MATCH_TIMEOUT = 5          # sau khi qua "Người thật", quá mức này chưa khớp → sai mặt
FACE_ABORT_SECONDS = 5          # mặt đã đứng ≥ mức này rồi bỏ đi/che camera → vẫn tính sai mặt
SESSION_MATCH_RATIO = 0.9       # tỉ lệ vector CẢ PHIÊN phải khớp cùng một người (đo lại bằng tools.measure_far_frr)
LIVENESS_MIN_VECTORS = 3        # số vector đạt chất lượng tối thiểu chụp TRONG lúc làm thử thách

# --- Liveness ---
LIVENESS_STEPS = 2
CHALLENGE_TIMEOUT = 6
EAR_CLOSED_RATIO = 0.75         # (đo) nhắm mắt khi EAR < 75% mức mắt mở của chính người đó
EAR_OPEN_RATIO = 0.85           # (đo) mở lại khi EAR > 85% mức mắt mở
TURN_YAW = 0.30                 # (đo) |yaw| vượt mức này là đã quay đầu
FRONTAL_YAW = 0.10              # |yaw| dưới mức này là nhìn thẳng
MOUTH_OPEN_MAR = 0.30           # (đo)
MIN_3D_RESIDUAL = 0.04          # (đo) sai số homography tối thiểu của mặt thật 3D
YAW_SIGN = 1                    # đổi thành -1 nếu webcam tự lật ảnh (trái/phải bị ngược)

# --- Camera / chất lượng ảnh ---
CAMERA_INDEX = 0
CAMERA_FAIL_FRAMES = 30
MIN_SHARPNESS = 30.0            # (đo) phương sai Laplacian của vùng mặt; webcam laptop đo được ~40–70 khi nhìn thẳng
MIN_BRIGHTNESS = 50             # (đo)
MAX_BRIGHTNESS = 210            # (đo)

# --- Đăng ký ---
ENROLL_CAPTURES = 10
ENROLL_CAPTURE_INTERVAL = 0.4
ENROLL_POSE_YAW = 0.12          # góc quay nhẹ khi chụp tư thế trái/phải
ENROLL_POSE_PITCH = 0.07        # (đo) lệch pitch so với mốc nhìn thẳng; đo thật: ngẩng/cúi ~0.10, nhiễu ~0.06
ENROLL_PITCH_MAX_YAW = 0.15     # ngẩng/cúi chỉ tính khi đầu gần như không quay ngang

# --- Khóa ---
MAX_FAILED = 3                  # đăng nhập admin
FACE_MAX_FAILED = 3             # sai mặt → FACE_DISABLED (khóa Face ID, chỉ nhận vân tay/PIN)
LOCK_MAX_FAILED = 3             # sai vân tay/PIN → LOCKED_OUT
LOCKOUT_STEPS = (30, 120, 600)  # cửa: sau mức cuối chỉ admin mở; admin: giữ 600 giây cho mỗi lần sai tiếp
UNLOCK_SECONDS = 5
ADMIN_IDLE_SECONDS = 300
ADMIN_MAX_SECONDS = 1800
CLOCK_TOLERANCE_SECONDS = 120     # đồng bộ giờ tự động (NTP) có thể lùi vài giây, không coi là can thiệp
LOG_RETENTION_DAYS = 30
