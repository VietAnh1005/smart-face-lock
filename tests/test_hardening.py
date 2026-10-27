import os
import stat
import subprocess
import sys

import pytest

from hardware.simulated_lock import SimulatedLock
from security.key_manager import load_crypto
from storage.database import Database
from tests.conftest import FakeClock
from ui.app import relock_if_expired


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows không có quyền kiểu 0o600/0o700 (chmod chỉ bật/tắt chỉ-đọc)")
def test_secret_files_are_private(tmp_path):
    load_crypto(tmp_path / ".env", tmp_path / "data" / "x.db")
    Database(tmp_path / "data" / "x.db").close()
    assert mode(tmp_path / ".env") == 0o600
    assert mode(tmp_path / "data") == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="Windows không có quyền kiểu 0o600/0o700 (chmod chỉ bật/tắt chỉ-đọc)")
def test_existing_loose_permissions_are_tightened(tmp_path):
    load_crypto(tmp_path / ".env", tmp_path / "data" / "x.db")
    (tmp_path / ".env").chmod(0o644)
    load_crypto(tmp_path / ".env", tmp_path / "data" / "x.db")
    assert mode(tmp_path / ".env") == 0o600


def test_expired_unlock_sends_lock_command():
    """Khóa thật không tự đóng: hết UNLOCK_SECONDS phải gửi lệnh khóa (khóa mô phỏng thì không hại gì)."""
    clock, calls = FakeClock(), []
    lock = SimulatedLock(clock)
    lock.lock = lambda: calls.append("lock")
    lock.unlock(5)
    was_locked = relock_if_expired(lock, lambda e: calls.append(e), was_locked=True)
    clock.t += 5
    relock_if_expired(lock, lambda e: calls.append(e), was_locked)
    assert calls == ["lock", "LOCK"]


def test_auth_service_import_does_not_load_dlib():
    code = "import sys, services.auth_service; print('face_recognition' in sys.modules)"
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_relay_lock_that_reports_relay_state_still_gets_locked():
    """Khóa thật báo is_locked() theo relay: nếu firmware không tự đóng, app vẫn phải gửi lệnh khóa."""
    clock, calls = FakeClock(), []

    class RelayLock(SimulatedLock):
        relay_open = False

        def unlock(self, seconds):
            super().unlock(seconds)
            self.relay_open = True

        def lock(self):
            calls.append("lock")
            self.relay_open = False

        def is_locked(self):
            return not self.relay_open

    lock = RelayLock(clock)
    lock.unlock(5)
    was_locked = relock_if_expired(lock, lambda e: calls.append(e), was_locked=True)
    clock.t += 5
    relock_if_expired(lock, lambda e: calls.append(e), was_locked)
    assert calls == ["lock", "LOCK"] and lock.is_locked()
