from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import main_menu
from ege_notifier.services.subscriptions import SubscriptionService

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, subscriptions: SubscriptionService
) -> None:
    await state.clear()
    user = message.from_user
    if user is not None:
        await subscriptions.upsert_user(user.id, user.username, user.full_name)
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
