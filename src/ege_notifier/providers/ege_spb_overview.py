from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from ege_notifier.providers._http import build_client, decode_response
from ege_notifier.utils import normalize_subject

logger = logging.getLogger(__name__)

# Кодировку (windows-1251), User-Agent и httpx-клиент берём из providers/_http.py —
# общие со страницей результатов (providers/ege_spb.py), чтобы не разъезжались.

# Счётчик «Количество результатов в базе данных: <span> 41 144 </span>». Число
# на сайте разбито пробелами/неразрывными пробелами — захватываем весь блок
# цифр-с-пробелами после подписи, лишнее срезаем в parse_results_count.
_COUNT_RE = re.compile(
    r"результатов\s+в\s+базе\s+данных\s*:?\s*([\d\s  ]+)",
    re.IGNORECASE,
)
# Префикс правой колонки строки предмета («Результаты размещены 11 июня 2026»).
_PUBLISHED_PREFIX_RE = re.compile(r"^Результаты\s+размещены\s*", re.IGNORECASE)


@dataclass(slots=True)
class PublishedSubject:
    """Один опубликованный предмет основного периода (строка #w2)."""

    title: str  # как на сайте, напр. «Химия»
    subject: str  # нормализованный ключ (utils.normalize_subject)
    published_at: str | None = None  # дата размещения результатов, напр. «11 июня 2026»
    exam_date: str | None = None  # дата экзамена (заголовок группы), напр. «1 июня 2026»


@dataclass(slots=True)
class PageSnapshot:
    """Снимок страницы-обзора: счётчик результатов и опубликованные предметы #w2."""

    results_count: int | None
    subjects: list[PublishedSubject] = field(default_factory=list)


def _count_from_soup(soup: BeautifulSoup) -> int | None:
    board = soup.select_one(".info-board")
    # Парсим внутри .info-board (там подпись и число рядом), иначе — по всей странице.
    text = (board or soup).get_text(" ", strip=True)
    match = _COUNT_RE.search(text)
    if match is None:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def parse_results_count(html: str) -> int | None:
    """Извлекает счётчик «Количество результатов в базе данных».

    Возвращает ``None``, если подпись не найдена (сайт изменил вёрстку/текст) —
    тогда монитор полагается только на список предметов #w2.
    """
    return _count_from_soup(BeautifulSoup(html, "html.parser"))


def _subjects_from_soup(soup: BeautifulSoup) -> list[PublishedSubject]:
    container = soup.select_one("#w2")
    if container is None:
        return []

    subjects: list[PublishedSubject] = []
    current_exam_date: str | None = None
    for row in container.select(".row"):
        date_cell = row.select_one(".exam-date")
        if date_cell is not None:
            current_exam_date = date_cell.get_text(strip=True) or None
            continue

        right = row.select_one(".text-right")
        if right is None:
            continue
        title = right.get_text(strip=True)
        if not title:
            continue

        left = row.select_one(".text-left")
        published = left.get_text(" ", strip=True) if left is not None else ""
        # Нет даты в правой колонке → предмет ещё не опубликован, пропускаем.
        if not published or not any(ch.isdigit() for ch in published):
            continue
        published_at = _PUBLISHED_PREFIX_RE.sub("", published).strip() or None

        subjects.append(
            PublishedSubject(
                title=title,
                subject=normalize_subject(title),
                published_at=published_at,
                exam_date=current_exam_date,
            )
        )
    return subjects


def parse_published_subjects(html: str) -> list[PublishedSubject]:
    """Список опубликованных предметов основного периода из блока #w2.

    Строки #w2 чередуются: заголовок-дата экзамена (``.exam-date``) и строки
    предметов (``.text-right`` — предмет, ``.text-left`` — «Результаты размещены
    {дата}»). Предмет считаем опубликованным, только если в правой колонке есть
    дата размещения; запланированные, но ещё не выложенные строки пропускаем.
    """
    return _subjects_from_soup(BeautifulSoup(html, "html.parser"))


def parse_overview(html: str) -> PageSnapshot:
    """Полный разбор страницы-обзора: счётчик + опубликованные предметы #w2.

    HTML парсится один раз (общий ``soup`` на оба разбора) — дешевле, чем строить
    дерево BeautifulSoup дважды на каждый опрос монитора.
    """
    soup = BeautifulSoup(html, "html.parser")
    return PageSnapshot(
        results_count=_count_from_soup(soup),
        subjects=_subjects_from_soup(soup),
    )


class EgeSpbOverviewMonitor:
    """Дешёвый опрос страницы-обзора ege.spb.ru (один GET, без паспортных данных)."""

    def __init__(self, url: str, timeout: float = 15.0):
        self._url = url
        self._client = build_client(timeout)

    async def fetch(self) -> PageSnapshot:
        response = await self._client.get(self._url)
        response.raise_for_status()
        return parse_overview(decode_response(response))

    async def aclose(self) -> None:
        await self._client.aclose()
