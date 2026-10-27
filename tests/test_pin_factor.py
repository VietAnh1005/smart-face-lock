import pytest

from security.crypto_utils import TamperError
from security.pin_auth import PinFactor, hash_pin
from tests.conftest import vector


@pytest.fixture
def users(ctx):
    a = ctx.users.add_user("An", hash_pin("123456"), [vector(1)])
    b = ctx.users.add_user("Bình", hash_pin("654321"), [vector(2)])
    return ctx, PinFactor(ctx.users), a, b


def test_pin_identifies_claimed_user(users):
    _, factor, a, _ = users
    assert factor.identify("123456", a) == a


def test_wrong_pin_or_other_users_pin(users):
    _, factor, a, _ = users
    assert factor.identify("000000", a) is None
    assert factor.identify("654321", a) is None   # PIN của Bình không mở được thay An


def test_pin_requires_claimed_user(users):
    _, factor, _, _ = users
    assert factor.identify("123456", None) is None


def test_tampered_user_raises(users):
    ctx, factor, a, _ = users
    ctx.db.conn.execute("UPDATE users SET pin_hash = ? WHERE id = ?", (hash_pin("000000"), a))
    with pytest.raises(TamperError):
        factor.identify("000000", a)
