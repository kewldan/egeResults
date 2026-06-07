from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import results_link_keyboard
from ege_notifier.config import Settings
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService

logger = logging.getLogger(__name__)


async def run_check_cycle(
    results: ResultsService, notifier: Notifier, settings: Settings
) -> None:
    """Один цикл: проверить всех учеников и разослать уведомления подписчикам."""
    updates = await results.check_all()
    markup = results_link_keyboard(settings.results_site_url)
    for upd in updates:
        text = texts.format_results_update(upd.student, upd.changes)
        await notifier.broadcast(upd.subscribers, text, markup)
    if updates:
        # Одно сводное сообщение админу на цикл — не по одному на ученика, иначе
        # пачка сообщений в один чат поймала бы TelegramRetryAfter.
        await notifier.notify_admin(texts.admin_results_digest(updates))
        logger.info("Разослано уведомлений по %d ученик(ам)", len(updates))


def build_scheduler(
    settings: Settings, results: ResultsService, notifier: Notifier
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
    return scheduler
