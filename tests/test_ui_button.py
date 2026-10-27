import tkinter as tk

import pytest

from ui.app import PRIMARY, button, set_enabled


def test_button_keeps_color_and_ignores_clicks_when_disabled():
    root = tk.Tk()
    try:
        hits = []
        w = button(root, "X", lambda: hits.append(1))
        w.pack()
        root.update()
        b = w.button
        assert b["bg"] == PRIMARY  # nút gốc macOS bỏ qua bg; Label thì giữ
        b.event_generate("<ButtonRelease-1>")
        set_enabled(w, False)
        b.event_generate("<ButtonRelease-1>")
        set_enabled(w, True)
        b.event_generate("<ButtonRelease-1>")
        assert hits == [1, 1]
    finally:
        root.destroy()


def test_entries_use_app_colors_not_system_theme():
    """macOS giao diện tối: chữ ô nhập mặc định màu trắng, trên nền trắng của app thì không thấy gì."""
    from tkinter import font as tkfont, ttk

    from ui.app import CARD, INPUT_SIZE, PRIMARY, TEXT, style_inputs

    root = tk.Tk()
    try:
        style_inputs(root)
        entry = tk.Entry(root)
        assert (entry["foreground"], entry["background"], entry["insertbackground"]) == (TEXT, CARD, TEXT)
        # Viền mảnh: xám khi chưa chọn, xanh khi đang nhập (không còn viền đen dày)
        assert (int(entry["borderwidth"]), int(entry["highlightthickness"])) == (0, 1)
        assert (entry["highlightcolor"], entry["highlightbackground"]) == (PRIMARY, "#bdbbb4")
        assert tkfont.Font(root, font=entry["font"]).actual("size") == INPUT_SIZE   # một cỡ chữ cho mọi ô nhập
        style = ttk.Style(root)                          # ô tích: nền trắng khi rê chuột, không viền chấm
        assert style.lookup("TCheckbutton", "background", ["active"]) == CARD
        assert style.lookup("TCheckbutton", "focuscolor") == CARD
        # Bộ gõ tiếng Việt: Tk bôi chọn phần chữ đang soạn, mật khẩu liền mạch nên bị bôi suốt.
        assert root.bind_class("Entry", "<<TkEndIMEMarkedText>>") == ""
    finally:
        root.update()
        root.destroy()


def test_show_password_toggle():
    from ui.login_dialog import show_password_toggle

    root = tk.Tk()
    try:
        entry = tk.Entry(root, show="●")
        toggle = show_password_toggle(root, entry)
        toggle.invoke()
        assert entry["show"] == ""
        toggle.invoke()
        assert entry["show"] == "●"
    finally:
        root.update()
        root.destroy()


@pytest.mark.parametrize("kind", ["primary", "secondary", "dark"])
def test_disabled_button_text_uses_app_color(kind):
    """Màu chữ nút tắt không lấy của hệ thống: giao diện tối cho màu gần trắng, trên nền trắng thì mất chữ."""
    root = tk.Tk()
    try:
        w = button(root, "X", lambda: None, kind)
        set_enabled(w, False)
        assert not str(w.button["disabledforeground"]).startswith("system")
    finally:
        root.update()
        root.destroy()


# ---------- Dropdown ----------

@pytest.fixture
def form():
    """Cửa sổ có dropdown và ô PIN xếp như _field() trong màn chính."""
    from ui.app import Dropdown, style_inputs

    root = tk.Tk()
    root.geometry("400x300")
    style_inputs(root)
    dd, entry = Dropdown(root, "Chọn tên của bạn"), tk.Entry(root)
    for w in (dd, entry):
        w.pack(fill="x", ipady=4, padx=10, pady=4)
    dd.set_values(["NVA", "TTB", "V"])
    root.update()
    yield root, dd, entry
    root.update()
    root.destroy()


def pick(root, dd, index):
    """Chạm vào một dòng: chọn ở lúc NHẢ (như nút), không phải lúc ấn."""
    lb = dd.listbox()
    lb.see(index)
    root.update()
    x, y, _w, _h = lb.bbox(index)
    lb.event_generate("<ButtonRelease-1>", x=x + 2, y=y + 2)
    root.update()


def test_dropdown_opens_picks_and_closes(form):
    root, dd, _ = form
    assert dd.current() == -1 and dd.text() == "Chọn tên của bạn"
    dd.toggle()
    root.update()
    assert dd.is_open() and dd.listbox().size() == 3
    pick(root, dd, 2)
    assert (dd.current(), dd.text(), dd.is_open()) == (2, "V", False)
    dd.set_values(["NVA"])                        # danh sách mới: bỏ lựa chọn cũ
    assert dd.current() == -1
    dd.current(0)
    assert dd.text() == "NVA"


def test_dropdown_matches_entry_height_and_font(form):
    """Cùng cỡ cao và cùng một font với ô nhập; mở danh sách không làm ô dày viền (form không nhích)."""
    from tkinter import font as tkfont

    root, dd, entry = form
    assert dd.winfo_height() == entry.winfo_height()
    before = int(dd["highlightthickness"])
    dd.toggle()
    root.update()
    assert int(dd["highlightthickness"]) == before
    actual = lambda w: str(tkfont.Font(root, font=w["font"]).actual())
    assert {actual(entry), actual(dd._field), actual(dd.listbox())} == {actual(entry)}


def test_dropdown_list_fits_window_and_scrolls_with_many_users(form):
    """Nhà đông người: danh sách không được tràn khỏi cửa sổ, phải cuộn được tới người cuối."""
    root, dd, _ = form
    dd.set_values([f"U{i:02d}" for i in range(30)])
    dd.toggle()
    root.update()
    popup = dd.listbox().master
    assert popup.winfo_y() >= 0 and popup.winfo_y() + popup.winfo_height() <= root.winfo_height()
    assert dd.listbox().yview()[1] < 1.0            # không hiện hết → có cuộn
    pick(root, dd, 29)
    assert dd.text() == "U29"


def test_dropdown_follows_width_when_window_resizes(form):
    root, dd, _ = form
    dd.toggle()
    root.update()
    root.geometry("600x300")
    root.update()
    assert dd.listbox().master.winfo_width() == dd.winfo_width()


def test_dropdown_closes_on_escape_and_click_outside(form):
    root, dd, entry = form
    dd.toggle()
    root.focus_force()  # phím chỉ tới cửa sổ đang có focus; chạy test ở nền thì cửa sổ không tự có
    root.update()
    root.event_generate("<Escape>")
    root.update()
    assert not dd.is_open()
    dd.toggle()
    root.update()
    entry.event_generate("<ButtonPress-1>")
    root.update()
    assert not dd.is_open()


def test_dropdown_does_not_pick_on_press(form):
    """Chọn lúc ấn sẽ đóng danh sách giữa chừng, cú nhả rơi xuống nút bên dưới (vd. "Mở cửa")."""
    root, dd, _ = form
    dd.toggle()
    root.update()
    lb = dd.listbox()
    x, y, _w, _h = lb.bbox(1)
    lb.event_generate("<ButtonPress-1>", x=x + 2, y=y + 2)
    root.update()
    assert dd.is_open() and dd.current() == -1


def test_button_ignores_release_outside_it():
    """Như nút chuẩn: ấn rồi kéo ra ngoài mới nhả thì không chạy lệnh."""
    root = tk.Tk()
    try:
        hits = []
        w = button(root, "X", lambda: hits.append(1))
        w.pack()
        root.update()
        w.button.event_generate("<ButtonRelease-1>", x=-20, y=-20)
        w.button.event_generate("<ButtonRelease-1>", x=2, y=2)
        assert hits == [1]
    finally:
        root.update()
        root.destroy()


def test_dropdown_closes_when_window_shrinks(form):
    root, dd, _ = form
    dd.toggle()
    root.update()
    root.geometry("400x200")
    root.update()
    assert not dd.is_open()


def test_dropdown_opening_upward_stays_inside_its_card():
    """Mở lên trên không được che phần phía trên khung chứa ô (thanh tiêu đề, nút Admin)."""
    from ui.app import Dropdown, style_inputs

    root = tk.Tk()
    try:
        root.geometry("400x300")
        style_inputs(root)
        tk.Frame(root, height=120, bg="black").pack(fill="x")          # thanh tiêu đề giả
        card = tk.Frame(root)
        card.pack(fill="both", expand=True)
        holder = tk.Frame(card)
        holder.pack(side="bottom", fill="x")
        dd = Dropdown(holder, "Chọn")
        dd.pack(fill="x", ipady=4)
        dd.set_values([f"U{i:02d}" for i in range(30)])
        root.update()
        dd.toggle()
        root.update()
        assert dd.listbox().master.winfo_y() >= card.winfo_y()
    finally:
        root.update()
        root.destroy()
