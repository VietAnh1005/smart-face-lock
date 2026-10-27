"""Màn hình chính – xác thực."""
import math
import tkinter as tk

from config import settings
from services.auth_service import FACE_DISABLED, LOCKED, LOCKED_OUT, UNLOCKED, VERIFYING, WAITING
from services.frame_result import FrameResult
from ui.app import (BG, CARD, DANGER, DISPLAY_SIZE, LABEL_SIZE, MUTED, SUCCESS, TEXT, WARNING, CameraPanel, Chip,
                    Dropdown, Overlay, button, card, font, header, notice_bar, set_enabled)
from ui.login_dialog import ask_admin_login

LOCK_LABELS = {
    LOCKED: ("●  ĐÃ KHÓA", DANGER),
    VERIFYING: ("●  ĐANG XÁC THỰC", WARNING),
    UNLOCKED: ("●  ĐÃ MỞ", SUCCESS),
    FACE_DISABLED: ("●  FACE ID TẠM TẮT", WARNING),
    LOCKED_OUT: ("●  TẠM KHÓA", DANGER),
}
CHIPS = {"FACE": ("active", "pending"), "FINGERPRINT": ("done", "active")}
FIELDS = {"fingerprint": ("pin",), "fallback": ("user", "pin"), None: ()}
TIMED_STATES = (VERIFYING, UNLOCKED, LOCKED_OUT)  # có đếm ngược cần cập nhật mượt


def initials(names: dict[int, str]) -> list[tuple[str, int]]:
    """Tên viết tắt cho danh sách chọn ở chế độ dự phòng ("Nguyễn Văn An" → "NVA"); trùng thì thêm số."""
    out, seen = [], {}
    for uid, name in sorted(names.items()):
        label = "".join(word[0] for word in name.split()).upper() or "?"
        seen[label] = seen.get(label, 0) + 1
        out.append((label if seen[label] == 1 else f"{label} {seen[label]}", uid))
    return out


class MainScreen(tk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, bg=BG)
        self.app = app
        self.auth = app.ctx.auth
        header(self, "🔒  SMART LOCK – FACE ID",
               right=lambda bar: button(bar, "Quản lý (Admin)", self._open_admin, "dark"))
        self.notice = notice_bar(self)

        body = tk.Frame(self, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", anchor="n")
        self.camera = CameraPanel(left)
        self.camera.pack()
        self.video = self.camera.video
        chips = tk.Frame(left, bg=BG)
        chips.pack(anchor="w", pady=(8, 0))
        self.chips = [Chip(chips, text) for text in ("1. Khuôn mặt", "2. Vân tay (PIN)")]
        for chip in self.chips:
            chip.pack(side="left", padx=(0, 6))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0), anchor="n")
        lock_card = card(right, fill="x")
        tk.Label(lock_card, text="Trạng thái khóa", bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(anchor="w")
        self.lock_label = tk.Label(lock_card, bg=CARD, font=font(DISPLAY_SIZE, "bold"))
        self.lock_label.pack(anchor="w", pady=(4, 0))

        info = card(right, fill="x", pady=(10, 0))
        self.user_value = self._row(info, "Người dùng")
        self.face_failed = self._row(info, "Sai khuôn mặt")
        self.lock_failed = self._row(info, "Sai vân tay (PIN)")

        self.form = card(right, fill="x", pady=(10, 0))
        self.pin_var = tk.StringVar()
        user_field, self.user_choice = self._field(
            "Người dùng", lambda f: Dropdown(f, "Chọn tên của bạn"))
        pin_field, self.pin_entry = self._field("PIN (6 số, thay vân tay)", lambda f: self._entry(f, self.pin_var))
        self.fields = {"user": user_field, "pin": pin_field}
        self._choices: list[tuple[str, int]] = []
        self._mode: str | None = "unset"

        self.primary = button(right, "Bắt đầu lại", self._primary)
        self.primary.pack(fill="x", pady=(12, 0), ipady=4)
        self._paused = False
        self._view = None
        self.overlay = Overlay("Mời nhìn vào camera", "Đứng cách camera khoảng 50 cm")
        self.notice.set("Hệ thống sẵn sàng.")
        self._render(None, None)

    # ---------- dựng widget ----------

    @staticmethod
    def _row(master, label: str) -> tk.Label:
        row = tk.Frame(master, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(side="left")
        value = tk.Label(row, text="—", bg=CARD, fg=TEXT, font=font(LABEL_SIZE, "bold"))
        value.pack(side="right")
        return value

    def _entry(self, master, var: tk.StringVar) -> tk.Entry:
        entry = tk.Entry(master, textvariable=var, show="●")
        entry.bind("<Return>", lambda _e: self._primary())
        return entry

    def _field(self, label: str, make) -> tuple[tk.Frame, tk.Widget]:
        """Nhãn + ô nhập trong một khung; ô nhập tạo bên trong khung để không bị khung che."""
        frame = tk.Frame(self.form, bg=CARD)
        tk.Label(frame, text=label, bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(anchor="w")
        widget = make(frame)
        widget.pack(fill="x", ipady=4, pady=(4, 8))
        return frame, widget

    # ---------- nhận frame ----------

    def on_frame(self, r: FrameResult) -> None:
        if self._paused:  # đang mở hộp thoại admin: không xác thực ngầm sau lưng hộp thoại
            return
        if r.error:
            # Vẫn hiện đúng trạng thái khóa: chế độ dự phòng (PIN) không cần camera.
            self.auth.abort()
            view = self.auth.view
            self._render(view, view.message if view.tone else r.error)  # đang hiện kết quả: giữ câu kết quả
            self.overlay = Overlay("Không có tín hiệu camera", r.error, "bad")
            return
        view = self.auth.feed(r)
        message = view.message + (". Camera quá tối hoặc bị che" if r.dark else "")
        self._render(view, message)

    def tick(self) -> None:
        """Gọi ở mọi nhịp vẽ: cập nhật số giây và vạch thời gian cho mượt."""
        if self._paused or self._view is None or self._view.state not in TIMED_STATES:
            return
        countdown = self.auth.countdown()
        if countdown is not None:
            self._apply_countdown(self.overlay, countdown)

    @staticmethod
    def _apply_countdown(overlay: Overlay, countdown: tuple[float, float | None]) -> None:
        left, total = countdown
        secs = math.ceil(left)
        overlay.seconds = f"{secs // 60}:{secs % 60:02d}" if total is None else f"{secs} giây"
        overlay.progress = None if total is None else left / total

    # ---------- hiển thị ----------

    def _overlay(self, view) -> Overlay:
        """Không bao giờ báo mặt đã khớp: bước khuôn mặt chỉ hiện hướng dẫn thử thách / nhìn thẳng."""
        state = view.state
        if view.tone == "ok":
            main, sub = "Đã mở khóa", view.user or ""
        elif view.tone == "bad":
            main, sub = "Bị từ chối", view.message
        elif state == VERIFYING and self.auth.challenge():
            instruction, step, total = self.auth.challenge()
            main, sub = instruction, f"Đang xác thực {step} / {total}"
        elif state == VERIFYING:
            main, sub = (("Nhìn thẳng vào camera", "Đang xác thực") if view.step == "FACE"
                         else ("Nhập PIN (thay vân tay)", "Dùng ô nhập bên phải"))
        elif state == LOCKED_OUT:
            main, sub = "Tạm khóa", view.message
        elif state == FACE_DISABLED:
            main, sub = "Face ID tạm tắt", "Chọn tên và nhập PIN bên phải"
        elif view.message == WAITING:
            main, sub = "Mời nhìn vào camera", "Đứng cách camera khoảng 50 cm"
        else:
            main, sub = view.message, ""
        tone = view.tone or {LOCKED_OUT: "bad", VERIFYING: "run"}.get(state, "")
        overlay = Overlay(main, sub, tone)
        countdown = self.auth.countdown()
        if countdown is not None:
            self._apply_countdown(overlay, countdown)
        return overlay

    def _set_mode(self, mode: str | None) -> None:
        """Hiện đúng các ô nhập; đổi chế độ thì xóa nội dung gõ dở (không để sót sang phiên sau)."""
        if mode == self._mode:
            return
        self._mode = mode
        self.user_choice.close()  # danh sách tên đang mở không được nằm lại khi form ẩn
        self.pin_var.set("")
        for frame in self.fields.values():
            frame.pack_forget()
        for name in FIELDS[mode]:
            self.fields[name].pack(fill="x")
        if mode == "fallback":
            # Danh sách tên luôn hiện từ đầu, không phụ thuộc kết quả lần thử trước.
            self._choices = initials(self.auth.user_names())
            self.user_choice.set_values([label for label, _ in self._choices])
        if mode == "fingerprint":
            self.pin_entry.focus_set()
        if mode is None:
            self.form.pack_forget()
        else:
            self.form.pack(fill="x", pady=(10, 0), before=self.primary)
        self.primary.configure(text={"fingerprint": "Xác nhận", "fallback": "Mở cửa"}.get(mode, "Bắt đầu lại"))

    def _render(self, view, message: str | None = None) -> None:
        self.face_failed.configure(text=f"{self.auth.face_failures} / {settings.FACE_MAX_FAILED}")
        self.lock_failed.configure(text=f"{self.auth.lock_failures} / {settings.LOCK_MAX_FAILED}")
        if view is None:  # lỗi camera / xử lý ảnh: phiên đã bị hủy
            self.lock_label.configure(text=LOCK_LABELS[LOCKED][0], fg=LOCK_LABELS[LOCKED][1])
            if message:
                self.notice.set(message, "bad")
            self._set_mode(None)
            set_enabled(self.primary, True)
            self.user_value.configure(text="—")
            for chip in self.chips:
                chip.set("pending")
            return
        self._view = view
        # Cửa còn mở (UNLOCK_SECONDS dài hơn thời gian hiện kết quả) thì vẫn báo ĐÃ MỞ.
        text, color = LOCK_LABELS[UNLOCKED if not self.app.ctx.lock.is_locked() else view.state]
        if view.state == LOCKED_OUT and self.auth.admin_only:
            text = "●  CHỈ QUẢN TRỊ MỞ ĐƯỢC"
        self.lock_label.configure(text=text, fg=color)
        self.overlay = self._overlay(view)
        self.notice.set(message or view.message, self.overlay.tone)
        self.user_value.configure(text=view.user or "—")
        for chip, status in zip(self.chips, CHIPS.get(view.step, ("pending", "pending"))):
            chip.set(status)
        if view.state == FACE_DISABLED:
            self._set_mode("fallback")
        elif view.step == "FINGERPRINT" and not view.tone:
            self._set_mode("fingerprint")
        else:
            self._set_mode(None)
        # Bước khuôn mặt: tắt nút (hủy sau 5 giây vẫn bị tính sai, tránh bấm nhầm)
        set_enabled(self.primary, not (view.state == VERIFYING and view.step == "FACE"))

    # ---------- thao tác ----------

    def _primary(self) -> None:
        if self._mode == "fingerprint":
            pin = self.pin_var.get()
            self.pin_var.set("")
            self._render(self.auth.submit_fingerprint(pin))
        elif self._mode == "fallback":
            index = self.user_choice.current()
            if index < 0 or not self.pin_var.get():
                # Thao tác thiếu, không phải lần đoán: không gửi nên không mất lượt.
                self.notice.set("Chọn tên và nhập PIN.", "bad")
                return
            uid = self._choices[index][1]
            view = self.auth.submit_fallback(self.pin_var.get(), uid, self.app.worker.latest_frame())
            self.pin_var.set("")
            self._render(view)
        elif self.auth.state == VERIFYING:  # phím Enter vẫn gọi được khi nút đang tắt
            return
        else:
            self.auth.abort()
            self.notice.set("Đã bắt đầu phiên mới, mời nhìn vào camera.")

    def _open_admin(self) -> None:
        self.auth.abort()
        self._paused = True
        try:
            ok = ask_admin_login(self.app)
        finally:
            self._paused = False
        if ok:
            from ui.admin_screen import AdminScreen
            self.app.show(AdminScreen)
