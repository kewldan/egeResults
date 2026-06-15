from __future__ import annotations

import httpx

# Сайт ege.spb.ru (и страница результатов, и страница-обзор) работает в кодировке
# windows-1251: тело POST кодируется в cp1251, ответ декодируется из cp1251. Держим
# кодировку в одном месте — её легко сломать, если разнести по провайдерам.
ENCODING = "windows-1251"

# Один User-Agent на все запросы к ege.spb.ru — чтобы при смене (анти-бот) не
# обновлять его в двух местах и не получить разное поведение fetcher'а и монитора.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Базовые заголовки, общие для GET-обзора и POST-проверки результатов.
_BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.9",
}


def build_client(
    timeout: float, extra_headers: dict[str, str] | None = None
) -> httpx.AsyncClient:
    """httpx-клиент с общими для ege.spb.ru заголовками (UA/Accept) и редиректами.

    ``extra_headers`` дополняет базовые — напр. ``Content-Type`` для POST-формы.
    """
    headers = dict(_BASE_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    return httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)


def decode_response(response: httpx.Response) -> str:
    """Декодирует тело ответа ege.spb.ru из windows-1251 (битые байты — заменой)."""
    return response.content.decode(ENCODING, errors="replace")
