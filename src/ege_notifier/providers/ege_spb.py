from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from ege_notifier.providers.base import FetchedResult, StudentQuery

logger = logging.getLogger(__name__)

# Сайт ege.spb.ru работает в кодировке windows-1251: тело запроса нужно кодировать
# в cp1251, а ответ — декодировать из cp1251.
ENCODING = "windows-1251"
# Значение submit-кнопки формы (как в реальном запросе).
SUBMIT_VALUE = "Показать результаты"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _normalize_subject(title: str) -> str:
    """Стабильный ключ предмета для сопоставления между проверками."""
    return " ".join(title.split()).lower()


def build_form_body(query: StudentQuery) -> str:
    """Собирает тело POST-запроса (поля в cp1251, как ожидает сайт)."""
    return urlencode(
        {
            "pLastName": query.last_name,
            "Series": query.passport_series,
            "Number": query.passport_number,
            "Login": SUBMIT_VALUE,
        },
        encoding=ENCODING,
    )


def parse_results_html(html: str) -> list[FetchedResult]:
    """Извлекает результаты из HTML страницы ege.spb.ru.

    Каждый результат лежит в блоке ``#result-data .exam-title``:
      - предмет и дата — в ``.exam-subject-info`` (дата во вложенном ``<span>``);
      - статус — в ``.exam-result-status`` (напр. «Действующий результат»);
      - значение — в ``.exam-result`` (балл «88» либо «Зачёт»/«Незачёт»).
    Если результатов нет (или ученик не найден) — возвращается пустой список.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#result-data")
    if container is None:
        return []

    results: list[FetchedResult] = []
    for title in container.select(".exam-title"):
        subject_el = title.select_one(".exam-subject-info")
        if subject_el is None:
            continue

        exam_date: str | None = None
        date_span = subject_el.find("span")
        if date_span is not None:
            exam_date = date_span.get_text(strip=True).strip("()") or None
            date_span.extract()  # убираем дату, чтобы остался чистый предмет

        subject_title = subject_el.get_text(strip=True)
        if not subject_title:
            continue

        result_el = title.select_one(".exam-result")
        status_el = title.select_one(".exam-result-status")
        value = result_el.get_text(strip=True) if result_el is not None else None
        status = status_el.get_text(strip=True) if status_el is not None else None
        score = int(value) if value is not None and value.isdigit() else None

        results.append(
            FetchedResult(
                subject=_normalize_subject(subject_title),
                subject_title=subject_title,
                score=score,
                value=value,
                status=status,
                exam_date=exam_date,
                raw={"value": value, "status": status, "date": exam_date},
            )
        )
    return results


class EgeSpbProvider:
    """Источник результатов с ege.spb.ru (POST формы проверки результатов)."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        mode: str = "ege2026",
        wave: int = 1,
    ):
        self._url = f"{base_url.rstrip('/')}/result/index.php"
        self._params = {"mode": mode, "wave": wave}
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.9",
            },
            follow_redirects=True,
        )

    async def fetch(self, query: StudentQuery) -> list[FetchedResult]:
        body = build_form_body(query)
        referer = f"{self._url}?{urlencode(self._params)}"
        response = await self._client.post(
            self._url,
            params=self._params,
            content=body,
            headers={"Referer": referer},
        )
        response.raise_for_status()
        html = response.content.decode(ENCODING, errors="replace")
        return parse_results_html(html)

    async def aclose(self) -> None:
        await self._client.aclose()
