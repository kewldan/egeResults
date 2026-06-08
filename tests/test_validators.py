from __future__ import annotations

from ege_notifier.bot.validators import (
    normalize_surname,
    validate_last_name,
    validate_number,
    validate_series,
)


def test_simple_last_name_capitalized():
    assert validate_last_name("тенишев") == "Тенишев"
    assert validate_last_name("ТЕНИШЕВ") == "Тенишев"


def test_space_separated_rejected():
    # Двойную фамилию вводят дефисом; пробел = ошибка. Раньше так в фамилию
    # попадало имя («Иванов Пётр»), и ege.spb.ru отвечал «участник не найден».
    assert validate_last_name("салтыков щедрин") is None
    assert validate_last_name("Иванов Пётр") is None


def test_hyphenated_last_name_keeps_hyphen():
    assert validate_last_name("салтыков-щедрин") == "Салтыков-Щедрин"


def test_edge_whitespace_stripped():
    assert validate_last_name("  тенишев  ") == "Тенишев"


def test_latin_rejected():
    assert validate_last_name("Ivanov") is None
    assert validate_last_name("") is None


def test_normalize_surname_takes_first_word():
    # Миграция: «насованные» в фамилию ФИО — берём только саму фамилию.
    assert normalize_surname("Иванов Пётр Сергеевич") == "Иванов"
    assert normalize_surname("иванов пётр") == "Иванов"
    assert normalize_surname("салтыков-щедрин") == "Салтыков-Щедрин"
    assert normalize_surname("") is None
    assert normalize_surname("   ") is None


def test_series_and_number():
    assert validate_series("40 22") == "4022"
    assert validate_series("123") is None
    assert validate_number("083074") == "083074"
    assert validate_number("12345") is None
