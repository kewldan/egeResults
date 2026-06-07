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

Docker (бот + Mongo + Redis одной командой):

```bash
cp .env.example .env           # заполнить BOT_TOKEN/ENCRYPTION_KEY/IDENTITY_SECRET
docker compose up -d --build   # MONGO_URI/REDIS_URL переопределяются на сервисы compose
```

Перед запуском: `cp .env.example .env`, заполнить `BOT_TOKEN`, `ENCRYPTION_KEY`, `IDENTITY_SECRET`; MongoDB должна быть доступна по `MONGO_URI`. Без `.env` запуск падает с `bot_token Field required` (ожидаемо).

Большинство тестов чистые (без БД/сети): `pythonpath=["src"]` и `asyncio_mode="auto"` заданы в `pyproject.toml`, импорт из `src/` напрямую. Интеграционные (`tests/test_services_integration.py`) требуют Mongo и **пропускаются**, если она недоступна по `MONGO_URI`; в CI (`.github/workflows/ci.yml`) поднимается сервис Mongo, поэтому там они выполняются.

## Архитектура (big picture)

Поток данных: **provider → diff → persist → notify**, запускаемый по расписанию.

1. `scheduler.run_check_cycle` (APScheduler) → `ResultsService.check_all()` обходит учеников, у которых есть подписчики.
2. Для каждого: `provider.fetch(StudentQuery)` → `list[FetchedResult]`.
3. Чистые функции `services/diff.py`: `diff_results()` вычисляет изменения (`ResultChange`), `merge_results()` строит новый снимок (сохраняет `first_seen_at`). Вся логика «что считать новым результатом» — здесь, без I/O, поэтому тестируется офлайн.
4. Изменения сохраняются в `Student.results`; `check_all` возвращает `StudentUpdate(student, changes, subscribers)`.
5. `Notifier.broadcast()` шлёт уведомление всем подписчикам ученика (пауза `BROADCAST_DELAY` между сообщениями — Telegram режет на ~30 msg/s) с URL-кнопкой «перейти на сайт»; параллельно `Notifier.notify_admin()` оповещает `ADMIN_ID` о новом результате.

### Источники результатов (`providers/`)

`ResultsProvider` — Protocol (`base.py`). Реализация выбирается в `build_provider()` по полю `Settings.provider`. **env-имя переменной — `RESULTS_PROVIDER`** (поле называется `provider`, env-имя задано через `validation_alias`; именно `RESULTS_PROVIDER`, не `PROVIDER`):
- `mock` — читает `fixtures/results.json` по номеру паспорта (для разработки; меняй файл при работающем боте, чтобы сымитировать появление баллов). Три состояния: ключа нет → `StudentNotFoundError`; ключ есть, список пуст → найден без результатов; список не пуст → результаты.
- `ege_spb` — реальный сайт.

**Три состояния источника.** Провайдеры различают «ученик не найден» (опечатка в фамилии/паспорте → `StudentNotFoundError` из `base.py`) и «найден, баллов пока нет» (пустой список). `ResultsService` на `StudentNotFoundError` ставит `Student.not_found=True`, сохраняет и пробрасывает выше; хендлеры показывают `texts.STUDENT_NOT_FOUND` («проверьте данные»), `check_all` глотает её, чтобы не уронить цикл. Существующие результаты при «не найден» не стираются (разовый сбой сайта не должен прятать баллы).

**Чтобы добавить источник:** реализовать `fetch()` (бросать `StudentNotFoundError`, когда ученик не найден), добавить значение в `Literal` в `config.Settings.provider` и ветку в `build_provider()`.

### Особенности ege.spb.ru (`providers/ege_spb.py`)

- Сайт работает в **windows-1251**: тело POST кодируется в cp1251 (`urlencode(..., encoding="cp1251")`), ответ декодируется из cp1251. Это легко сломать — держать кодирование/декодирование в `ENCODING`.
- Капчи и авторизации нет — обычный `POST /result/index.php?mode=&wave=` с полями `pLastName/Series/Number/Login`.
- HTTP вынесен из логики: `build_form_body()`, `parse_results_html()` и `looks_not_found()` — чистые функции (покрыты тестами на реальном HTML и точном теле запроса в `tests/fixtures/`). `looks_not_found()` отличает страницу-форму поиска (ученик не найден) от страницы найденного ученика по наличию блока `#exam-content`/`#result-data`/`#reg-data`; `fetch()` на форму поиска бросает `StudentNotFoundError`.
- Результат бывает числом (балл → `score`) или текстом («Зачёт» → `value`); диф сравнивает `value`/`score`/`status`.

### Модель данных (`models/`, Beanie ODM)

- **Beanie 2.1.0 использует асинхронный клиент pymongo (`AsyncMongoClient`), НЕ motor.** Init в `db.py`.
- `User` (по `telegram_id`), `Student`, `Subscription`, `ShareToken`. `Subscription` связывает `telegram_id ↔ student_id` (M:N): один пользователь → много учеников, один ученик → много подписчиков.
- `Student` дедуплицируется по `identity_hash` (HMAC паспорта, уникальный индекс) — поиск/слияние учеников без расшифровки PII. Когда отписывается последний подписчик, ученик удаляется вместе с PII (`SubscriptionService.unsubscribe`).
- `ShareToken` — одноразовая ссылка-приглашение на ученика. В deep-link уходит случайный токен (`secrets.token_urlsafe`), в БД хранится только его `sha256` (`security.hash_token`) — утечка базы не раскрывает живые ссылки. Гасится атомарно (`get_pymongo_collection().find_one_and_delete` в `redeem_share_token`) → срабатывает ровно раз; неиспользованные чистит TTL-индекс по `expires_at` (`SHARE_LINK_TTL_SECONDS`). Получатель становится обычным подписчиком — видит фамилию и маскированный паспорт, **не сами паспортные данные**. Выписать ссылку может только текущий подписчик ученика (проверка в `create_share_token`).
- **PII:** паспорт хранится зашифрованным (`security.Cipher`, Fernet) при заданном `ENCRYPTION_KEY`; иначе passthrough (только dev). `ENCRYPTION_KEY` и `IDENTITY_SECRET` нельзя менять после старта — иначе сломаются расшифровка и дедупликация. Защита от тихой порчи: дефолтный `IDENTITY_SECRET=change-me-please` логирует предупреждение при старте (`__main__`); `Cipher.decrypt` ловит `InvalidToken` и, если значение похоже на Fernet-токен (`gAAAAA…`), предупреждает о вероятной смене `ENCRYPTION_KEY` — не логируя само PII.

### Telegram-бот (`bot/`, aiogram 3)

- Сервисы инжектятся в хендлеры через workflow data: в `factory.build_dispatcher` делается `dp["subscriptions"|"results"|"notifier"|"settings"] = ...`, а хендлеры получают их **по имени аргумента** (`subscriptions`, `results`, `notifier`, `settings`). Имя параметра обязано совпадать с ключом.
- Добавление ученика — FSM (`states.AddStudent`): фамилия → серия → номер → подтверждение. Валидация паспорта РФ (серия 4 цифры, номер 6) в `validators.py`.
- **Список «Мои ученики»** — кнопка на ученика открывает его карточку (`student:` → `open_card`), а действия (🔄 обновить / 🔗 поделиться / 🗑 удалить) — внутри карточки (`bot/keyboards.student_card_keyboard`). Доступ к карточке/проверке/ссылке — только подписчику (иначе подделанный callback вытянул бы чужие баллы).
- **Шеринг:** `share:` → `share_student` зовёт `create_share_token`, строит deep-link через `aiogram.utils.deep_linking.create_start_link`. Приём приглашения — отдельный хендлер `common.cmd_start_shared` на `CommandStart(deep_link=True)`, зарегистрирован **выше** обычного `cmd_start` (иначе обычный `CommandStart()` перехватил бы и нагрузку).
- **Анти-спам ручных проверок:** `ResultsService.check_student(..., manual=True)` под блокировкой ученика сверяет `last_checked_at` с `MANUAL_CHECK_COOLDOWN_SECONDS` (общий лимит на всех подписчиков, учитывает и плановые проверки) и бросает `RefreshThrottled(retry_after)`; плановый цикл зовёт без `manual` и лимиту не подчиняется. Хендлеры показывают `texts.refresh_throttled`; `confirm_add`/`cmd_start_shared` глотают throttle (снимок уже показан).
- **Уведомления о новых результатах** несут URL-кнопку «перейти на сайт» (`keyboards.results_link_keyboard(settings.results_site_url)`). О каждом новом результате и о каждом новом пользователе уведомляется админ — `Notifier.notify_admin` при заданном `ADMIN_ID` (`upsert_user` теперь возвращает `(user, created)`; новизну пользователя ловит `common._register_user`).
- **Хранилище FSM** выбирает `factory.build_storage(redis_url)`: `RedisStorage` при заданном `REDIS_URL` (состояние переживает рестарт; `redis` импортируется лениво), иначе `MemoryStorage`. `__main__` закрывает `dp.storage` на завершении.
- Все пользовательские тексты и форматирование уведомлений — в `bot/texts.py` (parse_mode=HTML задаётся в `factory.build_bot`).

### Расписание (`scheduler.py`)

APScheduler `AsyncIOScheduler` в таймзоне `TIMEZONE` (по умолчанию `Europe/Moscow`). Если задан `CHECK_CRON` — используется он, иначе `CHECK_INTERVAL_SECONDS`. Job — `max_instances=1, coalesce=True` (новый цикл не стартует поверх незавершённого). Между учениками — пауза `REQUEST_DELAY` (анти-бан). При `CHECK_ON_STARTUP=true` `__main__` гоняет один цикл сразу при запуске отдельной фоновой задачей (ссылка на неё удерживается, исключения логируются).
