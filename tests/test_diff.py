from __future__ import annotations

from ege_notifier.models.student import ResultItem
from ege_notifier.providers.base import FetchedResult
from ege_notifier.services.diff import ChangeType, diff_results, merge_results


def test_new_result_detected():
    changes = diff_results([], [FetchedResult(subject="russian", score=88, status="готов")])
    assert len(changes) == 1
    assert changes[0].type == ChangeType.NEW
    assert changes[0].new_score == 88


def test_no_change():
    existing = [ResultItem(subject="russian", score=88, status="готов")]
    fetched = [FetchedResult(subject="russian", score=88, status="готов")]
    assert diff_results(existing, fetched) == []


def test_score_update_detected():
    existing = [ResultItem(subject="russian", score=88, status="готов")]
    fetched = [FetchedResult(subject="russian", score=90, status="готов")]
    changes = diff_results(existing, fetched)
    assert len(changes) == 1
    assert changes[0].type == ChangeType.UPDATED
    assert (changes[0].old_score, changes[0].new_score) == (88, 90)


def test_status_update_detected():
    existing = [ResultItem(subject="russian", score=None, status="на проверке")]
    fetched = [FetchedResult(subject="russian", score=None, status="результат получен")]
    changes = diff_results(existing, fetched)
    assert len(changes) == 1
    assert changes[0].type == ChangeType.UPDATED


def test_merge_preserves_first_seen_and_updates_score():
    existing = [ResultItem(subject="russian", score=None, status="на проверке")]
    first_seen = existing[0].first_seen_at
    fetched = [FetchedResult(subject="russian", score=88, status="результат получен")]
    merged = merge_results(existing, fetched)
    assert len(merged) == 1
    assert merged[0].first_seen_at == first_seen
    assert merged[0].score == 88
    assert merged[0].status == "результат получен"


def test_merge_keeps_unseen_subjects():
    existing = [
        ResultItem(subject="russian", score=88),
        ResultItem(subject="math", score=70),
    ]
    fetched = [FetchedResult(subject="russian", score=88)]
    merged = merge_results(existing, fetched)
    subjects = {m.subject for m in merged}
    assert subjects == {"russian", "math"}
