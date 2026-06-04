from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class StudentNotFoundError(Exception):
    """Источник не нашёл ученика по фамилии и паспорту (опечатка/неверные данные).

    Отличается от «ученик найден, но результатов ещё нет» (пустой список): в этом
    случае пользователю нужно подсказать проверить введённые данные, а не сообщать
    «результатов пока нет». Провайдеры поднимают её, когда сайт явно вернул форму
    поиска / сообщение «не найдено», а не страницу с результатами.
    """


@dataclass(slots=True)
class StudentQuery:
    """Данные, по которым провайдер ищет результаты (паспорт уже расшифрован)."""

    last_name: str
    passport_series: str
    passport_number: str


@dataclass(slots=True)
class FetchedResult:
    """Один результат, полученный от источника."""

    subject: str  # нормализованный ключ предмета
    subject_title: str | None = None
    score: int | None = None  # числовой балл, если результат — число
    value: str | None = None  # отображаемое значение ("88" или "Зачёт")
    status: str | None = None  # статус результата ("Действующий результат" и т. п.)
    exam_date: str | None = None
    raw: dict = field(default_factory=dict)


@runtime_checkable
class ResultsProvider(Protocol):
    """Источник результатов ЕГЭ. Реализации: MockResultsProvider, EgeSpbProvider."""

    async def fetch(self, query: StudentQuery) -> list[FetchedResult]: ...
