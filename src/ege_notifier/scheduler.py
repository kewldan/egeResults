from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import results_link_keyboard
from ege_notifier.config import Settings
from ege_notifier.services.monitor import MonitorService
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService, StudentUpdate
from ege_notifier.services.subscriptions import SubscriptionService

logger = logging.getLogger(__name__)


async def broadcast_updates(
    updates: list[StudentUpdate], notifier: Notifier, settings: Settings
) -> None:
    """Рассылает изменения подписчикам каждого ученика + сводку админу.

    Общая часть планового цикла и монитора: текст на ученика → веер подписчикам,
    одно сводное сообщение админу за вызов (а не по одному на ученика — иначе пачка
    в один чат поймала бы TelegramRetryAfter)."""
    markup = results_link_keyboard(settings.results_site_url)
    for upd in updates:
        text = texts.format_results_update(upd.student, upd.changes)
        await notifier.broadcast(upd.subscribers, text, markup)
    if updates:
        await notifier.notify_admin(texts.admin_results_digest(updates))
        logger.info("Разослано уведомлений по %d ученик(ам)", len(updates))


async def run_check_cycle(
    results: ResultsService, notifier: Notifier, settings: Settings
) -> None:
    """Один цикл: проверить всех учеников и разослать уведомления подписчикам."""
    updates = await results.check_all()
    await broadcast_updates(updates, notifier, settings)


async def run_monitor_cycle(
    monitor: MonitorService,
    results: ResultsService,
    notifier: Notifier,
    subscriptions: SubscriptionService,
    settings: Settings,
) -> None:
    """Опрашивает страницу-обзор; при изменении — проверяет учеников и шлёт анонс.

    Главный быстрый триггер (раз в несколько минут): дешёвый GET одной страницы.
    Если счётчик «результатов в базе» вырос или в #w2 появился новый предмет —
    (1) полная проверка учеников и рассылка их баллов подписчикам; (2) анонс
    «результаты выложили» тем, кто в боте, но не вводил паспортные данные."""
    try:
        change = await monitor.poll()
    except Exception as exc:  # сетевая/парсинговая ошибка не должна валить планировщик
        logger.warning("Монитор: ошибка опроса страницы-обзора: %s", exc)
        return

    if not change.has_results_update:
        return

    logger.info(
        "Монитор: изменение страницы (счётчик→%s, Δ=%s, новых предметов=%d) — "
        "запускаем проверку учеников",
        change.new_count,
        change.delta,
        len(change.new_subjects),
    )

    try:
        # (1) Проверяем учеников с подписчиками и шлём их баллы — как плановый цикл.
        updates = await results.check_all()
        await broadcast_updates(updates, notifier, settings)

        # (2) Анонс публикации — только при новом предмете (есть что назвать и оценить).
        if change.new_subjects:
            audience = await subscriptions.passportless_user_ids()
            if audience:
                text = texts.results_published_announcement(
                    change.new_subjects, change.delta, change.new_count
                )
                await notifier.broadcast(
                    audience, text, results_link_keyboard(settings.results_site_url)
                )
                logger.info(
                    "Анонс публикации разослан %d пользователю(ям)", len(audience)
                )
            await notifier.notify_admin(
                texts.admin_subjects_published(change.new_subjects, change.delta)
            )
    except Exception:
        # Состояние НЕ фиксируем — изменение поймается на следующем опросе (анонс не
        # теряется). Рассылка идемпотентна, повтор до успеха не задваивает баллы.
        logger.exception(
            "Монитор: обработка изменения упала — состояние не фиксируем, повторим позже"
        )
        return

    # Фиксируем новое состояние страницы только после успешной проверки и рассылки.
    await monitor.commit(change)


def build_scheduler(
    settings: Settings,
    results: ResultsService,
    notifier: Notifier,
    subscriptions: SubscriptionService | None = None,
    monitor: MonitorService | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    if settings.check_cron:
        trigger = CronTrigger.from_crontab(
            settings.check_cron, timezone=settings.timezone
        )
        logger.info("Расписание проверок: cron='%s'", settings.check_cron)
    else:
        trigger = IntervalTrigger(seconds=settings.check_interval_seconds)
        logger.info("Расписание проверок: каждые %d с", settings.check_interval_seconds)

    scheduler.add_job(
        run_check_cycle,
        trigger=trigger,
        args=[results, notifier, settings],
        id="check_results",
        max_instances=1,  # не запускать новый цикл, пока не закончился предыдущий
        coalesce=True,
    )

    # Монитор страницы-обзора — основной, быстрый триггер проверок. monitor создаётся
    # в __main__ только при page_monitor_enabled, поэтому отдельно его тут не проверяем;
    # subscriptions нужен телу цикла (passportless_user_ids), без него job не ставим.
    if monitor is not None and subscriptions is not None:
        scheduler.add_job(
            run_monitor_cycle,
            trigger=IntervalTrigger(seconds=settings.page_monitor_interval_seconds),
            args=[monitor, results, notifier, subscriptions, settings],
            id="page_monitor",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Монитор страницы: каждые %d с", settings.page_monitor_interval_seconds
        )
    return scheduler
