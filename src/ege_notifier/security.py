from __future__ import annotations

import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def normalize_digits(value: str) -> str:
    """Оставляет только цифры — чтобы '40 03' и '4003' считались одинаковыми."""
    return "".join(ch for ch in value if ch.isdigit())


def identity_hash(passport_series: str, passport_number: str, secret: str) -> str:
    """Детерминированный HMAC-хэш паспорта для дедупликации учеников без расшифровки."""
    payload = f"{normalize_digits(passport_series)}:{normalize_digits(passport_number)}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def mask_passport(passport_series: str, passport_number: str) -> str:
    """Маскированное представление паспорта для отображения (показываем 2 последние цифры)."""
    num = normalize_digits(passport_number)
    tail = num[-2:] if len(num) >= 2 else num
    return f"●●●● ●●●●{tail}"


class Cipher:
    """Шифрование строковых PII-полей (паспорт).

    Если ключ не задан — работает как passthrough (только для локальной разработки).
    """

    def __init__(self, key: str | None):
        self._fernet = Fernet(key.encode()) if key else None
        if self._fernet is None:
            logger.warning(
                "ENCRYPTION_KEY не задан — паспортные данные хранятся в открытом виде "
                "(допустимо только для разработки)."
            )

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            return value
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            return value
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            # Все Fernet-токены начинаются с "gAAAAA". Если значение похоже на токен,
            # но не расшифровалось — почти наверняка сменили ENCRYPTION_KEY (это
            # запрещено: расшифровка PII ломается). Предупреждаем, не логируя само PII.
            if value.startswith("gAAAAA"):
                logger.warning(
                    "Не удалось расшифровать PII-поле — вероятно, изменён ENCRYPTION_KEY."
                )
            # Иначе значение сохранено в открытом виде (до включения шифрования).
            return value

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
