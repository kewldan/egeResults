from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow


class Criterion(BaseModel):
    """Один критерий/часть результата («Крит. К1 → Зачёт», «Первичный балл → 37»).

    Покрывает обе раскладки сайта: «Результаты по критериям» (зачётные предметы) и
    «Первичные баллы по частям» (балльные предметы). Это справочная детализация —
    в diff не участвует, поэтому её появление НЕ считается новым результатом.
    """

    name: str  # подпись («Крит. К1», «Задания с кратким ответом», «Первичный балл (сумма)»)
    value: str  # значение («Зачёт» / «16» / «Отсутствует в КИМ»)


class BlankImage(BaseModel):
    """Скан бланка ответов с сайта (ссылка на download.php, абсолютный URL).

    ``path`` — путь к уже скачанному файлу относительно ``Settings.blanks_dir``
    (заполняется при проверке, см. ResultsService._download_blanks); ``None``, пока
    файл не скачан. Имея файл, бот не зависит от протухания одноразовой ссылки."""

    title: str  # «Бланк записи лист 1», «Бланк ответов №2 (лист 1)»
    url: str  # прямая ссылка на скачивание
    path: str | None = None  # локальный путь относительно blanks_dir


class TaskAnswer(BaseModel):
    """Распознанный ответ по одному заданию («№ 4 → 134»)."""

    task: str  # номер задания, как на сайте
    answer: str  # распознанный ответ


class Registration(BaseModel):
    """Регистрация ученика на экзамен (когда / какой предмет / где).

    Берётся из таблицы «Регистрация на экзамены» (#reg-data). Может быть на экзамен,
    результата по которому ещё нет, поэтому хранится отдельно от ``results`` и в diff
    не участвует."""

    subject: str  # нормализованный ключ предмета
    subject_title: str | None = None  # как на сайте
    exam_date: str | None = None  # дата проведения
    place: str | None = None  # пункт проведения (ППЭ), напр. «ГБОУ СОШ №669»
    address: str | None = None  # адрес пункта (None, если ещё не опубликован)


class ResultItem(BaseModel):
    """Один результат ЕГЭ по предмету (встроенный документ внутри Student)."""

    subject: str  # нормализованный ключ предмета (напр. "русский язык")
    subject_title: str | None = None  # как отображается на сайте
    score: int | None = None  # числовой балл, если результат — число
    value: str | None = None  # отображаемое значение ("88" или "Зачёт")
    status: str | None = None  # напр. "Действующий результат", "на проверке"
    exam_date: str | None = None
    # Детализация со страницы результата. Не влияет на diff/уведомления (см.
    # services.diff._is_changed) — обновляется тихо, повторных уведомлений не вызывает.
    criteria: list[Criterion] = Field(default_factory=list)
    primary_score: int | None = None  # «Первичный балл (сумма)», если есть
    recognition: list[TaskAnswer] = Field(default_factory=list)  # распознанные ответы
    blanks: list[BlankImage] = Field(default_factory=list)  # сканы бланков
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
    # Регистрации на экзамены (когда/какой/где) со страницы результата. Справочные —
    # в diff не участвуют, поэтому обновление не шлёт уведомлений.
    registrations: list[Registration] = Field(default_factory=list)

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
