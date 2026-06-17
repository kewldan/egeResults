"""Команды администратора: топ по предмету и ручной запуск проверки результатов.

Доступ ограничен фильтром ``IsAdmin`` на уровне роутера (см. ``settings.admin_ids``):
сообщения не-админов сюда не попадают и проваливаются в следующие роутеры, как если
бы этих команд не существовало. Админов может быть несколько (``ADMIN_ID`` — список
ID через запятую). Роутер включается в ``factory`` ВЫШЕ ``add_student``, чтобы ``/top``
и ``/check`` ловились по Command-фильтру даже во время FSM-добавления.

``/top``  — топ учеников по предмету (или список доступных предметов без аргумента).
``/check`` — запускает плановую проверку всех учеников в фоне (как цикл по расписанию).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

from ege_notifier.bot import texts
from ege_notifier.config import Settings
from ege_notifier.models import Student
from ege_notifier.scheduler import broadcast_updates
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.ranking import available_subjects, rank_by_subject
from ege_notifier.services.results import ResultsService
from ege_notifier.utils import normalize_subject

logger = logging.getLogger(__name__)

router = Router(name="admin")


class IsAdmin(BaseFilter):
    """Пропускает только сообщения от админов (``settings.admin_ids``; DI отдаёт ``settings``)."""

    async def __call__(self, message: Message, settings: Settings) -> bool:
        return (
            message.from_user is not None
            and message.from_user.id in settings.admin_ids
        )


router.message.filter(IsAdmin())


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject) -> None:
    """Топ по предмету. Без аргумента — список доступных предметов с числом учеников.

    Необязательный фильтр по заметке (``Student.notes``) — после ``|``:
    ``/top русский | группа А`` оставит в топе только учеников, в чьей заметке
    встречается «группа А» (подстрока, без учёта регистра).
    """
    # Админ-команда, набор учеников — это отслеживаемый «класс» (десятки записей),
    # поэтому грузим всех одним запросом и считаем в памяти (без N+1).
    students = await Student.find_all().to_list()

    arg = (command.args or "").strip()
    if not arg:
        await message.answer(texts.admin_subjects_overview(available_subjects(students)))
        return

    # «предмет | фильтр по заметке» — предмет может быть из нескольких слов, поэтому
    # разделитель явный. Без ``|`` фильтра нет, поведение прежнее.
    subject_arg, _, notes_arg = arg.partition("|")
    subject_arg = subject_arg.strip()
    notes_arg = notes_arg.strip()

    entries = rank_by_subject(students, normalize_subject(subject_arg), notes_arg)
    if not entries:
        await message.answer(texts.admin_top_empty(subject_arg, notes_arg or None))
        return
    # Заголовок — как предмет называет сайт (subject_title), иначе ввод администратора.
    title = entries[0].subject_title or subject_arg
    await message.answer(texts.admin_subject_ranking(title, entries, notes_arg or None))


# Защита от параллельных ручных запусков: плановая и ручная проверки безопасны
# (per-student блокировки + идемпотентный diff), но дёргать сайт дважды незачем.
_check_running = False


@router.message(Command("check"))
async def cmd_check(
    message: Message,
    results: ResultsService,
    notifier: Notifier,
    settings: Settings,
) -> None:
    """Запускает проверку всех учеников в фоне и шлёт админу сводку по завершении."""
    global _check_running
    if _check_running:
        await message.answer(texts.ADMIN_CHECK_ALREADY_RUNNING)
        return
    _check_running = True
    await message.answer(texts.ADMIN_CHECK_STARTED)
    # В фоне, чтобы не блокировать обработку апдейтов на время цикла (с request_delay
    # он длится десятки секунд). Сводку и рассылку подписчикам делает _run_check.
    _spawn(_run_check(results, notifier, settings))


async def _run_check(
    results: ResultsService, notifier: Notifier, settings: Settings
) -> None:
    """Один проход проверки: обновить всех учеников, разослать баллы и сводку админу."""
    global _check_running
    try:
        updates = await results.check_all()
        # Рассылка подписчикам + сводный дайджест админу (общий код планового цикла).
        await broadcast_updates(updates, notifier, settings)
        await notifier.notify_admin(texts.admin_check_done(len(updates)))
    finally:
        _check_running = False


# Сильные ссылки на фоновые задачи: иначе их может собрать GC до завершения, а
# исключения — потеряться.
_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Фоновая admin-задача завершилась с ошибкой", exc_info=exc)
