"""Разовый импорт: завести список учеников, подписать на них одного пользователя
и проставить им заметку (``Student.notes``).

Зачем: нужно массово добавить класс учеников и привязать их к администратору,
не вводя каждого через FSM бота. Скрипт переиспользует ``SubscriptionService`` —
поэтому шифрование паспорта, дедупликация по ``identity_hash`` и обработка гонок
ведут себя ровно как в боте.

Идемпотентность: повторный запуск не плодит дублей — ученик ищется по паспорту
(``get_or_create_student``), подписка защищена уникальным индексом. ``notes``
проставляется на найденного/созданного ученика.

PII/секреты: используются те же ``ENCRYPTION_KEY``/``IDENTITY_SECRET`` из ``.env``,
что и у бота, — иначе паспорт зашифруется другим ключом и не совпадёт хэш.
Нужен доступ к MongoDB (``MONGO_URI``/``MONGO_DB``).

Запуск (по умолчанию dry-run — только показывает, что изменится):

    uv run python scripts/import_students.py            # предпросмотр
    uv run python scripts/import_students.py --apply    # записать изменения
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Чтобы скрипт работал и без установленного пакета (uv run python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pymongo.errors import DuplicateKeyError  # noqa: E402

from ege_notifier.config import Settings  # noqa: E402
from ege_notifier.db import init_db  # noqa: E402
from ege_notifier.models import User  # noqa: E402
from ege_notifier.security import Cipher  # noqa: E402
from ege_notifier.services.subscriptions import SubscriptionService  # noqa: E402

logger = logging.getLogger("import_students")

# Кому привязываем учеников и какую заметку ставим.
TELEGRAM_ID = 787751346
NOTES = "diman"

# (фамилия, серия, номер). Серия/номер — строки: важны ведущие нули в номере.
STUDENTS: list[tuple[str, str, str]] = [
    ("Астратков", "4022", "101050"),
    ("Богданов", "4022", "028057"),
    ("Буйняк", "4022", "102739"),
    ("Вагин", "4022", "254756"),
    ("Глуховский", "4022", "392947"),
    ("Данилова", "4022", "216322"),
    ("Дельцова", "4022", "028125"),
    ("Зацепурин", "4022", "080771"),
    ("Каллимулин", "4022", "028908"),
    ("Каретников", "4022", "394001"),
    ("Кучерявый", "4022", "101140"),
    ("Левина", "4022", "254294"),
    ("Лисицын", "4022", "254356"),
    ("Луковников", "4022", "100916"),
    ("Луковникова", "4022", "100915"),
    ("Макарова", "4022", "101612"),
    ("Павлов", "4022", "242472"),
    ("Семина", "4022", "254106"),
    ("Соловьев", "4022", "101355"),
    ("Федоров", "4022", "216319"),
    ("Черняхович", "4022", "343583"),
    ("Чижова", "4022", "236996"),
    ("Шалыгина", "4022", "215983"),
    ("Штих", "4022", "101521"),
]


async def ensure_user(telegram_id: int, apply: bool) -> None:
    """Создаёт пользователя, если его ещё нет (не трогая существующего).

    Без записи в ``users`` подписки всё равно работают, но ученик не считался бы
    «отслеживаемым» активным пользователем (``passportless_user_ids`` и т.п.).
    Существующего пользователя не перезаписываем — чтобы не затереть имя/username.
    """
    user = await User.find_one(User.telegram_id == telegram_id)
    if user is not None:
        return
    logger.info("tg=%s: пользователя нет — создаём", telegram_id)
    if apply:
        try:
            await User(telegram_id=telegram_id).insert()
        except DuplicateKeyError:
            pass  # гонка — создан параллельно, ок


async def run(apply: bool) -> None:
    settings = Settings()
    cipher = Cipher(settings.encryption_key)
    subscriptions = SubscriptionService(settings, cipher)

    client = await init_db(settings.mongo_uri, settings.mongo_db)
    subscribed = created_sub = noted = 0
    try:
        await ensure_user(TELEGRAM_ID, apply)
        for last_name, series, number in STUDENTS:
            if apply:
                student, is_new = await subscriptions.subscribe(
                    TELEGRAM_ID, last_name, series, number
                )
                if is_new:
                    created_sub += 1
                if student.notes != NOTES:
                    student.notes = NOTES
                    await student.save()
                    noted += 1
                logger.info(
                    "%s (%s …%s): ученик=%s, подписка=%s, notes=%r",
                    last_name,
                    series,
                    number[-2:],
                    student.id,
                    "новая" if is_new else "была",
                    student.notes,
                )
            else:
                logger.info(
                    "%s (%s …%s): подпишем tg=%s, notes=%r",
                    last_name,
                    series,
                    number[-2:],
                    TELEGRAM_ID,
                    NOTES,
                )
            subscribed += 1
    finally:
        await client.close()

    mode = "ПРИМЕНЕНО" if apply else "DRY-RUN (изменения не записаны)"
    logger.info(
        "%s. Учеников=%d, новых подписок=%d, проставлено notes=%d",
        mode,
        subscribed,
        created_sub,
        noted,
    )
    if not apply:
        logger.info("Запустите с --apply, чтобы записать изменения.")


def main() -> None:
    # На Windows консоль часто в cp1252 — переключаем вывод в UTF-8, иначе
    # кириллица в логах (фамилии) валит скрипт UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Импорт учеников: подписать tg=%d и проставить notes=%r."
        % (TELEGRAM_ID, NOTES)
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать изменения в БД (по умолчанию — только предпросмотр)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run(args.apply))


if __name__ == "__main__":
    main()
