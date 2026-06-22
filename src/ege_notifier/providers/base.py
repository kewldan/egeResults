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
class Criterion:
    """Критерий/часть результата («Крит. К1 → Зачёт», «Первичный балл → 37»)."""

    name: str
    value: str


@dataclass(slots=True)
class BlankImage:
    """Скан бланка ответов (ссылка на скачивание)."""

    title: str
    url: str


@dataclass(slots=True)
class TaskAnswer:
    """Распознанный ответ по одному заданию."""

    task: str
    answer: str


@dataclass(slots=True)
class Registration:
    """Регистрация на экзамен: когда, какой предмет, где (ППЭ + адрес)."""

    subject: str  # нормализованный ключ предмета
    subject_title: str | None = None
    exam_date: str | None = None
    place: str | None = None
    address: str | None = None


@dataclass(slots=True)
class FetchedResult:
    """Один результат, полученный от источника."""

    subject: str  # нормализованный ключ предмета
    subject_title: str | None = None
    score: int | None = None  # числовой балл, если результат — число
    value: str | None = None  # отображаемое значение ("88" или "Зачёт")
    status: str | None = None  # статус результата ("Действующий результат" и т. п.)
    exam_date: str | None = None
    # Детализация со страницы результата. В diff НЕ участвует (см. services.diff):
    # её появление не считается изменением и не вызывает уведомлений.
    criteria: list[Criterion] = field(default_factory=list)
    primary_score: int | None = None
    recognition: list[TaskAnswer] = field(default_factory=list)
    blanks: list[BlankImage] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass(slots=True)
class StudentSnapshot:
    """Полный снимок ученика со страницы результата: результаты + регистрации.

    Регистрации (когда/какой/где) — student-уровень: на экзамен может ещё не быть
    результата, поэтому они отдельно от ``results`` и в diff не участвуют.
    """

    results: list[FetchedResult] = field(default_factory=list)
    registrations: list[Registration] = field(default_factory=list)


@runtime_checkable
class ResultsProvider(Protocol):
    """Источник результатов ЕГЭ. Реализации: MockResultsProvider, EgeSpbProvider."""

    async def fetch(self, query: StudentQuery) -> StudentSnapshot: ...
