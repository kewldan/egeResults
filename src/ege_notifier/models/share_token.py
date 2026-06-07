from __future__ import annotations

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow


class ShareToken(Document):
    """Одноразовая ссылка-приглашение отслеживать ученика.

    В deep-link кладётся случайный токен, а в БД хранится только его SHA-256-хэш
    (как и PII — секрет не лежит в открытом виде). Гасится атомарно при первом
    использовании (``find_one_and_delete`` в ``SubscriptionService``), поэтому
    срабатывает ровно один раз. Получатель подписывается на ученика и видит ровно
    то же, что прочие подписчики — фамилию и маскированный паспорт, — но НЕ сами
    паспортные данные.
    """

    token_hash: str  # SHA-256 от токена из ссылки (сам токен не храним)
    student_id: PydanticObjectId
    created_by: int  # telegram_id создателя ссылки
    expires_at: datetime  # после — ссылка недействительна (чистит TTL-индекс)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "share_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            # TTL: Mongo сам удаляет документ, когда expires_at оказывается в прошлом
            # (фоновый sweep ~раз в минуту — поэтому при гашении ещё фильтруем по дате).
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
