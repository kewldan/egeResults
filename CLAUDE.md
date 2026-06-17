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

Docker (бот + Redis + рендерер карточек одной командой; Mongo — внешняя по `MONGO_URI`):

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
5. `Notifier.broadcast()` шлёт уведомление всем подписчикам ученика (пауза `BROADCAST_DELAY` между сообщениями — Telegram режет на ~30 msg/s) с URL-кнопкой «перейти на сайт»; параллельно `Notifier.notify_admin()` оповещает админов о новом результате (`ADMIN_ID` — один или несколько ID через запятую, `Settings.admin_ids`).

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
- `Student` дедуплицируется по `identity_hash` (HMAC **только паспорта** — серия+номер, см. `security.identity_hash`; фамилия в хэш НЕ входит) — поиск/слияние учеников без расшифровки PII. **`identity_hash` не зависит от `last_name`:** правка фамилии (напр. миграцией) хэш не меняет.
- **`Student` никогда не удаляется автоматически.** Отписка (`SubscriptionService.unsubscribe`) удаляет только `Subscription` — сам ученик с накопленными результатами остаётся в БД, даже когда подписчиков не осталось (намеренно: история не теряется, можно снова подписаться/принять приглашение). Защитный код «не воскрешать удалённую запись» (`results._persist` через `replace()`, None-проверки) остаётся на случай ручного удаления из БД. Кнопка 🗑 = отписка, не удаление ученика.
- `ShareToken` — одноразовая ссылка-приглашение на ученика. В deep-link уходит случайный токен (`secrets.token_urlsafe`), в БД хранится только его `sha256` (`security.hash_token`) — утечка базы не раскрывает живые ссылки. Гасится атомарно (`get_pymongo_collection().find_one_and_delete` в `redeem_share_token`) → срабатывает ровно раз; неиспользованные чистит TTL-индекс по `expires_at` (`SHARE_LINK_TTL_SECONDS`). Получатель становится обычным подписчиком — видит фамилию и маскированный паспорт, **не сами паспортные данные**. Выписать ссылку может только текущий подписчик ученика (проверка в `create_share_token`).
- **PII:** паспорт хранится зашифрованным (`security.Cipher`, Fernet) при заданном `ENCRYPTION_KEY`; иначе passthrough (только dev). `ENCRYPTION_KEY` и `IDENTITY_SECRET` нельзя менять после старта — иначе сломаются расшифровка и дедупликация. Защита от тихой порчи: дефолтный `IDENTITY_SECRET=change-me-please` логирует предупреждение при старте (`__main__`); `Cipher.decrypt` ловит `InvalidToken` и, если значение похоже на Fernet-токен (`gAAAAA…`), предупреждает о вероятной смене `ENCRYPTION_KEY` — не логируя само PII.

### Telegram-бот (`bot/`, aiogram 3)

- Сервисы инжектятся в хендлеры через workflow data: в `factory.build_dispatcher` делается `dp["subscriptions"|"results"|"notifier"|"settings"] = ...`, а хендлеры получают их **по имени аргумента** (`subscriptions`, `results`, `notifier`, `settings`). Имя параметра обязано совпадать с ключом.
- Добавление ученика — FSM (`states.AddStudent`): фамилия → серия → номер → подтверждение. Валидация в `bot/validators.py`: паспорт РФ (серия 4 цифры, номер 6) и **фамилия — одно слово кириллицей (допустим дефис), без пробелов**. Двойную фамилию вводят через дефис («Петров-Водкин»); пробел = ошибка — иначе в фамилию попадает имя («Иванов Пётр») и ege.spb.ru, сверяющий фамилию точно, отвечает «участник не найден». `normalize_surname()` (берёт первое слово) переиспользуется миграцией `scripts/fix_last_names.py`.
- **Навигация:** `/start` — одно приветственное сообщение + постоянная нижняя клавиатура (`main_reply_keyboard`), без инлайн-меню. Экран «Мои ученики» — одно сообщение: кнопка на каждого ученика (`student:` → `open_card`) + «➕ Добавить ученика» (всё в `keyboards.students_keyboard`, работает и при пустом списке). Действия над учеником (🔄 обновить / 🔗 поделиться / 🗑 удалить) — внутри карточки (`student_card_keyboard`). Доступ к карточке/проверке/ссылке — только подписчику (иначе подделанный callback вытянул бы чужие баллы). Отдельного `main_menu`/«⬅️ Меню» больше нет — назад ведёт `back_to_list_keyboard` («⬅️ К списку» → `my_students`).
- **Шеринг:** `share:` → `share_student` зовёт `create_share_token`, строит deep-link через `aiogram.utils.deep_linking.create_start_link`. Приём приглашения — отдельный хендлер `common.cmd_start_shared` на `CommandStart(deep_link=True)`, зарегистрирован **выше** обычного `cmd_start` (иначе обычный `CommandStart()` перехватил бы и нагрузку).
- **Анти-спам ручных проверок:** `ResultsService.check_student(..., manual=True)` под блокировкой ученика сверяет `last_checked_at` с `MANUAL_CHECK_COOLDOWN_SECONDS` (общий лимит на всех подписчиков, учитывает и плановые проверки) и бросает `RefreshThrottled(retry_after)`; плановый цикл зовёт без `manual` и лимиту не подчиняется. Хендлеры показывают `texts.refresh_throttled`; `confirm_add`/`cmd_start_shared` глотают throttle (снимок уже показан).
- **Уведомления о новых результатах** несут URL-кнопку «перейти на сайт» (`keyboards.results_link_keyboard(settings.results_site_url)`). О новых результатах и новых пользователях уведомляются админы — `Notifier.notify_admin` шлёт каждому из `settings.admin_ids` (`upsert_user` возвращает `(user, created)`; новизну ловит `common._register_user`). Плановый цикл шлёт админам **одно сводное** сообщение за цикл (`texts.admin_results_digest`), а не по одному на ученика — иначе пачка сообщений в один чат словила бы `TelegramRetryAfter`.
- **Несколько админов:** `ADMIN_ID` (env) принимает один ID или **список через запятую** (`787751346,1268132424`); `Settings.admin_ids: list[int]` парсит его `field_validator`'ом (поле помечено `NoDecode`, чтобы pydantic-settings не пытался читать значение как JSON). Пустое значение → `[]` → админ-функции выключены.
- **Админ-команды** (`bot/handlers/admin.py`, роутер `admin`): доступ ограничен фильтром `IsAdmin` на уровне роутера (DI отдаёт `settings`, проверка `from_user.id in settings.admin_ids`) — сообщения не-админов проваливаются в следующие роутеры. Роутер включён **выше** `add_student`, чтобы команды ловились по `Command`-фильтру даже во время FSM-добавления. `/top [предмет [| заметка]]` — топ учеников по предмету (`services.ranking`: чистые `rank_by_subject`/`available_subjects`/`average_score`, грузят всех учеников одним `Student.find_all()` и считают в памяти; сопоставление предмета через `normalize_subject`, числовые баллы по убыванию, «Зачёт» в конце; без аргумента — список доступных предметов). Необязательный фильтр по `Student.notes` — после `|` (`/top русский | группа А`): `rank_by_subject(..., notes_query)` оставляет учеников, в чьей заметке есть подстрока (без учёта регистра); разделитель явный, т.к. предмет бывает из нескольких слов. Баллы в топе показываются **открыто** (это админ-инструмент, не спойлер). `/check` — ручной запуск полной проверки в фоне (`_spawn` + `_run_check` зовут `results.check_all()` и общий `scheduler.broadcast_updates`), с защитой `_check_running` от параллельных запусков и сводкой админу по завершении.
- **Постоянная нижняя клавиатура** (`keyboards.main_reply_keyboard`, `is_persistent`): «📋 Мои ученики» (открывает список), «🛡 Безопасность», «ℹ️ О боте» — ловятся в `common` по `F.text == texts.BTN_*` (подписи кнопок — единый источник правды в `texts.py`). Ставится при `/start` и при приёме приглашения. Обработчики кнопок живут в `common` (router включён первым), чтобы срабатывать даже во время FSM добавления.
- **Не плодим сообщения:** навигация по инлайн-кнопкам правит текущее сообщение через `bot/ui.edit_message` (а не шлёт новое); тот же helper переживает `TelegramRetryAfter` (ждёт и повторяет) и откатывается на `answer`, если правка невозможна (`TelegramBadRequest`). Новые сообщения остаются только там, где это реально новый контент (снимок баллов, рассылка подписчикам).
- **Анти-флуд Telegram:** весь веер идёт через `Notifier` — `broadcast` ставит паузу `BROADCAST_DELAY` (~20 msg/s, ниже лимита ~30/s), а `send` ловит `TelegramRetryAfter` и повторяет после паузы. Разовые ответы хендлеров на действие пользователя редки и не веерные.
- **Хранилище FSM** выбирает `factory.build_storage(redis_url)`: `RedisStorage` при заданном `REDIS_URL` (состояние переживает рестарт; `redis` импортируется лениво), иначе `MemoryStorage`. `__main__` закрывает `dp.storage` на завершении.
- Все пользовательские тексты и форматирование уведомлений — в `bot/texts.py` (parse_mode=HTML задаётся в `factory.build_bot`). **Любое подставляемое в сообщение значение из внешних источников экранируется** `texts._esc` (`html.escape` для `&<>`): `subject`/`status`/`value` приходят с сайта, `full_name` — из Telegram. Подпись ученика для HTML-шаблонов берут через `texts.student_label()` (экранирует фамилию+маску), а не сырым полем. **Результаты экзамена прячутся под спойлер** `<tg-spoiler>…</tg-spoiler>` (`texts._spoiler`) — балл/«Зачёт» в снимке и в уведомлениях.
- **Картинка с результатами «для сторис»** (`bot/handlers/my_students.py::make_card`, кнопка `card:` в `student_card_keyboard`): по кнопке генерируется PNG-карточка и отправляется как фото (`answer_photo` — это реально новый контент, не правка). Доступ — только подписчику (как у `open_card`/`check`). Кнопку показываем лишь когда `card_renderer_enabled` И у ученика есть `results` (`_can_card`). Рендер — отдельный сервис (см. ниже) через `services.cards.CardRenderer`; сбои (`CardRenderError`) → алерт, бота не роняют. Спойлер тут НЕ нужен — картинку человек сам захотел показать. Единственный `callback.answer` даём в конце (спиннер на кнопке = «рисую»), иначе алерт об ошибке не показался бы. В карточку идут только фамилия + баллы, **паспорт — нет**.

### Рендерер карточек (`render-takumi/`, `services/cards.py`)

Отдельный HTTP-сервис на **Bun + takumi-js** (`render-takumi/`, завендорен в репо: `src/*.tsx`, `fonts/*.ttf`, `Dockerfile`; `node_modules` в `.gitignore`). Рисует PNG-карточку результатов; бот ходит к нему по HTTP. Запуск: docker compose (сервис `card-renderer`, бот находит его по `CARD_RENDERER_URL=http://card-renderer:3000`) или локально `cd render-takumi && bun install && bun run serve`.

- Эндпоинты: `GET /cards/<slug>.png` (мок-данные) и `POST /cards/<slug>.png` (JSON-тело мержится поверх мок). `slug` — `summary` (сводная: сумма + список предметов; её и шлёт бот) или `russian` (одна дисциплина крупно, нужны порог/максимум — в нашей модели их нет, поэтому не используем). `?scale=1..4` — множитель PNG.
- **Кириллица:** takumi без системного фолбэка, дизайнерские шрифты только латиница → к ним зарегистрированы кириллические компаньоны (Manrope/JetBrains Mono) в `src/fonts.ts`.
- Python-сторона (`services/cards.py`): чистая `build_card_payload(student, exam)` строит `(slug, тело)` — сумма/максимум считаются ТОЛЬКО по числовым баллам, «Зачёт» и пр. идут в список как текст, но не в сумму (имя на карточке = `last_name`); `CardRenderer` (httpx, ленивый клиент, `aclose()` на shutdown) шлёт POST и заворачивает любые сбои в `CardRenderError`. Инжектится в хендлеры через `dp["cards"]` (None, если выключен).

### Монитор страницы-обзора (`providers/ege_spb_overview.py`, `services/monitor.py`)

**Основной триггер проверок.** Вместо «слепой» периодической проверки каждого ученика дёшево опрашиваем ОДНУ публичную страницу-обзор (`results_site_url`, тот же `?mode=&wave=`) раз в `PAGE_MONITOR_INTERVAL_SECONDS` (по умолч. 300 с). Паспортные данные при этом не нужны — просто GET, декодируется из cp1251.

- Парсеры **чистые** (тесты на реальном HTML в `tests/fixtures/ege_spb_overview.html`): `parse_results_count()` берёт счётчик «Количество результатов в базе данных» из `.info-board` (число разбито неразрывными пробелами — срезаем `\D`); `parse_published_subjects()` собирает опубликованные предметы **Основного периода из `#w2`** (строки чередуются: `.exam-date` — дата экзамена, `.text-right` — предмет, `.text-left` — «Результаты размещены {дата}»; без даты в правой колонке предмет считаем ещё не выложенным). `subject` нормализуется `utils.normalize_subject` — теми же ключами, что и результаты учеников.
- Состояние — синглтон-документ `SiteState` (`key="ege_spb"`): последний счётчик + множество уже опубликованных предметов. `MonitorService.poll()` сравнивает свежий снимок (`diff_page` — чистая, на примитивах) и возвращает `PageChange` (с самим снимком), **не сохраняя**; новое состояние фиксирует `MonitorService.commit(change)`, который `run_monitor_cycle` зовёт **только после успешной проверки и рассылки**. Если рассылка упадёт — состояние не двигается и изменение поймается на следующем опросе (анонс не теряется); повтор безопасен, т.к. баллы дедуплицируются по ученику, а `Notifier` глотает ошибки доставки. **Первый запуск** молча сохраняет базовый снимок (`is_baseline`) прямо в `poll()` — чтобы при свежем деплое не разослать анонс об уже опубликованных баллах.
- Триггер изменения = счётчик вырос **или** в `#w2` появился новый предмет (`PageChange.has_results_update`). Тогда `run_monitor_cycle`: (1) `results.check_all()` + `broadcast_updates` (баллы подписчикам, как плановый цикл); (2) при новом предмете — анонс `texts.results_published_announcement` тем, кто **без паспортных данных** (`subscriptions.passportless_user_ids()` — активные юзеры без подписок), с оценкой «сколько сдавали» по приросту счётчика (`delta`).

### Расписание (`scheduler.py`)

APScheduler `AsyncIOScheduler` в таймзоне `TIMEZONE` (по умолчанию `Europe/Moscow`). **Два job'а:** `page_monitor` (монитор выше, интервал `PAGE_MONITOR_INTERVAL_SECONDS`, добавляется при `PAGE_MONITOR_ENABLED`) — основной быстрый триггер; `check_results` — **редкая страховка** (`CHECK_CRON`, иначе `CHECK_INTERVAL_SECONDS`, по умолч. 6 ч): ловит смену статуса/апелляции, не двигающие счётчик. Оба — `max_instances=1, coalesce=True`. Между учениками — пауза `REQUEST_DELAY` (анти-бан). При старте `__main__` отдельными фоновыми задачами гоняет: при `CHECK_ON_STARTUP=true` — один `run_check_cycle`; при включённом мониторе — один `run_monitor_cycle` (сидирует базовый снимок и ловит изменения, случившиеся, пока бот был выключен). Ссылки на задачи удерживаются, исключения логируются. `broadcast_updates` — общий код рассылки баллов подписчикам + сводка админу для обоих циклов.
