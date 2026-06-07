from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

from ege_notifier.models import User

logger = logging.getLogger(__name__)


class Notifier:
    """Отправка уведомлений пользователям через Telegram с обработкой ошибок."""

    def __init__(
        self, bot: Bot, broadcast_delay: float = 0.05, admin_id: int | None = None
    ):
        self._bot = bot
        # Пауза между сообщениями веерной рассылки (анти-rate-limit Telegram).
        self._broadcast_delay = broadcast_delay
        # Кому слать служебные уведомления (новые результаты/пользователи); None — выкл.
        self._admin_id = admin_id

    async def send(
        self,
        telegram_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        try:
            await self._bot.send_message(telegram_id, text, reply_markup=reply_markup)
            return True
        except TelegramRetryAfter as exc:
            # Превышен лимит — ждём и пробуем снова один раз.
            logger.warning("Rate limit, ждём %s с", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            return await self.send(telegram_id, text, reply_markup)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — помечаем неактивным.
            await self._deactivate(telegram_id)
            return False
        except TelegramBadRequest as exc:
            logger.warning("Не удалось отправить сообщение %s: %s", telegram_id, exc)
            return False

    async def broadcast(
        self,
        telegram_ids: Iterable[int],
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> int:
        sent = 0
        for i, tid in enumerate(telegram_ids):
            if i and self._broadcast_delay > 0:
                await asyncio.sleep(
                    self._broadcast_delay
                )  # троттлинг под лимит Telegram
            if await self.send(tid, text, reply_markup):
                sent += 1
        return sent

    async def notify_admin(self, text: str) -> bool:
        """Шлёт служебное уведомление админу (если ADMIN_ID задан)."""
        if self._admin_id is None:
            return False
        return await self.send(self._admin_id, text)

    async def _deactivate(self, telegram_id: int) -> None:
        user = await User.find_one(User.telegram_id == telegram_id)
        if user is not None and user.is_active:
            user.is_active = False
            await user.save()
            logger.info(
                "Пользователь %s заблокировал бота — помечен неактивным", telegram_id
            )
