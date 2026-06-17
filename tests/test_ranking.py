"""Тесты составления топа по предмету (``services.ranking``).

Чистые функции без БД/сети: учеников подменяем лёгкими ``SimpleNamespace`` — топ
сортирует числовые баллы по убыванию, нечисловые («Зачёт») уносит в конец, а
сопоставление предмета идёт через ``normalize_subject`` (синонимы находят друг друга).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from ege_notifier.models import Student
from ege_notifier.services.ranking import (
    available_subjects,
    average_score,
    rank_by_subject,
)


def _item(subject, *, title=None, score=None, value=None, status=None):
    return SimpleNamespace(
        subject=subject,
        subject_title=title or subject,
        score=score,
        value=value,
        status=status,
    )


def _student(last_name, results, *, masked="●●●● ●●●●00", notes="") -> Student:
    return cast(
        Student,
        SimpleNamespace(
            last_name=last_name,
            passport_masked=masked,
            notes=notes,
            results=results,
        ),
    )


def test_rank_sorts_numeric_scores_descending():
    students = [
        _student("Петров", [_item("математика профильная", score=70)]),
        _student("Иванов", [_item("математика профильная", score=92)]),
        _student("Сидоров", [_item("математика профильная", score=85)]),
        _student("Без", [_item("физика", score=99)]),  # другой предмет — не в топе
    ]
    entries = rank_by_subject(students, "математика профильная")
    assert [e.last_name for e in entries] == ["Иванов", "Сидоров", "Петров"]
    assert [e.score for e in entries] == [92, 85, 70]


def test_rank_matches_subject_synonyms():
    # Ученики записаны под разными формулировками одного предмета — оба попадают в топ.
    students = [
        _student("Иванов", [_item("Информатика и ИКТ", score=80)]),
        _student("Петров", [_item("Информатика", score=88)]),
    ]
    entries = rank_by_subject(students, "информатика")
    assert [e.last_name for e in entries] == ["Петров", "Иванов"]


def test_rank_puts_non_numeric_results_last_alphabetically():
    students = [
        _student("Яшин", [_item("сочинение", value="Зачёт")]),
        _student("Иванов", [_item("сочинение", score=90)]),
        _student("Абрамов", [_item("сочинение", value="Зачёт")]),
    ]
    entries = rank_by_subject(students, "сочинение")
    # Числовой балл первым, затем «Зачёт»-ы по алфавиту фамилий.
    assert [e.last_name for e in entries] == ["Иванов", "Абрамов", "Яшин"]
    assert entries[0].score == 90 and entries[1].score is None


def test_average_score_ignores_non_numeric():
    students = [
        _student("Иванов", [_item("математика базовая", score=60)]),
        _student("Петров", [_item("математика базовая", score=80)]),
        _student("Сидоров", [_item("математика базовая", value="Зачёт")]),
    ]
    entries = rank_by_subject(students, "математика базовая")
    assert average_score(entries) == 70.0  # (60+80)/2, «Зачёт» не учитывается


def test_average_score_none_when_no_numeric():
    students = [_student("Иванов", [_item("сочинение", value="Зачёт")])]
    entries = rank_by_subject(students, "сочинение")
    assert average_score(entries) is None


def test_available_subjects_counts_students_and_sorts_by_count():
    students = [
        _student("Иванов", [_item("русский язык", score=80), _item("физика", score=70)]),
        _student("Петров", [_item("русский язык", score=88)]),
        _student("Сидоров", [_item("Русский", score=60)]),  # синоним → тот же ключ
    ]
    subjects = available_subjects(students)
    by_key = {s.subject: s.count for s in subjects}
    assert by_key["русский язык"] == 3  # все трое, синоним учтён
    assert by_key["физика"] == 1
    # Сортировка по убыванию числа учеников — русский впереди физики.
    assert subjects[0].subject == "русский язык"


def test_available_subjects_empty_when_no_results():
    assert available_subjects([_student("Иванов", [])]) == []
