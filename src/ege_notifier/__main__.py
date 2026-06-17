from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable

from ege_notifier.bot.factory import build_bot, build_dispatcher, build_storage
from ege_notifier.config import Settings
from ege_notifier.db import init_db
from ege_notifier.logging_setup import setup_logging
from ege_notifier.providers import build_provider
from ege_notifier.providers.ege_spb_overview import EgeSpbOverviewMonitor
from ege_notifier.scheduler import build_scheduler, run_check_cycle, run_monitor_cycle
from ege_notifier.security import Cipher
from ege_notifier.services.cards import CardRenderer
from ege_notifier.services.monitor import MonitorService
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
        logger.error("Фоновая стартовая задача завершилась с ошибкой", exc_info=exc)


async def _safe_close(label: str, coro: Awaitable[object]) -> None:
    """Закрывает ресурс на shutdown, не давая его сбою оборвать остальные closer'ы."""
    try:
        await coro
    except Exception as exc:
        logger.warning("Ошибка при закрытии (%s): %s", label, exc)


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

    # Монитор страницы-обзора — основной триггер проверок (см. scheduler).
    overview: EgeSpbOverviewMonitor | None = None
    monitor: MonitorService | None = None
    if settings.page_monitor_enabled:
        overview = EgeSpbOverviewMonitor(
            settings.results_site_url, timeout=settings.request_timeout
        )
        monitor = MonitorService(overview)

    # Рендерер карточек результатов (отдельный сервис на Bun). Выключен → кнопки нет.
    cards: CardRenderer | None = None
    if settings.card_renderer_enabled:
        cards = CardRenderer(
            settings.card_renderer_url,
            scale=settings.card_render_scale,
            timeout=settings.card_render_timeout,
        )

    storage = build_storage(settings.redis_url)
    dp = build_dispatcher(subscriptions, results, notifier, settings, storage, cards)
    scheduler = build_scheduler(settings, results, notifier, subscriptions, monitor)
    scheduler.start()
    logger.info(
        "Запущено. Источник=%s, монитор=%s, FSM=%s",
        settings.provider,
        "on" if monitor is not None else "off",
        "redis" if settings.redis_url else "memory",
    )

    # Держим ссылки на задачи: иначе их может собрать GC, а исключения — потеряться.
    startup_tasks: list[asyncio.Task] = []
    if settings.check_on_startup:
        startup_tasks.append(
            asyncio.create_task(run_check_cycle(results, notifier, settings))
        )
    if monitor is not None:
        # Один опрос сразу при старте: запоминает базовый снимок (свежий деплой) и
        # ловит изменения, случившиеся, пока бот был выключен. До первого тика
        # планировщика иначе ждать целый интервал.
        startup_tasks.append(
            asyncio.create_task(
                run_monitor_cycle(monitor, results, notifier, subscriptions, settings)
            )
        )
    for task in startup_tasks:
        task.add_done_callback(_log_task_exception)

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        for task in startup_tasks:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        scheduler.shutdown(wait=False)
        # Закрываем ресурсы по очереди; сбой одного closer'а не должен оборвать
        # остальные (иначе, напр., упавший overview.aclose оставил бы Mongo открытым).
        await _safe_close("FSM storage", dp.storage.close())  # пул Redis (Memory — no-op)
        await _safe_close("bot session", bot.session.close())
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await _safe_close("provider", aclose())
        if overview is not None:
            await _safe_close("overview monitor", overview.aclose())
        if cards is not None:
            await _safe_close("card renderer", cards.aclose())
        await _safe_close("mongo client", client.close())


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
