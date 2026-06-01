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

from ege_notifier.models import User

logger = logging.getLogger(__name__)


class Notifier:
    """Отправка уведомлений пользователям через Telegram с обработкой ошибок."""

    def __init__(self, bot: Bot):
        self._bot = bot

    async def send(self, telegram_id: int, text: str) -> bool:
        try:
            await self._bot.send_message(telegram_id, text)
            return True
        except TelegramRetryAfter as exc:
            # Превышен лимит — ждём и пробуем снова один раз.
            logger.warning("Rate limit, ждём %s с", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            return await self.send(telegram_id, text)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — помечаем неактивным.
            await self._deactivate(telegram_id)
            return False
        except TelegramBadRequest as exc:
            logger.warning("Не удалось отправить сообщение %s: %s", telegram_id, exc)
            return False

    async def broadcast(self, telegram_ids: Iterable[int], text: str) -> int:
        sent = 0
        for tid in telegram_ids:
            if await self.send(tid, text):
                sent += 1
        return sent

    async def _deactivate(self, telegram_id: int) -> None:
        user = await User.find_one(User.telegram_id == telegram_id)
        if user is not None and user.is_active:
            user.is_active = False
            await user.save()
            logger.info("Пользователь %s заблокировал бота — помечен неактивным", telegram_id)
