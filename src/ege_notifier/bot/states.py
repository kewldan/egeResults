from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddStudent(StatesGroup):
    """Шаги диалога добавления ученика."""

    last_name = State()
    passport_series = State()
    passport_number = State()
    confirm = State()
