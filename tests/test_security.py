from __future__ import annotations

from ege_notifier.security import (
    Cipher,
    hash_token,
    identity_hash,
    mask_passport,
    normalize_digits,
)


def test_normalize_digits():
    assert normalize_digits("40 03") == "4003"
    assert normalize_digits("№123-456") == "123456"


def test_identity_hash_normalizes_spaces():
    assert identity_hash("40 03", "123 456", "s") == identity_hash(
        "4003", "123456", "s"
    )


def test_identity_hash_depends_on_secret():
    assert identity_hash("4003", "123456", "s1") != identity_hash(
        "4003", "123456", "s2"
    )


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


def test_hash_token_is_deterministic_and_hex():
    a = hash_token("secret-token")
    assert a == hash_token("secret-token")  # детерминирован
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)  # sha256 hex
    assert a != hash_token("other-token")  # разные токены — разные хэши
    assert "secret-token" not in a  # сам токен в хэше не виден


def test_mask_passport_shows_tail():
    masked = mask_passport("4003", "123456")
    assert masked.endswith("56")
    assert "123456" not in masked


def test_decrypt_with_wrong_key_warns_and_passes_through(caplog):
    # Токен, зашифрованный одним ключом, нельзя расшифровать другим (смена ключа).
    token = Cipher(Cipher.generate_key()).encrypt("123456")
    other = Cipher(Cipher.generate_key())
    with caplog.at_level("WARNING"):
        result = other.decrypt(token)
    assert result == token  # отдаём как есть, не падаем
    assert "ENCRYPTION_KEY" in caplog.text  # но предупреждаем
    assert "123456" not in caplog.text  # и не светим PII


def test_decrypt_legacy_plaintext_is_silent(caplog):
    # Значение из «до шифрования» (не похоже на Fernet-токен) — без предупреждения.
    cipher = Cipher(Cipher.generate_key())
    with caplog.at_level("WARNING"):
        assert cipher.decrypt("123456") == "123456"
    assert caplog.text == ""
