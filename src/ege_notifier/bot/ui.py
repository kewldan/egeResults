from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message


async def edit_message(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Правит текст/клавиатуру существующего сообщения вместо отправки нового.

    Так навигация по инлайн-кнопкам не плодит сообщения. Обрабатываем два случая:
    - ``TelegramRetryAfter`` (флуд-контроль) — ждём указанное время и повторяем,
      чтобы не потерять правку;
    - ``TelegramBadRequest`` (сообщение слишком старое, текст не изменился или его
      вовсе нет) — отправляем новое сообщение как запасной путь.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        await edit_message(message, text, reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)
