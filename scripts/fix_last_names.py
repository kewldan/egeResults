"""Однократная миграция: вычистить имя из поля ``last_name`` у ``Student``.

Зачем: в фамилию ученика по ошибке вводили «Фамилия Имя [Отчество]» одной
строкой. ege.spb.ru сверяет фамилию точно, поэтому такие записи перестают
находиться. Скрипт оставляет в ``last_name`` только саму фамилию (первое слово),
нормализуя регистр и дефис так же, как ``validators.normalize_surname``.

Про ``identity_hash``: пересчитывать НЕ нужно. ``identity_hash`` считается ТОЛЬКО
из паспорта (серия+номер) — см. ``security.identity_hash``, — а паспорт скрипт
не трогает. Фамилия в хэш не входит, поэтому дедупликация учеников от правки
``last_name`` не меняется (пересчёт дал бы тот же самый хэш).

PII: скрипт не расшифровывает и не трогает паспортные поля — только ``last_name``.
``ENCRYPTION_KEY``/``IDENTITY_SECRET`` не требуются; нужен лишь доступ к MongoDB
(``MONGO_URI``/``MONGO_DB`` из ``.env``, как у бота).

Запуск (по умолчанию dry-run — только показывает, что изменится):

    uv run python scripts/fix_last_names.py            # предпросмотр
    uv run python scripts/fix_last_names.py --apply    # записать изменения
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Чтобы скрипт работал и без установленного пакета (uv run python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ege_notifier.bot.validators import normalize_surname  # noqa: E402
from ege_notifier.config import Settings  # noqa: E402
from ege_notifier.db import init_db  # noqa: E402
from ege_notifier.models import Student  # noqa: E402

logger = logging.getLogger("fix_last_names")


async def migrate(apply: bool) -> None:
    settings = Settings()
    client = await init_db(settings.mongo_uri, settings.mongo_db)
    total = changed = skipped = 0
    try:
        async for student in Student.find_all():
            total += 1
            new = normalize_surname(student.last_name)
            if new is None:
                # Первое слово невалидно как фамилия (латиница/пусто/мусор) — не
                # трогаем, чтобы не испортить запись; разберитесь вручную.
                logger.warning(
                    "id=%s: не удалось нормализовать last_name=%r — пропуск",
                    student.id,
                    student.last_name,
                )
                skipped += 1
                continue
            if new == student.last_name:
                continue  # уже чистая фамилия
            changed += 1
            logger.info("id=%s: %r -> %r", student.id, student.last_name, new)
            if apply:
                student.last_name = new
                await student.save()
    finally:
        await client.close()

    mode = "ПРИМЕНЕНО" if apply else "DRY-RUN (изменения не записаны)"
    logger.info(
        "%s. Всего=%d, к изменению=%d, пропущено=%d", mode, total, changed, skipped
    )
    if not apply and changed:
        logger.info("Запустите с --apply, чтобы записать изменения.")


def main() -> None:
    # На Windows консоль часто в cp1252 — переключаем вывод в UTF-8, иначе
    # кириллица в логах (фамилии) валит скрипт UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Очистка last_name у Student: оставить только фамилию."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать изменения в БД (по умолчанию — только предпросмотр)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(migrate(args.apply))


if __name__ == "__main__":
    main()
