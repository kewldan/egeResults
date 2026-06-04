from __future__ import annotations

import re
from datetime import datetime, timezone

_PUNCT_RE = re.compile(r"[^\w\s]")


def utcnow() -> datetime:
    """Текущее время в UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def normalize_subject(title: str) -> str:
    """Стабильный ключ предмета для сопоставления между проверками.

    Пунктуация отбрасывается, регистр и пробелы нормализуются, чтобы изменение
    формулировки на сайте («Математика профильная» → «Математика (профильная)»)
    не давало нового ключа и ложного дубль-уведомления. Функция идемпотентна.

    Живёт здесь (а не в провайдере), потому что ключ сопоставления — общий для
    всех источников: слой ``services.diff`` нормализует обе стороны сам и не
    зависит от того, нормализует ли конкретный провайдер ``subject``.
    """
    cleaned = _PUNCT_RE.sub(" ", title)  # убираем скобки/точки/дефисы и т. п.
    return " ".join(cleaned.split()).lower()
