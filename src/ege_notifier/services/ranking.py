from __future__ import annotations

from dataclasses import dataclass

from ege_notifier.models import Student
from ege_notifier.utils import normalize_subject


@dataclass(slots=True)
class RankEntry:
    """Одна строка топа по предмету (балл одного ученика)."""

    last_name: str
    passport_masked: str
    notes: str
    subject_title: str | None
    score: int | None
    value: str | None
    status: str | None


@dataclass(slots=True)
class SubjectCount:
    """Предмет и сколько учеников имеют по нему результат (для подсказки /top)."""

    subject: str  # нормализованный ключ
    title: str  # отображаемое название
    count: int


@dataclass(slots=True)
class SubjectSlot:
    """Один предмет в комбо-топе (`/top МИР`): код, название, подходящие ключи."""

    code: str  # буквенный код, как разобран из ввода («М», «И», «Р», «ИЯ»)
    title: str  # человекочитаемое название («Математика (профильная)»)
    keys: tuple[str, ...]  # нормализованные ключи, любой из которых засчитывается


@dataclass(slots=True)
class ComboRankEntry:
    """Строка комбо-топа: суммарный балл ученика по набору предметов."""

    last_name: str
    passport_masked: str
    notes: str
    scores: list[int]  # числовой балл по каждому слоту, в порядке combo
    total: int


# Буквенные коды предметов для комбо-топа по сумме баллов (`/top МИР`). Опираются на
# сокращения из официального расписания ЕГЭ Рособрнадзора (Р, М(б)/М(п), Ф, Х, Б, Г,
# О, Л, ИКТ, ИЯ), но с двумя осознанными отступлениями ради привычных IT-аббревиатур:
#   • «И» — ИНФОРМАТИКА (а не история): комбинация «МИР» = Математика+Информатика+
#     Русский. История доступна как «ИСТ».
#   • «М» по умолчанию — ПРОФИЛЬНАЯ математика (база — «МБ»): профиль входит в комбо.
# Значение = (отображаемое название, кортеж нормализованных ключей). Ключи обязаны
# совпадать с каноническими ключами utils.normalize_subject. Для «ИЯ» подходит любой
# иностранный язык — берём лучший балл ученика среди них.
_FOREIGN_LANGUAGE_KEYS = (
    "английский язык",
    "немецкий язык",
    "французский язык",
    "испанский язык",
    "китайский язык",
)
_SUBJECT_CODES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Р": ("Русский язык", ("русский язык",)),
    "М": ("Математика (профильная)", ("математика профильная",)),
    "МП": ("Математика (профильная)", ("математика профильная",)),
    "МБ": ("Математика (базовая)", ("математика базовая",)),
    "Ф": ("Физика", ("физика",)),
    "Х": ("Химия", ("химия",)),
    "Б": ("Биология", ("биология",)),
    "Г": ("География", ("география",)),
    "О": ("Обществознание", ("обществознание",)),
    "Л": ("Литература", ("литература",)),
    "И": ("Информатика", ("информатика",)),
    "ИНФ": ("Информатика", ("информатика",)),
    "ИКТ": ("Информатика", ("информатика",)),
    "ИСТ": ("История", ("история",)),
    "ИЯ": ("Иностранный язык", _FOREIGN_LANGUAGE_KEYS),
}
_MAX_CODE_LEN = max(len(code) for code in _SUBJECT_CODES)


def parse_subject_combo(token: str) -> list[SubjectSlot] | None:
    """Жадно разбирает строку буквенных кодов в набор слотов («МИР» → М, И, Р).

    Регистр и пробелы игнорируются; на каждом шаге берётся самый ДЛИННЫЙ код,
    подходящий с текущей позиции (longest-match), чтобы многобуквенные коды
    («ИКТ», «ИСТ», «ИЯ») выигрывали у одиночных. Возвращает ``None``, если строку
    не удалось разобрать целиком (встретилась неизвестная буква) — вызывающий тогда
    трактует ввод как название одиночного предмета, а не комбинацию."""
    s = "".join(token.upper().split())
    if not s:
        return None
    slots: list[SubjectSlot] = []
    i = 0
    while i < len(s):
        code = None
        for length in range(min(_MAX_CODE_LEN, len(s) - i), 0, -1):
            candidate = s[i : i + length]
            if candidate in _SUBJECT_CODES:
                code = candidate
                break
        if code is None:
            return None
        title, keys = _SUBJECT_CODES[code]
        slots.append(SubjectSlot(code=code, title=title, keys=keys))
        i += len(code)
    return slots


def is_combo_query(token: str) -> bool:
    """Похож ли ввод на комбинацию кодов (``/top МИР``), а не на название предмета.

    Комбо вводят ЗАГЛАВНЫМ акронимом из букв (МИР, МИФ, ФИХ), а названия предметов —
    обычным текстом со строчными буквами («математика профильная»). Поэтому требуем:
    только буквы, ни одной строчной, и строка разбирается целиком минимум в ДВА кода.
    Это разводит два пространства имён без ложных срабатываний на словах вроде
    «химия» (которая заглавными случайно разобралась бы в Х+И+М+ИЯ)."""
    stripped = "".join(token.split())
    if not stripped or not stripped.isalpha() or any(c.islower() for c in stripped):
        return False
    slots = parse_subject_combo(stripped)
    return slots is not None and len(slots) >= 2


def _best_score_for(student: Student, keys: tuple[str, ...]) -> int | None:
    """Лучший числовой балл ученика среди результатов с ключом из ``keys``.

    Для обычного слота ``keys`` — один ключ. Для «ИЯ» их несколько (любой
    иностранный язык) — берём максимум, если ученик сдавал больше одного."""
    best: int | None = None
    for item in student.results:
        if item.score is None:
            continue
        if normalize_subject(item.subject) in keys and (best is None or item.score > best):
            best = item.score
    return best


def rank_by_combo(
    students: list[Student], slots: list[SubjectSlot], notes_query: str | None = None
) -> list[ComboRankEntry]:
    """Топ по СУММЕ баллов за набор предметов (по убыванию суммы).

    Чистая функция. В топ попадают ТОЛЬКО ученики, у которых есть числовой балл по
    КАЖДОМУ предмету набора (получили результаты по всем) — иначе сумму не посчитать
    и сравнение было бы нечестным; такие ученики отбрасываются целиком. Сопоставление
    предмета идёт через ``normalize_subject`` (как в ``rank_by_subject``). ``notes_query``
    (если задан) сужает выборку по подстроке в ``Student.notes`` без учёта регистра."""
    needle = (notes_query or "").strip().casefold()
    entries: list[ComboRankEntry] = []
    for st in students:
        if needle and needle not in (st.notes or "").casefold():
            continue
        scores: list[int] = []
        for slot in slots:
            score = _best_score_for(st, slot.keys)
            if score is None:
                break  # нет результата хотя бы по одному предмету — ученик не в топе
            scores.append(score)
        if len(scores) != len(slots):
            continue
        entries.append(
            ComboRankEntry(
                last_name=st.last_name,
                passport_masked=st.passport_masked,
                notes=st.notes,
                scores=scores,
                total=sum(scores),
            )
        )
    entries.sort(key=lambda e: (-e.total, e.last_name.lower()))
    return entries


def _result_for(student: Student, subject_key: str):
    """Результат ученика по нормализованному ключу предмета, либо ``None``."""
    for item in student.results:
        if normalize_subject(item.subject) == subject_key:
            return item
    return None


def rank_by_subject(
    students: list[Student], subject_key: str, notes_query: str | None = None
) -> list[RankEntry]:
    """Сортирует учеников по баллу за предмет (по убыванию).

    Чистая функция (без I/O): принимает уже загруженных учеников и нормализованный
    ключ предмета. Сопоставление идёт через ``normalize_subject`` на обеих сторонах,
    поэтому синонимы («Информатика и ИКТ» / «Информатика») и формулировки с разной
    пунктуацией находят один и тот же предмет. Числовые баллы идут первыми по
    убыванию; результаты без балла («Зачёт») — в конце, по алфавиту фамилий.

    ``notes_query`` (если задан) оставляет только учеников, в чьей заметке
    (``Student.notes``) встречается подстрока — без учёта регистра. Удобно сузить
    топ до конкретной группы/потока, помеченной в заметке.
    """
    needle = (notes_query or "").strip().casefold()
    entries: list[RankEntry] = []
    for st in students:
        if needle and needle not in (st.notes or "").casefold():
            continue
        item = _result_for(st, subject_key)
        if item is None:
            continue
        entries.append(
            RankEntry(
                last_name=st.last_name,
                passport_masked=st.passport_masked,
                notes=st.notes,
                subject_title=item.subject_title,
                score=item.score,
                value=item.value,
                status=item.status,
            )
        )
    entries.sort(
        key=lambda e: (e.score is None, -(e.score or 0), e.last_name.lower())
    )
    return entries


def available_subjects(students: list[Student]) -> list[SubjectCount]:
    """Предметы, по которым у учеников есть результаты — по убыванию числа учеников.

    Подсказка для администратора: какой ключ передать в ``/top``. Заголовок берётся
    от первого встретившегося ``subject_title`` для ключа (как показывает сайт)."""
    counts: dict[str, int] = {}
    titles: dict[str, str] = {}
    for st in students:
        seen: set[str] = set()
        for item in st.results:
            key = normalize_subject(item.subject)
            if key in seen:
                continue  # один ученик считается по предмету один раз
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            titles.setdefault(key, item.subject_title or item.subject)
    result = [
        SubjectCount(subject=key, title=titles[key], count=count)
        for key, count in counts.items()
    ]
    result.sort(key=lambda s: (-s.count, s.title.lower()))
    return result


def average_score(entries: list[RankEntry]) -> float | None:
    """Средний числовой балл среди записей (``None``, если числовых баллов нет)."""
    scores = [e.score for e in entries if e.score is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)
