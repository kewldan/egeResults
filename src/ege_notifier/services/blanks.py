from __future__ import annotations

import logging
import mimetypes

import httpx

from ege_notifier.providers._http import build_client

logger = logging.getLogger(__name__)

# Расширение по content-type (явная таблица для частых типов; на остальное —
# mimetypes.guess_extension, иначе ``.bin``). Сайт отдаёт бланки PDF или картинкой.
_EXT_BY_TYPE = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
}


class BlankDownloadError(Exception):
    """Скан бланка не удалось скачать (сеть/HTTP) — отдаём пользователю мягкую ошибку."""


def _safe(name: str) -> str:
    """Заголовок с сайта → безопасное имя файла (оставляем только безопасные символы)."""
    return "".join(c if c.isalnum() or c in " -_()№" else "_" for c in name).strip() or "blank"


def _ext(content_type: str) -> str:
    media = content_type.split(";", 1)[0].strip().lower()
    return _EXT_BY_TYPE.get(media) or mimetypes.guess_extension(media) or ".bin"


def blank_filename(title: str, content_type: str) -> str:
    """Имя файла для одного бланка: безопасный заголовок + расширение по content-type."""
    return f"{_safe(title)}{_ext(content_type)}"


def blank_stem(subject_title: str, blank_title: str) -> str:
    """Имя файла бланка БЕЗ расширения «<предмет>__<лист>».

    По нему ищем уже скачанный файл (с любым расширением), чтобы не качать повторно —
    расширение заранее неизвестно (зависит от content-type ответа)."""
    return f"{_safe(subject_title)}__{_safe(blank_title)}"


def blank_basename(subject_title: str, blank_title: str, content_type: str) -> str:
    """Полное имя файла бланка в папке ученика: «<предмет>__<лист>.<ext>».

    Предмет в имени — чтобы одинаковые названия листов у разных предметов
    («Бланк ответов №1») не перетирали друг друга."""
    return f"{blank_stem(subject_title, blank_title)}{_ext(content_type)}"


class BlankDownloader:
    """Качает сканы бланков ответов с ege.spb.ru (ссылки download.php).

    Клиент httpx создаётся лениво и переиспользуется (keep-alive); закрывается в
    ``aclose()`` на shutdown. Сетевые/HTTP-сбои заворачиваются в
    ``BlankDownloadError``, чтобы хендлер показал мягкую ошибку, а не упал.
    Заголовки (User-Agent и пр.) — общие для ege.spb.ru (providers/_http)."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = build_client(self._timeout)
        return self._client

    async def download(self, url: str) -> tuple[bytes, str]:
        """Возвращает (содержимое, content-type). Бросает ``BlankDownloadError``."""
        try:
            response = await self._get_client().get(url)
        except httpx.HTTPError as exc:
            raise BlankDownloadError(f"не удалось скачать бланк: {exc}") from exc
        if response.status_code != 200:
            raise BlankDownloadError(f"бланк вернул HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        # Просроченная/битая ссылка отдаёт HTML-страницу ошибки, а не файл — не шлём
        # её пользователю как «бланк».
        if content_type.split(";", 1)[0].strip().lower() == "text/html":
            raise BlankDownloadError("ссылка на бланк недействительна (вернулась HTML-страница)")
        return response.content, content_type

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
