from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # пользователи). Пусто => админ-уведомления отключены.
    admin_id: int | None = 787751346

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

    # --- Расписание проверок ---
    # Если задан CHECK_CRON — используется он, иначе интервал в секундах.
    check_interval_seconds: int = 900
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
