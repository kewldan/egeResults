from __future__ import annotations

import logging
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from ege_notifier.providers._http import ENCODING, build_client, decode_response
from ege_notifier.providers.base import (
    BlankImage,
    Criterion,
    FetchedResult,
    Registration,
    StudentNotFoundError,
    StudentQuery,
    StudentSnapshot,
    TaskAnswer,
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


def _parse_criteria(scope: Tag) -> tuple[list[Criterion], int | None]:
    """Критерии/части результата из блоков ``#exam-additional-info-smod-*``.

    Покрывает обе раскладки сайта одним проходом: «Результаты по критериям»
    (зачётные предметы — ячейки ``.col`` с ``.info-header`` + ``.info-normaltext-center``)
    и «Первичные баллы по частям» (балльные — ``.col`` с ``.info-header`` +
    ``.info-bigvalue``). Имя класса-токена ``col`` есть только у этих ячеек-сводок;
    у поячейных таблиц («по заданиям») контейнеры ``col-md-*`` без токена ``col`` и в
    ``.ais-grid`` — поэтому они сюда не попадают. ``primary_score`` берём из строки
    «Первичный балл (сумма)», если значение числовое.
    """
    criteria: list[Criterion] = []
    primary: int | None = None
    for panel in scope.select('[id^="exam-additional-info-smod-"]'):
        for col in panel.select(".col"):
            if col.find_parent(class_="ais-grid") is not None:
                continue
            header = col.select_one(".info-header")
            value = col.select_one(".info-normaltext-center, .info-bigvalue")
            if header is None or value is None:
                continue
            name = header.get_text(" ", strip=True)
            val = value.get_text(" ", strip=True)
            if not name or not val:
                continue
            criteria.append(Criterion(name=name, value=val))
            if "первичный балл" in name.lower() and val.isdigit():
                primary = int(val)
    return criteria, primary


def _parse_recognition(scope: Tag) -> list[TaskAnswer]:
    """Распознанные ответы по заданиям из блоков ``#exam-additional-info-recogn-*``.

    Каждая ``.ais-grid`` — две внутренние колонки: первая (после заголовка
    «№ задания») — номера заданий, вторая («Результат распознавания») — ответы;
    значения лежат в ``.info-normaltext-center`` (заголовки — ``.info-header`` —
    отсекаются). Колонки сопоставляются попарно (zip)."""
    answers: list[TaskAnswer] = []
    for panel in scope.select('[id^="exam-additional-info-recogn-"]'):
        for grid in panel.select(".ais-grid"):
            cols = grid.find_all("div", recursive=False)
            if len(cols) < 2:
                continue
            tasks = [c.get_text(strip=True) for c in cols[0].select(".info-normaltext-center")]
            vals = [c.get_text(strip=True) for c in cols[1].select(".info-normaltext-center")]
            answers.extend(
                TaskAnswer(task=t, answer=a) for t, a in zip(tasks, vals) if t
            )
    return answers


def _parse_blanks(scope: Tag, base_url: str | None) -> list[BlankImage]:
    """Сканы бланков из блоков ``#exam-additional-info-blanks-*`` (ссылки download.php).

    Ссылки на сайте относительные (``download.php?filename=…``); при заданном
    ``base_url`` приводим к абсолютным (``urljoin``), чтобы их можно было скачать."""
    blanks: list[BlankImage] = []
    for panel in scope.select('[id^="exam-additional-info-blanks-"]'):
        for a in panel.select(".list-group a[href]"):
            href = a.get("href")
            title = a.get_text(" ", strip=True)
            if not href or not title:
                continue
            url = urljoin(base_url, href) if base_url else href
            blanks.append(BlankImage(title=title, url=url))
    return blanks


def _parse_exam(title_el: Tag, scope: Tag, base_url: str | None) -> FetchedResult | None:
    """Один результат: основные поля из ``.exam-title`` + детализация из ``scope``.

    Извлечение предмета/значения/статуса/даты сохранено байт-в-байт как раньше —
    от этих полей зависит diff (см. services.diff), и любое их изменение вызвало бы
    ложные уведомления. Детализация (критерии/баллы/распознавание/бланки) добавляется
    отдельно и на diff не влияет."""
    subject_el = title_el.select_one(".exam-subject-info")
    if subject_el is None:
        return None

    exam_date: str | None = None
    date_span = subject_el.find("span")
    if date_span is not None:
        exam_date = date_span.get_text(strip=True).strip("()") or None
        date_span.extract()  # убираем дату, чтобы остался чистый предмет

    subject_title = subject_el.get_text(strip=True)
    if not subject_title:
        return None

    result_el = title_el.select_one(".exam-result")
    status_el = title_el.select_one(".exam-result-status")
    value = result_el.get_text(strip=True) if result_el is not None else None
    status = status_el.get_text(strip=True) if status_el is not None else None
    score = int(value) if value is not None and value.isdigit() else None

    criteria, primary_score = _parse_criteria(scope)
    recognition = _parse_recognition(scope)
    blanks = _parse_blanks(scope, base_url)

    return FetchedResult(
        subject=normalize_subject(subject_title),
        subject_title=subject_title,
        score=score,
        value=value,
        status=status,
        exam_date=exam_date,
        criteria=criteria,
        primary_score=primary_score,
        recognition=recognition,
        blanks=blanks,
        raw={"value": value, "status": status, "date": exam_date},
    )


def _fallback_scope(title: Tag) -> Tag:
    """Изолированная область одного экзамена для страниц без обёртки ``#exam-detail``.

    Берём сам ``.exam-title`` и его следующие сиблинги до следующего ``.exam-title``
    и парсим их как отдельный фрагмент. Брать ``title.parent`` нельзя: если заголовки
    лежат прямо в ``#result-data``, scope стал бы всем контейнером и детализация
    (критерии/распознавание/бланки) одного экзамена приписалась бы всем остальным."""
    parts = [str(title)]
    for sib in title.find_next_siblings():
        if isinstance(sib, Tag) and "exam-title" in (sib.get("class") or []):
            break
        parts.append(str(sib))
    return BeautifulSoup("".join(parts), "html.parser")


def _results_from_soup(soup: Tag, base_url: str | None) -> list[FetchedResult]:
    container = soup.select_one("#result-data")
    if container is None:
        return []

    details = container.find_all(id="exam-detail")
    if details:
        blocks = [(d.select_one(".exam-title"), d) for d in details]
    else:
        # Без обёртки #exam-detail область каждого экзамена строим из его заголовка
        # и следующих сиблингов (см. _fallback_scope) — иначе детализация утекла бы
        # между экзаменами.
        blocks = [(t, _fallback_scope(t)) for t in container.select(".exam-title")]

    results: list[FetchedResult] = []
    for title_el, scope in blocks:
        if title_el is None or scope is None:
            continue
        parsed = _parse_exam(title_el, scope, base_url)
        if parsed is not None:
            results.append(parsed)
    return results


def parse_results_html(html: str, base_url: str | None = None) -> list[FetchedResult]:
    """Извлекает результаты (с детализацией) из HTML страницы ege.spb.ru.

    Каждый экзамен — блок ``#result-data #exam-detail`` (на старых/тестовых страницах
    без обёртки — просто ``.exam-title`` внутри ``#result-data``). В каждом:
      - предмет/дата — ``.exam-subject-info`` (дата во вложенном ``<span>``);
      - статус — ``.exam-result-status`` (напр. «Действующий результат»);
      - значение — ``.exam-result`` (балл «88» либо «Зачёт»/«Незачёт»);
      - детализация — критерии/первичные баллы, распознанные ответы, сканы бланков
        (``base_url`` нужен, чтобы абсолютизировать ссылки на бланки).
    Если результатов нет (или ученик не найден) — возвращается пустой список.
    """
    return _results_from_soup(BeautifulSoup(html, "html.parser"), base_url)


def _registrations_from_soup(soup: Tag) -> list[Registration]:
    table = soup.select_one("#reg-data .registrations-info-table") or soup.select_one(
        ".registrations-info-table"
    )
    if table is None:
        return []

    regs: list[Registration] = []
    for row in table.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:  # строка-заголовок (th) пропускается
            continue
        exam_date = cells[0].get_text(" ", strip=True) or None
        subject_title = cells[1].get_text(" ", strip=True)
        if not subject_title:
            continue
        place_cell = cells[2]
        bold = place_cell.find("b")
        if bold is not None:
            place = bold.get_text(" ", strip=True) or None
            rest = [t for t in place_cell.stripped_strings if t != place]
            address = " ".join(rest) or None
        else:
            # серое «доступно за день до экзамена» — пункт ещё не назначен
            place = None
            address = None
        regs.append(
            Registration(
                subject=normalize_subject(subject_title),
                subject_title=subject_title,
                exam_date=exam_date,
                place=place,
                address=address,
            )
        )
    return regs


def parse_registrations(html: str) -> list[Registration]:
    """Регистрации на экзамены из таблицы ``#reg-data .registrations-info-table``.

    Строки: Дата | Предмет | Место проведения. Место — ``<b>ППЭ</b><br>адрес`` либо
    серое «доступно за день до экзамена» (тогда место/адрес ещё нет → ``None``).
    Регистрация бывает на экзамен без результата (ещё не сдан) — поэтому это
    отдельный, student-уровневый список (в diff не участвует)."""
    return _registrations_from_soup(BeautifulSoup(html, "html.parser"))


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

    async def fetch(self, query: StudentQuery) -> StudentSnapshot:
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
        # Парсим страницу ОДИН раз и из общего soup берём и результаты, и регистрации.
        # Регистрации — до результатов: парсинг результатов вырезает <span> с датой
        # (date_span.extract()), но #reg-data это не затрагивает.
        # base_url = страница результата: ссылки на бланки (download.php) рядом с ней,
        # urljoin приведёт их к абсолютным.
        soup = BeautifulSoup(html, "html.parser")
        registrations = _registrations_from_soup(soup)
        results = _results_from_soup(soup, base_url=self._url)
        return StudentSnapshot(results=results, registrations=registrations)

    async def aclose(self) -> None:
        await self._client.aclose()
