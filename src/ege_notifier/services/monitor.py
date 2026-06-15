from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pymongo.errors import DuplicateKeyError

from ege_notifier.models import SiteState
from ege_notifier.models.site_state import SITE_STATE_KEY
from ege_notifier.providers.ege_spb_overview import (
    EgeSpbOverviewMonitor,
    PageSnapshot,
    PublishedSubject,
)
from ege_notifier.utils import utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PageChange:
    """Что изменилось на странице-обзоре между прошлым состоянием и свежим опросом."""

    new_subjects: list[PublishedSubject] = field(default_factory=list)
    new_count: int | None = None
    # Прирост счётчика «результатов в базе» (None, если одну из величин не распарсили).
    # ≈ сколько результатов добавилось — этим оцениваем «сколько сдавало предмет».
    delta: int | None = None
    # Первый запуск (состояния ещё нет): снимок просто запомнили, не уведомляем.
    is_baseline: bool = False
    # Снимок, по которому построено изменение. Кладётся сюда, чтобы commit() зафиксировал
    # состояние ТЕМ ЖЕ снимком уже ПОСЛЕ успешной рассылки (а не до неё).
    snapshot: PageSnapshot | None = None

    @property
    def counter_increased(self) -> bool:
        """Счётчик «результатов в базе» вырос (обе величины известны, прирост > 0)."""
        return self.delta is not None and self.delta > 0

    @property
    def has_results_update(self) -> bool:
        """Нужно ли запускать полную проверку учеников.

        Триггер — рост счётчика ИЛИ новый предмет в #w2. На базовом снимке (первый
        запуск) не триггерим, чтобы не разослать анонс об уже опубликованных баллах.
        """
        return not self.is_baseline and (
            self.counter_increased or bool(self.new_subjects)
        )


def diff_page(
    prev_count: int | None, prev_subjects: set[str], snapshot: PageSnapshot
) -> PageChange:
    """Чистое сравнение прошлого состояния страницы со свежим снимком.

    Принимает примитивы (а не ``SiteState``), чтобы быть тестируемой без БД. Новый
    предмет — тот, чей нормализованный ключ ещё не встречался. Счётчик считаем
    выросшим (``PageChange.counter_increased``) только когда обе величины известны и
    прирост положительный (разовый «не распарсили число» не выглядит как изменение).
    """
    new_subjects = [s for s in snapshot.subjects if s.subject not in prev_subjects]
    new_count = snapshot.results_count
    delta = (
        new_count - prev_count
        if prev_count is not None and new_count is not None
        else None
    )
    return PageChange(
        new_subjects=new_subjects,
        new_count=new_count,
        delta=delta,
        snapshot=snapshot,
    )


class MonitorService:
    """Следит за страницей-обзором ege.spb.ru.

    Дешёвый GET одной страницы раз в N минут: счётчик «результатов в базе» и список
    опубликованных предметов основного периода (#w2). Рост счётчика / новый предмет
    — главный, быстрый триггер для полной проверки учеников и анонса «результаты
    выложили». PII при опросе не используется.
    """

    def __init__(self, overview: EgeSpbOverviewMonitor):
        self._overview = overview

    async def poll(self) -> PageChange:
        """Опрашивает страницу и сравнивает с сохранённым состоянием (НЕ сохраняет его).

        На первом запуске (состояния ещё нет) молча запоминает базовый снимок — чтобы
        при свежем деплое не разослать анонс об уже опубликованных предметах.

        Новое состояние фиксирует уже ``commit()`` — вызывающий код зовёт его ПОСЛЕ
        успешной рассылки. Иначе сбой рассылки «съел» бы изменение: на следующем
        опросе оно не считалось бы новым и анонс потерялся бы.
        """
        snapshot = await self._overview.fetch()
        state = await SiteState.find_one(SiteState.key == SITE_STATE_KEY)
        if state is None:
            await self._seed(snapshot)
            logger.info(
                "Монитор: сохранено базовое состояние (счётчик=%s, предметов=%d)",
                snapshot.results_count,
                len(snapshot.subjects),
            )
            return PageChange(new_count=snapshot.results_count, is_baseline=True)

        return diff_page(state.results_count, set(state.published_subjects), snapshot)

    async def commit(self, change: PageChange) -> None:
        """Фиксирует новое состояние страницы — вызывать ПОСЛЕ успешной рассылки.

        Если проверка/рассылка упадёт до commit(), состояние не двигается и изменение
        поймается на следующем опросе (анонс не теряется). Повтор безопасен: баллы
        дедуплицируются по ученику под блокировкой (``ResultsService``), а анонс
        пассивной аудитории рассылается ``Notifier``, который глотает ошибки доставки
        и не поднимает их вверх — то есть до фактической отправки дело не доходит лишь
        при сбое ещё ДО рассылки, и тогда дубля не будет.
        """
        if change.snapshot is None or not change.has_results_update:
            return
        # Перечитываем актуальный документ (не держим старый между poll и commit).
        state = await SiteState.find_one(SiteState.key == SITE_STATE_KEY)
        if state is None:
            return
        await self._save(state, change.snapshot)

    async def _seed(self, snapshot: PageSnapshot) -> None:
        try:
            await SiteState(
                key=SITE_STATE_KEY,
                results_count=snapshot.results_count,
                published_subjects=sorted({s.subject for s in snapshot.subjects}),
            ).insert()
        except DuplicateKeyError:
            # Гонка старт-задачи и планового опроса — базовый снимок уже записан.
            pass

    async def _save(self, state: SiteState, snapshot: PageSnapshot) -> None:
        # Объединяем известные предметы с новыми: предмет не «исчезает», даже если
        # сайт временно не отдал строку. Счётчик берём свежий, когда он распарсился.
        merged = set(state.published_subjects) | {s.subject for s in snapshot.subjects}
        state.published_subjects = sorted(merged)
        if snapshot.results_count is not None:
            state.results_count = snapshot.results_count
        state.updated_at = utcnow()
        await state.save()
