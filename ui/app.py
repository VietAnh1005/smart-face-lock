"""Cửa sổ gốc, bảng màu và các thành phần giao diện dùng chung."""
import multiprocessing
import queue
import sys
import time
import tkinter as tk
import traceback
from dataclasses import dataclass
from functools import lru_cache
from tkinter import font as tkfont, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from config import settings
from services.frame_result import FrameResult
from ui.vision_worker import VisionWorker

TICK_MS = 30
PURGE_INTERVAL_MS = 60 * 60 * 1000  # xóa nhật ký quá hạn mỗi giờ
ERROR_REPEAT_SECONDS = 60           # cùng một lỗi chỉ bật hộp thoại tối đa 1 lần/phút
WINDOW_SIZE = "1000x660"
VIDEO_WIDTH = 520

# Bảng màu
BG = "#f4f3ef"          # nền cửa sổ
CARD = "#ffffff"        # nền thẻ
BORDER = "#e2e0da"
HEADER = "#1f1f1f"      # thanh tiêu đề
CAMERA_BG = "#2b2b2b"
TEXT = "#1f1f1f"
MUTED = "#6b6b6b"
PRIMARY = "#1e4fa3"     # nút chính (xanh dương)
DANGER = "#b3261e"
DANGER_BG = "#fbe3e1"
SUCCESS = "#2e7d32"
SUCCESS_BG = "#e3f1e4"
WARNING = "#a86b00"
DISABLED = "#c8c7c2"
FONT = "Arial"  # có trên cả Windows và macOS, đủ dấu tiếng Việt
# Thang cỡ chữ (point) dùng chung cho mọi màn hình; cùng vai trò thì cùng cỡ
CAPTION_SIZE = 9    # chú thích: chip, CAMERA LIVE, banner, lỗi nhỏ
LABEL_SIZE = 10     # nhãn ô, nhãn dòng, thông báo, nút, bảng
INPUT_SIZE = 12     # chữ trong ô nhập và dropdown
TITLE_SIZE = 12     # tiêu đề thẻ (đậm)
HEADING_SIZE = 14   # thanh tiêu đề, tiêu đề hộp thoại
DISPLAY_SIZE = 16   # dòng trạng thái khóa


def font(size: int = LABEL_SIZE, weight: str = "normal") -> tuple:
    return (FONT, size, weight)


def card(master, **pack) -> tk.Frame:
    """Thẻ nền trắng, viền xám mảnh."""
    frame = tk.Frame(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=12)
    if pack:
        frame.pack(**pack)
    return frame


def relock_if_expired(lock, log, was_locked: bool) -> bool:
    """Hết thời gian mở: gửi lệnh khóa rồi ghi LOCK. Trả True nếu đã hết hạn mở.

    Dựa vào seconds_open() (hạn chót tính từ lần unlock), KHÔNG dựa vào is_locked(): khóa thật có thể
    báo is_locked() theo relay, firmware không tự đóng thì is_locked() cứ False và lệnh khóa không bao giờ đi.
    Hai lớp bảo vệ: firmware nên tự đóng sau `seconds`, app vẫn gửi lock() khi hết hạn.
    """
    expired = lock.seconds_open() <= 0
    if expired and not was_locked:
        lock.lock()
        log("LOCK")
    return expired


def style_inputs(root: tk.Misc) -> None:
    """Ô nhập trông giống nhau trên mọi máy.

    - Màu của app, không theo giao diện sáng/tối: macOS giao diện tối cho chữ màu trắng,
      trên nền trắng của app thì gõ vào không thấy gì.
    - Một cỡ chữ (INPUT_SIZE) cho mọi ô nhập; ô tích nền trắng, không viền chấm, dấu tích màu chính.
    - Viền mảnh: xám khi chưa chọn, xanh khi đang nhập (thay cho viền đen dày của Tk).
    - Bỏ bôi chọn phần chữ đang soạn của bộ gõ (Telex/VNI): Tk 9 hiển thị nó bằng selection,
      mật khẩu/PIN liền mạch nên bị bôi suốt. Bộ gõ vẫn hoạt động, chỉ không tô màu.
    """
    for key, value in (("foreground", TEXT), ("background", CARD), ("insertBackground", TEXT),
                       ("disabledForeground", MUTED), ("disabledBackground", "#efeeea"),
                       ("relief", "flat"), ("borderWidth", 0), ("highlightThickness", 1),
                       ("highlightColor", PRIMARY), ("highlightBackground", "#bdbbb4"),
                       ("font", font(INPUT_SIZE))):
        root.option_add(f"*Entry.{key}", value)
    style = ttk.Style(root)
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=font(LABEL_SIZE), focuscolor=CARD,
                    indicatorbackground=CARD, indicatorforeground=PRIMARY)
    style.map("TCheckbutton", background=[("active", CARD)])
    root.bind_class("Entry", "<<TkEndIMEMarkedText>>", "")


def button(master, text: str, command, kind: str = "primary", size: int = LABEL_SIZE) -> tk.Widget:
    """kind: primary (xanh), secondary (viền xám), dark (viền xám trên thanh tiêu đề).

    Nút Tkinter trên Windows không vẽ được viền màu, nên nút có viền được bọc trong một
    Frame màu viền dày 1px. Trả về widget để pack; nút thật nằm ở thuộc tính `.button`.
    """
    styles = {
        "primary": dict(bg=PRIMARY, fg="white", activebackground="#173f84", activeforeground="white",
                        disabledforeground="white"),
        # disabledforeground luôn đặt: mặc định của hệ thống ở giao diện tối gần trắng, mất chữ trên nền trắng
        "secondary": dict(bg=CARD, fg=TEXT, activebackground=BG, disabledforeground=MUTED),
        "dark": dict(bg=HEADER, fg="white", activebackground="#333333", activeforeground="white",
                     disabledforeground="#8a8a8a"),
    }
    border = {"secondary": "#bdbbb4", "dark": "#8a8a8a"}.get(kind)
    outer = tk.Frame(master, bg=border) if border else None
    # Label thay cho tk.Button: nút gốc của macOS bỏ qua bg (chữ trắng trên nền sáng → chìm),
    # Label tô đúng màu trên cả Windows lẫn macOS.
    btn = tk.Label(outer or master, text=text, relief="flat", bd=0, cursor="hand2",
                   font=font(size, "bold" if kind == "primary" else "normal"), padx=12, pady=5,
                   **styles[kind])

    def hover(state: str):
        return lambda _e: btn["state"] != "disabled" and btn.configure(state=state)

    btn.bind("<Enter>", hover("active"))
    btn.bind("<Leave>", hover("normal"))
    # Như nút chuẩn: chỉ chạy khi nhả tay còn trong nút (ấn rồi kéo ra ngoài để hủy)
    btn.bind("<ButtonRelease-1>", lambda e: btn["state"] != "disabled"
             and 0 <= e.x < btn.winfo_width() and 0 <= e.y < btn.winfo_height() and command())
    if outer is None:
        btn.button = btn
        return btn
    btn.pack(fill="both", expand=True, padx=1, pady=1)
    outer.button = btn
    return outer


def set_enabled(widget: tk.Widget, enabled: bool) -> None:
    """Nút primary bị tắt thì chuyển xám."""
    btn = widget.button
    btn.configure(state="normal" if enabled else "disabled")
    if btn["fg"] == "white" and btn["bg"] in (PRIMARY, DISABLED):
        btn.configure(bg=PRIMARY if enabled else DISABLED)


def header(master, title: str, back=None, right=None) -> tk.Frame:
    """Thanh tiêu đề đen: [← Quay lại] TIÊU ĐỀ ........ [widget bên phải]."""
    bar = tk.Frame(master, bg=HEADER, padx=18, pady=10)
    bar.pack(fill="x")
    if back is not None:
        button(bar, "← Quay lại", back, "dark").pack(side="left", padx=(0, 14))
    tk.Label(bar, text=title, bg=HEADER, fg="white", font=font(HEADING_SIZE, "bold")).pack(side="left")
    if right is not None:
        right(bar).pack(side="right")
    return bar


# Màu chỉ dùng cho điểm nhấn nhỏ: chấm trạng thái, viền khung camera/khung mặt, vạch thời gian.
# tone: "" = chờ (xám), "run" = đang làm (trắng), "ok" = thành công (xanh), "bad" = từ chối (đỏ)
TONE_RGB = {"": (201, 201, 201), "run": (255, 255, 255), "ok": (95, 176, 108), "bad": (208, 100, 91)}
TONE_HEX = {"": "#a5a39d", "run": TEXT, "ok": SUCCESS, "bad": DANGER}


class NoticeBar(tk.Frame):
    """Dòng thông báo dưới cùng: nền trung tính, chấm màu nhỏ + câu đầy đủ."""

    def __init__(self, master) -> None:
        super().__init__(master, bg=BG, padx=18, pady=9)
        self._dot = tk.Label(self, text="●", bg=BG, font=font(CAPTION_SIZE))
        self._dot.pack(side="left")
        self._text = tk.Label(self, bg=BG, fg=TEXT, font=font(LABEL_SIZE), anchor="w")
        self._text.pack(side="left", fill="x", padx=(6, 0))

    def set(self, text: str, tone: str = "") -> None:
        self._dot.configure(fg=TONE_HEX.get(tone, TONE_HEX[""]))
        self._text.configure(text=text)


def notice_bar(master) -> NoticeBar:
    """Gọi trước khi pack phần thân để thanh thông báo luôn nằm đáy."""
    bar = NoticeBar(master)
    bar.pack(side="bottom", fill="x")
    tk.Frame(master, bg=BORDER, height=1).pack(side="bottom", fill="x")
    return bar


class CameraPanel(tk.Frame):
    """Khung camera nền tối có nhãn CAMERA LIVE; hướng dẫn được vẽ thẳng lên video (xem draw_overlay)."""

    def __init__(self, master) -> None:
        super().__init__(master, bg=CAMERA_BG, padx=10, pady=10)
        self.video = tk.Label(self, bg=CAMERA_BG)
        self.video.pack()
        tk.Label(self, text="CAMERA LIVE", bg=CAMERA_BG, fg="#d6d6d6", font=font(CAPTION_SIZE)).place(x=12, y=8)


@dataclass
class Overlay:
    """Lớp chữ trên video: dòng chính, dòng phụ, số giây và vạch thời gian (progress 0..1)."""
    main: str
    sub: str = ""
    tone: str = ""
    seconds: str = ""
    progress: float | None = None


@lru_cache(maxsize=8)
def _pil_font(size: int, bold: bool = False):
    # Arial trên cả 2 hệ điều hành nhưng khác tên file: arial.ttf / arialbd.ttf (Windows, Pillow phân biệt
    # hoa thường) và Arial.ttf / Arial Bold.ttf (macOS). Font mặc định của Pillow không có dấu tiếng Việt.
    for name in (("arialbd.ttf", "Arial Bold.ttf") if bold else ("arial.ttf", "Arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


@lru_cache(maxsize=4)
def _scrim(width: int, height: int) -> Image.Image:
    """Lớp nền tối mờ dần từ trong suốt (trên) đến đậm (dưới)."""
    alpha = np.linspace(0, 200, height).astype(np.uint8)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.putalpha(Image.fromarray(np.repeat(alpha[:, None], width, axis=1)))
    return layer


def draw_overlay(img: Image.Image, ov: Overlay) -> Image.Image:
    w, h = img.size
    base = img.convert("RGBA")
    base.alpha_composite(_scrim(w, 90), (0, h - 90))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # vẽ lên lớp trong suốt rồi ghép để màu bán trong suốt hòa đúng
    draw = ImageDraw.Draw(layer)
    color = TONE_RGB.get(ov.tone, TONE_RGB[""])
    draw.ellipse((16, h - 52, 24, h - 44), fill=color)
    draw.text((32, h - 60), ov.main, font=_pil_font(17, True), fill="white")
    if ov.sub:
        draw.text((16, h - 32), ov.sub, font=_pil_font(12), fill=(255, 255, 255, 185))
    if ov.seconds:
        small = _pil_font(12)
        draw.text((w - 16 - draw.textlength(ov.seconds, font=small), h - 56), ov.seconds, font=small,
                  fill=(255, 255, 255, 190))
    if ov.progress is not None:
        draw.rectangle((0, h - 3, w, h), fill=(255, 255, 255, 40))
        bar = color if ov.tone in ("ok", "bad") else (255, 255, 255, 220)
        draw.rectangle((0, h - 3, int(w * max(0.0, min(1.0, ov.progress))), h), fill=bar)
    if ov.tone in ("ok", "bad"):
        draw.rectangle((0, 0, w - 1, h - 1), outline=color, width=3)  # viền kết quả
    base.alpha_composite(layer)
    return base.convert("RGB")


class Chip(tk.Label):
    """Ô bước: chờ (xám) / đang làm (đen) / xong (xanh lá, có ✓)."""

    def __init__(self, master, text: str) -> None:
        super().__init__(master, font=font(CAPTION_SIZE), padx=8, pady=3)
        self._text = text
        self.set("pending")

    def set(self, status: str) -> None:
        colors = {"pending": ("#e6e5e0", MUTED), "active": (HEADER, "white"), "done": (SUCCESS_BG, SUCCESS)}
        bg, fg = colors[status]
        self.configure(bg=bg, fg=fg, text=self._text + (" ✓" if status == "done" else ""))


class Dropdown(tk.Frame):
    """Ô chọn tự vẽ thay cho ttk.Combobox.

    Combobox trên macOS tô xanh đậm ô đã chọn và danh sách thả xuống luôn màu xám tối
    (không đổi được bằng style). Ở đây: ô trắng + mũi tên; danh sách là một Listbox trắng nổi
    ngay dưới ô (không đủ chỗ thì mở lên trên), tự cuộn khi đông người, dòng đang chọn nền
    xanh nhạt có dấu ✓. Đóng khi chọn, chạm lại vào ô, chạm ra ngoài hoặc nhấn Esc.
    """

    def __init__(self, master, placeholder: str) -> None:
        super().__init__(master, bg=CARD, highlightthickness=1, highlightbackground="#bdbbb4", cursor="hand2")
        self._placeholder = placeholder
        self._values: list[str] = []
        self._index = -1
        self._popup: tk.Frame | None = None
        self._list: tk.Listbox | None = None
        self._bindings: list[tuple[str, str]] = []
        # pady=1 như đệm trong sẵn có của tk.Entry: _field() trong màn hình đã thêm ipady cho mọi ô,
        # nên dropdown cao đúng bằng ô nhập (test_dropdown_matches_entry_height_and_font)
        self._field = tk.Label(self, bg=CARD, anchor="w", font=font(INPUT_SIZE), padx=12, pady=1, bd=0)
        self._field.pack(side="left", fill="x", expand=True)
        self._arrow = tk.Label(self, bg=CARD, fg=MUTED, font=font(INPUT_SIZE), padx=12, pady=1, bd=0)
        self._arrow.pack(side="right")
        for widget in (self, self._field, self._arrow):
            widget.bind("<ButtonRelease-1>", lambda _e: self.toggle())
        self._render()

    def set_values(self, values: list[str]) -> None:
        """Danh sách mới: đóng lại và bỏ lựa chọn cũ."""
        self._values = list(values)
        self._index = -1
        self.close()

    def current(self, index: int | None = None) -> int:
        """Như ttk.Combobox.current: không đối số thì trả vị trí đang chọn (-1 = chưa chọn)."""
        if index is not None:
            self._index = index
            self._render()
        return self._index

    def text(self) -> str:
        return self._field["text"]

    def is_open(self) -> bool:
        return self._popup is not None

    def listbox(self) -> tk.Listbox | None:
        return self._list

    def toggle(self) -> None:
        if self._popup is not None:
            self.close()
        elif self._values:
            self._open()
            self._render()

    def close(self) -> None:
        if self._popup is not None:
            top = self.winfo_toplevel()
            for sequence, funcid in self._bindings:
                top.unbind(sequence, funcid)
            self._bindings = []
            self._popup.destroy()
            self._popup = self._list = None
        self._render()

    def _render(self) -> None:
        picked = self._index >= 0
        self._field.configure(text=self._values[self._index] if picked else self._placeholder,
                              fg=TEXT if picked else MUTED)  # cùng font với ô nhập; chữ đậm trông to hơn
        self._arrow.configure(text="▴" if self._popup else "▾")
        # Chỉ đổi màu viền như ô nhập; đổi độ dày sẽ làm cả form nhích 1px mỗi lần mở/đóng
        self.configure(highlightbackground=PRIMARY if self._popup else "#bdbbb4")

    def _open(self) -> None:
        top = self.winfo_toplevel()
        self._popup = tk.Frame(top, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=4, pady=4)
        self._list = tk.Listbox(self._popup, font=font(INPUT_SIZE), bd=0, highlightthickness=0, activestyle="none",
                                bg=CARD, fg=TEXT, selectbackground="#e8eef8", selectforeground=PRIMARY,
                                selectborderwidth=0, exportselection=False, cursor="hand2")
        for i, value in enumerate(self._values):
            self._list.insert("end", f"  {value}  ✓" if i == self._index else f"  {value}")
        # Đủ chỗ phía dưới thì mở xuống, không thì mở lên phía còn nhiều chỗ hơn; vẫn thiếu thì cuộn.
        item = tkfont.Font(top, font=font(INPUT_SIZE)).metrics("linespace") + 2
        y_top = self.winfo_rooty() - top.winfo_rooty()
        below = top.winfo_height() - (y_top + self.winfo_height()) - 16
        # Mở lên trên chỉ trong khung chứa ô (thẻ form), không che thanh tiêu đề / nút Admin phía trên
        card = self.master.master if self.master is not top else top
        above = y_top - (card.winfo_rooty() - top.winfo_rooty()) - 16
        down = len(self._values) * item <= below or below >= above
        rows = max(1, min(len(self._values), (below if down else above) // item))
        self._list.configure(height=rows)
        if rows < len(self._values):
            bar = ttk.Scrollbar(self._popup, orient="vertical", command=self._list.yview)
            self._list.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y")
        self._list.pack(side="left", fill="both", expand=True)
        if self._index >= 0:
            self._list.selection_set(self._index)
            self._list.see(self._index)
        # Chọn lúc NHẢ: chọn lúc ấn sẽ đóng danh sách giữa chừng và cú nhả rơi xuống nút bên dưới
        self._list.bind("<ButtonRelease-1>", self._on_release)
        # in_=self: Tk tự giữ danh sách bám đúng vị trí và độ rộng của ô khi cửa sổ đổi cỡ.
        # relwidth tính bên trong viền 1px của ô, nên x=-1, width=+2 để danh sách rộng đúng bằng ô.
        if down:
            self._popup.place(in_=self, relx=0, rely=1, x=-1, y=4, relwidth=1, width=2)
        else:
            self._popup.place(in_=self, relx=0, rely=0, x=-1, y=-4, relwidth=1, width=2, anchor="sw")
        self._popup.lift()
        height = top.winfo_height()
        self._bindings = [
            ("<Escape>", top.bind("<Escape>", lambda _e: self.close(), add="+")),
            ("<ButtonPress-1>", top.bind("<ButtonPress-1>", self._on_click_anywhere, add="+")),
            # Số dòng chỉ tính lúc mở: cửa sổ thấp đi thì đóng, tránh danh sách tràn ra ngoài
            ("<Configure>", top.bind("<Configure>", lambda e: e.widget is top and e.height < height
                                     and self.close(), add="+")),
        ]

    def _on_release(self, event) -> None:
        if self._list is None or not 0 <= event.y < self._list.winfo_height() or not self._values:
            return  # nhả ngoài danh sách (kéo ra để hủy)
        self._index = self._list.nearest(event.y)
        self.close()

    def _on_click_anywhere(self, event) -> None:
        """Chạm ra ngoài ô và danh sách thì đóng (bind trên cửa sổ gốc nhận mọi cú chạm trong cửa sổ)."""
        name = str(event.widget)
        if not (name.startswith(str(self._popup)) or name.startswith(str(self))):
            self.close()

    def destroy(self) -> None:
        self.close()  # danh sách nằm trên cửa sổ gốc, không tự hủy theo ô chọn
        super().destroy()


def show_frame(label: tk.Label, frame_bgr, boxes=(), width: int = VIDEO_WIDTH,
               overlay: Overlay | None = None) -> None:
    """Vẽ khung mặt, lật ảnh như gương, vẽ lớp chữ hướng dẫn rồi hiển thị lên label."""
    img = frame_bgr.copy()
    r, g, b = TONE_RGB["ok"] if overlay is None or overlay.tone not in ("ok", "bad") else TONE_RGB[overlay.tone]
    for top, right, bottom, left in boxes:
        cv2.rectangle(img, (left, top), (right, bottom), (b, g, r), 3)  # OpenCV dùng thứ tự BGR
    img = cv2.flip(img, 1)
    h, w = img.shape[:2]
    img = cv2.resize(img, (width, int(h * width / w)))
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if overlay is not None:
        pil = draw_overlay(pil, overlay)
    photo = ImageTk.PhotoImage(pil)
    label.configure(image=photo)
    label.image = photo  # giữ tham chiếu, nếu không ảnh bị thu hồi


class App(tk.Tk):
    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.title("Smart Face Lock")
        self.geometry(WINDOW_SIZE)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.report_callback_exception = self._on_error
        style = ttk.Style(self)
        style.theme_use("clam")
        style_inputs(self)
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                        rowheight=28, font=font(LABEL_SIZE),
                        borderwidth=0)
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED, font=font(LABEL_SIZE), relief="flat")
        style.configure("Blue.Horizontal.TProgressbar", troughcolor="#e6e5e0", background=PRIMARY,
                        bordercolor="#e6e5e0", lightcolor=PRIMARY, darkcolor=PRIMARY, thickness=8)
        self._frames = multiprocessing.Queue(maxsize=1)  # FrameResult từ process xử lý
        self.worker = VisionWorker(self._frames)
        self.worker.start()
        self._was_locked = True
        self._showing_error = False
        self._last_error_at = -ERROR_REPEAT_SECONDS  # lỗi đầu tiên luôn được báo bằng hộp thoại
        self._boxes: list = []
        self.screen = None
        from ui.main_screen import MainScreen
        self.show(MainScreen)
        self.after(TICK_MS, self._tick)
        self._purge_old_logs()  # xóa ngay khi khởi động, sau đó lặp lại mỗi giờ

    def show(self, screen_cls) -> None:
        old, self.screen = self.screen, None  # không để self.screen trỏ vào màn hình đã hủy nếu dựng màn mới lỗi
        if old is not None:
            old.destroy()
        try:
            screen = screen_cls(self)
        except Exception:
            from ui.main_screen import MainScreen
            if screen_cls is MainScreen:
                self.after(2000, lambda: self.show(MainScreen))  # màn chính lỗi: thử dựng lại, không để trắng mãi
                raise
            screen = MainScreen(self)  # dựng màn hình lỗi (vd. DB bị khóa): quay về màn chính
            self._on_error(*sys.exc_info())
        self.screen = screen
        screen.pack(fill="both", expand=True)

    def _tick(self) -> None:
        try:
            self._tick_once()
        except Exception:
            self._on_error(*sys.exc_info())
        finally:
            self.after(TICK_MS, self._tick)  # luôn lên lịch lại: một lỗi không được làm đứng cả ứng dụng

    def _tick_once(self) -> None:
        if self.screen is None:
            return
        try:
            result = self._frames.get_nowait()
        except queue.Empty:
            result = None
        if not self.worker.is_alive():  # một tiến trình chết: báo lỗi ở mọi tick, không xen kẽ với kết quả cũ
            result = FrameResult(None, error="Tiến trình xử lý ảnh đã dừng. Hãy khởi động lại ứng dụng.")
        if result is not None:
            self._boxes = result.boxes
            self.screen.on_frame(result)
        tick = getattr(self.screen, "tick", None)
        if tick is not None:
            tick()  # cập nhật đếm ngược mượt theo nhịp vẽ, không chờ kết quả xử lý ảnh
        # Video vẽ frame camera mới nhất ở mọi tick; khung mặt lấy từ lần xử lý gần nhất.
        frame = self.worker.latest_frame()
        video = getattr(self.screen, "video", None)
        if frame is not None and video is not None:
            show_frame(video, frame, self._boxes, overlay=getattr(self.screen, "overlay", None))
        self._was_locked = relock_if_expired(self.ctx.lock, self.ctx.logger.log, self._was_locked)

    def _purge_old_logs(self) -> None:
        """Xóa nhật ký và ảnh quá hạn định kỳ, kể cả khi ứng dụng chạy liên tục nhiều ngày."""
        try:
            self.ctx.logs.purge_older_than(settings.LOG_RETENTION_DAYS)
        finally:
            self.after(PURGE_INTERVAL_MS, self._purge_old_logs)

    def _on_error(self, exc_type, exc, tb) -> None:
        traceback.print_exception(exc_type, exc, tb)
        self.ctx.lock.lock()  # fail-secure
        text = f"Đã xảy ra lỗi: {exc}"
        now = time.monotonic()
        # Lỗi kéo dài (vd. DB bị chương trình khác khóa) lặp lại ở mọi tick: không bật hộp thoại liên tục,
        # kể cả khi nhiều lỗi khác nhau xen kẽ; trong lúc chờ thì hiện ở thanh thông báo.
        if self._showing_error or now - self._last_error_at < ERROR_REPEAT_SECONDS:
            if self.screen is not None and hasattr(self.screen, "notice"):
                self.screen.notice.set(text, "bad")
            return
        self._showing_error = True
        try:
            messagebox.showerror("Lỗi", text, parent=self)
        finally:
            self._showing_error = False
            self._last_error_at = time.monotonic()

    def close(self) -> None:
        try:
            self.ctx.auth.abort()  # tắt app giữa phiên đã khớp mặt vẫn bị tính một lần sai
        except Exception:
            traceback.print_exc()
        finally:
            self.ctx.lock.lock()
            self.worker.stop()
            self.destroy()
