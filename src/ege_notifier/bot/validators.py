from __future__ import annotations

import re

_LAST_NAME_RE = re.compile(r"^[А-Яа-яЁё][А-Яа-яЁё\-\s]{1,59}$")


def validate_last_name(value: str) -> str | None:
    """Проверяет фамилию (кириллица, дефис, пробел) и нормализует регистр.

    Регистр приводится к «Тенишев» (как ждёт ege.spb.ru), но разделители
    сохраняются: двойная фамилия «Салтыков Щедрин» остаётся с пробелом, а
    «салтыков-щедрин» — с дефисом. Менять разделитель нельзя — сайт сверяет
    фамилию точно, и подмена пробела дефисом обнулит поиск.
    """
    v = " ".join(value.split())  # схлопываем повторные пробелы, убираем края
    if _LAST_NAME_RE.match(v):
        return re.sub(r"[А-Яа-яЁё]+", lambda m: m.group().capitalize(), v)
    return None


def validate_series(value: str) -> str | None:
    """Серия паспорта РФ — 4 цифры."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits if len(digits) == 4 else None


def validate_number(value: str) -> str | None:
    """Номер паспорта РФ — 6 цифр."""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits if len(digits) == 6 else None
