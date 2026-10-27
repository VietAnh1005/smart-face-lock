"""Sửa DB / xóa khóa trái phép phải bị phát hiện."""
import pytest

from security.crypto_utils import TamperError
from security.key_manager import ConfigError, load_crypto
from security.pin_auth import hash_pin
from tests.conftest import vector


def test_modified_pin_hash_detected(ctx):
    uid = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    ctx.db.conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?", (hash_pin("000000"), uid))
    with pytest.raises(TamperError):
        ctx.users.get_user(uid)
    known, tampered = ctx.users.load_known_encodings()
    assert known == {} and tampered == 1


def test_encoding_moved_to_other_user_detected(ctx):
    a = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    b = ctx.users.add_user("Binh", hash_pin("654321"), [vector(2)])
    ctx.db.conn.execute("UPDATE face_encodings SET user_id = ? WHERE user_id = ?", (b, a))
    known, tampered = ctx.users.load_known_encodings()
    assert tampered == 1 and len(known[b]) == 1


def test_deleted_admin_hash_is_tamper_not_first_run(ctx):
    ctx.state.set("admin_hash", "x")
    ctx.db.conn.execute("DELETE FROM app_state WHERE key = 'admin_hash'")
    with pytest.raises(TamperError):
        ctx.state.get("admin_hash")


def test_modified_state_detected(ctx):
    ctx.db.conn.execute("UPDATE app_state SET value = '0' WHERE key = 'lockout_until'")
    with pytest.raises(TamperError):
        ctx.state.get("lockout_until")
    assert ctx.state.get("failed_count") == "0"  # khóa khác vẫn đọc bình thường
    ctx.db.conn.execute("UPDATE app_state SET value = '99' WHERE key = 'lockout_level'")
    with pytest.raises(TamperError):
        ctx.state.get("lockout_level")


def test_missing_keys_with_existing_db_refuses(tmp_path):
    db_path = tmp_path / "smart_lock.db"
    db_path.write_bytes(b"")
    with pytest.raises(ConfigError):
        load_crypto(tmp_path / ".env", db_path)


def test_keys_created_only_on_fresh_install(tmp_path):
    env = tmp_path / ".env"
    load_crypto(env, tmp_path / "none.db")
    first = env.read_text()
    load_crypto(env, tmp_path / "none.db")
    assert env.read_text() == first  # không ghi đè khóa đã có
