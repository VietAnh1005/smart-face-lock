import pytest

from config import settings
from security.admin_auth import AdminAuth, hash_password
from services.lockout_service import LockoutService

PASSWORD = "matkhau123"


@pytest.fixture
def admin(ctx, clock):
    ctx.state.set("admin_hash", hash_password(PASSWORD))
    LockoutService.install(ctx.state, "admin_", now=clock())
    return AdminAuth(ctx.state, LockoutService(ctx.state, ctx.logger, "admin_", clock), ctx.logger, clock)


def test_login_and_idle_expiry(admin, clock):
    assert admin.login(PASSWORD)[0] and admin.is_active()
    clock.t += settings.ADMIN_IDLE_SECONDS - 1
    admin.touch()                                  # thao tác → gia hạn
    clock.t += settings.ADMIN_IDLE_SECONDS - 1
    assert admin.is_active()
    clock.t += 2
    assert not admin.is_active()


def test_max_session_even_with_activity(admin, clock):
    admin.login(PASSWORD)
    while clock.t < 1_000_000 + settings.ADMIN_MAX_SECONDS - 60:
        clock.t += 60
        admin.touch()
    clock.t += 120
    assert not admin.is_active()


def test_wrong_password_reports_attempts_then_locks(admin, ctx):
    ok, message = admin.login("sai")
    assert not ok and "Còn 2 lần thử" in message
    admin.login("sai")
    ok, message = admin.login("sai")
    assert not ok and "Thử lại sau" in message
    assert not admin.login(PASSWORD)[0]           # đúng mật khẩu cũng bị chặn khi đang khóa tạm
    assert ctx.lockout.failed_count() == 0        # bộ đếm mở cửa không bị ảnh hưởng


def test_deleted_admin_hash_refuses_login(admin, ctx):
    ctx.db.conn.execute("DELETE FROM app_state WHERE key = 'admin_hash'")
    ok, message = admin.login(PASSWORD)
    assert not ok and "--reset" in message
