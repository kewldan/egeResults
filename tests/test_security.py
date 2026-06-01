from __future__ import annotations

from ege_notifier.security import Cipher, identity_hash, mask_passport, normalize_digits


def test_normalize_digits():
    assert normalize_digits("40 03") == "4003"
    assert normalize_digits("№123-456") == "123456"


def test_identity_hash_normalizes_spaces():
    assert identity_hash("40 03", "123 456", "s") == identity_hash("4003", "123456", "s")


def test_identity_hash_depends_on_secret():
    assert identity_hash("4003", "123456", "s1") != identity_hash("4003", "123456", "s2")


def test_cipher_roundtrip():
    cipher = Cipher(Cipher.generate_key())
    assert cipher.enabled
    encrypted = cipher.encrypt("123456")
    assert encrypted != "123456"
    assert cipher.decrypt(encrypted) == "123456"


def test_cipher_passthrough_without_key():
    cipher = Cipher(None)
    assert not cipher.enabled
    assert cipher.encrypt("123456") == "123456"
    assert cipher.decrypt("123456") == "123456"


def test_mask_passport_shows_tail():
    masked = mask_passport("4003", "123456")
    assert masked.endswith("56")
    assert "123456" not in masked
