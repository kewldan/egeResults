# syntax=docker/dockerfile:1
#
# Образ бота ege-notifier. Зависимости ставятся через uv; код проекта — отдельным
# слоем, чтобы пересборка при правках кода не переустанавливала зависимости.

FROM python:3.14-slim-bookworm

# uv берём из официального образа (фиксированная версия — воспроизводимость сборки).
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /uvx /bin/

# UV_COMPILE_BYTECODE   — компилируем .pyc для чуть более быстрого старта;
# UV_LINK_MODE=copy     — без жёстких ссылок (кеш и venv на разных слоях/ФС);
# UV_PYTHON_DOWNLOADS=never — используем python из базового образа, не качаем свой.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Слой зависимостей: только манифесты → кешируется, пока не менялись pyproject/lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2) Код проекта и фикстуры mock-источника.
COPY src ./src
COPY fixtures ./fixtures
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Каталог для скачанных сканов бланков (BLANKS_DIR). Создаём в образе, чтобы
# named-volume при первом монтировании унаследовал владельца appuser (иначе
# непривилегированный процесс не смог бы в него писать).
RUN mkdir -p /app/data/blanks

# Непривилегированный пользователь.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "ege_notifier"]
