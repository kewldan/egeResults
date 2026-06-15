from __future__ import annotations

from pathlib import Path

from ege_notifier.providers.ege_spb_overview import (
    parse_overview,
    parse_published_subjects,
    parse_results_count,
)

# Реальная страница-обзор ege.spb.ru?mode=ege2026&wave=1 (как и страница ученика —
# тест на настоящем HTML, чтобы поймать поломку вёрстки сайта).
SAMPLE = (Path(__file__).parent / "fixtures" / "ege_spb_overview.html").read_text(
    encoding="utf-8"
)


def test_parse_results_count_from_sample():
    # На странице: «Количество результатов в базе данных: 41 144».
    assert parse_results_count(SAMPLE) == 41144


def test_parse_count_missing_returns_none():
    assert parse_results_count("<html><body>нет счётчика</body></html>") is None


def test_parse_published_subjects_from_sample():
    subjects = parse_published_subjects(SAMPLE)
    keys = {s.subject for s in subjects}
    # Основной период (#w2): июньские предметы + декабрьские сочинение/изложение.
    assert {"химия", "история", "литература"} <= keys
    assert {"сочинение", "изложение"} <= keys

    by_title = {s.title: s for s in subjects}
    assert by_title["Химия"].published_at == "11 июня 2026"
    assert by_title["Химия"].exam_date == "1 июня 2026"


def test_parse_overview_combines_both():
    snapshot = parse_overview(SAMPLE)
    assert snapshot.results_count == 41144
    assert any(s.subject == "химия" for s in snapshot.subjects)


def test_unpublished_rows_are_skipped():
    # Строка без даты в правой колонке — предмет ещё не выложен, не считаем.
    html = """
    <div id="w2">
      <div class="row"><div class="col exam-date">1 июня 2026</div></div>
      <div class="row">
        <div class="text-right">Химия</div>
        <div class="text-left">Результаты размещены 11 июня 2026</div>
      </div>
      <div class="row">
        <div class="text-right">Физика</div>
        <div class="text-left"></div>
      </div>
    </div>
    """
    titles = {s.title for s in parse_published_subjects(html)}
    assert "Химия" in titles
    assert "Физика" not in titles


def test_no_w2_block_returns_empty():
    assert parse_published_subjects("<html><body>пусто</body></html>") == []
