# Smart Face Lock

Khóa cửa mô phỏng: **khuôn mặt (có chống giả mạo) + vân tay**. Hiện vân tay được giả lập bằng **PIN 6 số**; thay bằng cảm biến thật chỉ cần một lớp mới có `identify(sample, claimed_user_id)` (xem `security/pin_auth.py`) và bỏ bước chọn tên ở chế độ dự phòng.

## Cài đặt (macOS)

Cần Python 3.12+ từ python.org (đã kèm Tkinter) và Xcode Command Line Tools (`xcode-select --install`). Trên macOS `dlib` được build từ mã nguồn (mất vài phút):

```bash
python3 -m venv ~/.venvs/smart_face_lock
source ~/.venvs/smart_face_lock/bin/activate
pip install cmake                      # dlib cần cmake lúc build
pip install -r requirements.txt
pip install --no-deps face_recognition==1.3.0
```

Lần đầu chạy, macOS hỏi quyền camera cho Terminal: bấm Cho phép (bị từ chối thì bật lại ở System Settings → Privacy & Security → Camera). Khi gõ mật khẩu admin nên dùng bàn phím ABC: bộ gõ tiếng Việt có thể đổi chữ (`aa` → `â`).

## Cài đặt (Windows)

dlib không đọc được file model nếu đường dẫn có dấu (ví dụ `D:\Tài liệu\...`), nên **venv phải đặt ở đường dẫn không dấu**:

```bash
py -3.12 -m venv %USERPROFILE%\.venvs\smart_face_lock
%USERPROFILE%\.venvs\smart_face_lock\Scripts\activate
pip install -r requirements.txt
pip install --no-deps face_recognition==1.3.0
```

## Chạy

| Lệnh | Việc |
| --- | --- |
| `python main.py` | chạy ứng dụng; lần đầu hỏi đặt mật khẩu admin |
| `python main.py --calibrate` | xem EAR / yaw / độ mở miệng / độ phẳng / độ nét để chỉnh các ngưỡng "(đo)" trong `config/settings.py` |
| `python main.py --reset` | xóa toàn bộ dữ liệu + khóa (dùng khi quên mật khẩu admin) |
| `python -m tools.measure_far_frr capture "Ten"` | chụp 20 ảnh một người vào `dataset/` |
| `python -m tools.measure_far_frr measure` | đo FAR/FRR ở các ngưỡng 0.40–0.60 |
| `python -m tools.measure_far_frr capture-session "Ten"` | thu vector liên tục 12 giây (nháy mắt, quay đầu, há miệng) vào `dataset_sessions/` |
| `python -m tools.measure_far_frr measure-session` | khoảng cách theo phiên: cùng người / khác người, ghi `dataset_sessions/distances.csv` |
| `python -m pytest` | chạy test tự động |

Quy trình dùng: Quản lý (Admin) → nhập mật khẩu → **+ Đăng ký mới** → nhập tên, PIN, nhập lại PIN → **Bắt đầu chụp** → làm 2 thử thách người thật → xoay đầu theo hướng dẫn đến khi chụp đủ 10 ảnh → **Lưu**. Sau đó đứng trước camera ở màn hình chính: 2 thử thách người thật (luôn có 1 bước quay đầu, chạy cho mọi khuôn mặt trước khi so khớp) → nhìn thẳng → nhập PIN (thay vân tay).

Admin bấm **Gỡ khóa** trong màn Quản lý để gỡ khóa và bật lại Face ID (ghi log `ADMIN_CLEAR_LOCKOUT`).

**Lần đầu cài trên máy mới, chạy `--calibrate` và chỉnh:** `YAW_SIGN` (nếu trái/phải bị ngược), `EAR_CLOSED_RATIO`/`EAR_OPEN_RATIO`, `ENROLL_POSE_PITCH`, `MIN_3D_RESIDUAL` (giơ ảnh in nghiêng và quay đầu thật, chọn giá trị nằm giữa), `MIN_SHARPNESS`, `MIN_BRIGHTNESS`.

Giải thích chi tiết cách hệ thống hoạt động: xem tài liệu hướng dẫn đi kèm.
