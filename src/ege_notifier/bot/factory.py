from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ege_notifier.bot.handlers import add_student, common, my_students
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService
from ege_notifier.services.subscriptions import SubscriptionService


def build_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher(
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Сервисы прокидываются в хендлеры через workflow data (по имени аргумента).
    dp["subscriptions"] = subscriptions
    dp["results"] = results
    dp["notifier"] = notifier

    dp.include_router(common.router)
    dp.include_router(add_student.router)
    dp.include_router(my_students.router)
    return dp
