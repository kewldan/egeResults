from __future__ import annotations

from pathlib import Path

from ege_notifier.providers.base import StudentQuery
from ege_notifier.providers.ege_spb import (
    build_form_body,
    looks_not_found,
    parse_registrations,
    parse_results_html,
)

SAMPLE = (Path(__file__).parent / "fixtures" / "ege_spb_sample.html").read_text(
    encoding="utf-8"
)


def test_build_form_body_uses_cp1251():
    # Должно совпадать с реальным телом запроса ege.spb.ru (поля в windows-1251).
    body = build_form_body(
        StudentQuery(
            last_name="Тенишев", passport_series="4022", passport_number="083074"
        )
    )
    assert body == (
        "pLastName=%D2%E5%ED%E8%F8%E5%E2"
        "&Series=4022"
        "&Number=083074"
        "&Login=%CF%EE%EA%E0%E7%E0%F2%FC+%F0%E5%E7%F3%EB%FC%F2%E0%F2%FB"
    )


def test_parse_sample_response():
    results = parse_results_html(SAMPLE)
    assert len(results) == 1
    r = results[0]
    assert r.subject_title == "Сочинение"
    assert r.subject == "сочинение"
    assert r.value == "Зачёт"
    assert r.score is None  # «Зачёт» — не число
    assert r.status == "Действующий результат"
    assert r.exam_date == "3 декабря 2025"


def test_parse_sample_detail():
    """Детализация (критерии / распознавание / бланки) парсится из того же блока."""
    r = parse_results_html(SAMPLE)[0]
    # критерии
    assert [(c.name, c.value) for c in r.criteria] == [
        ("Крит. T1", "Зачёт"),
        ("Крит. К1", "Зачёт"),
        ("Крит. К5", "Незачёт"),
    ]
    # распознанные ответы части 1 (номер задания ↔ ответ)
    assert [(t.task, t.answer) for t in r.recognition] == [("1", "АБВ"), ("2", "123")]
    # сканы бланков
    assert [b.title for b in r.blanks] == ["Бланк записи лист 1", "Бланк записи лист 2"]
    # без base_url ссылки остаются относительными
    assert r.blanks[0].url.startswith("download.php?filename=SAMPLE_TOKEN_1")


def test_blanks_absolutized_with_base_url():
    base = "https://www.ege.spb.ru/result/index.php"
    r = parse_results_html(SAMPLE, base_url=base)[0]
    assert (
        r.blanks[0].url
        == "https://www.ege.spb.ru/result/download.php?filename=SAMPLE_TOKEN_1&v=1"
    )


def test_parse_registrations_from_sample():
    regs = parse_registrations(SAMPLE)
    assert len(regs) == 2
    first, second = regs
    # опубликованный пункт: название + адрес
    assert first.subject == "сочинение"
    assert first.exam_date == "3 декабря 2025"
    assert first.place == "ГБОУ СОШ №669"
    assert first.address is not None and "Образцовая" in first.address
    # пункт ещё не назначен («доступно за день до экзамена») → place/address пусты
    assert second.subject == "русский язык"
    assert second.place is None
    assert second.address is None


def test_parse_primary_scores_block():
    """Балльная раскладка «Первичные баллы по частям» → criteria + primary_score."""
    html = """
    <div id="result-data"><div class="exam-area"><div id="exam-detail">
      <div class="exam-title">
        <div class="exam-subject-info">Русский язык&nbsp;<span>(4 июня 2026)</span></div>
        <div class="exam-result-status current">Действующий результат</div>
        <div class="exam-result good">88</div>
      </div>
      <div class="exam-additional-info">
        <div id="exam-additional-info-smod-1" class="panel">
          <div class="panel unhidden"><div class="panel-body"><div class="row row-no-gutters">
            <div class="col col-md-3"><div class="info-header info-cell">Задания с кратким ответом</div><div class="info-bigvalue info-cell">16</div></div>
            <div class="col col-md-3"><div class="info-header info-cell">Первичный балл (сумма)</div><div class="info-bigvalue info-cell">37</div></div>
          </div></div></div>
        </div>
      </div>
    </div></div></div>
    """
    r = parse_results_html(html)[0]
    assert r.score == 88
    assert [(c.name, c.value) for c in r.criteria] == [
        ("Задания с кратким ответом", "16"),
        ("Первичный балл (сумма)", "37"),
    ]
    assert r.primary_score == 37


def test_fallback_scope_does_not_cross_contaminate_detail():
    """Без обёртки #exam-detail детализация одного экзамена НЕ утекает в соседний.

    Регрессия: раньше scope=весь #result-data, поэтому каждый экзамен собирал бланки
    и критерии всех экзаменов (бланк математики приписывался русскому)."""
    html = """
    <div id="result-data">
      <div class="exam-title">
        <div class="exam-subject-info">Русский язык&nbsp;<span>(4 июня 2026)</span></div>
        <div class="exam-result good">88</div>
      </div>
      <div class="exam-additional-info">
        <div id="exam-additional-info-blanks-1"><div class="list-group">
          <a href="download.php?f=rus">Бланк РУС лист 1</a>
        </div></div>
      </div>
      <div class="exam-title">
        <div class="exam-subject-info">Физика&nbsp;<span>(7 июня 2026)</span></div>
        <div class="exam-result good">70</div>
      </div>
      <div class="exam-additional-info">
        <div id="exam-additional-info-blanks-2"><div class="list-group">
          <a href="download.php?f=fiz">Бланк ФИЗ лист 1</a>
        </div></div>
      </div>
    </div>
    """
    results = parse_results_html(html)
    assert len(results) == 2
    rus, fiz = results
    assert rus.value == "88" and fiz.value == "70"
    assert [b.title for b in rus.blanks] == ["Бланк РУС лист 1"]
    assert [b.title for b in fiz.blanks] == ["Бланк ФИЗ лист 1"]


def test_parse_empty_or_unknown():
    assert parse_results_html("<html><body>ничего</body></html>") == []


# --- «не найден» vs «результатов пока нет» ---------------------------------

# Форма поиска, которую сайт отдаёт при неверных данных (нет блока ученика).
SEARCH_FORM = """
<html><body>
  <form method="post" action="index.php">
    <input type="text" name="pLastName" value="">
    <input type="text" name="Series" value="">
    <input type="text" name="Number" value="">
    <input type="submit" name="Login" value="Показать результаты">
  </form>
</body></html>
"""

# Ученик найден, но баллов ещё нет: есть регистрация на экзамены, блока
# результатов нет.
FOUND_NO_RESULTS = """
<html><body>
  <div id="exam-content">
    <div id="reg-data">
      <table class="registrations-info-table"><tr><td>Русский язык</td></tr></table>
    </div>
  </div>
</body></html>
"""


def test_looks_not_found_on_search_form():
    # Сайт вернул форму поиска (опечатка/неверные данные) → «не найден».
    assert looks_not_found(SEARCH_FORM) is True


def test_looks_not_found_false_on_results_page():
    # Страница с результатами — ученик найден.
    assert looks_not_found(SAMPLE) is False


def test_looks_not_found_false_when_found_but_no_results():
    # Найден, но результатов ещё нет — это НЕ «не найден» (есть регистрация).
    assert looks_not_found(FOUND_NO_RESULTS) is False
    assert parse_results_html(FOUND_NO_RESULTS) == []


def test_parse_numeric_score():
    html = """
    <div id="result-data">
      <div class="exam-title">
        <div class="exam-subject-info">Русский язык&nbsp;<span>(4 июня 2026)</span></div>
        <div class="exam-result-status current">Действующий результат</div>
        <div class="exam-result good">88</div>
      </div>
    </div>
    """
    results = parse_results_html(html)
    assert len(results) == 1
    assert results[0].subject == "русский язык"
    assert results[0].value == "88"
    assert results[0].score == 88
