from __future__ import annotations

import logging

from beanie import PydanticObjectId
from beanie.operators import In
from pymongo.errors import DuplicateKeyError

from ege_notifier.config import Settings
from ege_notifier.models import Student, Subscription, User
from ege_notifier.providers.base import StudentQuery
from ege_notifier.security import (
    Cipher,
    identity_hash,
    mask_passport,
    normalize_digits,
)

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Регистрация пользователей и управление подписками на учеников."""

    def __init__(self, settings: Settings, cipher: Cipher):
        self._settings = settings
        self._cipher = cipher

    async def upsert_user(
        self, telegram_id: int, username: str | None, full_name: str | None
    ) -> User:
        user = await User.find_one(User.telegram_id == telegram_id)
        if user is None:
            candidate = User(
                telegram_id=telegram_id, username=username, full_name=full_name
            )
            try:
                await candidate.insert()
                return candidate
            except DuplicateKeyError:
                # Гонка (двойной /start) — запись уже создана параллельно; перечитываем.
                user = await User.find_one(User.telegram_id == telegram_id)
                if user is None:
                    raise

        changed = False
        if user.username != username:
            user.username, changed = username, True
        if user.full_name != full_name:
            user.full_name, changed = full_name, True
        if not user.is_active:
            user.is_active, changed = True, True
        if changed:
            await user.save()
        return user

    async def get_or_create_student(
        self, last_name: str, passport_series: str, passport_number: str
    ) -> Student:
        ihash = identity_hash(
            passport_series, passport_number, self._settings.identity_secret
        )
        student = await Student.find_one(Student.identity_hash == ihash)
        if student is not None:
            return student

        student = Student(
            last_name=last_name.strip(),
            passport_series_enc=self._cipher.encrypt(normalize_digits(passport_series)),
            passport_number_enc=self._cipher.encrypt(normalize_digits(passport_number)),
            identity_hash=ihash,
            passport_masked=mask_passport(passport_series, passport_number),
        )
        try:
            await student.insert()
        except DuplicateKeyError:
            # Гонка: тот же паспорт вставлен параллельно (уникальный identity_hash).
            existing = await Student.find_one(Student.identity_hash == ihash)
            if existing is None:
                raise
            return existing
        logger.info("Создан ученик id=%s", student.id)
        return student

    async def subscribe(
        self,
        telegram_id: int,
        last_name: str,
        passport_series: str,
        passport_number: str,
    ) -> tuple[Student, bool]:
        """Подписывает пользователя на ученика. Возвращает (ученик, создана_ли_подписка)."""
        student = await self.get_or_create_student(
            last_name, passport_series, passport_number
        )
        existing = await Subscription.find_one(
            Subscription.telegram_id == telegram_id,
            Subscription.student_id == student.id,
        )
        if existing is not None:
            return student, False
        try:
            await Subscription(telegram_id=telegram_id, student_id=student.id).insert()
        except DuplicateKeyError:
            # Гонка (двойное подтверждение) — подписка уже создана параллельно.
            return student, False
        logger.info("Подписка: tg=%s -> ученик=%s", telegram_id, student.id)
        return student, True

    async def list_subscriptions(self, telegram_id: int) -> list[Student]:
        subs = await Subscription.find(
            Subscription.telegram_id == telegram_id
        ).to_list()
        if not subs:
            return []
        ids = [s.student_id for s in subs]
        students = await Student.find(In(Student.id, ids)).to_list()
        order = {sid: i for i, sid in enumerate(ids)}
        students.sort(key=lambda st: order.get(st.id, 0))
        return students

    async def unsubscribe(self, telegram_id: int, student_id: PydanticObjectId) -> bool:
        sub = await Subscription.find_one(
            Subscription.telegram_id == telegram_id,
            Subscription.student_id == student_id,
        )
        if sub is None:
            return False
        await sub.delete()

        # Если на ученика больше никто не подписан — удаляем его вместе с PII.
        remaining = await Subscription.find(
            Subscription.student_id == student_id
        ).count()
        if remaining == 0:
            student = await Student.get(student_id)
            if student is not None:
                await student.delete()
                logger.info("Ученик id=%s удалён (не осталось подписчиков)", student_id)
        return True

    async def subscribers_for(self, student_id: PydanticObjectId) -> list[int]:
        subs = await Subscription.find(Subscription.student_id == student_id).to_list()
        return [s.telegram_id for s in subs]

    async def subscribers_by_student(self) -> dict[PydanticObjectId, list[int]]:
        """Все подписки одним запросом, сгруппированные по ученику.

        Заменяет ``Student.find_all()`` + ``subscribers_for`` на каждого (N+1):
        ученики без подписчиков сюда не попадают вовсе."""
        grouped: dict[PydanticObjectId, list[int]] = {}
        for sub in await Subscription.find_all().to_list():
            grouped.setdefault(sub.student_id, []).append(sub.telegram_id)
        return grouped

    def to_query(self, student: Student) -> StudentQuery:
        """Готовит запрос к источнику, расшифровывая паспортные данные."""
        return StudentQuery(
            last_name=student.last_name,
            passport_series=self._cipher.decrypt(student.passport_series_enc),
            passport_number=self._cipher.decrypt(student.passport_number_enc),
        )
