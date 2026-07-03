from __future__ import annotations

from ege_notifier.models.student import BlankImage as StoredBlank
from ege_notifier.models.student import Criterion as StoredCriterion
from ege_notifier.models.student import ResultItem
from ege_notifier.providers.base import (
    BlankImage,
    Criterion,
    FetchedResult,
    TaskAnswer,
)
from ege_notifier.services.diff import ChangeType, diff_results, merge_results


def test_new_result_detected():
    changes = diff_results(
        [], [FetchedResult(subject="russian", score=88, status="готов")]
    )
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


def test_diff_matches_old_key_after_normalization_change():
    # Предмет сохранён под старым ключом (со скобками), сайт прислал тот же
    # балл — это НЕ новый результат, ключи сопоставляются нормализованно.
    existing = [ResultItem(subject="математика (профильная)", score=88, status="готов")]
    fetched = [FetchedResult(subject="математика профильная", score=88, status="готов")]
    assert diff_results(existing, fetched) == []


def test_two_results_same_subject_different_waves_are_stable():
    """Два действующих результата по одному предмету из разных волн (основная +
    резервный день) НЕ считаются изменением друг друга.

    Регрессия на спам уведомлениями: раньше сопоставление шло по одному лишь
    нормализованному предмету, поэтому оба результата по «Математике профильной»
    делили ключ, побеждал последний, и на каждой проверке первый выглядел «сменой
    балла» (27→11) — админам летела сводка каждый цикл. Ключ теперь включает дату."""
    existing = [
        ResultItem(subject="математика профильная", score=11, exam_date="8 июня 2026"),
        ResultItem(subject="математика профильная", score=27, exam_date="24 июня 2026"),
    ]
    fetched = [
        FetchedResult(subject="математика профильная", score=11, exam_date="8 июня 2026"),
        FetchedResult(subject="математика профильная", score=27, exam_date="24 июня 2026"),
    ]
    assert diff_results(existing, fetched) == []

    merged = merge_results(existing, fetched)
    assert len(merged) == 2  # оба результата сохранены, не схлопнуты
    assert {(m.score, m.exam_date) for m in merged} == {
        (11, "8 июня 2026"),
        (27, "24 июня 2026"),
    }
    # updated_at не двигается — нет ложного «нового результата».
    assert {m.updated_at for m in merged} == {e.updated_at for e in existing}


def test_new_wave_result_for_existing_subject_is_new_not_update():
    """Появление второго результата по уже известному предмету (новая волна) —
    это НОВЫЙ результат по своей дате, а не «обновление» прежнего балла."""
    existing = [
        ResultItem(subject="математика профильная", score=11, exam_date="8 июня 2026"),
    ]
    fetched = [
        FetchedResult(subject="математика профильная", score=11, exam_date="8 июня 2026"),
        FetchedResult(subject="математика профильная", score=27, exam_date="24 июня 2026"),
    ]
    changes = diff_results(existing, fetched)
    assert len(changes) == 1
    assert changes[0].type == ChangeType.NEW
    assert (changes[0].new_score, changes[0].old_score) == (27, None)


def test_detail_only_change_is_not_a_change():
    """Появление детализации (критерии/баллы/распознавание/бланки) при том же
    value/score/status НЕ считается изменением — иначе после обновления парсера всем
    отслеживаемым ученикам прилетели бы повторные уведомления."""
    existing = [ResultItem(subject="russian", score=88, status="готов")]
    fetched = [
        FetchedResult(
            subject="russian",
            score=88,
            status="готов",
            criteria=[Criterion(name="Крит. К1", value="2")],
            primary_score=37,
            recognition=[TaskAnswer(task="1", answer="АБВ")],
            blanks=[BlankImage(title="Бланк 1", url="https://x/d?f=1")],
        )
    ]
    assert diff_results(existing, fetched) == []


def test_merge_adds_detail_without_bumping_updated_at():
    """Деталь сохраняется, но updated_at не двигается (раз value/score/status те же)."""
    existing = [ResultItem(subject="russian", score=88, status="готов")]
    prev_updated = existing[0].updated_at
    fetched = [
        FetchedResult(
            subject="russian",
            score=88,
            status="готов",
            criteria=[Criterion(name="Крит. К1", value="2")],
            primary_score=37,
            blanks=[BlankImage(title="Бланк 1", url="https://x/d?f=1")],
        )
    ]
    merged = merge_results(existing, fetched)
    assert merged[0].primary_score == 37
    assert merged[0].criteria == [StoredCriterion(name="Крит. К1", value="2")]
    assert merged[0].blanks == [StoredBlank(title="Бланк 1", url="https://x/d?f=1")]
    assert merged[0].updated_at == prev_updated  # тихое обновление, без «нового результата»


def test_merge_preserves_downloaded_blank_path():
    """Путь до уже скачанного скана переносится на свежий снимок по заголовку.

    Ссылка download.php одноразовая и в ответе меняется, а файл на диске остаётся —
    без переноса path кнопка «Бланки» теряла бы локальный файл и качала заново."""
    existing = [
        ResultItem(
            subject="russian",
            score=88,
            blanks=[StoredBlank(title="Бланк 1", url="https://x/d?f=old", path="HASH/x.pdf")],
        )
    ]
    fetched = [
        FetchedResult(
            subject="russian",
            score=88,
            blanks=[BlankImage(title="Бланк 1", url="https://x/d?f=NEW")],
        )
    ]
    merged = merge_results(existing, fetched)
    assert merged[0].blanks[0].url == "https://x/d?f=NEW"  # ссылка свежая
    assert merged[0].blanks[0].path == "HASH/x.pdf"  # путь к скачанному сохранён


def test_merge_drops_stale_detail_when_result_changed():
    """Если value/score/status изменились — прежняя деталь (от старого балла) не
    тащится к новому результату (иначе экран «Детали» противоречил бы новому баллу)."""
    existing = [
        ResultItem(
            subject="russian",
            score=88,
            criteria=[StoredCriterion(name="К1", value="2")],
            primary_score=37,
        )
    ]
    fetched = [FetchedResult(subject="russian", score=90)]  # новый балл, без детали
    merged = merge_results(existing, fetched)
    assert merged[0].score == 90
    assert merged[0].criteria == []
    assert merged[0].primary_score is None


def test_merge_keeps_old_detail_when_fetch_lacks_it():
    """Если источник не отдал детализацию — уже известную не затираем."""
    existing = [
        ResultItem(
            subject="russian",
            score=88,
            criteria=[StoredCriterion(name="Крит. К1", value="2")],
            primary_score=37,
        )
    ]
    fetched = [FetchedResult(subject="russian", score=88)]  # без детали
    merged = merge_results(existing, fetched)
    assert merged[0].criteria == [StoredCriterion(name="Крит. К1", value="2")]
    assert merged[0].primary_score == 37


def test_merge_migrates_old_key_without_duplicating():
    # При смене ключа предмет не дублируется, а лениво переезжает на канонический.
    existing = [ResultItem(subject="математика (профильная)", score=88)]
    first_seen = existing[0].first_seen_at
    fetched = [FetchedResult(subject="математика профильная", score=90)]
    merged = merge_results(existing, fetched)
    assert len(merged) == 1
    assert merged[0].subject == "математика профильная"  # канонический ключ
    assert merged[0].score == 90
    assert merged[0].first_seen_at == first_seen  # история сохранена
