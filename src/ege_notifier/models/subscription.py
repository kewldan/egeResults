from __future__ import annotations

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow


class Subscription(Document):
    """Связь «пользователь ⟷ ученик». Один пользователь может отслеживать многих
    учеников, а на одного ученика может быть подписано несколько пользователей."""

    telegram_id: int
    student_id: PydanticObjectId
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "subscriptions"
        indexes = [
            IndexModel(
                [("telegram_id", ASCENDING), ("student_id", ASCENDING)],
                unique=True,
            ),
            IndexModel([("student_id", ASCENDING)]),
        ]
