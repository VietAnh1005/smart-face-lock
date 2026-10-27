import tkinter as tk
from types import SimpleNamespace

import pytest

from config import settings
from hardware.simulated_lock import SimulatedLock
from security.pin_auth import PinFactor, hash_pin
from services.auth_service import AuthService
from services.frame_result import FrameResult
from services.lockout_service import FaceCounter, LockoutService
from tests.conftest import vector
from ui.app import style_inputs
from ui.main_screen import MainScreen, initials


def test_initials_and_duplicates():
    names = {1: "Nguyễn Văn An", 2: "Ngô Văn Anh", 3: "Bình"}
    assert initials(names) == [("NVA", 1), ("NVA 2", 2), ("B", 3)]


@pytest.fixture
def screen(ctx, clock):
    ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    lockout = LockoutService(ctx.state, ctx.logger, "", clock, settings.LOCK_MAX_FAILED, admin_after_last=True)
    lock = SimulatedLock(clock)
    auth = AuthService(ctx.users, lockout, FaceCounter(ctx.state, ctx.logger), PinFactor(ctx.users),
                       ctx.logger, lock, clock)
    root = tk.Tk()
    style_inputs(root)                               # như App: ô nhập dùng font/màu của app
    root.ctx = SimpleNamespace(auth=auth, lock=lock)
    root.worker = SimpleNamespace(latest_frame=lambda: None)
    scr = MainScreen(root)
    ctx.state.set(FaceCounter.KEY, settings.FACE_MAX_FAILED)
    scr.on_frame(FrameResult(None, boxes=[], seq=1))
    yield scr, lockout
    root.update()  # xử lý hết sự kiện chờ trước khi hủy: Tk trên macOS segfault ở Tk() kế tiếp nếu bỏ qua
    root.destroy()


def test_camera_error_keeps_fallback_form(screen):
    scr, _ = screen
    scr.on_frame(FrameResult(None, error="Mất tín hiệu camera"))
    assert scr._mode == "fallback" and "FACE ID" in scr.lock_label["text"]


def test_fallback_without_chosen_user_is_not_counted(screen):
    scr, lockout = screen
    scr.pin_var.set("123456")
    scr._primary()                                    # quên chọn tên
    assert lockout.failed_count() == 0


def test_camera_error_does_not_hide_result_being_shown(screen):
    scr, _ = screen
    scr.user_choice.current(0)
    scr.pin_var.set("123456")
    scr._primary()                                   # mở cửa bằng đường dự phòng: đang hiện "Xin chào…"
    scr.on_frame(FrameResult(None, error="Tiến trình xử lý ảnh đã dừng"))
    assert scr.notice._text["text"].startswith("Xin chào")


def test_open_user_list_closes_when_form_hides(screen):
    """Mở cửa thành công khi danh sách tên đang mở: danh sách không được nằm lại trên màn hình."""
    scr, _ = screen
    scr.user_choice.current(0)
    scr.user_choice.toggle()
    scr.update()
    scr.pin_var.set("123456")
    scr._primary()
    scr.update()
    assert scr._mode is None and not scr.user_choice.is_open()
