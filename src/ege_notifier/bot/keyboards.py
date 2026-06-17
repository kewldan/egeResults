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


def student_card_keyboard(
    student_id: object, *, with_card: bool = False
) -> InlineKeyboardMarkup:
    """Карточка ученика: действия над ним (проверить/поделиться/удалить).

    ``with_card`` добавляет кнопку «🖼 Картинка для сторис» — показываем её только
    когда рендерер включён и у ученика уже есть результаты (иначе рисовать нечего)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=f"check:{student_id}")
    kb.button(text="🔗 Поделиться", callback_data=f"share:{student_id}")
    if with_card:
        kb.button(text="🖼 Картинка для сторис", callback_data=f"card:{student_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del:{student_id}")
    kb.button(text="⬅️ К списку", callback_data="my_students")
    # Раскладка: «обновить»/«поделиться» в ряд, затем картинка (если есть), удалить,
    # «к списку» — каждая своей строкой.
    kb.adjust(2, *([1] * (3 if with_card else 2)))
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
