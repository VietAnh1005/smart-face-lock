"""Màn hình quản lý: người dùng, khóa tạm, lịch sử truy cập."""
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from cryptography.fernet import InvalidToken

from services.enrollment_service import EnrollmentError
from services.frame_result import FrameResult
from ui.app import (BG, CAPTION_SIZE, CARD, DANGER, DANGER_BG, LABEL_SIZE, MUTED, SUCCESS, TEXT, TITLE_SIZE, WARNING,
                    button, card, font, header, show_frame)

# Sự kiện kỹ thuật → nội dung cột "Kết quả" và màu (tag) hiển thị
RESULTS = {
    "GRANTED": ("✓ Mở khóa", "ok"),
    "LOCKED_OUT": ("Khóa tạm", "warn"),
    "TAMPER_DETECTED": ("⚠ Dữ liệu bị can thiệp", "bad"),
    "CLOCK_TAMPER": ("⚠ Đồng hồ bị chỉnh lùi", "bad"),
    "ADMIN_LOGIN_FAILED": ("✕ Sai mật khẩu admin", "bad"),
    "ADMIN_CLEAR_LOCKOUT": ("Admin mở khóa tạm", "warn"),
    "ADMIN_LOGIN": ("Admin đăng nhập", ""),
    "ENROLL": ("Đăng ký người dùng", ""),
    "DELETE_USER": ("Xóa người dùng", ""),
    "FACE_MISMATCH": ("✕ Khuôn mặt không khớp", "bad"),
    "SPOOF_DETECTED": ("✕ Phát hiện giả mạo", "bad"),
    "FACE_TIMEOUT": ("✕ Hết giờ bước khuôn mặt", "bad"),
    "FACE_ABORTED": ("✕ Bỏ dở bước khuôn mặt", "bad"),
    "FACE_LOW_QUALITY": ("✕ Ảnh mặt mờ / tối", "bad"),
    "FINGERPRINT_FAILED": ("✕ Sai vân tay (PIN)", "bad"),
    "FACE_DISABLED": ("Face ID tạm tắt", "warn"),
    "LOCKED_OUT_1": ("Khóa 30 giây", "warn"),
    "LOCKED_OUT_2": ("Khóa 2 phút", "warn"),
    "LOCKED_OUT_3": ("Khóa 10 phút", "warn"),
    "ADMIN_ONLY_LOCKOUT": ("⚠ Khóa: chỉ quản trị mở", "bad"),
}
HIDDEN_EVENTS = ("UNLOCK", "LOCK")  # trùng ý với GRANTED, không cần hiện trong lịch sử


class AdminScreen(tk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, bg=BG)
        self.app = app
        self.ctx = app.ctx
        header(self, "QUẢN LÝ", back=self._back,
               right=lambda bar: button(bar, "Đăng xuất", self._logout, "dark"))

        body = tk.Frame(self, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        users = card(body, side="left", fill="y", padx=(0, 14))
        users.configure(width=290)
        users.pack_propagate(False)
        top = tk.Frame(users, bg=CARD)
        top.pack(fill="x", pady=(0, 10))
        self.users_title = tk.Label(top, bg=CARD, fg=TEXT, font=font(TITLE_SIZE, "bold"))
        self.users_title.pack(side="left")
        button(top, "+ Đăng ký mới", self._enroll).pack(side="right")
        self.user_list = tk.Frame(users, bg=CARD)
        self.user_list.pack(fill="both", expand=True)
        self.lockout_banner = tk.Frame(users, bg=DANGER_BG, padx=10, pady=8)
        self.lockout_text = tk.Label(self.lockout_banner, bg=DANGER_BG, fg=DANGER, font=font(CAPTION_SIZE),
                                     justify="left")
        self.lockout_text.pack(side="left")
        button(self.lockout_banner, "Gỡ khóa", self._clear_lockout, "secondary").pack(side="right")

        logs = card(body, side="left", fill="both", expand=True)
        top = tk.Frame(logs, bg=CARD)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Lịch sử truy cập", bg=CARD, fg=TEXT, font=font(TITLE_SIZE, "bold")).pack(side="left")
        button(top, "Xuất CSV", self._export, "secondary").pack(side="right")
        self.logs = ttk.Treeview(logs, columns=("time", "who", "result", "photo"), show="headings")
        for col, title, width in (("time", "Thời gian", 110), ("who", "Người", 140), ("result", "Kết quả", 190),
                                  ("photo", "Ảnh", 60)):
            self.logs.heading(col, text=title, anchor="w")
            self.logs.column(col, width=width, anchor="w")
        self.logs.tag_configure("ok", foreground=SUCCESS)
        self.logs.tag_configure("bad", foreground=DANGER)
        self.logs.tag_configure("warn", foreground=WARNING)
        scroll = ttk.Scrollbar(logs, orient="vertical", command=self.logs.yview)
        self.logs.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.logs.pack(fill="both", expand=True)
        self.logs.bind("<ButtonRelease-1>", self._on_log_click)
        self._snapshots: dict[str, str] = {}
        self._leaving = False
        self.refresh()
        self._tick_lockout()

    # ---------- dữ liệu ----------

    def refresh(self) -> None:
        for child in self.user_list.winfo_children():
            child.destroy()
        users = self.ctx.users.list_users()
        self.users_title.configure(text=f"Người dùng ({len(users)})")
        for u in users:
            self._user_row(u)
        self.logs.delete(*self.logs.get_children())
        self._snapshots.clear()
        for row in self.ctx.logs.list():
            if row["event"] in HIDDEN_EVENTS:
                continue
            result, tag = RESULTS.get(row["event"], (row["event"], ""))
            who = row["name"] or ("Người lạ" if row["snapshot"] else "—")
            time = datetime.fromisoformat(row["timestamp"]).strftime("%d/%m %H:%M")
            iid = self.logs.insert("", "end", values=(time, who, result, "Xem" if row["snapshot"] else "—"),
                                   tags=(tag,))
            if row["snapshot"]:
                self._snapshots[iid] = row["snapshot"]

    def _user_row(self, u: dict) -> None:
        row = tk.Frame(self.user_list, bg=CARD, highlightbackground="#e2e0da", highlightthickness=1,
                       padx=10, pady=6)
        row.pack(fill="x", pady=(0, 8))
        text = tk.Frame(row, bg=CARD)
        text.pack(side="left")
        tk.Label(text, text=u["name"], bg=CARD, fg=TEXT, font=font(LABEL_SIZE, "bold")).pack(anchor="w")
        sub = f"{u['photos']} ảnh" if u["valid"] else "⚠ Dữ liệu bị can thiệp"
        tk.Label(text, text=sub, bg=CARD, fg=MUTED if u["valid"] else DANGER, font=font(CAPTION_SIZE)).pack(anchor="w")
        button(row, "✕", lambda uid=u["id"], name=u["name"]: self._delete(uid, name), "secondary").pack(side="right")

    def destroy(self) -> None:
        # getattr: màn hình có thể bị hủy khi đang dựng dở (lỗi DB trong __init__), lúc đó chưa có job.
        job = getattr(self, "_lockout_job", None)
        if job is not None:
            self.after_cancel(job)
        super().destroy()

    def _tick_lockout(self) -> None:
        """Banner khóa / Face ID tắt, cập nhật mỗi giây; lỗi DB thoáng qua không làm banner ngừng cập nhật."""
        try:
            lines = []
            wait = self.ctx.lockout.remaining()
            if self.ctx.lockout.admin_only():
                lines.append("Cửa bị khóa: chỉ quản trị mở được")
            elif wait:
                lines.append(f"Cửa đang khóa tạm ({wait // 60}:{wait % 60:02d})")
            if self.ctx.faces.disabled():
                lines.append("Face ID đang tạm tắt")
            if lines:
                self.lockout_text.configure(text="\n".join(lines))
                self.lockout_banner.pack(side="bottom", fill="x")
            else:
                self.lockout_banner.pack_forget()
        finally:
            self._lockout_job = self.after(1000, self._tick_lockout)

    # ---------- thao tác ----------

    def on_frame(self, r: FrameResult) -> None:
        if not self.ctx.admin.is_active():
            self._back("Phiên admin đã hết hạn.")

    def _guard(self) -> bool:
        if not self.ctx.admin.is_active():
            self._back("Phiên admin đã hết hạn.")
            return False
        self.ctx.admin.touch()
        return True

    def _enroll(self) -> None:
        if self._guard():
            from ui.enroll_screen import EnrollScreen
            self.app.show(EnrollScreen)

    def _delete(self, uid: int, name: str) -> None:
        if self._guard() and messagebox.askyesno(
                "Xóa người dùng", f"Xóa {name} cùng dữ liệu khuôn mặt và ảnh liên quan?", parent=self.app):
            try:
                self.ctx.enroll.delete_user(uid)
            except EnrollmentError as exc:  # phiên hết hạn trong lúc hộp thoại xác nhận đang mở
                self._back(str(exc))
                return
            self.refresh()

    def _clear_lockout(self) -> None:
        if self._guard():
            self.ctx.lockout.clear()
            self.ctx.faces.reset()
            self.refresh()

    def _on_log_click(self, event) -> None:
        iid = self.logs.identify_row(event.y)
        if self.logs.identify_column(event.x) != "#4" or iid not in self._snapshots or not self._guard():
            return
        name = self._snapshots[iid]
        try:
            image = self.ctx.logger.load_snapshot(name)
        except (OSError, InvalidToken):
            messagebox.showerror("Ảnh", "Không đọc được ảnh (đã bị xóa hoặc bị sửa).", parent=self.app)
            return
        window = tk.Toplevel(self)
        window.title("Ảnh người lạ")
        label = tk.Label(window)
        label.pack()
        show_frame(label, image, width=480)

    def _export(self) -> None:
        if not self._guard():
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], parent=self.app)
        if path and self._guard():  # phiên có thể đã hết trong lúc hộp thoại chọn file đang mở
            self.ctx.logs.export_csv(path)

    def _logout(self) -> None:
        self.ctx.admin.logout()
        self._back()

    def _back(self, message: str | None = None) -> None:
        # Gọi lặp khi hộp thoại đang mở (vòng sự kiện lồng nhau vẫn chạy on_frame): chỉ xử lý lần đầu.
        if self._leaving or self.app.screen is not self:
            return
        self._leaving = True
        if message:  # hiện trước khi về màn chính để không có phiên xác thực nào chạy ngầm sau hộp thoại
            messagebox.showinfo("Quản trị", message, parent=self.app)
        from ui.main_screen import MainScreen
        self.app.show(MainScreen)
