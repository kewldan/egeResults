# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with **uv** (the venv has no `pip`). Python 3.14 in `.venv`.

```bash
uv sync                       # установить зависимости (включая dev-группу)
uv add <package>              # добавить зависимость (правит pyproject + lock + ставит)

uv run python -m ege_notifier # запустить бота + планировщик (нужен .env с BOT_TOKEN)
uv run ege-notifier           # то же через console-script

uv run pytest                 # все тесты
uv run pytest tests/test_ege_spb.py::test_parse_sample_response   # один тест

# Сгенерировать Fernet-ключ для ENCRYPTION_KEY:
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Перед запуском: `cp .env.example .env`, заполнить `BOT_TOKEN`, `ENCRYPTION_KEY`, `IDENTITY_SECRET`; MongoDB должна быть доступна по `MONGO_URI`. Без `.env` запуск падает с `bot_token Field required` (ожидаемо).

Тесты чистые (без БД/сети): `pythonpath=["src"]` и `asyncio_mode="auto"` заданы в `pyproject.toml`, поэтому импортируются из `src/` напрямую и не требуют запущенной Mongo.

## Архитектура (big picture)

Поток данных: **provider → diff → persist → notify**, запускаемый по расписанию.

1. `scheduler.run_check_cycle` (APScheduler) → `ResultsService.check_all()` обходит учеников, у которых есть подписчики.
2. Для каждого: `provider.fetch(StudentQuery)` → `list[FetchedResult]`.
3. Чистые функции `services/diff.py`: `diff_results()` вычисляет изменения (`ResultChange`), `merge_results()` строит новый снимок (сохраняет `first_seen_at`). Вся логика «что считать новым результатом» — здесь, без I/O, поэтому тестируется офлайн.
4. Изменения сохраняются в `Student.results`; `check_all` возвращает `StudentUpdate(student, changes, subscribers)`.
5. `Notifier.broadcast()` шлёт уведомление всем подписчикам ученика.

### Источники результатов (`providers/`)

`ResultsProvider` — Protocol (`base.py`). Реализация выбирается через `RESULTS_PROVIDER` в `build_provider()`:
- `mock` — читает `fixtures/results.json` по номеру паспорта (для разработки; меняй файл при работающем боте, чтобы сымитировать появление баллов).
- `ege_spb` — реальный сайт.

**Чтобы добавить источник:** реализовать `fetch()`, добавить значение в `Literal` в `config.Settings.provider` и ветку в `build_provider()`.

### Особенности ege.spb.ru (`providers/ege_spb.py`)

- Сайт работает в **windows-1251**: тело POST кодируется в cp1251 (`urlencode(..., encoding="cp1251")`), ответ декодируется из cp1251. Это легко сломать — держать кодирование/декодирование в `ENCODING`.
- Капчи и авторизации нет — обычный `POST /result/index.php?mode=&wave=` с полями `pLastName/Series/Number/Login`.
- HTTP вынесен из логики: `build_form_body()` и `parse_results_html()` — чистые функции (покрыты тестами на реальном HTML и точном теле запроса в `tests/fixtures/`). Парсер устойчив к «ученик не найден» → пустой список (без ложных уведомлений).
- Результат бывает числом (балл → `score`) или текстом («Зачёт» → `value`); диф сравнивает `value`/`score`/`status`.

### Модель данных (`models/`, Beanie ODM)

- **Beanie 2.1.0 использует асинхронный клиент pymongo (`AsyncMongoClient`), НЕ motor.** Init в `db.py`.
- `User` (по `telegram_id`), `Student`, `Subscription`. `Subscription` связывает `telegram_id ↔ student_id` (M:N): один пользователь → много учеников, один ученик → много подписчиков.
- `Student` дедуплицируется по `identity_hash` (HMAC паспорта, уникальный индекс) — поиск/слияние учеников без расшифровки PII. Когда отписывается последний подписчик, ученик удаляется вместе с PII (`SubscriptionService.unsubscribe`).
- **PII:** паспорт хранится зашифрованным (`security.Cipher`, Fernet) при заданном `ENCRYPTION_KEY`; иначе passthrough (только dev). `ENCRYPTION_KEY` и `IDENTITY_SECRET` нельзя менять после старта — иначе сломаются расшифровка и дедупликация.

### Telegram-бот (`bot/`, aiogram 3)

- Сервисы инжектятся в хендлеры через workflow data: в `factory.build_dispatcher` делается `dp["subscriptions"|"results"|"notifier"] = ...`, а хендлеры получают их **по имени аргумента** (`subscriptions`, `results`, `notifier`). Имя параметра обязано совпадать с ключом.
- Добавление ученика — FSM (`states.AddStudent`): фамилия → серия → номер → подтверждение. Валидация паспорта РФ (серия 4 цифры, номер 6) в `validators.py`.
- Все пользовательские тексты и форматирование уведомлений — в `bot/texts.py` (parse_mode=HTML задаётся в `factory.build_bot`).

### Расписание (`scheduler.py`)

APScheduler `AsyncIOScheduler`. Если задан `CHECK_CRON` — используется он, иначе `CHECK_INTERVAL_SECONDS`. Job — `max_instances=1, coalesce=True` (новый цикл не стартует поверх незавершённого). Между учениками — пауза `REQUEST_DELAY` (анти-бан).
