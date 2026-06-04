"""Тесты маршрутизации уведомлений в хендлерах (без БД и aiogram-рантайма).

Сервисы и объекты Telegram подменяются лёгкими двойниками, а ссылки на
``Message``/``Student`` в модулях хендлеров — monkeypatch'атся, чтобы проверки
``isinstance`` и ``Student.get`` работали без реального окружения.

Главное, что фиксируем: ручная проверка (при подписке и по кнопке «проверить
сейчас») рассылает найденные изменения ВСЕМ подписчикам ученика, а не только
инициатору — иначе остальные пропустят результат (плановый diff его уже не увидит).
"""

from __future__ import annotations

from types import SimpleNamespace

from beanie import PydanticObjectId

from ege_notifier.bot.handlers import add_student, my_students
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.diff import ChangeType, ResultChange


# --- двойники Telegram --------------------------------------------------------


class FakeMessage:
    def __init__(self):
        self.answers: list[str] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)


class FakeCallback:
    def __init__(self, message, user_id, data=None):
        self.message = message
        self.from_user = SimpleNamespace(id=user_id, username=None, full_name=None)
        self.data = data
        self.answered: list[str | None] = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append(text)


class FakeState:
    def __init__(self, data):
        self._data = dict(data)

    async def get_data(self):
        return self._data

    async def clear(self):
        self._data = {}


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.broadcasts: list[tuple[list[int], str]] = []

    async def send(self, telegram_id, text):
        self.sent.append((telegram_id, text))
        return True

    async def broadcast(self, telegram_ids, text):
        ids = list(telegram_ids)
        self.broadcasts.append((ids, text))
        return len(ids)


# --- двойники сервисов --------------------------------------------------------


class FakeSubscriptions:
    def __init__(self, student, created, subscribers):
        self._student = student
        self._created = created
        self._subscribers = subscribers

    async def subscribe(self, telegram_id, last_name, series, number):
        return self._student, self._created

    async def subscribers_for(self, student_id):
        return list(self._subscribers)


class FakeResults:
    def __init__(self, changes):
        self._changes = changes

    async def check_student(self, student):
        return self._changes


class FakeResultsNotFound:
    """check_student бросает StudentNotFoundError — как при опечатке в данных."""

    async def check_student(self, student):
        raise StudentNotFoundError("not found")


def _student(results=None):
    sid = PydanticObjectId()
    return SimpleNamespace(
        id=sid,
        label="Иванов · ●●●● ●●●●74",
        last_name="Иванов",
        passport_masked="●●●● ●●●●74",
        results=results or [],
    )


def _result_item():
    return SimpleNamespace(
        subject="русский язык",
        subject_title="Русский язык",
        value="88",
        score=88,
        status="Действующий результат",
    )


def _new_change():
    return ResultChange(
        type=ChangeType.NEW,
        subject="математика",
        subject_title="Математика",
        old_value=None,
        new_value=None,
        old_score=None,
        new_score=70,
        old_status=None,
        new_status="готов",
    )


# --- confirm_add --------------------------------------------------------------


async def test_confirm_add_sends_snapshot_to_new_subscriber(monkeypatch):
    monkeypatch.setattr(add_student, "Message", FakeMessage)
    student = _student(results=[_result_item()])  # уже отслеживается, баллы есть
    subs = FakeSubscriptions(student, created=True, subscribers=[2, 7])
    notifier = FakeNotifier()
    callback = FakeCallback(FakeMessage(), user_id=7)
    state = FakeState({"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"})

    await add_student.confirm_add(callback, state, subs, FakeResults([]), notifier)

    # Новому подписчику ушёл снимок текущих результатов; рассылки нет (изменений нет).
    assert [tid for tid, _ in notifier.sent] == [7]
    assert "Русский язык" in notifier.sent[0][1]
    assert notifier.broadcasts == []


async def test_confirm_add_warns_when_student_not_found(monkeypatch):
    monkeypatch.setattr(add_student, "Message", FakeMessage)
    student = _student(results=[])
    subs = FakeSubscriptions(student, created=True, subscribers=[7])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=7)
    state = FakeState({"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"})

    await add_student.confirm_add(callback, state, subs, FakeResultsNotFound(), notifier)

    # Пользователю подсказали проверить данные; рассылок/снимков нет.
    assert any("не нашлось" in a for a in message.answers)
    assert notifier.broadcasts == []
    assert notifier.sent == []


async def test_confirm_add_broadcasts_new_results_to_all_subscribers(monkeypatch):
    monkeypatch.setattr(add_student, "Message", FakeMessage)
    student = _student(results=[])
    subs = FakeSubscriptions(student, created=True, subscribers=[2, 7])
    notifier = FakeNotifier()
    callback = FakeCallback(FakeMessage(), user_id=7)
    state = FakeState({"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"})

    await add_student.confirm_add(callback, state, subs, FakeResults([_new_change()]), notifier)

    # Найденные при проверке изменения уходят ВСЕМ подписчикам, а не только инициатору.
    assert len(notifier.broadcasts) == 1
    ids, text = notifier.broadcasts[0]
    assert ids == [2, 7]
    assert "Математика" in text


# --- check_now ----------------------------------------------------------------


def _patch_student_get(monkeypatch, student):
    class FakeStudentModel:
        @staticmethod
        async def get(student_id):
            return student

    monkeypatch.setattr(my_students, "Student", FakeStudentModel)


async def test_check_now_notifies_other_subscribers_and_replies_inline(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(callback, subs, FakeResults([_new_change()]), notifier)

    # Инициатору (1) — сразу в чат; остальным подписчикам (2, 3) — рассылкой, без дубля себе.
    assert any("Математика" in a for a in message.answers)
    assert len(notifier.broadcasts) == 1
    ids, _ = notifier.broadcasts[0]
    assert ids == [2, 3]


async def test_check_now_warns_when_student_not_found(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(callback, subs, FakeResultsNotFound(), notifier)

    assert any("не нашлось" in a for a in message.answers)
    assert notifier.broadcasts == []


async def test_check_now_no_changes_does_not_broadcast(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(callback, subs, FakeResults([]), notifier)

    assert notifier.broadcasts == []
    assert any("Новых результатов" in a for a in message.answers)
