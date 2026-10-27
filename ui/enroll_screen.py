"""Màn hình đăng ký khuôn mặt."""
import tkinter as tk
from tkinter import messagebox, ttk

from config import settings
from services.enrollment_service import DONE, FAILED_ENROLL, EnrollmentError
from services.frame_result import FrameResult
from ui.app import (BG, CAPTION_SIZE, CARD, LABEL_SIZE, MUTED, SUCCESS, TEXT, CameraPanel, Overlay, button, card,
                    font, header, notice_bar, set_enabled)

SAVE_HINT = "Nút Lưu chỉ bật khi chụp đủ 10 ảnh và qua kiểm tra người thật."


class EnrollScreen(tk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, bg=BG)
        self.app = app
        self.service = app.ctx.enroll
        self.admin = app.ctx.admin
        self.session_label = None
        self._dialog_open = False

        def session_info(bar):
            self.session_label = tk.Label(bar, bg=bar["bg"], fg="#d6d6d6", font=font(CAPTION_SIZE))
            return self.session_label

        header(self, "ĐĂNG KÝ KHUÔN MẶT", back=self._back, right=session_info)
        self.notice = notice_bar(self)
        self.notice.set(SAVE_HINT)
        self.overlay = Overlay("Nhập tên và PIN", "Rồi bấm Bắt đầu chụp")

        body = tk.Frame(self, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)
        self.camera = CameraPanel(body)
        self.camera.pack(side="left", anchor="n")
        self.video = self.camera.video

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        form = card(right, fill="x")
        self.name = self._field(form, "Tên người dùng")
        self.pin = self._field(form, "PIN 6 số", show="●")
        self.pin_again = self._field(form, "Nhập lại PIN", show="●")

        status = card(right, fill="x", pady=(10, 0))
        row = tk.Frame(status, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Đã chụp", bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(side="left")
        self.count_label = tk.Label(row, bg=CARD, fg=TEXT, font=font(LABEL_SIZE, "bold"))
        self.count_label.pack(side="right")
        self.progress = ttk.Progressbar(status, maximum=settings.ENROLL_CAPTURES,
                                        style="Blue.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=6)
        row = tk.Frame(status, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Kiểm tra người thật", bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(side="left")
        self.liveness_label = tk.Label(row, bg=CARD, font=font(LABEL_SIZE, "bold"))
        self.liveness_label.pack(side="right")

        actions = tk.Frame(right, bg=BG)
        actions.pack(side="bottom", fill="x")
        self.start_button = button(actions, "Bắt đầu chụp", self._start, "secondary")
        self.start_button.pack(side="left", expand=True, fill="x", padx=(0, 6), ipady=4)
        self.save_button = button(actions, "Lưu", self._save)
        self.save_button.pack(side="left", expand=True, fill="x", padx=(6, 0), ipady=4)
        self._refresh()

    @staticmethod
    def _field(master, label: str, show: str = "") -> tk.Entry:
        tk.Label(master, text=label, bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(anchor="w")
        entry = tk.Entry(master, show=show)
        entry.pack(fill="x", ipady=4, pady=(3, 8))
        return entry

    def _refresh(self) -> None:
        """Cập nhật số ảnh, trạng thái kiểm tra người thật, nút Lưu, thời gian phiên admin."""
        self.count_label.configure(text=f"{self.service.captured} / {settings.ENROLL_CAPTURES}")
        self.progress["value"] = self.service.captured
        passed = self.service.liveness_passed
        self.liveness_label.configure(text="Đạt" if passed else "Chưa", fg=SUCCESS if passed else MUTED)
        set_enabled(self.save_button, self.service.ready)
        set_enabled(self.start_button, not self.service.active)
        left = self.admin.seconds_left()
        self.session_label.configure(text=f"Đang đăng nhập: admin · hết hạn sau {left // 60}:{left % 60:02d}")

    def _message(self, show, text: str) -> None:
        """Hộp thoại chạy vòng sự kiện lồng nhau; tạm dừng on_frame để không đổi màn hình sau lưng nó."""
        self._dialog_open = True
        try:
            show("Đăng ký", text, parent=self.app)
        finally:
            self._dialog_open = False

    def _start(self) -> None:
        try:
            self.service.start(self.name.get(), self.pin.get(), self.pin_again.get())
        except EnrollmentError as exc:
            self._message(messagebox.showerror, str(exc))
            if not self.admin.is_active():
                self._back()
            return
        self._refresh()

    def _save(self) -> None:
        try:
            state, message, _ = self.service.save()
        except EnrollmentError as exc:
            self._message(messagebox.showerror, str(exc))
            if not self.admin.is_active():
                self._back()
            return
        if state == DONE:
            self._message(messagebox.showinfo, message)
            self._back()
        else:
            self._show_failure(message)

    def _show_failure(self, message: str) -> None:
        self.overlay = Overlay("Đăng ký thất bại", "Bấm Bắt đầu chụp để làm lại", "bad")
        self.notice.set(message, "bad")
        self._refresh()

    def on_frame(self, r: FrameResult) -> None:
        if self._dialog_open:
            return
        if not self.admin.is_active():
            self._back()
            return
        self._refresh()
        if r.error:
            self.overlay = Overlay("Không có tín hiệu camera", r.error, "bad")
            self.notice.set(r.error, "bad")
            return
        if not self.service.active:
            return
        try:
            state, message, _ = self.service.feed(r)
        except EnrollmentError as exc:
            self._message(messagebox.showerror, str(exc))
            self._back()
            return
        if state == FAILED_ENROLL:
            self._show_failure(message)
            return
        done = self.service.ready
        sub = ("Kiểm tra người thật" if not self.service.liveness_passed
               else f"Đã chụp {self.service.captured} / {settings.ENROLL_CAPTURES}")
        self.overlay = Overlay(message, sub, "ok" if done else "run")
        self.notice.set(SAVE_HINT if not done else "Đã chụp đủ ảnh. Bấm Lưu để hoàn tất.", "ok" if done else "run")
        self._refresh()

    def _back(self) -> None:
        # Có thể bị gọi lần hai khi hộp thoại đang mở mà phiên admin vừa hết hạn (màn hình đã bị thay).
        if self.app.screen is not self:
            return
        self.service.cancel()
        from ui.admin_screen import AdminScreen
        from ui.main_screen import MainScreen
        self.app.show(AdminScreen if self.admin.is_active() else MainScreen)
