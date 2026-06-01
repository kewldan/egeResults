from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow


class User(Document):
    """Пользователь Telegram, который пользуется ботом."""

    telegram_id: int
    username: str | None = None
    full_name: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "users"
        indexes = [IndexModel([("telegram_id", ASCENDING)], unique=True)]
