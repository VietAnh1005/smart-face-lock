from config import settings
from services.lockout_service import LockoutService


TO_ADMIN_ONLY = settings.LOCK_MAX_FAILED + len(settings.LOCKOUT_STEPS)  # 3 + 3 = 6 lần sai


def fail_n(lockout, n):
    return [lockout.register_failure() for _ in range(n)][-1]


def test_escalating_lockout(ctx, clock):
    assert fail_n(ctx.lockout, settings.MAX_FAILED)
    assert ctx.lockout.remaining() == settings.LOCKOUT_STEPS[0]
    clock.t += settings.LOCKOUT_STEPS[0]
    assert ctx.lockout.remaining() == 0
    fail_n(ctx.lockout, settings.MAX_FAILED)
    assert ctx.lockout.remaining() == settings.LOCKOUT_STEPS[1]


def test_lockout_survives_restart(ctx, clock):
    fail_n(ctx.lockout, settings.MAX_FAILED)
    restarted = LockoutService(ctx.state, ctx.logger, "", clock)
    assert restarted.remaining() > 0


def test_success_resets(ctx, clock):
    fail_n(ctx.lockout, settings.MAX_FAILED - 1)
    ctx.lockout.register_success()
    assert not ctx.lockout.register_failure()


def test_clock_rollback_detected(ctx, clock):
    ctx.lockout.register_failure()
    clock.t -= 3600
    assert ctx.lockout.remaining() == settings.LOCKOUT_STEPS[-1]
    assert ctx.logs.list()[0]["event"] == "CLOCK_TAMPER"
    ctx.lockout.remaining()
    assert [r["event"] for r in ctx.logs.list()].count("CLOCK_TAMPER") == 1  # không ghi log lặp lại


def test_clock_rollback_keeps_remaining_lockout(ctx, clock):
    fail_n(ctx.lockout, settings.MAX_FAILED)
    clock.t += 10
    clock.t -= 3600
    # Lùi giờ không xóa được khóa đang chạy; thời gian còn lại tính từ lần ghi cuối (thận trọng: không ngắn đi)
    assert ctx.lockout.remaining() == settings.LOCKOUT_STEPS[0]


def test_clock_skewed_forward_then_corrected_recovers(ctx, clock):
    """Đồng hồ từng chạy nhanh (pin CMOS, đặt nhầm năm) rồi được chỉnh lại: không bị khóa vĩnh viễn."""
    clock.t += 365 * 24 * 3600
    ctx.lockout.register_success()
    clock.t -= 365 * 24 * 3600
    assert ctx.lockout.remaining() <= settings.LOCKOUT_STEPS[-1]
    ctx.lockout.clear()                                   # admin gỡ được
    assert ctx.lockout.remaining() == 0
    clock.t += 1
    assert ctx.lockout.remaining() == 0


def test_small_ntp_adjustment_is_tolerated(ctx, clock):
    ctx.lockout.register_failure()
    clock.t -= 30
    assert ctx.lockout.remaining() == 0


def test_deleted_state_is_punished(ctx):
    ctx.db.conn.execute("DELETE FROM app_state WHERE key = 'lockout_until'")
    assert ctx.lockout.remaining() == settings.LOCKOUT_STEPS[-1]
    assert ctx.logs.list()[0]["event"] == "TAMPER_DETECTED"


def test_door_lockout_reaches_admin_only_after_all_steps(ctx, clock):
    door = ctx.door
    assert fail_n(door, settings.LOCK_MAX_FAILED)                       # đủ ngưỡng → 30 giây
    assert door.remaining() == settings.LOCKOUT_STEPS[0]
    for step in settings.LOCKOUT_STEPS[1:]:
        clock.t += door.remaining()
        assert door.register_failure()                                  # chỉ 1 lần thử sau mỗi lần hết khóa
        assert door.remaining() == step
    clock.t += door.remaining()
    assert door.register_failure() and door.admin_only()               # lần sai cuối (thứ TO_ADMIN_ONLY)
    clock.t += 10 ** 6
    assert door.admin_only() and door.remaining() == 0
    events = [r["event"] for r in ctx.logs.list()]
    assert {"LOCKED_OUT_1", "LOCKED_OUT_2", "LOCKED_OUT_3", "ADMIN_ONLY_LOCKOUT"} <= set(events)


def test_door_lockout_cleared_by_admin(ctx, clock):
    fail_n(ctx.door, TO_ADMIN_ONLY)
    ctx.door.clear()
    assert not ctx.door.admin_only() and ctx.door.failed_count() == 0


def test_door_lockout_survives_restart_at_admin_only(ctx, clock):
    for _ in range(TO_ADMIN_ONLY):
        clock.t += ctx.door.remaining()
        ctx.door.register_failure()
    restarted = LockoutService(ctx.state, ctx.logger, "", clock, settings.LOCK_MAX_FAILED, admin_after_last=True)
    assert restarted.admin_only()
