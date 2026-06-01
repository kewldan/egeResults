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
    kb = InlineKeyboardBuilder()
    for st in students:
        kb.button(text=f"🔄 {st.last_name}", callback_data=f"check:{st.id}")
        kb.button(text="🗑", callback_data=f"del:{st.id}")
    kb.button(text="⬅️ Меню", callback_data="menu")
    kb.adjust(2)
    return kb.as_markup()
