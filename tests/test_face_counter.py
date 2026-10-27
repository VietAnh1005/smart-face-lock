from config import settings


def events(ctx):
    return [r["event"] for r in ctx.logs.list()]


def test_disables_after_max_and_logs_once(ctx):
    for _ in range(settings.FACE_MAX_FAILED - 1):
        ctx.faces.register_failure()
    assert not ctx.faces.disabled()
    ctx.faces.register_failure()
    ctx.faces.register_failure()
    assert ctx.faces.disabled()
    assert events(ctx).count("FACE_DISABLED") == 1


def test_reset(ctx):
    for _ in range(settings.FACE_MAX_FAILED):
        ctx.faces.register_failure()
    ctx.faces.reset()
    assert ctx.faces.count() == 0


def test_tampered_counter_counts_as_disabled(ctx):
    ctx.db.conn.execute("UPDATE app_state SET value = '1' WHERE key = 'face_failed'")
    assert ctx.faces.disabled() and ctx.faces.disabled()
    assert events(ctx).count("TAMPER_DETECTED") == 1


def test_missing_counter_counts_as_disabled(ctx):
    ctx.db.conn.execute("DELETE FROM app_state WHERE key = 'face_failed'")
    assert ctx.faces.disabled()
