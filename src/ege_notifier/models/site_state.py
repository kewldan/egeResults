from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from ege_notifier.utils import utcnow

# Ключ единственного документа состояния страницы (синглтон-коллекция).
SITE_STATE_KEY = "ege_spb"


class SiteState(Document):
    """Снимок страницы-обзора ege.spb.ru (синглтон, один документ на источник).

    Хранит последний известный счётчик «Количество результатов в базе данных» и
    множество уже опубликованных предметов основного периода (#w2). Монитор
    сравнивает свежий опрос с этим снимком, чтобы поймать рост счётчика / появление
    нового предмета ровно один раз и не разослать анонс повторно.
    """

    key: str = SITE_STATE_KEY
    results_count: int | None = None
    # Нормализованные ключи предметов (utils.normalize_subject), уже опубликованных
    # в #w2 «Основной период». Сравниваются как множество.
    published_subjects: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "site_state"
        indexes = [IndexModel([("key", ASCENDING)], unique=True)]
