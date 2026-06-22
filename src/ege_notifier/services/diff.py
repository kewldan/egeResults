from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ege_notifier.models.student import BlankImage, Criterion, ResultItem, TaskAnswer
from ege_notifier.providers.base import FetchedResult
from ege_notifier.utils import normalize_subject, utcnow


class ChangeType(str, Enum):
    NEW = "new"  # появился результат по предмету, которого раньше не было
    UPDATED = "updated"  # изменилось значение/балл или статус


@dataclass(slots=True)
class ResultChange:
    type: ChangeType
    subject: str
    subject_title: str | None
    old_value: str | None
    new_value: str | None
    old_score: int | None
    new_score: int | None
    old_status: str | None
    new_status: str | None


def _is_changed(old: ResultItem, fetched: FetchedResult) -> bool:
    """Считается ли результат изменившимся (→ уведомление).

    ВАЖНО: сравниваем ТОЛЬКО ``value``/``score``/``status``. Детализация
    (критерии, первичные баллы, распознанные ответы, бланки, регистрации) сюда НЕ
    входит специально — её появление после обновления парсера не должно вызывать
    повторных уведомлений у уже отслеживаемых учеников."""
    value_changed = fetched.value is not None and fetched.value != old.value
    score_changed = fetched.score is not None and fetched.score != old.score
    status_changed = fetched.status is not None and fetched.status != old.status
    return value_changed or score_changed or status_changed


def _detail_kwargs(
    fetched: FetchedResult, old: ResultItem | None, *, changed: bool = False
) -> dict:
    """Поля детализации для ``ResultItem``: свежие из ответа, иначе — прежние.

    Детализацию сохраняем всегда (свежая важнее), но если источник её не отдал
    (пустые списки / ``None``) — не затираем уже известную. На diff не влияет:
    ``_is_changed`` её не смотрит, поэтому обновление детали уведомлений не шлёт.

    ``changed=True`` (изменились value/score/status) сбрасывает «прежнюю» деталь: она
    относилась к старому баллу, и держать её рядом с новым нельзя — пусть заполнится
    свежей на этой же / следующей проверке.

    ``BlankImage.path`` уже скачанного скана переносим со старого по совпадению
    заголовка: ссылка ``download.php`` одноразовая и в ответе меняется, а файл на
    диске остаётся — иначе пересборка снимка «теряла» бы путь до скачанного бланка."""
    if changed:
        old = None
    old_blank_path = {b.title: b.path for b in old.blanks} if old else {}
    criteria = [Criterion(name=c.name, value=c.value) for c in fetched.criteria]
    recognition = [TaskAnswer(task=t.task, answer=t.answer) for t in fetched.recognition]
    blanks = [
        BlankImage(title=b.title, url=b.url, path=old_blank_path.get(b.title))
        for b in fetched.blanks
    ]
    return {
        "criteria": criteria or (old.criteria if old else []),
        "primary_score": (
            fetched.primary_score
            if fetched.primary_score is not None
            else (old.primary_score if old else None)
        ),
        "recognition": recognition or (old.recognition if old else []),
        "blanks": blanks or (old.blanks if old else []),
    }


def diff_results(
    existing: list[ResultItem], fetched: list[FetchedResult]
) -> list[ResultChange]:
    """Чистая функция: сравнивает известные результаты с полученными от источника
    и возвращает список изменений (новые предметы и обновлённые значения/статусы).

    Сопоставление идёт по нормализованному ключу предмета (на обеих сторонах),
    поэтому смена формулировки на сайте или изменение правил нормализации не
    рвут связь со старым снимком (без ложных «новых результатов»)."""
    by_subject = {normalize_subject(item.subject): item for item in existing}
    changes: list[ResultChange] = []
    for f in fetched:
        old = by_subject.get(normalize_subject(f.subject))
        if old is None:
            changes.append(
                ResultChange(
                    type=ChangeType.NEW,
                    subject=f.subject,
                    subject_title=f.subject_title,
                    old_value=None,
                    new_value=f.value,
                    old_score=None,
                    new_score=f.score,
                    old_status=None,
                    new_status=f.status,
                )
            )
        elif _is_changed(old, f):
            changes.append(
                ResultChange(
                    type=ChangeType.UPDATED,
                    subject=f.subject,
                    subject_title=f.subject_title or old.subject_title,
                    old_value=old.value,
                    new_value=f.value if f.value is not None else old.value,
                    old_score=old.score,
                    new_score=f.score if f.score is not None else old.score,
                    old_status=old.status,
                    new_status=f.status if f.status is not None else old.status,
                )
            )
    return changes


def merge_results(
    existing: list[ResultItem], fetched: list[FetchedResult]
) -> list[ResultItem]:
    """Возвращает новый список результатов: обновляет существующие предметы,
    добавляет новые и сохраняет ранее известные, которых нет в текущем ответе.
    ``first_seen_at`` сохраняется, ``updated_at`` обновляется при изменении.

    Сопоставление и ключ хранения — нормализованные (см. ``diff_results``):
    предметы, сохранённые под старым ключом, лениво переезжают на канонический,
    поэтому смена правил нормализации не плодит дубли."""
    by_subject = {normalize_subject(item.subject): item for item in existing}
    now = utcnow()
    merged: list[ResultItem] = []
    seen: set[str] = set()

    for f in fetched:
        key = normalize_subject(f.subject)
        seen.add(key)
        old = by_subject.get(key)
        if old is None:
            merged.append(
                ResultItem(
                    subject=key,
                    subject_title=f.subject_title,
                    score=f.score,
                    value=f.value,
                    status=f.status,
                    exam_date=f.exam_date,
                    raw=f.raw,
                    first_seen_at=now,
                    updated_at=now,
                    **_detail_kwargs(f, None),
                )
            )
        else:
            changed = _is_changed(old, f)
            merged.append(
                ResultItem(
                    subject=key,
                    subject_title=f.subject_title or old.subject_title,
                    score=f.score if f.score is not None else old.score,
                    value=f.value if f.value is not None else old.value,
                    status=f.status if f.status is not None else old.status,
                    exam_date=f.exam_date or old.exam_date,
                    raw=f.raw or old.raw,
                    first_seen_at=old.first_seen_at,
                    # updated_at двигается только при изменении value/score/status —
                    # тихое обновление детали его не трогает (нет «нового результата»).
                    updated_at=now if changed else old.updated_at,
                    **_detail_kwargs(f, old, changed=changed),
                )
            )

    # Сохраняем ранее известные предметы, которых не было в этом ответе.
    for item in existing:
        if normalize_subject(item.subject) not in seen:
            merged.append(item)
    return merged
