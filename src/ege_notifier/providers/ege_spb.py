from __future__ import annotations

import logging
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ege_notifier.providers._http import ENCODING, build_client, decode_response
from ege_notifier.providers.base import (
    FetchedResult,
    StudentNotFoundError,
    StudentQuery,
)
from ege_notifier.utils import normalize_subject

logger = logging.getLogger(__name__)

# ENCODING (windows-1251) и httpx-клиент — общие для всех запросов к ege.spb.ru,
# живут в providers/_http.py (см. fetch ниже и providers/ege_spb_overview.py).

# Значение submit-кнопки формы (как в реальном запросе).
SUBMIT_VALUE = "Показать результаты"


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


def looks_not_found(html: str) -> bool:
    """True, если сайт вернул форму поиска вместо страницы ученика (опечатка/неверные данные).

    Найденному ученику ege.spb.ru показывает блок результатов/регистрации
    (``#exam-content`` / ``#result-data`` / ``#reg-data``) — даже когда баллов ещё
    нет (есть регистрация на экзамены). Если же фамилия+паспорт не совпали, сайт
    повторно отдаёт форму поиска с полем ``pLastName``. Так мы отличаем «не нашли
    ученика» от «ученик есть, результатов пока нет».

    Чтобы случайно не принять временную ошибку/непонятную страницу за «не найден»,
    требуем оба признака: есть форма поиска И нет контента ученика. Иначе считаем
    ответ обычной страницей (пустой список → «результатов пока нет»)."""
    soup = BeautifulSoup(html, "html.parser")
    has_content = bool(
        soup.select_one("#exam-content")
        or soup.select_one("#result-data")
        or soup.select_one("#reg-data")
    )
    has_search_form = soup.find("input", attrs={"name": "pLastName"}) is not None
    return has_search_form and not has_content


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
                subject=normalize_subject(subject_title),
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
        self._client = build_client(
            timeout,
            {"Content-Type": "application/x-www-form-urlencoded"},
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
        html = decode_response(response)
        if looks_not_found(html):
            raise StudentNotFoundError(
                "ege.spb.ru вернул форму поиска — ученик не найден по фамилии и паспорту"
            )
        return parse_results_html(html)

    async def aclose(self) -> None:
        await self._client.aclose()
