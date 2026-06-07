from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.deep_linking import create_start_link
from beanie import PydanticObjectId

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import (
    back_to_list_keyboard,
    main_menu,
    results_card_keyboard,
    results_link_keyboard,
    student_card_keyboard,
    students_keyboard,
)
from ege_notifier.bot.ui import edit_message
from ege_notifier.config import Settings
from ege_notifier.models import Student
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import RefreshThrottled, ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

router = Router(name="my_students")


def _parse_id(data: str) -> PydanticObjectId | None:
    try:
        return PydanticObjectId(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def _show_list(
    message: Message, subscriptions: SubscriptionService, telegram_id: int
) -> None:
    students = await subscriptions.list_subscriptions(telegram_id)
    if not students:
        await edit_message(message, texts.NO_STUDENTS, main_menu())
        return
    await edit_message(
        message, texts.students_overview(students), students_keyboard(students)
    )


@router.callback_query(F.data == "my_students")
async def list_students(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    if isinstance(callback.message, Message):
        await _show_list(callback.message, subscriptions, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"))
async def open_card(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    """Карточка ученика: текущие результаты + действия (обновить/поделиться/удалить)."""
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    # Авторизация: карточку (PII-баллы) показываем только подписчикам — иначе
    # подделанный callback дал бы доступ к результатам чужого ученика.
    if callback.from_user.id not in await subscriptions.subscribers_for(student_id):
        await callback.answer("Ученик не найден", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await edit_message(
            callback.message,
            texts.format_current_results(student),
            student_card_keyboard(student_id),
        )


@router.callback_query(F.data.startswith("share:"))
async def share_student(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    settings: Settings,
) -> None:
    """Выдаёт одноразовую ссылку-приглашение (получатель не узнает паспорт)."""
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    # Авторизация (подписчик?) — внутри create_share_token: вернёт None, если нет.
    token = await subscriptions.create_share_token(student_id, callback.from_user.id)
    if token is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return
    await callback.answer()
    if not isinstance(callback.message, Message) or callback.bot is None:
        return
    link = await create_start_link(callback.bot, token)
    ttl = texts.human_duration(settings.share_link_ttl_seconds)
    await edit_message(
        callback.message,
        texts.SHARE_LINK.format(link=link, ttl=ttl),
        back_to_list_keyboard(),
    )


@router.callback_query(F.data.startswith("del:"))
async def delete_student(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    await subscriptions.unsubscribe(callback.from_user.id, student_id)
    await callback.answer("🗑 Удалено")
    # Карточку правим обратно в список (без отдельного сообщения «Удалено»).
    if isinstance(callback.message, Message):
        await _show_list(callback.message, subscriptions, callback.from_user.id)


@router.callback_query(F.data.startswith("check:"))
async def check_now(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
    settings: Settings,
) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return

    # Авторизация: запускать проверку и видеть результаты может только подписчик —
    # иначе подделанный callback вытянул бы баллы чужого ученика инлайном. Этот же
    # список нужен ниже для рассылки остальным подписчикам, поэтому берём один раз.
    assert student.id is not None  # student получен через Student.get выше
    subscriber_ids = await subscriptions.subscribers_for(student.id)
    if callback.from_user.id not in subscriber_ids:
        await callback.answer("Ученик не найден", show_alert=True)
        return

    await callback.answer("Проверяю…")
    if not isinstance(callback.message, Message):
        return

    card = student_card_keyboard(student.id)
    try:
        changes = await results.check_student(student, manual=True)
    except StudentNotFoundError:
        await edit_message(
            callback.message, texts.STUDENT_NOT_FOUND.format(label=student.label), card
        )
        return
    except RefreshThrottled as exc:
        # Источник опрашивали слишком недавно (общий лимит на ученика) — не дёргаем сайт.
        await edit_message(
            callback.message, texts.refresh_throttled(exc.retry_after), card
        )
        return

    if changes:
        text = texts.format_results_update(student, changes)
        # Инициатору правим карточку в результат (кнопки: сайт + назад к списку).
        await edit_message(
            callback.message, text, results_card_keyboard(settings.results_site_url)
        )
        # check_student уже записал снимок в БД → плановая проверка эти изменения
        # больше не увидит; уведомляем остальных подписчиков, иначе они пропустят.
        others = [tid for tid in subscriber_ids if tid != callback.from_user.id]
        await notifier.broadcast(
            others, text, results_link_keyboard(settings.results_site_url)
        )
        await notifier.notify_admin(texts.admin_new_results(student, changes))
    else:
        await edit_message(
            callback.message, texts.NO_CHANGES.format(label=student.label), card
        )
