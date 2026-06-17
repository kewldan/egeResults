from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from ege_notifier.bot.handlers import add_student, admin, common, my_students
from ege_notifier.config import Settings
from ege_notifier.services.cards import CardRenderer
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
    settings: Settings,
    storage: BaseStorage | None = None,
    cards: CardRenderer | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())
    # Сервисы прокидываются в хендлеры через workflow data (по имени аргумента).
    dp["subscriptions"] = subscriptions
    dp["results"] = results
    dp["notifier"] = notifier
    dp["settings"] = settings
    # Рендерер карточек: None, если выключен — хендлер make_card это учитывает.
    dp["cards"] = cards

    dp.include_router(common.router)
    # admin — выше add_student, чтобы /top и /check ловились по Command-фильтру даже
    # во время FSM добавления (иначе их перехватили бы state-хендлеры add_student).
    dp.include_router(admin.router)
    dp.include_router(add_student.router)
    dp.include_router(my_students.router)
    return dp
