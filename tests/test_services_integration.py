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
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pymongo
import pytest
from beanie import init_beanie
from pymongo import AsyncMongoClient

from ege_notifier.config import Settings
from ege_notifier.models import ALL_DOCUMENTS, ShareToken, Student, Subscription
from ege_notifier.providers.base import (
    FetchedResult,
    ResultsProvider,
    StudentNotFoundError,
)
from ege_notifier.security import Cipher, hash_token
from ege_notifier.services.results import RefreshThrottled, ResultsService
from ege_notifier.services.subscriptions import SubscriptionService
from ege_notifier.utils import utcnow


def _settings(**kwargs: object) -> Settings:
    """Заглушка настроек: сервисам нужны лишь пара полей, а не весь Settings."""
    return cast(Settings, SimpleNamespace(**kwargs))


def _provider(fetch) -> ResultsProvider:
    """Заглушка источника: достаточно одного метода ``fetch``."""
    return cast(ResultsProvider, SimpleNamespace(fetch=fetch))


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
    settings = _settings(identity_secret="test-secret", request_delay=0)
    subs = SubscriptionService(settings, Cipher(None))
    provider = _provider(_make_fetch(fetched or []))
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
        assert (
            await Subscription.find(Subscription.student_id == student.id).count() == 1
        )
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
        assert reloaded is not None
        assert len(reloaded.results) == 1 and reloaded.results[0].score == 88
        # Повторная проверка тем же ответом — изменений нет.
        assert await results.check_student(student) == []
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_check_student_does_not_resurrect_deleted_student():
    """Если ученика удалили (последняя отписка) во время fetch, save не должен
    его воскресить — проверка молча завершается без уведомления."""
    fetched = [FetchedResult(subject="русский язык", score=88, value="88")]
    client = await _fresh_db()
    try:
        subs, _ = _services()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")

        async def fetch_then_delete(_query):
            # Имитируем параллельную отписку: ученик удаляется во время запроса
            # к источнику (после reread в check_student, но до записи).
            doc = await Student.get(student.id)
            assert doc is not None
            await doc.delete()
            return list(fetched)

        provider = _provider(fetch_then_delete)
        results = ResultsService(_settings(request_delay=0), provider, subs)
        changes = await results.check_student(student)
        assert changes == []  # удалённого ученика не уведомляем
        assert await Student.get(student.id) is None  # и НЕ воскрешаем
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_check_student_not_found_sets_flag_and_reraises():
    """StudentNotFoundError помечает ученика not_found, сохраняет это и пробрасывается."""
    client = await _fresh_db()
    try:
        subs = SubscriptionService(
            _settings(identity_secret="test-secret", request_delay=0),
            Cipher(None),
        )

        async def fetch_not_found(_query):
            raise StudentNotFoundError("опечатка")

        results = ResultsService(
            _settings(request_delay=0),
            _provider(fetch_not_found),
            subs,
        )
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")

        with pytest.raises(StudentNotFoundError):
            await results.check_student(student)

        reloaded = await Student.get(student.id)
        assert reloaded is not None
        assert reloaded.not_found is True
        assert reloaded.last_checked_at is not None
        assert reloaded.results == []
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_check_all_survives_not_found_student():
    """Один «не найден» не должен ронять весь цикл; флаг сохраняется."""
    client = await _fresh_db()
    try:
        subs = SubscriptionService(
            _settings(identity_secret="test-secret", request_delay=0),
            Cipher(None),
        )

        async def fetch_not_found(_query):
            raise StudentNotFoundError("опечатка")

        results = ResultsService(
            _settings(request_delay=0),
            _provider(fetch_not_found),
            subs,
        )
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")

        updates = await results.check_all()  # не должно бросить
        assert updates == []
        reloaded = await Student.get(student.id)
        assert reloaded is not None
        assert reloaded.not_found is True
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


# --- ручная проверка: кулдаун на ученика -----------------------------------


def _services_with_cooldown(cooldown: int, fetched: list[FetchedResult]):
    settings = _settings(
        identity_secret="test-secret",
        request_delay=0,
        manual_check_cooldown_seconds=cooldown,
    )
    subs = SubscriptionService(settings, Cipher(None))
    provider = _provider(_make_fetch(fetched))
    return subs, ResultsService(settings, provider, subs)


async def test_manual_check_is_throttled_within_cooldown():
    fetched = [FetchedResult(subject="русский язык", score=88, value="88")]
    client = await _fresh_db()
    try:
        subs, results = _services_with_cooldown(300, fetched)
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        # Первая ручная проверка проходит и проставляет last_checked_at.
        assert len(await results.check_student(student, manual=True)) == 1
        # Вторая — внутри окна кулдауна — отклоняется (источник не дёргаем).
        with pytest.raises(RefreshThrottled) as exc:
            await results.check_student(student, manual=True)
        assert exc.value.retry_after > 0
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_scheduled_check_ignores_cooldown():
    """Плановая проверка (manual=False) кулдауну не подчиняется."""
    fetched = [FetchedResult(subject="русский язык", score=88, value="88")]
    client = await _fresh_db()
    try:
        subs, results = _services_with_cooldown(300, fetched)
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        await results.check_student(student, manual=True)
        # Сразу после — без manual: не бросает, просто нет новых изменений.
        assert await results.check_student(student) == []
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_manual_check_allowed_after_cooldown_elapses():
    """Кулдаун=0 фактически отключает лимит — повторная ручная проверка проходит."""
    fetched = [FetchedResult(subject="русский язык", score=88, value="88")]
    client = await _fresh_db()
    try:
        subs, results = _services_with_cooldown(0, fetched)
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        await results.check_student(student, manual=True)
        # cooldown=0 → второй раз не throttle (изменений нет, но без исключения).
        assert await results.check_student(student, manual=True) == []
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


# --- одноразовые ссылки-приглашения (шеринг) -------------------------------


def _share_subs() -> SubscriptionService:
    return SubscriptionService(
        _settings(
            identity_secret="test-secret",
            request_delay=0,
            share_link_ttl_seconds=86400,
        ),
        Cipher(None),
    )


async def test_share_token_subscribes_recipient_without_pii():
    client = await _fresh_db()
    try:
        subs = _share_subs()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert student.id is not None
        token = await subs.create_share_token(student.id, telegram_id=1)
        assert token is not None

        # Получатель (2) гасит ссылку и подписывается на того же ученика.
        redeemed = await subs.redeem_share_token(token, telegram_id=2)
        assert redeemed is not None and redeemed.id == student.id
        assert set(await subs.subscribers_for(student.id)) == {1, 2}

        # Получатель видит лишь маскированный паспорт — расшифрованных данных в БД нет.
        reloaded = await Student.get(student.id)
        assert reloaded is not None
        assert reloaded.passport_masked.endswith("74")
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_share_token_is_one_time():
    client = await _fresh_db()
    try:
        subs = _share_subs()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert student.id is not None
        token = await subs.create_share_token(student.id, telegram_id=1)
        assert token is not None
        assert await subs.redeem_share_token(token, telegram_id=2) is not None
        # Повторное использование той же ссылки невозможно.
        assert await subs.redeem_share_token(token, telegram_id=3) is None
        assert 3 not in await subs.subscribers_for(student.id)
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_concurrent_redeem_consumes_token_once():
    """Гонка двух получателей одной ссылки: подписывается ровно один."""
    client = await _fresh_db()
    try:
        subs = _share_subs()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert student.id is not None
        token = await subs.create_share_token(student.id, telegram_id=1)
        assert token is not None
        a, b = await asyncio.gather(
            subs.redeem_share_token(token, telegram_id=2),
            subs.redeem_share_token(token, telegram_id=3),
        )
        # Ровно один получил ученика (одноразовый find_one_and_delete).
        assert (a is None) != (b is None)
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_create_share_token_rejects_non_subscriber():
    client = await _fresh_db()
    try:
        subs = _share_subs()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert student.id is not None
        # Пользователь 999 не подписан → ссылку выписать нельзя.
        assert await subs.create_share_token(student.id, telegram_id=999) is None
    finally:
        await client.drop_database(TEST_DB)
        await client.close()


async def test_redeem_invalid_or_expired_token_returns_none():
    client = await _fresh_db()
    try:
        subs = _share_subs()
        student, _ = await subs.subscribe(1, "Иванов", "4022", "083074")
        assert student.id is not None
        # Несуществующий токен.
        assert await subs.redeem_share_token("nope", telegram_id=2) is None
        # Просроченный токен (вставлен напрямую с прошедшим expires_at).
        await ShareToken(
            token_hash=hash_token("expired"),
            student_id=student.id,
            created_by=1,
            expires_at=utcnow() - timedelta(seconds=1),
        ).insert()
        assert await subs.redeem_share_token("expired", telegram_id=2) is None
        assert 2 not in await subs.subscribers_for(student.id)
    finally:
        await client.drop_database(TEST_DB)
        await client.close()
