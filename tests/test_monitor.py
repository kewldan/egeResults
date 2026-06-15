from __future__ import annotations

from ege_notifier.providers.ege_spb_overview import PageSnapshot, PublishedSubject
from ege_notifier.services.monitor import diff_page


def _subj(title: str, key: str) -> PublishedSubject:
    return PublishedSubject(title=title, subject=key)


def test_counter_increase_is_update():
    change = diff_page(
        100, {"химия"}, PageSnapshot(results_count=150, subjects=[_subj("Химия", "химия")])
    )
    assert change.counter_increased
    assert change.delta == 50
    assert change.new_subjects == []
    assert change.has_results_update


def test_new_subject_is_update_even_without_counter_move():
    change = diff_page(
        100,
        {"химия"},
        PageSnapshot(
            results_count=100,
            subjects=[_subj("Химия", "химия"), _subj("История", "история")],
        ),
    )
    assert not change.counter_increased
    assert [s.subject for s in change.new_subjects] == ["история"]
    assert change.has_results_update


def test_no_change_is_not_update():
    change = diff_page(
        100, {"химия"}, PageSnapshot(results_count=100, subjects=[_subj("Химия", "химия")])
    )
    assert not change.has_results_update


def test_counter_decrease_is_not_update():
    # Счётчик уменьшился (разовый сбой сайта) — не триггерим проверку.
    change = diff_page(
        100, {"химия"}, PageSnapshot(results_count=90, subjects=[_subj("Химия", "химия")])
    )
    assert not change.counter_increased
    assert change.delta == -10
    assert not change.has_results_update


def test_missing_count_falls_back_to_subjects():
    # Счётчик не распарсился (None) — изменение ловим по новому предмету, delta=None.
    change = diff_page(
        100,
        {"химия"},
        PageSnapshot(
            results_count=None,
            subjects=[_subj("Химия", "химия"), _subj("Физика", "физика")],
        ),
    )
    assert change.delta is None
    assert not change.counter_increased
    assert [s.subject for s in change.new_subjects] == ["физика"]
    assert change.has_results_update


def test_baseline_is_never_an_update():
    # На базовом снимке (первый запуск) не уведомляем, даже если «всё новое».
    change = diff_page(
        None, set(), PageSnapshot(results_count=100, subjects=[_subj("Химия", "химия")])
    )
    change.is_baseline = True
    assert not change.has_results_update
