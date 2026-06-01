from __future__ import annotations

from types import SimpleNamespace

from ege_notifier.bot import texts
from ege_notifier.services.diff import ChangeType, ResultChange


def _student(results: list) -> SimpleNamespace:
    # texts.* обращаются только к этим полям ученика — duck-typing избавляет от БД.
    return SimpleNamespace(
        last_name="Иванов", passport_masked="●●●● ●●●●74", results=results
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
    assert "✏️" in text and "70 → 82" in text
