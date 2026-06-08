from __future__ import annotations

import re

# Фамилия — одно слово кириллицей; двойную вводят через дефис («Салтыков-Щедрин»).
# Пробелы запрещены: иначе в фамилию попадает имя («Иванов Пётр»), а ege.spb.ru
# сверяет фамилию точно и отвечает «участник не найден».
_LAST_NAME_RE = re.compile(r"^[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*$")
_MAX_LAST_NAME_LEN = 60


def _capitalize_parts(value: str) -> str:
    """Капитализирует каждое слово: «салтыков-щедрин» → «Салтыков-Щедрин»."""
    return re.sub(r"[А-Яа-яЁё]+", lambda m: m.group().capitalize(), value)


def validate_last_name(value: str) -> str | None:
    """Проверяет фамилию (одно слово кириллицей, допустим дефис) и нормализует регистр.

    Возвращает капитализированную фамилию («Тенишев», «Салтыков-Щедрин») либо
    ``None``, если ввод невалиден. Пробел = ошибка: двойную фамилию вводят через
    дефис. Заменять дефис пробелом нельзя — сайт сверяет фамилию точно, лишнее
    слово (имя) обнулит поиск.
    """
    v = value.strip()
    if not v or len(v) > _MAX_LAST_NAME_LEN or not _LAST_NAME_RE.match(v):
        return None
    return _capitalize_parts(v)


def normalize_surname(value: str) -> str | None:
    """Извлекает саму фамилию из строки, куда могли слипнуться ФИО.

    Берёт первое слово (до пробела) и нормализует его как фамилию. Нужна для
    миграции старых записей вида «Иванов Пётр» → «Иванов». Возвращает ``None``,
    если первого слова нет или оно невалидно как фамилия.
    """
    parts = value.split()
    return validate_last_name(parts[0]) if parts else None


def validate_series(value: str) -> str | None:
    """Серия паспорта РФ — 4 цифры."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits if len(digits) == 4 else None


def validate_number(value: str) -> str | None:
    """Номер паспорта РФ — 6 цифр."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits if len(digits) == 6 else None
