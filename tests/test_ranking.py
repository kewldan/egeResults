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
    is_combo_query,
    parse_subject_combo,
    rank_by_combo,
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


def test_rank_filters_by_notes_substring_case_insensitive():
    students = [
        _student("Иванов", [_item("русский язык", score=92)], notes="Группа А"),
        _student("Петров", [_item("русский язык", score=88)], notes="группа б"),
        _student("Сидоров", [_item("русский язык", score=70)], notes="ГРУППА А, поток 1"),
    ]
    # Подстрока без учёта регистра — оба «группа А» проходят, «группа б» отсеивается.
    entries = rank_by_subject(students, "русский язык", "группа а")
    assert [e.last_name for e in entries] == ["Иванов", "Сидоров"]


def test_rank_notes_filter_blank_keeps_everyone():
    students = [
        _student("Иванов", [_item("русский язык", score=92)], notes="Группа А"),
        _student("Петров", [_item("русский язык", score=88)], notes=""),
    ]
    # Пустой/пробельный фильтр = фильтра нет, поведение прежнее.
    assert [e.last_name for e in rank_by_subject(students, "русский язык", "  ")] == [
        "Иванов",
        "Петров",
    ]
    assert [e.last_name for e in rank_by_subject(students, "русский язык")] == [
        "Иванов",
        "Петров",
    ]


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


# --- комбо-топ по сумме баллов (parse / is_combo_query / rank_by_combo) --------


def test_parse_subject_combo_splits_mir():
    slots = parse_subject_combo("МИР")
    assert [s.code for s in slots] == ["М", "И", "Р"]
    # «М» по умолчанию — профильная, «И» — информатика (а не история).
    assert [s.keys for s in slots] == [
        ("математика профильная",),
        ("информатика",),
        ("русский язык",),
    ]


def test_parse_subject_combo_longest_match_wins():
    # Многобуквенные коды выигрывают у одиночных: ИСТ — история, ИКТ/ИНФ — информатика.
    assert [s.code for s in parse_subject_combo("МИСТ")] == ["М", "ИСТ"]
    assert [s.code for s in parse_subject_combo("РИКТ")] == ["Р", "ИКТ"]
    # «ИЯ» (иностранный) подбирает любой язык.
    iya = parse_subject_combo("ИЯ")
    assert iya[0].keys[0] == "английский язык" and "немецкий язык" in iya[0].keys


def test_parse_subject_combo_case_and_spaces_insensitive():
    assert [s.code for s in parse_subject_combo(" м и р ")] == ["М", "И", "Р"]


def test_parse_subject_combo_returns_none_on_unknown_letter():
    assert parse_subject_combo("МZР") is None
    assert parse_subject_combo("") is None


def test_is_combo_query_distinguishes_acronym_from_subject_name():
    assert is_combo_query("МИР") is True
    assert is_combo_query("МИФ") is True  # математика+информатика+физика
    # Названия предметов вводят строчными — это НЕ комбо.
    assert is_combo_query("химия") is False
    assert is_combo_query("математика профильная") is False
    # Одна буква (даже валидная) — не комбинация (нужно ≥2 кода).
    assert is_combo_query("Р") is False
    # Слово с неизвестными буквами не разбирается целиком.
    assert is_combo_query("ФИЗИКА") is False


def test_rank_by_combo_sums_and_sorts_descending():
    slots = parse_subject_combo("МИР")
    students = [
        _student(
            "Петров",
            [
                _item("Математика профильная", score=70),
                _item("Информатика", score=80),
                _item("Русский язык", score=75),
            ],
        ),  # сумма 225
        _student(
            "Иванов",
            [
                _item("Математика профильная", score=92),
                _item("Информатика и ИКТ", score=88),  # синоним → информатика
                _item("Русский язык", score=90),
            ],
        ),  # сумма 270
    ]
    entries = rank_by_combo(students, slots)
    assert [e.last_name for e in entries] == ["Иванов", "Петров"]
    assert [e.total for e in entries] == [270, 225]
    assert entries[0].scores == [92, 88, 90]


def test_rank_by_combo_excludes_students_missing_a_subject():
    slots = parse_subject_combo("МИР")
    students = [
        _student(
            "Полный",
            [
                _item("Математика профильная", score=60),
                _item("Информатика", score=60),
                _item("Русский язык", score=60),
            ],
        ),
        # Нет информатики — в топ по сумме не попадает.
        _student(
            "Неполный",
            [
                _item("Математика профильная", score=99),
                _item("Русский язык", score=99),
            ],
        ),
        # Информатика есть, но без числа («Зачёт») — суммировать нечего, исключаем.
        _student(
            "Зачёт",
            [
                _item("Математика профильная", score=99),
                _item("Информатика", value="Зачёт"),
                _item("Русский язык", score=99),
            ],
        ),
    ]
    entries = rank_by_combo(students, slots)
    assert [e.last_name for e in entries] == ["Полный"]


def test_rank_by_combo_foreign_language_takes_best_score():
    # «ИЯ» засчитывает любой иностранный; если сдавал несколько — берём максимум.
    slots = parse_subject_combo("МИЯ")  # математика(проф) + иностранный
    student = _student(
        "Полиглот",
        [
            _item("Математика профильная", score=80),
            _item("Немецкий язык", score=70),
            _item("Английский язык", score=95),
        ],
    )
    entries = rank_by_combo([student], slots)
    assert entries[0].scores == [80, 95] and entries[0].total == 175


def test_rank_by_combo_filters_by_notes():
    slots = parse_subject_combo("МР")
    make = lambda name, notes: _student(  # noqa: E731
        name,
        [_item("Математика профильная", score=80), _item("Русский язык", score=80)],
        notes=notes,
    )
    students = [make("Иванов", "Группа А"), make("Петров", "группа б")]
    entries = rank_by_combo(students, slots, "группа а")
    assert [e.last_name for e in entries] == ["Иванов"]
