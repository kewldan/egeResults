"""Тесты показа детальных данных ученика: тексты расписания/деталей, кнопки
карточки и загрузчик бланков.

Тексты и клавиатуру проверяем на ученике-двойнике (``SimpleNamespace``) — как в
``test_cards``. ``BlankDownloader`` — через ``httpx.MockTransport`` (без сети).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import student_card_keyboard
from ege_notifier.services.blanks import (
    BlankDownloadError,
    BlankDownloader,
    blank_basename,
    blank_filename,
    blank_stem,
)
from ege_notifier.services.results import ResultsService


def _crit(name, value):
    return SimpleNamespace(name=name, value=value)


def _ans(task, answer):
    return SimpleNamespace(task=task, answer=answer)


def _blank(title, url):
    return SimpleNamespace(title=title, url=url)


def _reg(subject, *, title=None, date=None, place=None, address=None):
    return SimpleNamespace(
        subject=subject,
        subject_title=title,
        exam_date=date,
        place=place,
        address=address,
    )


def _item(subject, *, title=None, score=None, criteria=None, primary=None, recognition=None, blanks=None):
    return SimpleNamespace(
        subject=subject,
        subject_title=title,
        score=score,
        value=None,
        status=None,
        criteria=criteria or [],
        primary_score=primary,
        recognition=recognition or [],
        blanks=blanks or [],
    )


def _student(*, last_name="Иванов", masked="●●●● ●●●●74", id="abc", results=None, registrations=None):
    return SimpleNamespace(
        id=id,
        last_name=last_name,
        passport_masked=masked,
        results=results or [],
        registrations=registrations or [],
    )


# --- texts.format_schedule ----------------------------------------------------


def test_schedule_lists_dates_place_and_address():
    student = _student(
        registrations=[
            _reg("сочинение", title="Сочинение", date="3 декабря 2025",
                 place="ГБОУ СОШ №669", address="196605, Образцовая ул, 7"),
            _reg("русский язык", title="Русский язык", date="4 июня 2026"),
        ]
    )
    text = texts.format_schedule(student)
    assert "Сочинение" in text and "3 декабря 2025" in text
    assert "ГБОУ СОШ №669" in text and "Образцовая" in text
    # без места — подсказка, а не пустая строка
    assert "станет известен" in text


def test_schedule_empty_prompts_refresh():
    text = texts.format_schedule(_student(registrations=[]))
    assert "не загружено" in text


def test_schedule_escapes_html():
    student = _student(registrations=[_reg("x", title="<b>Хим</b>", date="1 июня")])
    text = texts.format_schedule(student)
    assert "&lt;b&gt;Хим&lt;/b&gt;" in text


# --- texts.format_details -----------------------------------------------------


def test_details_shows_criteria_primary_and_recognition_openly():
    student = _student(
        results=[
            _item("сочинение", title="Сочинение",
                  criteria=[_crit("Крит. К1", "Зачёт"), _crit("Крит. К5", "Незачёт")],
                  primary=37,
                  recognition=[_ans("1", "АБВ"), _ans("2", "123")]),
        ]
    )
    text = texts.format_details(student)
    assert "Сочинение" in text
    assert "Первичный балл: <b>37</b>" in text
    assert "Крит. К1: <b>Зачёт</b>" in text
    assert "1: АБВ" in text and "2: 123" in text
    assert "tg-spoiler" not in text  # показываем открыто


def test_details_skips_subjects_without_detail():
    student = _student(results=[_item("физика", title="Физика", score=70)])
    text = texts.format_details(student)
    assert "пока нет" in text


# --- keyboards.student_card_keyboard ------------------------------------------


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_card_shows_data_buttons_only_when_data_present():
    student = _student(
        registrations=[_reg("x", title="X")],
        results=[
            _item("y", title="Y", criteria=[_crit("К1", "2")],
                  blanks=[_blank("Бланк 1", "download.php?f=1")]),
        ],
    )
    cbs = _callbacks(student_card_keyboard(student))
    assert "schedule:abc" in cbs
    assert "details:abc" in cbs
    assert "blanks:abc" in cbs


def test_card_hides_data_buttons_when_absent():
    student = _student(results=[_item("y", title="Y", score=70)])  # без деталей/бланков/регистраций
    cbs = _callbacks(student_card_keyboard(student))
    assert not any(c.startswith(("schedule:", "details:", "blanks:")) for c in cbs)
    # базовые действия на месте
    assert "check:abc" in cbs and "my_students" in cbs


def test_card_keyboard_with_card_button():
    student = _student(results=[_item("y", title="Y", score=70)])
    cbs = _callbacks(student_card_keyboard(student, with_card=True))
    assert "card:abc" in cbs


# --- blanks.blank_filename ----------------------------------------------------


@pytest.mark.parametrize(
    "title,ctype,expected",
    [
        ("Бланк записи лист 1", "application/pdf", "Бланк записи лист 1.pdf"),
        ("Бланк ответов №2", "image/jpeg", "Бланк ответов №2.jpg"),
        ("scan", "image/png; charset=binary", "scan.png"),
        ("weird/name*?", "application/octet-stream", "weird_name__.bin"),
    ],
)
def test_blank_filename(title, ctype, expected):
    assert blank_filename(title, ctype) == expected


# --- BlankDownloader (HTTP) ---------------------------------------------------


def _downloader_with(handler):
    dl = BlankDownloader()
    dl._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return dl


async def test_download_returns_content_and_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    dl = _downloader_with(handler)
    content, ctype = await dl.download("https://www.ege.spb.ru/result/download.php?f=1")
    assert content == b"%PDF-1.4"
    assert ctype == "application/pdf"
    await dl.aclose()


async def test_download_raises_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="gone")

    dl = _downloader_with(handler)
    with pytest.raises(BlankDownloadError):
        await dl.download("https://x/d?f=1")
    await dl.aclose()


async def test_download_raises_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    dl = _downloader_with(handler)
    with pytest.raises(BlankDownloadError):
        await dl.download("https://x/d?f=1")
    await dl.aclose()


async def test_download_rejects_html_error_page():
    # Просроченная ссылка → сайт отдаёт HTML-страницу, а не файл.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>устарело</html>", headers={"content-type": "text/html; charset=windows-1251"})

    dl = _downloader_with(handler)
    with pytest.raises(BlankDownloadError):
        await dl.download("https://x/d?f=1")
    await dl.aclose()


# --- blank_stem / blank_basename ----------------------------------------------


def test_blank_stem_and_basename():
    assert blank_stem("Сочинение", "Бланк 1") == "Сочинение__Бланк 1"
    assert blank_basename("Сочинение", "Бланк 1", "application/pdf") == "Сочинение__Бланк 1.pdf"


# --- ResultsService._download_blanks (запись на диск при проверке) -------------


class _FakeBlanks:
    def __init__(self):
        self.urls: list[str] = []

    async def download(self, url):
        self.urls.append(url)
        return b"%PDF-1.4", "application/pdf"


def _svc(blanks, tmp):
    settings = SimpleNamespace(blanks_dir=str(tmp), download_blanks=True)
    return ResultsService(settings, provider=None, subscriptions=None, blanks=blanks)


def _student_with_blank(path=None):
    blank = SimpleNamespace(title="Бланк 1", url="https://x/d?f=1", path=path)
    item = SimpleNamespace(subject="сочинение", subject_title="Сочинение", blanks=[blank])
    return SimpleNamespace(identity_hash="HASH", results=[item]), blank


async def test_download_blanks_writes_file_and_sets_path(tmp_path):
    blanks = _FakeBlanks()
    student, blank = _student_with_blank()
    await _svc(blanks, tmp_path)._download_blanks(student)

    assert blank.path == "HASH/Сочинение__Бланк 1.pdf"
    assert (tmp_path / "HASH" / "Сочинение__Бланк 1.pdf").read_bytes() == b"%PDF-1.4"
    assert blanks.urls == ["https://x/d?f=1"]


async def test_download_blanks_skips_already_present(tmp_path):
    # Файл с тем же stem (любое расширение) уже есть → не качаем повторно.
    (tmp_path / "HASH").mkdir(parents=True)
    (tmp_path / "HASH" / "Сочинение__Бланк 1.jpg").write_bytes(b"img")
    blanks = _FakeBlanks()
    student, blank = _student_with_blank()
    await _svc(blanks, tmp_path)._download_blanks(student)

    assert blanks.urls == []  # повторно не скачивали
    assert blank.path == "HASH/Сочинение__Бланк 1.jpg"


async def test_download_blanks_noop_without_downloader(tmp_path):
    student, blank = _student_with_blank()
    settings = SimpleNamespace(blanks_dir=str(tmp_path), download_blanks=True)
    svc = ResultsService(settings, provider=None, subscriptions=None, blanks=None)
    await svc._download_blanks(student)
    assert blank.path is None


async def test_download_blanks_survives_disk_error(tmp_path, monkeypatch):
    """Дисковый сбой записи (read-only/full/нет прав) НЕ валит проверку — best-effort.

    Регрессия: OSError из write_bytes раньше выбивал весь плановый цикл (check_all
    ловит только StudentNotFoundError)."""
    from ege_notifier.services import results as results_mod

    def boom(base, name, content):
        raise PermissionError("read-only fs")

    monkeypatch.setattr(results_mod, "_save_blank", boom)
    blanks = _FakeBlanks()
    student, blank = _student_with_blank()

    await _svc(blanks, tmp_path)._download_blanks(student)  # не должно бросить
    assert blank.path is None  # не записался, но проверка жива


def test_details_truncates_on_line_boundary_without_breaking_html():
    """Длинная детализация обрезается ПО СТРОКАМ — HTML-теги остаются сбалансированы.

    Регрессия: посимвольный срез мог прийтись на середину ``<b>``/сущности → Telegram
    «can't parse entities» → сообщение не отрисовывалось вовсе."""
    results = [
        _item(
            f"s{i}",
            title=f"Предмет {i}",
            criteria=[_crit(f"Крит. К{j}", "Зачёт") for j in range(10)],
            primary=37,
            recognition=[_ans(str(k), "АБВГД123") for k in range(30)],
        )
        for i in range(20)
    ]
    text = texts.format_details(_student(results=results))
    assert len(text) <= texts._MSG_LIMIT
    assert text.rstrip().endswith("детали обрезаны.")  # пометка про обрезку
    assert text.count("<b>") == text.count("</b>")  # ни один тег не разорван
