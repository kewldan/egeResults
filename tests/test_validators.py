from __future__ import annotations

from ege_notifier.bot.validators import (
    validate_last_name,
    validate_number,
    validate_series,
)


def test_simple_last_name_capitalized():
    assert validate_last_name("тенишев") == "Тенишев"
    assert validate_last_name("ТЕНИШЕВ") == "Тенишев"


def test_double_last_name_keeps_space():
    # Двойную фамилию нельзя склеивать дефисом — сайт сверяет фамилию точно.
    assert validate_last_name("салтыков щедрин") == "Салтыков Щедрин"


def test_hyphenated_last_name_keeps_hyphen():
    assert validate_last_name("салтыков-щедрин") == "Салтыков-Щедрин"


def test_extra_whitespace_collapsed():
    assert validate_last_name("  салтыков   щедрин  ") == "Салтыков Щедрин"


def test_latin_rejected():
    assert validate_last_name("Ivanov") is None
    assert validate_last_name("") is None


def test_series_and_number():
    assert validate_series("40 22") == "4022"
    assert validate_series("123") is None
    assert validate_number("083074") == "083074"
    assert validate_number("12345") is None
