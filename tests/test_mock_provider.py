"""Тесты mock-источника: три состояния (не найден / нет результатов / есть баллы)."""

from __future__ import annotations

import json

import pytest

from ege_notifier.providers.base import StudentNotFoundError, StudentQuery
from ege_notifier.providers.mock import MockResultsProvider


def _write(tmp_path, data: dict) -> str:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _query(number: str = "654321") -> StudentQuery:
    return StudentQuery(last_name="Иванов", passport_series="4022", passport_number=number)


async def test_absent_passport_raises_not_found(tmp_path):
    provider = MockResultsProvider(_write(tmp_path, {"111111": []}))
    with pytest.raises(StudentNotFoundError):
        await provider.fetch(_query("654321"))


async def test_present_but_empty_returns_no_results(tmp_path):
    provider = MockResultsProvider(_write(tmp_path, {"654321": []}))
    assert await provider.fetch(_query("654321")) == []


async def test_present_with_results(tmp_path):
    provider = MockResultsProvider(
        _write(tmp_path, {"654321": [{"subject": "русский язык", "score": 88}]})
    )
    results = await provider.fetch(_query("654321"))
    assert len(results) == 1
    assert results[0].score == 88


async def test_missing_file_returns_empty(tmp_path):
    # Файла нет вовсе — не считаем это «ученик не найден» (это ошибка конфигурации).
    provider = MockResultsProvider(str(tmp_path / "nope.json"))
    assert await provider.fetch(_query()) == []
