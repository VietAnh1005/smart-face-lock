from datetime import datetime, timedelta

import numpy as np
import pytest

from security.pin_auth import hash_pin
from tests.conftest import vector


def test_add_list_load(ctx):
    uid = ctx.users.add_user("Nguyễn Văn An", hash_pin("123456"), [vector(1), vector(2)])
    assert ctx.users.list_users()[0]["valid"]
    known, tampered = ctx.users.load_known_encodings()
    assert tampered == 0 and len(known[uid]) == 2
    assert np.allclose(known[uid][0], vector(1))


def test_invalid_name_and_vector(ctx):
    with pytest.raises(ValueError):
        ctx.users.add_user("Robert'); DROP TABLE users;--", hash_pin("123456"), [vector(1)])
    with pytest.raises(ValueError):
        ctx.users.add_user("An", hash_pin("123456"), [np.zeros(64)])
    assert ctx.users.list_users() == []  # transaction bị hủy, không còn dòng dở dang


def test_delete_cascades_and_removes_snapshots(ctx):
    uid = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    ctx.logger.log("FINGERPRINT_FAILED", uid, frame_bgr=np.zeros((10, 10, 3), np.uint8))
    snapshot = ctx.logs.list()[0]["snapshot"]
    assert (ctx.logs.snapshot_dir / snapshot).exists()
    ctx.logs.delete_snapshots_of_user(uid)
    ctx.users.delete_user(uid)
    assert not (ctx.logs.snapshot_dir / snapshot).exists()
    assert ctx.db.conn.execute("SELECT COUNT(*) FROM face_encodings").fetchone()[0] == 0
    assert ctx.logs.list()[0]["name"] is None  # log vẫn giữ, user_id = NULL


def test_snapshot_is_encrypted(ctx):
    image = np.full((8, 8, 3), 200, np.uint8)
    ctx.logger.log("FACE_MISMATCH", frame_bgr=image)
    name = ctx.logs.list()[0]["snapshot"]
    assert not (ctx.logs.snapshot_dir / name).read_bytes().startswith(b"\xff\xd8")  # không phải JPEG thô
    assert ctx.logger.load_snapshot(name).shape == image.shape


def test_purge_old_logs(ctx):
    ctx.logger.log("FACE_MISMATCH", frame_bgr=np.zeros((4, 4, 3), np.uint8))
    old = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
    ctx.db.conn.execute("UPDATE access_logs SET timestamp = ?", (old,))
    name = ctx.logs.list()[0]["snapshot"]
    ctx.logs.purge_older_than(30)
    assert ctx.logs.list() == [] and not (ctx.logs.snapshot_dir / name).exists()
