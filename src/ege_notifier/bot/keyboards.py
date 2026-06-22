from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from ege_notifier.bot import texts
from ege_notifier.models import Student


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная нижняя клавиатура быстрого доступа (живёт между сообщениями)."""
    kb = ReplyKeyboardBuilder()
    kb.button(text=texts.BTN_MY_STUDENTS)
    kb.button(text=texts.BTN_SECURITY)
    kb.button(text=texts.BTN_ABOUT)
    kb.adjust(1, 2)
    return kb.as_markup(resize_keyboard=True, is_persistent=True)


def back_to_list_keyboard() -> InlineKeyboardMarkup:
    """Одна кнопка «к списку» — для экранов без других действий (напр. ссылка)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К списку", callback_data="my_students")
    return kb.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сохранить", callback_data="confirm_add")
    kb.button(text="✖️ Отмена", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def students_keyboard(students: list[Student]) -> InlineKeyboardMarkup:
    """Список учеников: кнопка на каждого (открывает карточку) + «добавить ученика».

    При большом списке (> 8 учеников) кнопки учеников раскладываются в 2 колонки,
    чтобы список не растягивался на весь экран. Кнопка «добавить» всегда остаётся
    на всю ширину отдельной строкой. Работает и для пустого списка."""
    kb = InlineKeyboardBuilder()
    for st in students:
        kb.button(text=f"👤 {st.last_name}", callback_data=f"student:{st.id}")
    kb.button(text="➕ Добавить ученика", callback_data="add_student")

    cols = 2 if len(students) > 8 else 1
    # Явно задаём размер КАЖДОЙ строки (а не полагаемся на repeat в adjust):
    # полные строки по `cols`, при нечётном числе — остаток отдельной строкой,
    # и «добавить» всегда одной кнопкой в строке.
    full, rem = divmod(len(students), cols)
    sizes = [cols] * full + ([rem] if rem else []) + [1]
    kb.adjust(*sizes)
    return kb.as_markup()


def _has_details(student: Student) -> bool:
    """Есть ли у ученика подробности по предметам (критерии/первичный балл/ответы)."""
    return any(
        r.criteria or r.primary_score is not None or r.recognition
        for r in student.results
    )


def _has_blanks(student: Student) -> bool:
    return any(r.blanks for r in student.results)


def student_card_keyboard(
    student: Student, *, with_card: bool = False
) -> InlineKeyboardMarkup:
    """Карточка ученика: действия (проверить/поделиться/удалить) + просмотр данных.

    Кнопки данных показываем только когда есть что показать: 📅 «Расписание» (есть
    регистрации), 📊 «Детали» (есть критерии/первичный балл/распознанные ответы),
    📄 «Бланки» (есть сканы). ``with_card`` добавляет «🖼 Картинка для сторис» —
    только когда рендерер включён и у ученика есть результаты."""
    sid = student.id
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=f"check:{sid}")
    kb.button(text="🔗 Поделиться", callback_data=f"share:{sid}")

    info_buttons = 0
    if student.registrations:
        kb.button(text="📅 Расписание", callback_data=f"schedule:{sid}")
        info_buttons += 1
    if _has_details(student):
        kb.button(text="📊 Детали", callback_data=f"details:{sid}")
        info_buttons += 1
    if _has_blanks(student):
        kb.button(text="📄 Бланки", callback_data=f"blanks:{sid}")
        info_buttons += 1

    if with_card:
        kb.button(text="🖼 Картинка для сторис", callback_data=f"card:{sid}")
    kb.button(text="🗑 Удалить", callback_data=f"del:{sid}")
    kb.button(text="⬅️ К списку", callback_data="my_students")

    # Раскладка: «обновить»/«поделиться» в ряд; кнопки данных по 2 в ряд; картинка,
    # удалить, «к списку» — каждая своей строкой.
    full, rem = divmod(info_buttons, 2)
    info_rows = [2] * full + ([rem] if rem else [])
    kb.adjust(2, *info_rows, *([1] * (3 if with_card else 2)))
    return kb.as_markup()


def back_to_card_keyboard(student_id: object) -> InlineKeyboardMarkup:
    """Возврат из экрана данных (расписание/детали) обратно в карточку ученика."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"student:{student_id}")
    return kb.as_markup()


def results_link_keyboard(url: str | None) -> InlineKeyboardMarkup | None:
    """Кнопка-ссылка «перейти на сайт» под уведомлением о новых результатах.

    Возвращает ``None``, если URL не задан (тогда сообщение уйдёт без клавиатуры)."""
    if not url:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Перейти на сайт", url=url)
    return kb.as_markup()


def results_card_keyboard(url: str | None) -> InlineKeyboardMarkup:
    """Клавиатура под результатами в карточке инициатора: сайт + возврат к списку."""
    kb = InlineKeyboardBuilder()
    if url:
        kb.button(text="🌐 Перейти на сайт", url=url)
    kb.button(text="⬅️ К списку", callback_data="my_students")
    kb.adjust(1)
    return kb.as_markup()
