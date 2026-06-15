from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from beanie import PydanticObjectId
from beanie.operators import In
from pymongo.errors import DuplicateKeyError

from ege_notifier.config import Settings
from ege_notifier.models import ShareToken, Student, Subscription, User
from ege_notifier.providers.base import StudentQuery
from ege_notifier.security import (
    Cipher,
    hash_token,
    identity_hash,
    mask_passport,
    normalize_digits,
)
from ege_notifier.utils import utcnow

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Регистрация пользователей и управление подписками на учеников."""

    def __init__(self, settings: Settings, cipher: Cipher):
        self._settings = settings
        self._cipher = cipher

    async def upsert_user(
        self, telegram_id: int, username: str | None, full_name: str | None
    ) -> tuple[User, bool]:
        """Создаёт или обновляет пользователя. Возвращает (пользователь, создан_ли_новый)."""
        user = await User.find_one(User.telegram_id == telegram_id)
        if user is None:
            candidate = User(
                telegram_id=telegram_id, username=username, full_name=full_name
            )
            try:
                await candidate.insert()
                return candidate, True
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
        return user, False

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
        # Ученика НЕ удаляем, даже если подписчиков не осталось: сохраняем его и
        # накопленные результаты (намеренно — история не теряется, можно снова
        # подписаться напрямую или по ссылке-приглашению). Запись чистится только
        # вручную.
        return True

    async def subscribers_for(self, student_id: PydanticObjectId) -> list[int]:
        subs = await Subscription.find(Subscription.student_id == student_id).to_list()
        return [s.telegram_id for s in subs]

    async def passportless_user_ids(self) -> list[int]:
        """Активные пользователи, не отслеживающие ни одного ученика.

        Те, кто зашёл в бота, но не вводил паспортные данные (нет ни одной подписки).
        Им шлём анонс «результаты выложили» — подписчики и так получают свои баллы.

        Тянем только ``telegram_id`` (``distinct``), не материализуя документы целиком:
        иначе на каждый опрос монитора грузили бы все подписки и всех пользователей."""
        subscribed = set(
            await Subscription.get_pymongo_collection().distinct("telegram_id")
        )
        active = await User.get_pymongo_collection().distinct(
            "telegram_id", {"is_active": True}
        )
        return [tid for tid in active if tid not in subscribed]

    async def subscribers_by_student(self) -> dict[PydanticObjectId, list[int]]:
        """Все подписки одним запросом, сгруппированные по ученику.

        Заменяет ``Student.find_all()`` + ``subscribers_for`` на каждого (N+1):
        ученики без подписчиков сюда не попадают вовсе."""
        grouped: dict[PydanticObjectId, list[int]] = {}
        for sub in await Subscription.find_all().to_list():
            grouped.setdefault(sub.student_id, []).append(sub.telegram_id)
        return grouped

    # --- шеринг ученика по одноразовой ссылке ---------------------------------

    async def create_share_token(
        self, student_id: PydanticObjectId, telegram_id: int
    ) -> str | None:
        """Создаёт одноразовую ссылку-приглашение на ученика.

        Возвращает секрет для deep-link (его кладут в ``?start=``), либо ``None``,
        если запросивший не подписан на ученика — делиться чужим учеником нельзя
        (иначе по подделанному callback можно было бы выписать ссылку на любого).

        В deep-link уходит сам токен, а в БД сохраняется только его хэш."""
        if telegram_id not in await self.subscribers_for(student_id):
            return None
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(seconds=self._settings.share_link_ttl_seconds)
        await ShareToken(
            token_hash=hash_token(token),
            student_id=student_id,
            created_by=telegram_id,
            expires_at=expires_at,
        ).insert()
        logger.info(
            "Создана ссылка-приглашение: tg=%s -> ученик=%s", telegram_id, student_id
        )
        return token

    async def redeem_share_token(self, token: str, telegram_id: int) -> Student | None:
        """Гасит одноразовую ссылку и подписывает её получателя на ученика.

        Возвращает ученика при успехе, иначе ``None`` (токен неверный, просрочен
        или уже использован). Получатель НЕ видит паспортных данных — становится
        обычным подписчиком (фамилия + маскированный паспорт, как у всех)."""
        if not token:
            return None
        # Атомарное гашение: победитель гонки получает документ, остальные — None
        # (одноразовость). Фильтр по expires_at — на случай, если TTL-индекс ещё не
        # успел удалить просроченный токен (sweep раз в ~минуту).
        doc = await ShareToken.get_pymongo_collection().find_one_and_delete(
            {"token_hash": hash_token(token), "expires_at": {"$gt": utcnow()}}
        )
        if doc is None:
            return None
        student = await Student.get(doc["student_id"])
        if student is None:
            return None  # ученика нет в БД (удалён вручную)
        assert student.id is not None  # получен через Student.get
        try:
            await Subscription(telegram_id=telegram_id, student_id=student.id).insert()
            logger.info(
                "Подписка по ссылке: tg=%s -> ученик=%s", telegram_id, student.id
            )
        except DuplicateKeyError:
            pass  # уже подписан — ссылка всё равно погашена (одноразовая)
        return student

    def to_query(self, student: Student) -> StudentQuery:
        """Готовит запрос к источнику, расшифровывая паспортные данные."""
        return StudentQuery(
            last_name=student.last_name,
            passport_series=self._cipher.decrypt(student.passport_series_enc),
            passport_number=self._cipher.decrypt(student.passport_number_enc),
        )
