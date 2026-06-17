from __future__ import annotations

from dataclasses import dataclass

from ege_notifier.models import Student
from ege_notifier.utils import normalize_subject


@dataclass(slots=True)
class RankEntry:
    """Одна строка топа по предмету (балл одного ученика)."""

    last_name: str
    passport_masked: str
    notes: str
    subject_title: str | None
    score: int | None
    value: str | None
    status: str | None


@dataclass(slots=True)
class SubjectCount:
    """Предмет и сколько учеников имеют по нему результат (для подсказки /top)."""

    subject: str  # нормализованный ключ
    title: str  # отображаемое название
    count: int


def _result_for(student: Student, subject_key: str):
    """Результат ученика по нормализованному ключу предмета, либо ``None``."""
    for item in student.results:
        if normalize_subject(item.subject) == subject_key:
            return item
    return None


def rank_by_subject(
    students: list[Student], subject_key: str, notes_query: str | None = None
) -> list[RankEntry]:
    """Сортирует учеников по баллу за предмет (по убыванию).

    Чистая функция (без I/O): принимает уже загруженных учеников и нормализованный
    ключ предмета. Сопоставление идёт через ``normalize_subject`` на обеих сторонах,
    поэтому синонимы («Информатика и ИКТ» / «Информатика») и формулировки с разной
    пунктуацией находят один и тот же предмет. Числовые баллы идут первыми по
    убыванию; результаты без балла («Зачёт») — в конце, по алфавиту фамилий.

    ``notes_query`` (если задан) оставляет только учеников, в чьей заметке
    (``Student.notes``) встречается подстрока — без учёта регистра. Удобно сузить
    топ до конкретной группы/потока, помеченной в заметке.
    """
    needle = (notes_query or "").strip().casefold()
    entries: list[RankEntry] = []
    for st in students:
        if needle and needle not in (st.notes or "").casefold():
            continue
        item = _result_for(st, subject_key)
        if item is None:
            continue
        entries.append(
            RankEntry(
                last_name=st.last_name,
                passport_masked=st.passport_masked,
                notes=st.notes,
                subject_title=item.subject_title,
                score=item.score,
                value=item.value,
                status=item.status,
            )
        )
    entries.sort(
        key=lambda e: (e.score is None, -(e.score or 0), e.last_name.lower())
    )
    return entries


def available_subjects(students: list[Student]) -> list[SubjectCount]:
    """Предметы, по которым у учеников есть результаты — по убыванию числа учеников.

    Подсказка для администратора: какой ключ передать в ``/top``. Заголовок берётся
    от первого встретившегося ``subject_title`` для ключа (как показывает сайт)."""
    counts: dict[str, int] = {}
    titles: dict[str, str] = {}
    for st in students:
        seen: set[str] = set()
        for item in st.results:
            key = normalize_subject(item.subject)
            if key in seen:
                continue  # один ученик считается по предмету один раз
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            titles.setdefault(key, item.subject_title or item.subject)
    result = [
        SubjectCount(subject=key, title=titles[key], count=count)
        for key, count in counts.items()
    ]
    result.sort(key=lambda s: (-s.count, s.title.lower()))
    return result


def average_score(entries: list[RankEntry]) -> float | None:
    """Средний числовой балл среди записей (``None``, если числовых баллов нет)."""
    scores = [e.score for e in entries if e.score is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)
