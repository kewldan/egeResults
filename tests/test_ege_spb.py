from __future__ import annotations

from pathlib import Path

from ege_notifier.providers.base import StudentQuery
from ege_notifier.providers.ege_spb import (
    build_form_body,
    looks_not_found,
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
