from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import main_menu, results_link_keyboard
from ege_notifier.config import Settings
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import RefreshThrottled, ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

router = Router(name="common")


async def _register_user(
    message: Message, subscriptions: SubscriptionService, notifier: Notifier
) -> None:
    """Регистрирует/обновляет пользователя; о новом — уведомляет админа."""
    user = message.from_user
    if user is None:
        return
    registered, created = await subscriptions.upsert_user(
        user.id, user.username, user.full_name
    )
    if created:
        await notifier.notify_admin(texts.admin_new_user(registered))


# Deep-link /start <token> — приглашение по одноразовой ссылке. Регистрируем ВЫШЕ
# обычного /start: CommandStart(deep_link=True) срабатывает только при наличии
# полезной нагрузки, а CommandStart() поймал бы и её — побеждает первый по порядку.
@router.message(CommandStart(deep_link=True))
async def cmd_start_shared(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
    settings: Settings,
) -> None:
    await state.clear()
    await _register_user(message, subscriptions, notifier)
    user = message.from_user
    if user is None:
        return

    student = await subscriptions.redeem_share_token(command.args or "", user.id)
    if student is None:
        await message.answer(texts.SHARE_INVALID, reply_markup=main_menu())
        return

    await message.answer(
        texts.SHARE_REDEEMED.format(label=student.label), reply_markup=main_menu()
    )
    # Уже известные баллы показываем сразу — diff ниже их не выдаст (они не новые).
    if student.results:
        await notifier.send(user.id, texts.format_current_results(student))

    # Подтягиваем свежие результаты (с учётом анти-спам кулдауна на ученика).
    try:
        changes = await results.check_student(student, manual=True)
    except (StudentNotFoundError, RefreshThrottled):
        return
    if changes:
        assert student.id is not None  # ученик существует (redeem вернул его)
        subscriber_ids = await subscriptions.subscribers_for(student.id)
        text = texts.format_results_update(student, changes)
        await notifier.broadcast(
            subscriber_ids, text, results_link_keyboard(settings.results_site_url)
        )
        await notifier.notify_admin(texts.admin_new_results(student, changes))


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    subscriptions: SubscriptionService,
    notifier: Notifier,
) -> None:
    await state.clear()
    await _register_user(message, subscriptions, notifier)
    await message.answer(texts.WELCOME, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.CANCELLED, reply_markup=main_menu())


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.CANCELLED, reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.WELCOME, reply_markup=main_menu())
    await callback.answer()
