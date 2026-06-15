from __future__ import annotations

from ege_notifier.bot import texts
from ege_notifier.providers.ege_spb_overview import PublishedSubject


def test_announcement_lists_subjects_and_count():
    out = texts.results_published_announcement(
        [PublishedSubject(title="Химия", subject="химия")],
        delta=1500,
        total=41144,
    )
    assert "Химия" in out
    assert "предмету" in out  # единственное число для одного предмета
    assert texts._group_digits(1500) in out  # прирост — оценка «сколько сдавали»
    assert texts._group_digits(41144) in out  # всего в базе, с группировкой разрядов


def test_announcement_plural_for_many_subjects():
    out = texts.results_published_announcement(
        [
            PublishedSubject(title="Химия", subject="химия"),
            PublishedSubject(title="История", subject="история"),
        ],
        delta=None,
        total=None,
    )
    assert "предметам" in out  # множественное число
    # delta=None → строки про прирост нет.
    assert "В базу добавилось" not in out


def test_announcement_escapes_subject_title():
    # subject_title приходит с сайта — должен экранироваться (parse_mode=HTML).
    out = texts.results_published_announcement(
        [PublishedSubject(title="Хи<b>мия", subject="химия")],
        delta=None,
        total=None,
    )
    assert "Хи&lt;b&gt;мия" in out
    assert "Хи<b>мия" not in out


def test_admin_subjects_published_compact():
    out = texts.admin_subjects_published(
        [PublishedSubject(title="Химия", subject="химия")], delta=1500
    )
    assert "[админ]" in out
    assert "Химия" in out
    assert "1500" in out
