from __future__ import annotations

import asyncio
from typing import Any, cast

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from ege_notifier.services.notifier import Notifier


class FakeBot:
    """Минимальный двойник aiogram.Bot: записывает отправленные сообщения и умеет
    по запросу падать с заданными ошибками."""

    def __init__(
        self, fail_ids: set[int] | None = None, retry_ids: set[int] | None = None
    ):
        self.sent: list[tuple[int, str]] = []
        self._fail = fail_ids or set()
        self._retry_pending = set(retry_ids or set())

    async def send_message(
        self, telegram_id: int, text: str, reply_markup: object = None
    ) -> None:
        if telegram_id in self._fail:
            raise TelegramBadRequest(method=cast(Any, None), message="bad request")
        if telegram_id in self._retry_pending:
            self._retry_pending.discard(telegram_id)  # второй раз пройдёт
            raise TelegramRetryAfter(
                method=cast(Any, None), message="slow down", retry_after=0
            )
        self.sent.append((telegram_id, text))


async def test_broadcast_sends_to_all():
    bot = FakeBot()
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0)
    sent = await notifier.broadcast([1, 2, 3], "hi")
    assert sent == 3
    assert [tid for tid, _ in bot.sent] == [1, 2, 3]


async def test_broadcast_skips_failed_but_continues():
    bot = FakeBot(fail_ids={2})
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0)
    sent = await notifier.broadcast([1, 2, 3], "hi")
    assert sent == 2
    assert [tid for tid, _ in bot.sent] == [1, 3]


async def test_send_retries_once_on_rate_limit():
    bot = FakeBot(retry_ids={1})
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0)
    assert await notifier.send(1, "hi") is True
    assert bot.sent == [(1, "hi")]


async def test_notify_admin_sends_when_configured():
    bot = FakeBot()
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0, admin_id=777)
    assert await notifier.notify_admin("ping") is True
    assert bot.sent == [(777, "ping")]


async def test_notify_admin_noop_without_admin_id():
    bot = FakeBot()
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0)
    assert await notifier.notify_admin("ping") is False
    assert bot.sent == []


async def test_broadcast_throttles_between_messages(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    bot = FakeBot()
    notifier = Notifier(cast(Bot, bot), broadcast_delay=0.01)
    await notifier.broadcast([1, 2, 3], "hi")
    # Пауза между сообщениями — (n-1) раз, не перед первым и не после последнего.
    assert delays == [0.01, 0.01]
