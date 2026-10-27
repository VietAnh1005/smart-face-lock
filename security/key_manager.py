"""Đọc khóa bí mật từ .env; chỉ tạo khóa mới khi hệ thống chưa có dữ liệu."""
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values

from config import settings
from security.crypto_utils import Crypto


class ConfigError(RuntimeError):
    """Cấu hình thiếu hoặc sai, ứng dụng không được chạy tiếp."""


def load_crypto(env_path: Path = settings.ENV_PATH, db_path: Path = settings.DB_PATH) -> Crypto:
    values = dotenv_values(env_path) if env_path.exists() else {}
    fernet_key, hmac_key = values.get("FERNET_KEY"), values.get("HMAC_KEY")
    if fernet_key and hmac_key:
        env_path.chmod(0o600)  # chỉ tài khoản hiện tại đọc được khóa; siết lại mỗi lần mở
        try:
            return Crypto(fernet_key.encode(), bytes.fromhex(hmac_key))
        except ValueError as exc:
            raise ConfigError(f"Khóa trong {env_path.name} không hợp lệ.") from exc
    if db_path.exists():
        # Tạo khóa mới lúc này sẽ làm toàn bộ dữ liệu cũ không giải mã được,
        # và mở đường cho kẻ xóa .env để "cài đặt lại" hệ thống.
        raise ConfigError(
            f"Thiếu FERNET_KEY/HMAC_KEY trong {env_path.name} trong khi đã có dữ liệu. "
            "Khôi phục file .env, hoặc chạy `python main.py --reset` để xóa toàn bộ và cài lại."
        )
    fernet_key, hmac_key = Fernet.generate_key().decode(), secrets.token_hex(32)
    env_path.touch(mode=0o600)  # chỉ tài khoản hiện tại đọc được (Windows bỏ qua quyền kiểu này)
    env_path.write_text(f"FERNET_KEY={fernet_key}\nHMAC_KEY={hmac_key}\n", encoding="utf-8")
    return Crypto(fernet_key.encode(), bytes.fromhex(hmac_key))
