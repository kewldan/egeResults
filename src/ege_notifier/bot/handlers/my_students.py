from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from beanie import PydanticObjectId

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import main_menu, students_keyboard
from ege_notifier.models import Student
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

router = Router(name="my_students")


def _parse_id(data: str) -> PydanticObjectId | None:
    try:
        return PydanticObjectId(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def _show_list(message: Message, subscriptions: SubscriptionService, telegram_id: int) -> None:
    students = await subscriptions.list_subscriptions(telegram_id)
    if not students:
        await message.answer(texts.NO_STUDENTS, reply_markup=main_menu())
        return
    await message.answer(
        texts.students_overview(students), reply_markup=students_keyboard(students)
    )


@router.callback_query(F.data == "my_students")
async def list_students(callback: CallbackQuery, subscriptions: SubscriptionService) -> None:
    if isinstance(callback.message, Message):
        await _show_list(callback.message, subscriptions, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def delete_student(callback: CallbackQuery, subscriptions: SubscriptionService) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    student = await Student.get(student_id)
    label = student.label if student else "ученик"
    await subscriptions.unsubscribe(callback.from_user.id, student_id)
    await callback.answer("Удалено")
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.UNSUBSCRIBED.format(label=label))
        await _show_list(callback.message, subscriptions, callback.from_user.id)


@router.callback_query(F.data.startswith("check:"))
async def check_now(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return

    await callback.answer("Проверяю…")
    if not isinstance(callback.message, Message):
        return

    try:
        changes = await results.check_student(student)
    except NotImplementedError:
        await callback.message.answer(texts.PROVIDER_NOT_READY)
        return

    if changes:
        await callback.message.answer(texts.format_results_update(student, changes))
    else:
        await callback.message.answer(texts.NO_CHANGES.format(label=student.label))
