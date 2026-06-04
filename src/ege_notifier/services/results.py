from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass

from beanie import PydanticObjectId
from beanie.exceptions import DocumentNotFound
from beanie.operators import In

from ege_notifier.config import Settings
from ege_notifier.models import Student
from ege_notifier.providers.base import ResultsProvider, StudentNotFoundError
from ege_notifier.services.diff import ResultChange, diff_results, merge_results
from ege_notifier.services.subscriptions import SubscriptionService
from ege_notifier.utils import utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StudentUpdate:
    student: Student
    changes: list[ResultChange]
    subscribers: list[int]


class ResultsService:
    """Получение результатов у источника, вычисление изменений и их сохранение."""

    def __init__(
        self,
        settings: Settings,
        provider: ResultsProvider,
        subscriptions: SubscriptionService,
    ):
        self._settings = settings
        self._provider = provider
        self._subs = subscriptions
        # Блокировки по id ученика: ручная и плановая проверки не должны
        # одновременно сохранять одного ученика (lost update / дубль-уведомление).
        # WeakValueDictionary — чтобы запись жила, только пока блокировку кто-то
        # держит/вот-вот возьмёт, и не копилась навсегда по каждому ученику.
        self._locks: weakref.WeakValueDictionary[PydanticObjectId, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _lock_for(self, student_id: PydanticObjectId) -> asyncio.Lock:
        # Без await между get и присваиванием — конкурентные корутины получают
        # один и тот же объект блокировки (event loop однопоточный).
        lock = self._locks.get(student_id)
        if lock is None:
            lock = self._locks[student_id] = asyncio.Lock()
        return lock

    async def check_student(self, student: Student) -> list[ResultChange]:
        """Проверяет одного ученика, обновляет его результаты в БД и возвращает изменения.

        Поднимает ``NotImplementedError``, если выбранный источник ещё не настроен
        (например, ege.spb.ru до подключения реального запроса)."""
        if student.id is None:
            return await self._check_student_locked(student)
        async with self._lock_for(student.id):
            # Перечитываем актуальный снимок под блокировкой: если параллельная
            # проверка уже сохранила результаты, diff не выдаст их повторно.
            latest = await Student.get(student.id)
            if latest is None:
                # Ученик удалён (последняя отписка) — не воскрешаем его.
                return []
            student.results = latest.results
            student.last_checked_at = latest.last_checked_at
            student.last_changed_at = latest.last_changed_at
            student.last_error = latest.last_error
            student.not_found = latest.not_found
            return await self._check_student_locked(student)

    async def _persist(self, student: Student) -> bool:
        """Сохраняет ученика, НЕ воскрешая удалённую запись.

        Если последний подписчик отписался во время медленного fetch, ученик уже
        удалён — ``save()`` (upsert) воскресил бы его вместе с PII. ``replace()``
        не делает upsert и бросает ``DocumentNotFound`` — тогда просто молчим."""
        if student.id is None:
            await student.insert()
            return True
        try:
            await student.replace()
            return True
        except DocumentNotFound:
            logger.info(
                "Ученик id=%s удалён во время проверки — не воскрешаем", student.id
            )
            return False

    async def _check_student_locked(self, student: Student) -> list[ResultChange]:
        query = self._subs.to_query(student)
        try:
            fetched = await self._provider.fetch(query)
        except NotImplementedError:
            raise
        except StudentNotFoundError:
            # Источник не нашёл ученика (вероятна опечатка в фамилии/паспорте).
            # Помечаем флагом и пробрасываем выше — хендлер подскажет проверить
            # данные. Результаты НЕ трогаем: если ученик раньше находился, разовый
            # «не найден» (сбой сайта) не должен стирать уже известные баллы.
            student.not_found = True
            student.last_error = None
            student.last_checked_at = utcnow()
            await self._persist(student)
            logger.info("Ученик id=%s не найден источником (опечатка?)", student.id)
            raise
        except Exception as exc:  # сетевые/парсинговые ошибки не должны валить цикл
            student.last_error = str(exc)
            student.last_checked_at = utcnow()
            await self._persist(student)
            logger.warning("Ошибка проверки ученика id=%s: %s", student.id, exc)
            return []

        changes = diff_results(student.results, fetched)
        student.results = merge_results(student.results, fetched)
        student.last_checked_at = utcnow()
        student.last_error = None
        student.not_found = False
        if changes:
            student.last_changed_at = utcnow()
        if not await self._persist(student):
            return []  # ученика удалили во время проверки — не уведомляем
        return changes

    async def check_all(self) -> list[StudentUpdate]:
        """Проверяет всех учеников, у которых есть хотя бы один подписчик."""
        updates: list[StudentUpdate] = []
        subscribers_by_id = await self._subs.subscribers_by_student()
        if not subscribers_by_id:
            return updates
        # Берём только учеников с подписчиками (без find_all + N+1 на подписки).
        students = await Student.find(In(Student.id, list(subscribers_by_id))).to_list()
        logger.info("Плановая проверка: учеников с подписчиками=%d", len(students))
        for student in students:
            subscribers = subscribers_by_id.get(student.id, [])
            if not subscribers:
                continue  # некому слать — пропускаем (и не дёргаем источник)
            try:
                changes = await self.check_student(student)
            except StudentNotFoundError:
                # Флаг «не найден» уже сохранён; не уведомляем и не валим цикл.
                changes = []
            if changes:
                updates.append(
                    StudentUpdate(
                        student=student, changes=changes, subscribers=subscribers
                    )
                )
            if self._settings.request_delay > 0:
                await asyncio.sleep(self._settings.request_delay)
        return updates
