from __future__ import annotations

import logging

import httpx

from ege_notifier.models import Student

logger = logging.getLogger(__name__)

# Карточку шлём «сводную» (см. render-takumi/src/cards.tsx): сумма баллов + список
# предметов. Она корректно рисует и одного предмета, и нескольких — в отличие от
# «одной дисциплины», которой нужны порог/максимум, а их в модели нет.
CARD_SLUG = "summary"

# Максимум строк-предметов на карточке: высота фиксированная (820px), лишние строки
# обрезались бы overflow:hidden. У ЕГЭ-выпускника предметов столько и не бывает —
# подстраховка от уродливой обрезки, а не реальный лимит.
_MAX_SUBJECTS = 7


class CardRenderError(Exception):
    """Рендерер недоступен/вернул ошибку или не-картинку — карточку не построить."""


def _display(value: str | None, score: int | None) -> str:
    """То же правило отображения, что в текстах: значение → балл → прочерк."""
    if value:
        return value
    if score is not None:
        return str(score)
    return "—"


def _subject_title(result) -> str:
    """Название предмета как на сайте (``subject_title``), иначе нормализованный ключ
    с заглавной буквы («русский язык» → «Русский язык»)."""
    title = result.subject_title or result.subject
    return title[:1].upper() + title[1:] if title else title


def build_card_payload(student: Student, exam: str) -> tuple[str, dict]:
    """Строит (slug, JSON-тело) для POST-рендера карточки результатов ученика.

    Чистая функция (без I/O) — тестируется офлайн. Сумма и максимум считаются
    только по числовым баллам; «Зачёт» и прочие нечисловые результаты попадают в
    список предметов как текст, но в сумму не входят. Имя на карточке — только
    фамилия (другого в модели нет); паспорт в карточку НЕ попадает.
    """
    subjects: list[dict] = []
    numeric: list[int] = []
    for item in student.results[:_MAX_SUBJECTS]:
        if item.score is not None:
            numeric.append(item.score)
            score: int | str = item.score
        else:
            score = _display(item.value, item.score)
        subjects.append({"name": _subject_title(item), "score": score})

    if numeric:
        total = sum(numeric)
        max_total = 100 * len(numeric)
        total_label = "Результат" if len(numeric) == 1 else "Сумма баллов"
    else:
        # Все результаты нечисловые (редкий случай): показываем число предметов,
        # чтобы не выводить бессмысленное «0 / 0».
        total = len(subjects)
        max_total = len(subjects)
        total_label = "Предметов"

    body = {
        "exam": exam,
        "totalLabel": total_label,
        "total": total,
        "maxTotal": max_total,
        "subjects": subjects,
        "name": student.last_name,
    }
    return CARD_SLUG, body


class CardRenderer:
    """HTTP-клиент к сервису render-takumi: отдаёт PNG-карточку результатов ученика.

    Клиент httpx создаётся лениво и переиспользуется (keep-alive); закрывается в
    ``aclose()`` на shutdown. Все сетевые/HTTP-сбои заворачиваются в
    ``CardRenderError``, чтобы хендлер показал понятную ошибку, а не упал.
    """

    def __init__(self, base_url: str, *, scale: int = 2, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._scale = max(1, min(4, scale))  # рендерер всё равно клампит 1..4
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def render_student(self, student: Student, *, exam: str = "ЕГЭ") -> bytes:
        """Возвращает PNG-карточку (bytes). Бросает ``CardRenderError`` при сбое."""
        slug, body = build_card_payload(student, exam)
        url = f"{self._base_url}/cards/{slug}.png"
        try:
            response = await self._get_client().post(
                url, params={"scale": self._scale}, json=body
            )
        except httpx.HTTPError as exc:
            raise CardRenderError(f"рендерер недоступен: {exc}") from exc

        if response.status_code != 200:
            snippet = response.text[:200]
            raise CardRenderError(
                f"рендерер вернул HTTP {response.status_code}: {snippet}"
            )
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise CardRenderError(f"неожиданный content-type: {content_type!r}")
        return response.content

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
