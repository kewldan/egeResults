"""Тесты выбора хранилища FSM (Redis vs память) — без живого Redis."""

from __future__ import annotations

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from ege_notifier.bot.factory import build_storage


def test_build_storage_memory_by_default():
    assert isinstance(build_storage(None), MemoryStorage)
    assert isinstance(build_storage(""), MemoryStorage)


async def test_build_storage_redis_when_url_set():
    # from_url создаёт клиент лениво — подключения к Redis при сборке нет.
    storage = build_storage("redis://localhost:6379/0")
    assert isinstance(storage, RedisStorage)
    await storage.close()
