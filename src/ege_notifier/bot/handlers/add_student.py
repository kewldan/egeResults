from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import (
    confirm_keyboard,
    main_menu,
    results_link_keyboard,
)
from ege_notifier.bot.states import AddStudent
from ege_notifier.bot.validators import (
    validate_last_name,
    validate_number,
    validate_series,
)
from ege_notifier.config import Settings
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import RefreshThrottled, ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

router = Router(name="add_student")


@router.callback_query(F.data == "add_student")
async def start_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddStudent.last_name)
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.ASK_LAST_NAME)
    await callback.answer()


@router.message(AddStudent.last_name)
async def got_last_name(message: Message, state: FSMContext) -> None:
    name = validate_last_name(message.text or "")
    if name is None:
        await message.answer(texts.BAD_LAST_NAME)
        return
    await state.update_data(last_name=name)
    await state.set_state(AddStudent.passport_series)
    await message.answer(texts.ASK_SERIES)


@router.message(AddStudent.passport_series)
async def got_series(message: Message, state: FSMContext) -> None:
    series = validate_series(message.text or "")
    if series is None:
        await message.answer(texts.BAD_SERIES)
        return
    await state.update_data(passport_series=series)
    await state.set_state(AddStudent.passport_number)
    await message.answer(texts.ASK_NUMBER)


@router.message(AddStudent.passport_number)
async def got_number(message: Message, state: FSMContext) -> None:
    number = validate_number(message.text or "")
    if number is None:
        await message.answer(texts.BAD_NUMBER)
        return
    await state.update_data(passport_number=number)
    data = await state.get_data()
    await state.set_state(AddStudent.confirm)
    await message.answer(texts.confirm_text(data), reply_markup=confirm_keyboard())


@router.callback_query(AddStudent.confirm, F.data == "confirm_add")
async def confirm_add(
    callback: CallbackQuery,
    state: FSMContext,
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
    settings: Settings,
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()

    student, created = await subscriptions.subscribe(
        callback.from_user.id,
        data["last_name"],
        data["passport_series"],
        data["passport_number"],
    )

    if not isinstance(callback.message, Message):
        return

    # Снимок берём до check_student — он перезапишет student.results.
    had_results = bool(student.results)

    if created:
        await callback.message.answer(
            texts.SUBSCRIBED.format(label=student.label), reply_markup=main_menu()
        )
        # Ученик уже отслеживается кем-то и баллы в базе → diff будет пуст,
        # поэтому показываем новому подписчику текущий снимок результатов.
        if had_results:
            await notifier.send(
                callback.from_user.id, texts.format_current_results(student)
            )
    else:
        await callback.message.answer(
            texts.ALREADY_SUBSCRIBED.format(label=student.label),
            reply_markup=main_menu(),
        )

    # Сразу проверим текущие результаты.
    try:
        changes = await results.check_student(student, manual=True)
    except StudentNotFoundError:
        # Источник не нашёл ученика — почти всегда опечатка в данных.
        await callback.message.answer(
            texts.STUDENT_NOT_FOUND.format(label=student.label)
        )
        return
    except RefreshThrottled:
        # Ученика недавно уже проверяли (другим подписчиком/планово). Снимок текущих
        # результатов новый подписчик уже получил выше; плановая проверка догонит.
        return
    if changes:
        # check_student уже записал свежий снимок в БД, поэтому плановая проверка
        # этих изменений больше не увидит — рассылаем их всем подписчикам ученика
        # сразу, иначе остальные подписчики останутся без уведомления.
        assert student.id is not None  # подписанный ученик уже сохранён в БД
        subscriber_ids = await subscriptions.subscribers_for(student.id)
        text = texts.format_results_update(student, changes)
        await notifier.broadcast(
            subscriber_ids, text, results_link_keyboard(settings.results_site_url)
        )
        await notifier.notify_admin(texts.admin_new_results(student, changes))
