# 📨 ege-notifier

> Telegram-бот, который отслеживает появление результатов ЕГЭ на **ege.spb.ru**
> и уведомляет всех подписчиков ученика, как только у него появляются новые баллы.

[![CI](https://img.shields.io/github/actions/workflow/status/kewldan/egeResults/ci.yml?branch=master&style=flat&label=CI)](https://github.com/kewldan/egeResults/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.13%2B-2CA5E0?style=flat&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Beanie%202.1-47A248?style=flat&logo=mongodb&logoColor=white)](https://beanie-odm.dev/)
[![uv](https://img.shields.io/badge/package%20manager-uv-DE5FE9?style=flat)](https://docs.astral.sh/uv/)
[![Bun](https://img.shields.io/badge/card%20renderer-Bun%20%2B%20takumi-F9F1E1?style=flat&logo=bun&logoColor=black)](render-takumi/)

## ✨ Возможности

- 🔔 **Уведомления о новых баллах** — всем подписчикам ученика, баллы под
  спойлером `tg-spoiler`, с кнопкой «перейти на сайт».
- 👨‍👩‍👧 **Много-ко-многим** — один пользователь отслеживает нескольких учеников,
  на одного ученика подписано несколько пользователей.
- 🕵️ **Монитор страницы-обзора** — дешёвый GET одной публичной страницы раз в
  5 минут: вырос счётчик результатов или появился новый предмет → мгновенно
  запускается полная проверка (плюс редкая «слепая» проверка-страховка).
- 🔗 **Ссылки-приглашения** — одноразовый deep-link, чтобы поделиться учеником;
  в БД хранится только SHA-256 токена, ссылка гаснет атомарно.
- 🖼 **PNG-карточка «для сторис»** — сумма и список баллов красивой картинкой
  (отдельный рендерер на Bun + takumi-js).
- 📄 **Сканы бланков** — скачиваются на диск и отправляются альбомами: переживают
  протухание одноразовых ссылок `download.php`.
- 📊 **Детализация** — критерии, первичные баллы, распознанные ответы,
  📅 расписание экзаменов (регистрации).
- 👮 **Админ-команды** — `/top [предмет]` (в т.ч. комбо-топ по сумме, например
  `/top МИР`), `/check` (ручная полная проверка), служебные сводки.
- 🔐 **PII всерьёз** — паспорт шифруется Fernet, дедупликация по HMAC-хэшу без
  расшифровки, маскирование при показе.

## 🛠 Стек

- Python 3.11+ (проверено на 3.14)
- [aiogram 3](https://docs.aiogram.dev/) — Telegram-бот
- [Beanie 2.1.0](https://beanie-odm.dev/) + **pymongo** (async) — MongoDB ODM
- [APScheduler](https://apscheduler.readthedocs.io/) — расписание проверок
- [httpx](https://www.python-httpx.org/) — HTTP-клиент к источнику
- [cryptography](https://cryptography.io/) — шифрование паспортных данных (PII)
- [Bun](https://bun.sh/) + takumi-js — рендерер PNG-карточек (`render-takumi/`)
- управление зависимостями — [uv](https://docs.astral.sh/uv/)

## 🚀 Запуск

```bash
# 1. Зависимости
uv sync

# 2. Конфигурация
cp .env.example .env
#  - вставьте BOT_TOKEN от @BotFather
#  - сгенерируйте ENCRYPTION_KEY:
#    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#  - укажите свой IDENTITY_SECRET

# 3. MongoDB должна быть доступна по MONGO_URI (локально или Atlas)

# 4. Запуск
uv run python -m ege_notifier
# или, через console-script:
uv run ege-notifier
```

### 🐳 Docker

```bash
cp .env.example .env          # заполнить BOT_TOKEN, ENCRYPTION_KEY, IDENTITY_SECRET
docker compose up -d --build  # поднимет redis + card-renderer + bot
docker compose logs -f bot
```

`compose.yaml` переопределяет `MONGO_URI`/`REDIS_URL` на имена сервисов сети
compose, поэтому в `.env` их менять не нужно (Mongo — внешняя, по `MONGO_URI`).

### 🧪 Тесты

```bash
uv run pytest
```

Офлайн-тесты идут без БД и сети. Интеграционные (`tests/test_services_integration.py`)
требуют MongoDB и пропускаются, если она недоступна по `MONGO_URI`; в CI поднимается
сервис Mongo, поэтому там они выполняются (см. `.github/workflows/ci.yml`).

## ⚙️ Конфигурация (`.env`)

Полный список с комментариями — в [`.env.example`](.env.example). Ключевое:

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `BOT_TOKEN` | — | токен от @BotFather (обязательно) |
| `ADMIN_ID` | пусто | ID админов через запятую; пусто = админ-функции выключены |
| `MONGO_URI` / `MONGO_DB` | `mongodb://localhost:27017` / `ege_notifier` | MongoDB |
| `REDIS_URL` | пусто | FSM-состояния переживают рестарт (иначе память) |
| `RESULTS_PROVIDER` | `ege_spb` | источник: `ege_spb` (сайт) или `mock` (файл) |
| `EGE_SPB_MODE` / `EGE_SPB_WAVE` | `ege2026` / `1` | экзаменационная кампания и волна |
| `PAGE_MONITOR_ENABLED` / `PAGE_MONITOR_INTERVAL_SECONDS` | `true` / `300` | монитор страницы-обзора |
| `CHECK_INTERVAL_SECONDS` / `CHECK_CRON` | `21600` / — | «слепая» проверка-страховка |
| `MANUAL_CHECK_COOLDOWN_SECONDS` | `300` | анти-спам кнопки «Обновить» |
| `ENCRYPTION_KEY` | пусто | ключ Fernet для паспортов (пусто = открыто, только dev) |
| `IDENTITY_SECRET` | `change-me-please` | секрет HMAC-дедупликации учеников |
| `CARD_RENDERER_ENABLED` / `CARD_RENDERER_URL` | `true` / `http://localhost:3000` | рендерер карточек |
| `DOWNLOAD_BLANKS` / `BLANKS_DIR` | `true` / `data/blanks` | скачивание сканов бланков |

## 🧩 Как это работает

1. Пользователь в боте добавляет ученика (FSM: фамилия → серия → номер паспорта).
2. Создаётся `Student` (паспорт шифруется, для дедупликации хранится HMAC-хэш) и
   `Subscription`, связывающая Telegram-пользователя с учеником.
3. APScheduler периодически (интервал или cron из `.env`) запускает проверку: для
   каждого ученика с подписчиками вызывается провайдер, новые/изменённые результаты
   вычисляются `diff`-функцией и рассылаются всем подписчикам.

Основной триггер — **монитор страницы-обзора**: если вырос счётчик «Количество
результатов в базе данных» или появился новый предмет Основного периода,
немедленно запускается полная проверка и анонс «результаты выложили» тем,
кто ещё не ввёл паспортные данные.

### 🎭 Mock-источник (для разработки)

При `RESULTS_PROVIDER=mock` результаты берутся из `fixtures/results.json`
(ключ — номер паспорта, только цифры). Меняя файл при работающем боте, можно
сымитировать появление новых баллов и проверить весь конвейер уведомлений без
реального сайта. Пример уже содержит ученика с номером паспорта `654321`.

### 🌐 Источник ege.spb.ru

Источник `ege_spb` (`src/ege_notifier/providers/ege_spb.py`) — обычный `POST`
формы проверки результатов (`pLastName/Series/Number/Login`) в кодировке
**windows-1251**, без капчи и авторизации. Тело запроса и парсинг HTML вынесены
в чистые функции (`build_form_body`, `parse_results_html`) и покрыты тестами
на реальном фрагменте страницы.

Сайт даёт три состояния, и бот их различает:

- **ученик найден, есть баллы** → присылаем новые/изменившиеся результаты;
- **найден, баллов пока нет** (есть регистрация на экзамены) → «результатов пока нет»;
- **не найден** (сайт вернул форму поиска — опечатка в фамилии/паспорте) →
  подсказываем проверить данные (`StudentNotFoundError`), а не молчим про «нет баллов».

## 🖼 Картинка с результатами (для сторис)

В карточке ученика есть кнопка **«🖼 Картинка для сторис»** — бот генерирует
красивый PNG с баллами (сумма + список предметов). Рендерит отдельный сервис
[`render-takumi/`](render-takumi/) на **Bun + takumi-js**; бот ходит к нему по
HTTP (`POST /cards/summary.png`).

- В Docker сервис `card-renderer` поднимается автоматически (`docker compose up`),
  бот находит его по `CARD_RENDERER_URL=http://card-renderer:3000`.
- Локально без Docker: `cd render-takumi && bun install && bun run serve`
  (слушает `http://localhost:3000`), затем запустить бота как обычно.
- Выключить фичу целиком: `CARD_RENDERER_ENABLED=false` (кнопка не показывается).

Карточка содержит только фамилию и баллы — **паспортные данные в неё не попадают**.

## 👮 Админ-команды

Кто админ — задаёт `ADMIN_ID` в `.env`: один ID или **несколько через запятую**.
Пустое значение отключает админ-функции. Сообщения не-админов до этих команд
не доходят (фильтр `IsAdmin`), как будто команд нет.

- **`/top [предмет]`** — топ учеников по предмету (числовые баллы по убыванию,
  «Зачёт» — в конце). Без аргумента — список предметов, по которым есть
  результаты. Комбо-топ по сумме: `/top МИР` (Математика+Информатика+Русский).
  Фильтр по заметке — после `|`: `/top русский | группа А`.
- **`/check`** — вручную запускает полную проверку всех учеников в фоне:
  рассылает найденные баллы подписчикам и присылает админам сводку.
  Повторный запуск во время уже идущей проверки отклоняется.

Кроме команд, админам приходят служебные уведомления: о новом результате у любого
ученика и о новом пользователе бота; плановый цикл шлёт **одно сводное** сообщение
за проход.

## 🔐 Безопасность (PII)

Паспортные данные — чувствительная информация. В проекте:

- паспорт хранится зашифрованным (Fernet) при заданном `ENCRYPTION_KEY`;
- для поиска/дедупликации без расшифровки используется HMAC-хэш (`IDENTITY_SECRET`);
- при отображении паспорт маскируется (видны 2 последние цифры);
- в ссылке-приглашении уходит случайный токен, в БД — только его SHA-256;
- в PNG-карточку попадают только фамилия и баллы.

> Не коммитьте `.env`. Задайте реальные `ENCRYPTION_KEY` и `IDENTITY_SECRET`
> до первого запуска в проде — после старта их менять нельзя (иначе сломается
> расшифровка/дедупликация).

## 🗂 Структура

```
src/ege_notifier/
  config.py          — настройки (.env через pydantic-settings)
  security.py        — HMAC-дедупликация + Fernet-шифрование паспортов
  db.py              — инициализация Beanie + pymongo
  models/            — User, Student (+ ResultItem), Subscription, ShareToken, SiteState
  providers/         — источники результатов:
      base.py        —   протокол ResultsProvider + StudentQuery/FetchedResult
      mock.py        —   тестовый источник из JSON-файла
      ege_spb.py     —   реальный фетчер ege.spb.ru (POST формы, парсинг HTML)
      ege_spb_overview.py — парсер публичной страницы-обзора (счётчик, предметы)
  services/
      diff.py        — чистые функции сравнения/слияния результатов
      subscriptions.py — регистрация пользователей и подписки
      results.py     — проверка результатов и формирование изменений
      monitor.py     — монитор страницы-обзора (быстрый триггер проверок)
      notifier.py    — рассылка уведомлений в Telegram
      cards.py       — клиент рендерера карточек (PNG «для сторис»)
      blanks.py      — скачивание сканов бланков на диск
      ranking.py     — топы по предметам и комбо-суммам (/top)
  bot/               — aiogram 3: фабрика, FSM, хендлеры, тексты, клавиатуры
  scheduler.py       — APScheduler: монитор + периодическая проверка
  __main__.py        — точка входа (бот + планировщик)
render-takumi/       — отдельный сервис-рендерер карточек (Bun + takumi-js)
tests/               — офлайн-тесты (diff/merge, парсинг, хендлеры) + интеграционные
                       (нужна Mongo; иначе пропускаются)
fixtures/results.json — пример данных для mock-источника
```
