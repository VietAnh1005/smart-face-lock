"""Điểm khởi chạy Smart Face Lock.

    python main.py              chạy ứng dụng (lần đầu sẽ hỏi đặt mật khẩu admin)
    python main.py --calibrate  xem số đo EAR / yaw / độ mở miệng / độ phẳng để chỉnh ngưỡng
    python main.py --reset      xóa toàn bộ dữ liệu và khóa để cài lại (khi quên mật khẩu admin)
"""
import argparse
import shutil
import sqlite3
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, simpledialog

from config import settings
from hardware.simulated_lock import SimulatedLock
from security.admin_auth import AdminAuth, hash_password
from security.key_manager import ConfigError, load_crypto
from security.pin_auth import PinFactor
from services.access_logger import AccessLogger
from services.auth_service import AuthService
from services.enrollment_service import EnrollmentService
from services.lockout_service import FaceCounter, LockoutService
from storage.database import Database
from storage.log_repository import LogRepository
from storage.settings_repository import SettingsRepository
from storage.user_repository import UserRepository


def ask_admin_password() -> str | None:
    """Hộp thoại đặt mật khẩu admin lần đầu; trả None nếu người dùng hủy."""
    root = tk.Tk()
    root.withdraw()
    try:
        while True:
            first = simpledialog.askstring("Cài đặt lần đầu", "Đặt mật khẩu admin (8–72 ký tự):", show="●")
            if first is None:
                return None
            second = simpledialog.askstring("Cài đặt lần đầu", "Nhập lại mật khẩu admin:", show="●")
            if second is None:
                return None
            if first != second:
                messagebox.showerror("Cài đặt", "Hai lần nhập không khớp.")
                continue
            try:
                hash_password(first)
            except ValueError as exc:
                messagebox.showerror("Cài đặt", str(exc))
                continue
            return first
    finally:
        root.destroy()


def install(password: str) -> None:
    """Tạo khóa + DB + hash admin. Ghi vào file tạm rồi đổi tên để không bao giờ có DB dở dang."""
    crypto = load_crypto()  # DB chưa tồn tại nên được phép tạo khóa mới
    tmp_path = settings.DB_PATH.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    db = Database(tmp_path)
    repo = SettingsRepository(db, crypto)
    repo.set("admin_hash", hash_password(password))
    LockoutService.install(repo, "")
    LockoutService.install(repo, "admin_")
    FaceCounter.install(repo)
    db.close()
    tmp_path.replace(settings.DB_PATH)


@dataclass
class AppContext:
    """Mọi đối tượng dùng chung của ứng dụng; màn hình nào cần gì thì lấy từ `app.ctx`."""
    db: Database
    state: SettingsRepository
    users: UserRepository
    logs: LogRepository
    logger: AccessLogger
    lock: SimulatedLock
    admin: AdminAuth
    lockout: LockoutService   # bộ đếm khóa của cửa (bộ đếm admin nằm trong `admin`)
    faces: FaceCounter
    auth: AuthService
    enroll: EnrollmentService


def build_context() -> AppContext:
    crypto = load_crypto()
    db = Database(settings.DB_PATH)
    state = SettingsRepository(db, crypto)
    users = UserRepository(db, crypto)
    logs = LogRepository(db, settings.SNAPSHOT_DIR)
    logger = AccessLogger(logs, crypto)
    lock = SimulatedLock()
    admin = AdminAuth(state, LockoutService(state, logger, "admin_"), logger)
    lockout = LockoutService(state, logger, max_failed=settings.LOCK_MAX_FAILED, admin_after_last=True)
    faces = FaceCounter(state, logger)

    return AppContext(
        db=db, state=state, users=users, logs=logs, logger=logger, lock=lock, admin=admin,
        lockout=lockout, faces=faces,
        auth=AuthService(users, lockout, faces, PinFactor(users), logger, lock),
        enroll=EnrollmentService(users, logs, admin, logger),
    )


def reset() -> None:
    answer = input("Xóa TOÀN BỘ người dùng, nhật ký, ảnh và khóa bí mật? Gõ RESET để xác nhận: ")
    if answer != "RESET":
        print("Đã hủy.")
        return
    settings.DB_PATH.unlink(missing_ok=True)
    settings.ENV_PATH.unlink(missing_ok=True)
    shutil.rmtree(settings.SNAPSHOT_DIR, ignore_errors=True)
    print("Đã xóa. Chạy lại `python main.py` để cài đặt.")


def calibrate() -> None:
    """Hiện số đo trực tiếp để chỉnh các ngưỡng "(đo)" trong config/settings.py. Phím r: đặt lại mốc, q: thoát."""
    import cv2

    from core.camera_stream import CameraStream
    from core.face_detector import FaceDetector
    from core.image_quality import brightness, sharpness
    from core.landmark_utils import (eye_aspect_ratio, head_pitch, head_yaw, mouth_aspect_ratio,
                                     planarity_residual)

    detector, ref = FaceDetector(), None
    try:
        with CameraStream() as cam:
            while True:
                frame = cam.read_frame()
                if frame is None:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                boxes = detector.detect(rgb)
                lines = [f"faces={len(boxes)}  frame_brightness={brightness(gray):.0f}"]
                if len(boxes) == 1:
                    top, right, bottom, left = boxes[0]
                    lm = detector.landmarks(rgb, boxes[0])
                    yaw = settings.YAW_SIGN * head_yaw(lm)
                    if ref is None and abs(yaw) < settings.FRONTAL_YAW:
                        ref = lm
                    crop = gray[top:bottom, left:right]
                    ear = (eye_aspect_ratio(lm["left_eye"]) + eye_aspect_ratio(lm["right_eye"])) / 2
                    lines += [f"EAR={ear:.3f}  yaw={yaw:+.3f} (+ = trai cua ban)  MAR={mouth_aspect_ratio(lm):.3f}",
                              f"pitch={head_pitch(lm):.3f} (ngang len: giam, cui xuong: tang)",
                              f"sharpness={sharpness(crop):.0f}  face_brightness={brightness(crop):.0f}",
                              f"residual_3d={planarity_residual(ref, lm):.4f}" if ref
                              else "residual_3d: nhin thang de lay moc"]
                view = cv2.flip(frame, 1)
                for i, text in enumerate(lines):
                    cv2.putText(view, text, (10, 25 + 25 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.imshow("calibrate (r: reset, q: quit)", view)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("r"):
                    ref = None
    finally:
        cv2.destroyAllWindows()  # camera lỗi giữa chừng cũng không bỏ lại cửa sổ


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart Face Lock")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()
    if args.reset:
        reset()
        return 0
    if args.calibrate:
        calibrate()
        return 0

    try:
        if not settings.DB_PATH.exists():
            password = ask_admin_password()
            if password is None:
                return 1
            install(password)
        ctx = build_context()
        ctx.lock.lock()  # fail-secure: lần chạy trước crash khi cửa đang mở thì khóa lại ngay
    except (ConfigError, sqlite3.DatabaseError, OSError) as exc:
        # .env hỏng, DB hỏng/bị khóa, không ghi được thư mục data/: báo rõ thay vì in traceback
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Smart Face Lock", f"Không khởi động được: {exc}")
        root.destroy()
        return 1

    from ui.app import App
    try:
        try:
            app = App(ctx)
        except Exception as exc:  # vd. DB bị khóa khi dựng màn hình đầu tiên: báo rõ thay vì in traceback
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Smart Face Lock", f"Không khởi động được giao diện: {exc}")
            root.destroy()
            raise
        app.mainloop()
    finally:
        ctx.lock.lock()  # fail-secure: thoát bằng mọi đường đều khóa cửa
        ctx.db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
