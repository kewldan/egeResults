from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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

    async def fetch(self, query: StudentQuery) -> list[FetchedResult]:
        ...
