from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ege_notifier.models import Student


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить ученика", callback_data="add_student")
    kb.button(text="📋 Мои ученики", callback_data="my_students")
    kb.adjust(1)
    return kb.as_markup()


def confirm_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сохранить", callback_data="confirm_add")
    kb.button(text="✖️ Отмена", callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()


def students_keyboard(students: list[Student]) -> InlineKeyboardMarkup:
    """Список учеников: по кнопке на ученика, открывающей его карточку с действиями."""
    kb = InlineKeyboardBuilder()
    for st in students:
        kb.button(text=f"👤 {st.last_name}", callback_data=f"student:{st.id}")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def student_card_keyboard(student_id: object) -> InlineKeyboardMarkup:
    """Карточка ученика: действия над ним (проверить/поделиться/удалить)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=f"check:{student_id}")
    kb.button(text="🔗 Поделиться", callback_data=f"share:{student_id}")
    kb.button(text="🗑 Удалить", callback_data=f"del:{student_id}")
    kb.button(text="⬅️ К списку", callback_data="my_students")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def results_link_keyboard(url: str | None) -> InlineKeyboardMarkup | None:
    """Кнопка-ссылка «перейти на сайт» под уведомлением о новых результатах.

    Возвращает ``None``, если URL не задан (тогда сообщение уйдёт без клавиатуры)."""
    if not url:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="🌐 Перейти на сайт", url=url)
    return kb.as_markup()
