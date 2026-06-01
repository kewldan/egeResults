from __future__ import annotations

import asyncio
import logging

from ege_notifier.bot.factory import build_bot, build_dispatcher
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


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    client = await init_db(settings.mongo_uri, settings.mongo_db)

    cipher = Cipher(settings.encryption_key)
    provider = build_provider(settings)
    subscriptions = SubscriptionService(settings, cipher)
    bot = build_bot(settings.bot_token)
    notifier = Notifier(bot)
    results = ResultsService(settings, provider, subscriptions)

    dp = build_dispatcher(subscriptions, results, notifier)
    scheduler = build_scheduler(settings, results, notifier)
    scheduler.start()
    logger.info("Запущено. Источник=%s", settings.provider)

    if settings.check_on_startup:
        asyncio.create_task(run_check_cycle(results, notifier))

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await client.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
