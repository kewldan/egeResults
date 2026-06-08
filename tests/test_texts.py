from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from ege_notifier.bot import texts
from ege_notifier.models import Student
from ege_notifier.services.diff import ChangeType, ResultChange
from ege_notifier.services.results import StudentUpdate


def _student(results: list) -> Student:
    # texts.* обращаются только к этим полям ученика — duck-typing избавляет от БД.
    return cast(
        Student,
        SimpleNamespace(
            last_name="Иванов", passport_masked="●●●● ●●●●74", results=results
        ),
    )


def test_format_current_results_lists_all_known_results():
    student = _student(
        [
            SimpleNamespace(
                subject="russian",
                subject_title="Русский язык",
                value=None,
                score=88,
                status="Действующий результат",
            ),
            SimpleNamespace(
                subject="сочинение",
                subject_title="Сочинение",
                value="Зачёт",
                score=None,
                status=None,
            ),
        ]
    )
    text = texts.format_current_results(student)
    assert "Иванов" in text
    assert "Русский язык" in text and "88" in text
    assert "Действующий результат" in text
    assert "Сочинение" in text and "Зачёт" in text
    # Баллы спрятаны под спойлер.
    assert "<tg-spoiler>88</tg-spoiler>" in text
    assert "<tg-spoiler>Зачёт</tg-spoiler>" in text


def test_format_current_results_escapes_html_from_source():
    # subject_title/value/status приходят со стороннего сайта — спецсимволы HTML
    # должны экранироваться, иначе разметка сломается (или будет инъекция).
    student = _student(
        [
            SimpleNamespace(
                subject="x",
                subject_title="A<b> & C",
                value="<i>1</i>",
                score=None,
                status="ok & <fin>",
            )
        ]
    )
    text = texts.format_current_results(student)
    assert "A&lt;b&gt; &amp; C" in text
    assert "&lt;i&gt;1&lt;/i&gt;" in text
    assert "ok &amp; &lt;fin&gt;" in text


def test_format_current_results_empty_is_not_header_only():
    text = texts.format_current_results(_student([]))
    assert "Результатов пока нет" in text
    assert not text.endswith("\n")  # не «голый» заголовок с пустой строкой


def test_human_duration_rounds_up_with_russian_plurals():
    assert texts.human_duration(45) == "45 секунд"
    assert texts.human_duration(1) == "1 секунду"
    assert texts.human_duration(300) == "5 минут"
    assert texts.human_duration(61) == "2 минуты"  # округление вверх
    assert texts.human_duration(86400) == "24 часа"


def test_refresh_throttled_mentions_wait_time():
    text = texts.refresh_throttled(120)
    assert "2 минуты" in text
    assert "Обновить" in text


def test_admin_new_user_includes_id_and_username():
    user = cast(
        Student,
        SimpleNamespace(telegram_id=42, username="vasya", full_name="Вася Пупкин"),
    )
    text = texts.admin_new_user(user)
    assert "42" in text and "@vasya" in text and "Вася Пупкин" in text


def test_admin_results_digest_is_single_message_listing_students():
    # Сводка за цикл — одно сообщение со списком (анти-флуд админа).
    upd = cast(
        StudentUpdate,
        SimpleNamespace(student=_student([]), changes=[object()], subscribers=[1]),
    )
    text = texts.admin_results_digest([upd, upd, upd])
    assert "3 ученик" in text  # счётчик
    assert text.count("Иванов") == 3  # по строке на ученика
    assert "…" not in text  # порога усечения не достигли


def test_format_results_update_new_and_updated():
    changes = [
        ResultChange(
            type=ChangeType.NEW,
            subject="russian",
            subject_title="Русский язык",
            old_value=None,
            new_value=None,
            old_score=None,
            new_score=88,
            old_status=None,
            new_status="готов",
        ),
        ResultChange(
            type=ChangeType.UPDATED,
            subject="math",
            subject_title="Математика",
            old_value=None,
            new_value=None,
            old_score=70,
            new_score=82,
            old_status=None,
            new_status=None,
        ),
    ]
    text = texts.format_results_update(_student([]), changes)
    assert "🆕" in text and "Русский язык" in text and "88" in text
    # Баллы спрятаны под спойлер, поэтому «70 → 82» не идёт подряд.
    assert "✏️" in text and "Математика" in text
    assert "<tg-spoiler>70</tg-spoiler> → <tg-spoiler>82</tg-spoiler>" in text
