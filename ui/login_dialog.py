"""Hộp thoại đăng nhập quản trị."""
import tkinter as tk
from tkinter import ttk

from ui.app import CAPTION_SIZE, CARD, DANGER, HEADING_SIZE, LABEL_SIZE, MUTED, TEXT, button, font


def show_password_toggle(master, entry: tk.Entry) -> ttk.Checkbutton:
    """Ô tích "Hiện mật khẩu": thấy được chữ bộ gõ tiếng Việt đã đổi (aa → â) trước khi bấm Đăng nhập."""
    shown = tk.BooleanVar(master, False)
    return ttk.Checkbutton(master, text="Hiện mật khẩu", variable=shown,
                           command=lambda: entry.configure(show="" if shown.get() else "●"))


def ask_admin_login(app) -> bool:
    """Mở hộp thoại modal; trả True nếu đăng nhập thành công."""
    win = tk.Toplevel(app, bg=CARD, padx=28, pady=24)
    win.title("Đăng nhập quản trị")
    win.resizable(False, False)
    win.transient(app)
    result = {"ok": False}

    tk.Label(win, text="Đăng nhập quản trị", bg=CARD, fg=TEXT, font=font(HEADING_SIZE, "bold")).pack(anchor="w")
    tk.Label(win, text="Cần mật khẩu admin để đăng ký hoặc quản lý người dùng.", bg=CARD, fg=MUTED,
             font=font(LABEL_SIZE)).pack(anchor="w", pady=(4, 16))
    tk.Label(win, text="Mật khẩu", bg=CARD, fg=MUTED, font=font(LABEL_SIZE)).pack(anchor="w")
    entry = tk.Entry(win, show="●", width=34)
    entry.pack(anchor="w", ipady=4, pady=(4, 6))
    show_password_toggle(win, entry).pack(anchor="w", pady=(0, 6))
    error = tk.Label(win, text="", bg=CARD, fg=DANGER, font=font(CAPTION_SIZE), wraplength=340, justify="left")
    error.pack(anchor="w")

    def submit(_event=None) -> None:
        ok, message = app.ctx.admin.login(entry.get())
        entry.delete(0, "end")
        if ok:
            result["ok"] = True
            win.destroy()
        else:
            error.configure(text=message)

    actions = tk.Frame(win, bg=CARD)
    actions.pack(fill="x", pady=(40, 0))
    button(actions, "Hủy", win.destroy, "secondary").pack(side="left", expand=True, fill="x", padx=(0, 6))
    button(actions, "Đăng nhập", submit).pack(side="left", expand=True, fill="x", padx=(6, 0))
    entry.bind("<Return>", submit)
    win.bind("<Escape>", lambda _e: win.destroy())

    win.update_idletasks()
    x = app.winfo_rootx() + (app.winfo_width() - win.winfo_width()) // 2
    y = app.winfo_rooty() + (app.winfo_height() - win.winfo_height()) // 2
    win.geometry(f"+{x}+{y}")
    win.grab_set()
    entry.focus_set()
    app.wait_window(win)
    return result["ok"]
