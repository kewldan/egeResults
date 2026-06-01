"""Интеграционные тесты сервисного слоя против реальной MongoDB.

Покрывают логику, которую нельзя проверить офлайн (Beanie требует ``init_beanie``):
обработку гонок (``DuplicateKeyError``), дедупликацию ученика, блокировку и
перечитывание в ``check_student``, а также путь без N+1 в ``check_all``.

Тесты пропускаются целиком, если MongoDB недоступна по ``MONGO_URI``
(переменная окружения или ``mongodb://localhost:27017`` по умолчанию). Чтобы
запустить локально: поднимите Mongo и `MONGO_URI=... uv run pytest tests/test_services_integration.py`.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pymongo
import pytest
from beanie import init_beanie
from pymongo import AsyncMongoClient

from ege_notifier.models import ALL_DOCUMENTS, Student, Subscription
from ege_notifier.providers.base import FetchedResult
from ege_notifier.security import Cipher
from ege_notifier.services.results import ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
TEST_DB = "ege_notifier_test"


def _mongo_available() -> bool:
    try:
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=400)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB недоступна по {MONGO_URI}"
)


async def _fresh_db() -> AsyncMongoClient:
    """Чистая БД + инициализация Beanie (как в db.init_db)."""
    client: AsyncMongoClient = AsyncMongoClient(MONGO_URI, tz_aware=True)
    await client.drop_database(TEST_DB)
    await init_beanie(database=client[TEST_DB], document_models=ALL_DOCUMENTS)
    return client


def _services(fetched: list[FetchedResult] | None = None):
    settings = SimpleNamespace(identity_secret="test-secret", request_delay=0)
    subs = SubscriptionService(settings, Cipher(None))
    provider = SimpleNamespace(fetch=_make_fetch(fetched or []))
    results = ResultsService(settings, provider, subs)
    return subs, results


def _make_fetch(fetched: list[FetchedResult]):
    async def fetch(_query):
        return list(fetched)

    return fetch


# --- дедупликация ученика и гонки -----------------------------------------


async def test_get_or_create_student_is_idempotent():
    client = await _fresh_db()
    try:
        subs, _ = _services()
        a = await subs.get_or_create_student("Иванов", "4022", "083074")
        b = await subs.get_or_create_student("Иванов", "4022", "083074")
        assert a.id == b.id
        assert await Student.find_all().count() == 1
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_concurrent_get_or_create_does_not_crash():
    """Гонка двух подписок на один паспорт → один ученик, без DuplicateKeyError."""
    client = await _fresh_db()
    try:
        subs, _ = _services()
        results = await asyncio.gather(
            subs.get_or_create_student("Иванов", "4022", "083074"),
            subs.get_or_create_student("Иванов", "4022", "083074"),
        )
        ids = {s.id for s in results}
        assert len(ids) == 1
        assert await Student.find_all().count() == 1
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_subscribe_twice_is_idempotent():
    client = await _fresh_db()
    try:
        subs, _ = _services()
        student, created1 = await subs.subscribe(1, "Иванов", "4022", "083074")
        _, created2 = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert created1 is True
        assert created2 is False
        assert await Subscription.find(Subscription.student_id == student.id).count() == 1
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_two_users_one_student_grouping():
    client = await _fresh_db()
    try:
        subs, _ = _services()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        student2, _ = await subs.subscribe(2, "Иванов", "4022", "083074")
        assert student.id == student2.id
        grouped = await subs.subscribers_by_student()
        assert set(grouped[student.id]) == {1, 2}
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_unsubscribe_deletes_student_when_last_subscriber_leaves():
    client = await _fresh_db()
    try:
        subs, _ = _services()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        await subs.subscribe(2, "Иванов", "4022", "083074")
        await subs.unsubscribe(1, student.id)
        assert await Student.get(student.id) is not None  # ещё есть подписчик
        await subs.unsubscribe(2, student.id)
        assert await Student.get(student.id) is None  # PII удалена
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


# --- проверка результатов: блокировка/перечитывание и N+1 ------------------


async def test_check_student_reports_new_then_no_change():
    fetched = [
        FetchedResult(
            subject="русский язык",
            subject_title="Русский язык",
            score=88,
            value="88",
            status="готов",
        )
    ]
    client = await _fresh_db()
    try:
        subs, results = _services(fetched)
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        changes = await results.check_student(student)
        assert len(changes) == 1
        reloaded = await Student.get(student.id)
        assert len(reloaded.results) == 1 and reloaded.results[0].score == 88
        # Повторная проверка тем же ответом — изменений нет.
        assert await results.check_student(student) == []
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_check_all_skips_students_without_subscribers():
    fetched = [FetchedResult(subject="русский язык", score=88, value="88")]
    client = await _fresh_db()
    try:
        subs, results = _services(fetched)
        tracked, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        # Ученик без подписчиков — не должен попасть в проверку.
        await subs.get_or_create_student("Петров", "4022", "111111")
        updates = await results.check_all()
        assert len(updates) == 1
        assert updates[0].student.id == tracked.id
        assert updates[0].subscribers == [1]
    finally:
        await client.drop_database(TEST_DB)
        await client.close()
