from __future__ import annotations

import json
import logging
from pathlib import Path

from ege_notifier.providers.base import (
    FetchedResult,
    StudentNotFoundError,
    StudentQuery,
)
from ege_notifier.security import normalize_digits

logger = logging.getLogger(__name__)


class MockResultsProvider:
    """Тестовый источник: читает результаты из JSON-файла.

    Формат файла (ключ — номер паспорта, только цифры)::

        {
          "654321": [
            {"subject": "russian", "subject_title": "Русский язык",
             "score": 88, "status": "результат получен"}
          ]
        }

    Меняя файл во время работы бота, можно сымитировать появление новых
    результатов и проверить весь конвейер уведомлений без реального сайта.

    Семантика трёх состояний (как у реального источника):
      - ключа нет в файле        → ученик «не найден» (``StudentNotFoundError``);
      - ключ есть, список пуст    → ученик найден, результатов пока нет (``[]``);
      - ключ есть, список не пуст → результаты ученика.
    """

    def __init__(self, fixtures_path: str | Path):
        self._path = Path(fixtures_path)

    async def fetch(self, query: StudentQuery) -> list[FetchedResult]:
        if not self._path.exists():
            logger.warning("Файл фикстур не найден: %s", self._path)
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        key = normalize_digits(query.passport_number)
        if key not in data:
            raise StudentNotFoundError(f"mock: паспорт {key} не найден в фикстурах")
        entries = data[key]
        return [
            FetchedResult(
                subject=entry["subject"],
                subject_title=entry.get("subject_title"),
                score=entry.get("score"),
                value=entry.get("value"),
                status=entry.get("status"),
                exam_date=entry.get("exam_date"),
                raw=entry,
            )
            for entry in entries
        ]
