from __future__ import annotations

import logging

from beanie import init_beanie
from pymongo import AsyncMongoClient

from ege_notifier.models import ALL_DOCUMENTS

logger = logging.getLogger(__name__)


async def init_db(mongo_uri: str, mongo_db: str) -> AsyncMongoClient:
    """Создаёт асинхронный клиент pymongo и инициализирует Beanie (ODM).

    ``tz_aware=True`` — чтобы datetime читались из Mongo как timezone-aware UTC
    (как их пишет ``utils.utcnow``), иначе сравнения aware/naive будут падать.
    """
    client: AsyncMongoClient = AsyncMongoClient(mongo_uri, tz_aware=True)
    await init_beanie(database=client[mongo_db], document_models=ALL_DOCUMENTS)
    logger.info("MongoDB подключена: db=%s", mongo_db)
    return client
