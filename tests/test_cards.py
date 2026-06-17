"""Тесты карточки результатов: чистый билдер тела и HTTP-клиент рендерера.

``build_card_payload`` проверяем офлайн на ученике-двойнике; ``CardRenderer`` — через
``httpx.MockTransport`` (без живого сервиса): фиксируем URL/параметры/тело запроса и
что любые сбои заворачиваются в ``CardRenderError``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from ege_notifier.services.cards import (
    CARD_SLUG,
    CardRenderer,
    CardRenderError,
    build_card_payload,
)


def _item(subject, *, title=None, score=None, value=None):
    return SimpleNamespace(
        subject=subject, subject_title=title, score=score, value=value, status=None
    )


def _student(last_name="Иванов", results=None):
    return SimpleNamespace(last_name=last_name, results=results or [])


# --- build_card_payload -------------------------------------------------------


def test_payload_sums_numeric_scores():
    student = _student(
        results=[
            _item("математика профильная", title="Математика", score=98),
            _item("русский язык", title="Русский язык", score=94),
            _item("информатика", title="Информатика", score=91),
        ]
    )
    slug, body = build_card_payload(student, "ЕГЭ · 2026")

    assert slug == CARD_SLUG
    assert body["exam"] == "ЕГЭ · 2026"
    assert body["name"] == "Иванов"
    assert body["total"] == 283
    assert body["maxTotal"] == 300
    assert body["totalLabel"] == "Сумма баллов"
    assert body["subjects"] == [
        {"name": "Математика", "score": 98},
        {"name": "Русский язык", "score": 94},
        {"name": "Информатика", "score": 91},
    ]


def test_payload_single_subject_uses_result_label():
    student = _student(results=[_item("русский язык", title="Русский язык", score=88)])
    _, body = build_card_payload(student, "ЕГЭ · 2026")

    assert body["total"] == 88
    assert body["maxTotal"] == 100
    assert body["totalLabel"] == "Результат"


def test_payload_excludes_non_numeric_from_total_but_lists_it():
    student = _student(
        results=[
            _item("русский язык", title="Русский язык", score=80),
            _item("итоговое сочинение", title="Сочинение", value="Зачёт"),
        ]
    )
    _, body = build_card_payload(student, "ЕГЭ")

    # «Зачёт» в сумму не входит (один числовой балл), но в списке предметов есть.
    assert body["total"] == 80
    assert body["maxTotal"] == 100
    assert body["totalLabel"] == "Результат"
    assert {"name": "Сочинение", "score": "Зачёт"} in body["subjects"]


def test_payload_all_non_numeric_avoids_zero_over_zero():
    student = _student(
        results=[
            _item("сочинение", title="Сочинение", value="Зачёт"),
            _item("устный", title="Устный", value="Зачёт"),
        ]
    )
    _, body = build_card_payload(student, "ЕГЭ")

    assert body["totalLabel"] == "Предметов"
    assert body["total"] == 2 and body["maxTotal"] == 2


def test_payload_capitalizes_fallback_subject_key():
    # subject_title нет → берём нормализованный ключ и делаем первую букву заглавной.
    student = _student(results=[_item("физика", score=70)])
    _, body = build_card_payload(student, "ЕГЭ")

    assert body["subjects"][0]["name"] == "Физика"


def test_payload_caps_subject_rows():
    student = _student(results=[_item(f"предмет {i}", score=50) for i in range(9)])
    _, body = build_card_payload(student, "ЕГЭ")

    assert len(body["subjects"]) == 7  # _MAX_SUBJECTS — защита от обрезки карточки


# --- CardRenderer (HTTP) ------------------------------------------------------


def _renderer_with(handler, **kwargs):
    """CardRenderer с подменённым httpx-клиентом на MockTransport (без сети)."""
    renderer = CardRenderer("http://card-renderer:3000", **kwargs)
    renderer._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return renderer


async def test_render_posts_payload_and_returns_png():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, content=b"PNGBYTES", headers={"content-type": "image/png"}
        )

    renderer = _renderer_with(handler, scale=2)
    student = _student(results=[_item("физика", title="Физика", score=70)])
    png = await renderer.render_student(student, exam="ЕГЭ · 2026")

    assert png == b"PNGBYTES"
    req = captured[0]
    assert req.method == "POST"
    assert req.url.path == f"/cards/{CARD_SLUG}.png"
    assert req.url.params["scale"] == "2"
    body = json.loads(req.content)
    assert body["name"] == "Иванов" and body["total"] == 70
    await renderer.aclose()


async def test_render_clamps_scale():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    renderer = _renderer_with(handler, scale=99)
    await renderer.render_student(_student(results=[_item("физика", score=70)]))

    assert captured[0].url.params["scale"] == "4"  # клампится в 1..4
    await renderer.aclose()


async def test_render_raises_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    renderer = _renderer_with(handler)
    with pytest.raises(CardRenderError):
        await renderer.render_student(_student(results=[_item("физика", score=70)]))
    await renderer.aclose()


async def test_render_raises_on_non_image_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "nope"}, headers={"content-type": "application/json"}
        )

    renderer = _renderer_with(handler)
    with pytest.raises(CardRenderError):
        await renderer.render_student(_student(results=[_item("физика", score=70)]))
    await renderer.aclose()


async def test_render_raises_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    renderer = _renderer_with(handler)
    with pytest.raises(CardRenderError):
        await renderer.render_student(_student(results=[_item("физика", score=70)]))
    await renderer.aclose()
