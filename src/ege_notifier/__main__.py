from __future__ import annotations

import asyncio
import contextlib
import logging

from ege_notifier.bot.factory import build_bot, build_dispatcher, build_storage
from ege_notifier.config import Settings
from ege_notifier.db import init_db
from ege_notifier.logging_setup import setup_logging
from ege_notifier.providers import build_provider
from ege_notifier.scheduler import build_scheduler, run_check_cycle
from ege_notifier.security import Cipher
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    """Логирует исключение фоновой задачи (иначе оно молча проглатывается)."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Стартовая проверка завершилась с ошибкой", exc_info=exc)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    client = await init_db(settings.mongo_uri, settings.mongo_db)

    cipher = Cipher(settings.encryption_key)
    if settings.identity_secret == "change-me-please":
        logger.warning(
            "IDENTITY_SECRET не задан — используется значение по умолчанию. "
            "Установите свой секрет до накопления данных: менять его потом нельзя "
            "(сломается дедупликация учеников по identity_hash)."
        )
    provider = build_provider(settings)
    subscriptions = SubscriptionService(settings, cipher)
    bot = build_bot(settings.bot_token)
    notifier = Notifier(bot, settings.broadcast_delay, settings.admin_id)
    results = ResultsService(settings, provider, subscriptions)

    storage = build_storage(settings.redis_url)
    dp = build_dispatcher(subscriptions, results, notifier, settings, storage)
    scheduler = build_scheduler(settings, results, notifier)
    scheduler.start()
    logger.info(
        "Запущено. Источник=%s, FSM=%s",
        settings.provider,
        "redis" if settings.redis_url else "memory",
    )

    # Держим ссылку на задачу: иначе её может собрать GC, а исключения — потеряться.
    startup_task: asyncio.Task | None = None
    if settings.check_on_startup:
        startup_task = asyncio.create_task(run_check_cycle(results, notifier, settings))
        startup_task.add_done_callback(_log_task_exception)

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        if startup_task is not None and not startup_task.done():
            startup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await startup_task
        scheduler.shutdown(wait=False)
        await dp.storage.close()  # закрывает пул Redis (для MemoryStorage — no-op)
        await bot.session.close()
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await client.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
