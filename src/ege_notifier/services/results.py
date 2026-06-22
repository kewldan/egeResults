from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass
from pathlib import Path

from beanie import PydanticObjectId
from beanie.exceptions import DocumentNotFound
from beanie.operators import In

from ege_notifier.config import Settings
from ege_notifier.models import Registration, Student
from ege_notifier.providers.base import ResultsProvider, StudentNotFoundError
from ege_notifier.services.blanks import (
    BlankDownloader,
    BlankDownloadError,
    blank_basename,
    blank_stem,
)
from ege_notifier.services.diff import ResultChange, diff_results, merge_results
from ege_notifier.services.subscriptions import SubscriptionService
from ege_notifier.utils import utcnow

logger = logging.getLogger(__name__)


def _save_blank(base: Path, name: str, content: bytes) -> None:
    """Синхронная запись скана бланка на диск (создаёт каталог ученика при нужде).

    Вынесена отдельно, чтобы гонять её в пуле потоков (``asyncio.to_thread``) — запись
    файла блокирующая, а ``_download_blanks`` крутится внутри цикла проверки."""
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_bytes(content)


@dataclass(slots=True)
class StudentUpdate:
    student: Student
    changes: list[ResultChange]
    subscribers: list[int]


class RefreshThrottled(Exception):
    """Ручная проверка запрошена слишком рано после предыдущей (кулдаун на ученика).

    Лимит общий для всех подписчиков ученика: если источник опрашивали меньше
    кулдауна назад (другим подписчиком или плановой проверкой), повторная ручная
    проверка отклоняется. ``retry_after`` — сколько секунд осталось ждать.
    """

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"refresh throttled, retry after {retry_after:.0f}s")


class ResultsService:
    """Получение результатов у источника, вычисление изменений и их сохранение."""

    def __init__(
        self,
        settings: Settings,
        provider: ResultsProvider,
        subscriptions: SubscriptionService,
        blanks: BlankDownloader | None = None,
    ):
        self._settings = settings
        self._provider = provider
        self._subs = subscriptions
        # Загрузчик сканов бланков: при проверке кладём файлы на диск (см.
        # _download_blanks). None → диск не используем (кнопка качает «на лету»).
        self._blanks = blanks
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

    @staticmethod
    def _sync_snapshot(student: Student, latest: Student) -> None:
        """Переносит актуальные поля проверки из перечитанного документа в ``student``."""
        student.results = latest.results
        student.last_checked_at = latest.last_checked_at
        student.last_changed_at = latest.last_changed_at
        student.last_error = latest.last_error
        student.not_found = latest.not_found

    async def check_student(
        self, student: Student, *, manual: bool = False
    ) -> list[ResultChange]:
        """Проверяет одного ученика, обновляет его результаты в БД и возвращает изменения.

        ``manual=True`` (проверка по кнопке/подписке) включает анти-спам кулдаун:
        если источник опрашивали меньше ``manual_check_cooldown_seconds`` назад,
        бросается ``RefreshThrottled`` — и фетча не происходит. Плановая проверка
        (``manual=False``) кулдаун не применяет."""
        if student.id is None:
            return await self._check_student_locked(student)
        async with self._lock_for(student.id):
            # Перечитываем актуальный снимок под блокировкой: если параллельная
            # проверка уже сохранила результаты, diff не выдаст их повторно, а
            # кулдаун сверяется с зафиксированным в БД временем (а не устаревшим).
            latest = await Student.get(student.id)
            if latest is None:
                # Записи ученика нет в БД (удалена вручную) — не воскрешаем её.
                return []
            self._sync_snapshot(student, latest)
            if manual:
                self._enforce_cooldown(latest)
            return await self._check_student_locked(student)

    def _enforce_cooldown(self, latest: Student) -> None:
        """Бросает ``RefreshThrottled``, если ученика проверяли слишком недавно."""
        cooldown = self._settings.manual_check_cooldown_seconds
        if cooldown <= 0 or latest.last_checked_at is None:
            return
        elapsed = (utcnow() - latest.last_checked_at).total_seconds()
        if elapsed < cooldown:
            raise RefreshThrottled(cooldown - elapsed)

    async def _persist(self, student: Student) -> bool:
        """Сохраняет ученика, НЕ воскрешая удалённую запись.

        Если запись ученика удалили из БД во время медленного fetch, ``save()``
        (upsert) воскресил бы её вместе с PII. ``replace()`` не делает upsert и
        бросает ``DocumentNotFound`` — тогда просто молчим."""
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
            snapshot = await self._provider.fetch(query)
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

        fetched = snapshot.results
        changes = diff_results(student.results, fetched)
        student.results = merge_results(student.results, fetched)
        # Регистрации (когда/какой/где) — справочные, в diff не участвуют. Обновляем
        # только когда источник их отдал, чтобы разовый сбой не стёр уже известные.
        if snapshot.registrations:
            student.registrations = [
                Registration(
                    subject=r.subject,
                    subject_title=r.subject_title,
                    exam_date=r.exam_date,
                    place=r.place,
                    address=r.address,
                )
                for r in snapshot.registrations
            ]
        # Скачиваем новые сканы бланков на диск и проставляем им path (до persist,
        # чтобы пути сохранились в том же документе). Best-effort: сбой не валит проверку.
        await self._download_blanks(student)
        student.last_checked_at = utcnow()
        student.last_error = None
        student.not_found = False
        if changes:
            student.last_changed_at = utcnow()
        if not await self._persist(student):
            return []  # ученика удалили во время проверки — не уведомляем
        return changes

    async def _download_blanks(self, student: Student) -> None:
        """Качает сканы бланков ученика на диск и проставляет ``BlankImage.path``.

        Файлы лежат в ``<blanks_dir>/<identity_hash>/<предмет>__<лист>.<ext>``
        (identity_hash, а не id — стабилен и не зависит от PII/переподписки). Уже
        скачанный бланк не качаем повторно (ищем файл по имени без расширения).
        Best-effort: сбой скачивания одного файла лишь оставляет ``path=None`` —
        повторим на следующей проверке, проверку это не роняет."""
        if self._blanks is None or not getattr(self._settings, "download_blanks", True):
            return
        pairs = [(item, blank) for item in student.results for blank in item.blanks]
        if not pairs:
            return
        base = Path(self._settings.blanks_dir) / student.identity_hash
        for item, blank in pairs:
            subject = item.subject_title or item.subject
            stem = blank_stem(subject, blank.title)
            # Best-effort: ни сетевой сбой (BlankDownloadError), ни дисковый (OSError:
            # том только для чтения / переполнен / нет прав на named-volume) не должны
            # валить проверку — иначе исключение выбьет весь плановый цикл (check_all
            # ловит лишь StudentNotFoundError). Оставляем path как есть, повторим позже.
            try:
                existing = next(base.glob(f"{stem}.*"), None) if base.exists() else None
                if existing is not None:
                    blank.path = f"{student.identity_hash}/{existing.name}"
                    continue
                content, content_type = await self._blanks.download(blank.url)
                name = blank_basename(subject, blank.title, content_type)
                # Запись блокирующая — уводим с event loop, чтобы не тормозить цикл.
                await asyncio.to_thread(_save_blank, base, name, content)
                blank.path = f"{student.identity_hash}/{name}"
            except (BlankDownloadError, OSError) as exc:
                logger.info("Бланк не сохранён (%s): %s", blank.title, exc)
                continue

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
