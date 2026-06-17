from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow


class ResultItem(BaseModel):
    """Один результат ЕГЭ по предмету (встроенный документ внутри Student)."""

    subject: str  # нормализованный ключ предмета (напр. "русский язык")
    subject_title: str | None = None  # как отображается на сайте
    score: int | None = None  # числовой балл, если результат — число
    value: str | None = None  # отображаемое значение ("88" или "Зачёт")
    status: str | None = None  # напр. "Действующий результат", "на проверке"
    exam_date: str | None = None
    raw: dict = Field(default_factory=dict)  # сырые данные источника
    first_seen_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Student(Document):
    """Ученик, чьи результаты отслеживаются. Уникален по паспорту (identity_hash)."""

    last_name: str
    # Свободная заметка для администратора (напр. источник/группа ученика). Не PII.
    notes: str = ""
    # Паспортные данные хранятся в зашифрованном виде (см. security.Cipher).
    passport_series_enc: str
    passport_number_enc: str
    identity_hash: str  # HMAC паспорта — для дедупликации без расшифровки
    passport_masked: str  # маскированный паспорт для отображения

    results: list[ResultItem] = Field(default_factory=list)

    last_checked_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_error: str | None = None
    # Источник не нашёл ученика по фамилии+паспорту (вероятна опечатка), в отличие
    # от «найден, но результатов ещё нет». Сбрасывается, как только проверка прошла.
    not_found: bool = False

    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "students"
        indexes = [IndexModel([("identity_hash", ASCENDING)], unique=True)]
