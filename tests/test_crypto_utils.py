import pytest
from cryptography.fernet import Fernet, InvalidToken

from security.crypto_utils import Crypto


@pytest.fixture
def crypto():
    return Crypto(Fernet.generate_key(), b"secret-key")


def test_encrypt_roundtrip(crypto):
    token = crypto.encrypt(b"vector")
    assert token != b"vector" and crypto.decrypt(token) == b"vector"


def test_modified_ciphertext_rejected(crypto):
    token = bytearray(crypto.encrypt(b"vector"))
    token[-5] ^= 1
    with pytest.raises(InvalidToken):
        crypto.decrypt(bytes(token))


def test_signature(crypto):
    sig = crypto.sign("users", 1, "An")
    assert crypto.verify(sig, "users", 1, "An")
    assert not crypto.verify(sig, "users", 2, "An")
    assert not crypto.verify(sig, "app_state", 1, "An")       # không dùng chéo giữa các bảng
    assert crypto.sign("t", "ab", "c") != crypto.sign("t", "a", "bc")  # ranh giới trường rõ ràng
