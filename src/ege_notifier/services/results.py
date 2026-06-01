from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ege_notifier.config import Settings
from ege_notifier.models import Student
from ege_notifier.providers.base import ResultsProvider
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

    async def check_student(self, student: Student) -> list[ResultChange]:
        """Проверяет одного ученика, обновляет его результаты в БД и возвращает изменения.

        Поднимает ``NotImplementedError``, если выбранный источник ещё не настроен
        (например, ege.spb.ru до подключения реального запроса)."""
        query = self._subs.to_query(student)
        try:
            fetched = await self._provider.fetch(query)
        except NotImplementedError:
            raise
        except Exception as exc:  # сетевые/парсинговые ошибки не должны валить цикл
            student.last_error = str(exc)
            student.last_checked_at = utcnow()
            await student.save()
            logger.warning("Ошибка проверки ученика id=%s: %s", student.id, exc)
            return []

        changes = diff_results(student.results, fetched)
        student.results = merge_results(student.results, fetched)
        student.last_checked_at = utcnow()
        student.last_error = None
        if changes:
            student.last_changed_at = utcnow()
        await student.save()
        return changes

    async def check_all(self) -> list[StudentUpdate]:
        """Проверяет всех учеников, у которых есть хотя бы один подписчик."""
        updates: list[StudentUpdate] = []
        students = await Student.find_all().to_list()
        logger.info("Плановая проверка: учеников в базе=%d", len(students))
        for student in students:
            subscribers = await self._subs.subscribers_for(student.id)
            if not subscribers:
                continue  # некому слать — пропускаем (и не дёргаем источник)
            changes = await self.check_student(student)
            if changes:
                updates.append(
                    StudentUpdate(student=student, changes=changes, subscribers=subscribers)
                )
            if self._settings.request_delay > 0:
                await asyncio.sleep(self._settings.request_delay)
        return updates
