from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from ege_notifier.bot.handlers import add_student, common, my_students
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService
from ege_notifier.services.subscriptions import SubscriptionService


def build_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_storage(redis_url: str | None) -> BaseStorage:
    """Хранилище состояний FSM: Redis (переживает рестарт) или память (dev).

    ``redis`` импортируется лениво, чтобы пакет не требовался, когда бот работает
    на ``MemoryStorage`` (значение по умолчанию)."""
    if redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(redis_url)
    return MemoryStorage()


def build_dispatcher(
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
    storage: BaseStorage | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())
    # Сервисы прокидываются в хендлеры через workflow data (по имени аргумента).
    dp["subscriptions"] = subscriptions
    dp["results"] = results
    dp["notifier"] = notifier

    dp.include_router(common.router)
    dp.include_router(add_student.router)
    dp.include_router(my_students.router)
    return dp
