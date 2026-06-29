"""Тесты канонизации ключа предмета (``normalize_subject``).

Ключ предмета сравнивается между проверками, поэтому критичны два свойства:
синонимичные формулировки сводятся к одному ключу (нет ложных «новых результатов»),
а сам канонический ключ — неподвижная точка (повторная нормализация не плодит дубли,
старые снимки лениво переезжают на канонический ключ без расхождений)."""

from __future__ import annotations

from ege_notifier.utils import (
    _CANONICAL_BY_ALIAS,
    _SUBJECT_ALIASES,
    normalize_subject,
)


def test_punctuation_and_case_variants_merge():
    assert normalize_subject("Математика (профильная)") == normalize_subject(
        "Математика профильная"
    )
    assert normalize_subject("Русский язык") == "русский язык"


def test_synonyms_collapse_to_one_subject():
    # Разные формулировки одного предмета → один ключ.
    assert normalize_subject("Информатика и ИКТ") == normalize_subject("Информатика")
    assert normalize_subject("Информатика (КЕГЭ)") == normalize_subject("Информатика")
    assert normalize_subject("Математика профильный уровень") == normalize_subject(
        "Математика (профильная)"
    )
    assert normalize_subject("Английский") == normalize_subject(
        "Иностранный язык (английский)"
    )
    assert normalize_subject("Обществознание") == normalize_subject("Общество")


def test_base_and_profile_math_stay_distinct():
    # Базовая и профильная — разные предметы, сливать нельзя.
    assert normalize_subject("Математика базовая") != normalize_subject(
        "Математика профильная"
    )


def test_unknown_subject_passes_through_cleaned():
    # Незнакомый предмет всё равно получает стабильный очищенный ключ.
    assert normalize_subject("Астрономия!!") == "астрономия"


def test_normalize_is_idempotent():
    samples = [
        "Информатика и ИКТ",
        "Математика (профильная)",
        "Английский",
        "Русский язык",
        "Астрономия",
    ]
    for s in samples:
        once = normalize_subject(s)
        assert normalize_subject(once) == once, s


def test_canonical_keys_are_fixed_points():
    # Каждый канонический ключ нормализуется в себя — иначе сохранённый ключ «уехал»
    # бы при следующей проверке и дал ложный дубль.
    for canonical in _SUBJECT_ALIASES:
        assert normalize_subject(canonical) == canonical


def test_aliases_disjoint_from_canonicals_and_unique():
    # Канонический ключ не должен быть ещё и чьей-то альтернативой (иначе цепочка
    # переименований ломает неподвижность), а альтернатива — принадлежать двум
    # предметам сразу.
    canonicals = set(_SUBJECT_ALIASES)
    assert canonicals.isdisjoint(_CANONICAL_BY_ALIAS)
    all_aliases = [a for aliases in _SUBJECT_ALIASES.values() for a in aliases]
    assert len(all_aliases) == len(set(all_aliases))
