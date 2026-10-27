from PIL import ImageFont

from ui.app import _pil_font


def test_overlay_fonts_are_real_arial_not_pillow_default():
    """Font mặc định của Pillow không có dấu tiếng Việt: rơi về nó thì chữ trên camera bị lỗi."""
    for bold in (False, True):
        font = _pil_font(12, bold)
        assert isinstance(font, ImageFont.FreeTypeFont)
        assert "arial" in font.path.lower()
