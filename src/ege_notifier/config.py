from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlencode

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения. Значения читаются из переменных окружения / .env.

    Имя поля = имя переменной окружения (без учёта регистра). См. .env.example.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Telegram ---
    bot_token: str = Field(..., description="Токен бота от @BotFather")
    # Кому слать служебные уведомления (новые результаты у любого ученика, новые
    # пользователи) и кого пускать в админ-команды (/top, /check). Можно несколько
    # ID — через запятую в ADMIN_ID (или ADMIN_IDS). Пусто => админ-функции выключены.
    admin_ids: Annotated[list[int], NoDecode] = Field(
        default=[787751346, 1268132424],
        validation_alias=AliasChoices("admin_ids", "admin_id"),
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        """Принимает список, одиночный int или строку с ID через запятую/пробел.

        ``NoDecode`` отключает попытку pydantic-settings распарсить env-значение как
        JSON, поэтому строка вида ``787751346,1268132424`` доходит сюда сырой."""
        if value is None or value == "":
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(part) for part in re.split(r"[,\s]+", value.strip()) if part]
        return value

    # --- MongoDB ---
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ege_notifier"

    # --- Хранилище FSM бота ---
    # Если задан REDIS_URL — состояние «добавления ученика» переживает рестарт бота.
    # Иначе используется MemoryStorage (теряется при перезапуске; ок для разработки).
    redis_url: str | None = None

    # --- Источник результатов ---
    # mock    — читает результаты из JSON-файла (для разработки/тестов);
    # ege_spb — реальный фетчер ege.spb.ru (POST формы проверки результатов).
    # env-имя — RESULTS_PROVIDER (не PROVIDER): задаётся через validation_alias.
    provider: Literal["mock", "ege_spb"] = Field(
        "mock", validation_alias="results_provider"
    )
    mock_fixtures_path: str = "fixtures/results.json"
    ege_spb_base_url: str = "https://www.ege.spb.ru"
    # Параметры URL ege.spb.ru: ?mode=...&wave=... (экзаменационная кампания и волна).
    ege_spb_mode: str = "ege2026"
    ege_spb_wave: int = 1
    request_timeout: float = 15.0
    # Пауза между запросами по разным ученикам — снижает риск бана за частые обращения.
    request_delay: float = 1.0
    # Пауза между сообщениями при веерной рассылке — Telegram режет на ~30 msg/s.
    broadcast_delay: float = 0.05
    # Минимум между ручными проверками одного ученика (кнопка «обновить»), общий для
    # всех подписчиков: нельзя обновить, если источник уже опрашивали меньше N секунд
    # назад (кто угодно — другой подписчик или плановая проверка). Анти-спам источника.
    manual_check_cooldown_seconds: int = 300

    # --- Ссылки-приглашения (шеринг ученика) ---
    # Сколько живёт одноразовая ссылка, пока её не использовали (потом удаляется TTL).
    share_link_ttl_seconds: int = 86400

    # --- Картинка с результатами (рендерер render-takumi на Bun + takumi-js) ---
    # Из карточки ученика по кнопке генерируется красивый PNG с баллами — «можно
    # выложить в сторис». Бот ходит к сервису по HTTP (POST /cards/summary.png).
    # CARD_RENDERER_URL: адрес сервиса (в docker compose — http://card-renderer:3000).
    # Если выключено или сервис недоступен — кнопка не показывается / даёт ошибку.
    card_renderer_enabled: bool = True
    card_renderer_url: str = "http://localhost:3000"
    card_render_scale: int = 2  # множитель разрешения PNG (1..4)
    card_render_timeout: float = 30.0

    # --- Монитор страницы-обзора ege.spb.ru ---
    # Дешёвый GET одной страницы раз в N секунд: если вырос счётчик «Количество
    # результатов в базе данных» или в #w2 (Основной период) появился новый предмет —
    # запускаем полную проверку учеников и шлём анонс «результаты выложили» тем, кто
    # без паспортных данных. Это главный, быстрый триггер; плановая проверка ниже —
    # редкая страховка (ловит смену статуса/апелляции, не двигающие счётчик).
    page_monitor_enabled: bool = True
    page_monitor_interval_seconds: int = 300

    # --- Расписание проверок (страховка) ---
    # Если задан CHECK_CRON — используется он, иначе интервал в секундах. Поскольку
    # основной триггер — монитор страницы, «слепую» периодическую проверку держим
    # редкой (по умолчанию раз в 6 часов): меньше нагрузки на сайт, ниже риск бана.
    check_interval_seconds: int = 21600
    check_cron: str | None = None
    check_on_startup: bool = False
    timezone: str = "Europe/Moscow"

    # --- Безопасность (PII) ---
    # ENCRYPTION_KEY — ключ Fernet (base64). Если пусто — паспорта хранятся в открытом
    # виде (допустимо только для локальной разработки). Сгенерировать ключ:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str | None = None
    # Секрет для HMAC-хэша, по которому дедуплицируются ученики (без расшифровки паспорта).
    identity_secret: str = "change-me-please"

    log_level: str = "INFO"

    @property
    def results_site_url(self) -> str:
        """Публичная страница результатов на ege.spb.ru — для кнопки «перейти на сайт»."""
        base = self.ege_spb_base_url.rstrip("/")
        params = urlencode({"mode": self.ege_spb_mode, "wave": self.ege_spb_wave})
        return f"{base}/result/index.php?{params}"

    @property
    def exam_label(self) -> str:
        """Подпись кампании для карточки результатов: «ege2026» → «ЕГЭ · 2026»."""
        match = re.search(r"\d{4}", self.ege_spb_mode)
        return f"ЕГЭ · {match.group()}" if match else "ЕГЭ"
