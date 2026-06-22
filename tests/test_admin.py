"""Тесты админ-команд ``/top`` и ``/check`` (без БД и aiogram-рантайма).

Фильтр ``IsAdmin`` проверяем напрямую; в хендлерах ``Student``/фоновый ``_spawn``
подменяются двойниками. Главное, что фиксируем: доступ только у ``admin_id``, ``/top``
строит топ/список предметов, ``/check`` запускает проверку и шлёт сводку, а повторный
``/check`` во время уже идущей проверки отклоняется.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from ege_notifier.bot import texts
from ege_notifier.bot.handlers import admin
from ege_notifier.models import Student


# --- двойники -----------------------------------------------------------------


class FakeMessage:
    def __init__(self, user_id=None):
        self.answers: list[str] = []
        self.from_user = (
            SimpleNamespace(id=user_id) if user_id is not None else None
        )

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)


class FakeNotifier:
    def __init__(self):
        self.admin: list[str] = []
        self.broadcasts: list[tuple[list[int], str]] = []

    async def broadcast(self, telegram_ids, text, reply_markup=None):
        ids = list(telegram_ids)
        self.broadcasts.append((ids, text))
        return len(ids)

    async def notify_admin(self, text):
        self.admin.append(text)
        return True


class FakeResults:
    def __init__(self, updates):
        self._updates = updates

    async def check_all(self):
        return list(self._updates)


SETTINGS = SimpleNamespace(
    admin_ids=[42],
    results_site_url="https://www.ege.spb.ru/result/index.php?mode=ege2026&wave=1",
)


def _item(subject, *, title=None, score=None, value=None):
    return SimpleNamespace(
        subject=subject, subject_title=title or subject, score=score, value=value,
        status=None,
    )


def _student(last_name, results) -> Student:
    return cast(
        Student,
        SimpleNamespace(
            last_name=last_name, passport_masked="●●●● ●●●●74", notes="", results=results
        ),
    )


def _patch_students(monkeypatch, students):
    class _Query:
        async def to_list(self):
            return students

    monkeypatch.setattr(
        admin, "Student", SimpleNamespace(find_all=lambda: _Query())
    )


# --- IsAdmin ------------------------------------------------------------------


async def test_is_admin_allows_only_configured_admin():
    flt = admin.IsAdmin()
    assert await flt(FakeMessage(user_id=42), SETTINGS) is True
    assert await flt(FakeMessage(user_id=7), SETTINGS) is False


async def test_is_admin_false_when_admin_unset():
    flt = admin.IsAdmin()
    no_admin = SimpleNamespace(admin_ids=[])
    assert await flt(FakeMessage(user_id=42), no_admin) is False


async def test_is_admin_allows_any_of_several():
    flt = admin.IsAdmin()
    many = SimpleNamespace(admin_ids=[42, 1268132424])
    assert await flt(FakeMessage(user_id=1268132424), many) is True
    assert await flt(FakeMessage(user_id=99), many) is False


# --- /top ---------------------------------------------------------------------


async def test_top_without_arg_lists_available_subjects(monkeypatch):
    _patch_students(
        monkeypatch,
        [
            _student("Иванов", [_item("русский язык", title="Русский язык", score=80)]),
            _student("Петров", [_item("русский язык", title="Русский язык", score=88)]),
        ],
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args=None))

    assert any("Доступные предметы" in a for a in message.answers)
    assert any("Русский язык" in a for a in message.answers)


async def test_top_with_subject_builds_ranking(monkeypatch):
    _patch_students(
        monkeypatch,
        [
            _student("Петров", [_item("математика профильная", score=70)]),
            _student("Иванов", [_item("математика профильная", score=92)]),
        ],
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args="математика профильная"))

    text = message.answers[-1]
    assert "Топ по предмету" in text
    # Иванов (92) идёт раньше Петрова (70).
    assert text.index("Иванов") < text.index("Петров")
    assert "92" in text and "средний балл" in text


async def test_top_unknown_subject_reports_empty(monkeypatch):
    _patch_students(
        monkeypatch, [_student("Иванов", [_item("физика", score=80)])]
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args="химия"))

    assert any("пока нет результатов" in a for a in message.answers)


async def test_top_combo_builds_sum_ranking(monkeypatch):
    full = lambda name, m, i, r: _student(  # noqa: E731
        name,
        [
            _item("Математика профильная", score=m),
            _item("Информатика", score=i),
            _item("Русский язык", score=r),
        ],
    )
    _patch_students(
        monkeypatch,
        [
            full("Петров", 70, 80, 75),  # сумма 225
            full("Иванов", 92, 88, 90),  # сумма 270
        ],
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args="МИР"))

    text = message.answers[-1]
    assert "Топ по сумме" in text
    assert text.index("Иванов") < text.index("Петров")  # 270 выше 225
    assert "270" in text


async def test_top_combo_skips_students_without_all_subjects(monkeypatch):
    _patch_students(
        monkeypatch,
        [
            _student(
                "Полный",
                [
                    _item("Математика профильная", score=60),
                    _item("Информатика", score=60),
                    _item("Русский язык", score=60),
                ],
            ),
            _student(  # нет информатики — в комбо-топ не попадает
                "Неполный",
                [
                    _item("Математика профильная", score=99),
                    _item("Русский язык", score=99),
                ],
            ),
        ],
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args="МИР"))

    text = message.answers[-1]
    assert "Полный" in text and "Неполный" not in text


async def test_top_combo_empty_when_nobody_has_all(monkeypatch):
    _patch_students(
        monkeypatch, [_student("Иванов", [_item("Математика профильная", score=80)])]
    )
    message = FakeMessage(user_id=42)
    await admin.cmd_top(message, SimpleNamespace(args="МИР"))

    assert any("сразу по всем" in a for a in message.answers)


# --- /check -------------------------------------------------------------------


async def test_check_starts_and_reports_summary(monkeypatch):
    captured = []
    monkeypatch.setattr(admin, "_spawn", lambda coro: captured.append(coro))
    monkeypatch.setattr(admin, "_check_running", False, raising=False)

    notifier = FakeNotifier()
    message = FakeMessage(user_id=42)
    await admin.cmd_check(message, FakeResults([]), notifier, SETTINGS)

    # Сразу отвечаем «запускаю» и ставим фоновую задачу.
    assert any("Запускаю проверку" in a for a in message.answers)
    assert len(captured) == 1

    # Догоняем фоновую задачу — админу уходит сводка, флаг снимается.
    await captured[0]
    assert any("Проверка завершена" in a for a in notifier.admin)
    assert admin._check_running is False


async def test_check_rejects_when_already_running(monkeypatch):
    captured = []
    monkeypatch.setattr(admin, "_spawn", lambda coro: captured.append(coro))
    monkeypatch.setattr(admin, "_check_running", True, raising=False)

    message = FakeMessage(user_id=42)
    await admin.cmd_check(message, FakeResults([]), FakeNotifier(), SETTINGS)

    assert any("уже идёт" in a for a in message.answers)
    assert captured == []  # повторный запуск не ставит задачу


# --- форматирование -----------------------------------------------------------


def test_admin_check_done_plural_and_zero():
    assert "не появилось" in texts.admin_check_done(0)
    assert "1" in texts.admin_check_done(1)


def test_admin_subject_ranking_escapes_and_summarizes():
    from ege_notifier.services.ranking import rank_by_subject

    students = [
        _student("Иван<ов", [_item("физика", title="Физика", score=90)]),
        _student("Петров", [_item("физика", title="Физика", score=70)]),
    ]
    entries = rank_by_subject(students, "физика")
    text = texts.admin_subject_ranking("Физика", entries)
    assert "Иван&lt;ов" in text  # фамилия экранирована
    assert "средний балл: <b>80.0</b>" in text
    assert "макс/мин: <b>90</b>/<b>70</b>" in text


def test_admin_combo_ranking_shows_total_and_breakdown():
    from ege_notifier.services.ranking import parse_subject_combo, rank_by_combo

    slots = parse_subject_combo("МИР")
    students = [
        _student(
            "Иван<ов",
            [
                _item("Математика профильная", score=92),
                _item("Информатика", score=88),
                _item("Русский язык", score=90),
            ],
        ),
        _student(
            "Петров",
            [
                _item("Математика профильная", score=60),
                _item("Информатика", score=70),
                _item("Русский язык", score=65),
            ],
        ),
    ]
    entries = rank_by_combo(students, slots)
    text = texts.admin_combo_ranking(slots, entries)
    assert "Топ по сумме" in text
    assert "Иван&lt;ов" in text  # фамилия экранирована
    assert "<b>270</b>" in text  # сумма Иванова
    assert "М 92 + И 88 + Р 90" in text  # разбивка по предметам
    assert "средняя сумма: <b>232.5</b>" in text  # (270+195)/2
    assert "макс/мин: <b>270</b>/<b>195</b>" in text
