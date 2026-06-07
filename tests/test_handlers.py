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
from ege_notifier.services.results import RefreshThrottled


# --- двойники Telegram --------------------------------------------------------


class FakeMessage:
    def __init__(self):
        self.answers: list[str] = []
        self.edits: list[str] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeCallback:
    def __init__(self, message, user_id, data=None):
        self.message = message
        self.from_user = SimpleNamespace(id=user_id, username=None, full_name=None)
        self.data = data
        self.bot = (
            SimpleNamespace()
        )  # для create_start_link (в тестах monkeypatch'ится)
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
        self.admin: list[str] = []

    async def send(self, telegram_id, text, reply_markup=None):
        self.sent.append((telegram_id, text))
        return True

    async def broadcast(self, telegram_ids, text, reply_markup=None):
        ids = list(telegram_ids)
        self.broadcasts.append((ids, text))
        return len(ids)

    async def notify_admin(self, text):
        self.admin.append(text)
        return True


# Заглушка настроек: хендлерам нужны лишь URL сайта и TTL ссылки-приглашения.
SETTINGS = SimpleNamespace(
    results_site_url="https://www.ege.spb.ru/result/index.php?mode=ege2026&wave=1",
    share_link_ttl_seconds=86400,
)


# --- двойники сервисов --------------------------------------------------------


class FakeSubscriptions:
    def __init__(self, student, created, subscribers, share_token="tok123"):
        self._student = student
        self._created = created
        self._subscribers = subscribers
        self._share_token = share_token

    async def subscribe(self, telegram_id, last_name, series, number):
        return self._student, self._created

    async def subscribers_for(self, student_id):
        return list(self._subscribers)

    async def create_share_token(self, student_id, telegram_id):
        # Подписчик получает токен; не-подписчик — None (как в реальном сервисе).
        if telegram_id not in self._subscribers:
            return None
        return self._share_token


class FakeResults:
    def __init__(self, changes):
        self._changes = changes

    async def check_student(self, student, *, manual=False):
        return self._changes


class FakeResultsNotFound:
    """check_student бросает StudentNotFoundError — как при опечатке в данных."""

    async def check_student(self, student, *, manual=False):
        raise StudentNotFoundError("not found")


class FakeResultsThrottled:
    """check_student бросает RefreshThrottled — как при срабатывании кулдауна."""

    async def check_student(self, student, *, manual=False):
        raise RefreshThrottled(retry_after=120)


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
    state = FakeState(
        {"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"}
    )

    await add_student.confirm_add(
        callback, state, subs, FakeResults([]), notifier, SETTINGS
    )

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
    state = FakeState(
        {"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"}
    )

    await add_student.confirm_add(
        callback, state, subs, FakeResultsNotFound(), notifier, SETTINGS
    )

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
    state = FakeState(
        {"last_name": "Иванов", "passport_series": "4022", "passport_number": "083074"}
    )

    await add_student.confirm_add(
        callback, state, subs, FakeResults([_new_change()]), notifier, SETTINGS
    )

    # Найденные при проверке изменения уходят ВСЕМ подписчикам, а не только инициатору.
    assert len(notifier.broadcasts) == 1
    ids, text = notifier.broadcasts[0]
    assert ids == [2, 7]
    assert "Математика" in text
    # Админ тоже получил уведомление о новом результате.
    assert len(notifier.admin) == 1
    assert "Математика" in notifier.admin[0]


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

    await my_students.check_now(
        callback, subs, FakeResults([_new_change()]), notifier, SETTINGS
    )

    # Инициатору (1) — правим карточку на месте; остальным (2, 3) — рассылкой, без дубля себе.
    assert any("Математика" in a for a in message.edits)
    assert len(notifier.broadcasts) == 1
    ids, _ = notifier.broadcasts[0]
    assert ids == [2, 3]
    assert len(notifier.admin) == 1  # админ оповещён о новом результате


async def test_check_now_warns_when_student_not_found(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(
        callback, subs, FakeResultsNotFound(), notifier, SETTINGS
    )

    assert any("не нашлось" in a for a in message.edits)
    assert notifier.broadcasts == []


async def test_check_now_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(
        callback, subs, FakeResults([_new_change()]), notifier, SETTINGS
    )

    # Не подписан → проверка не запускается, ни ответа/правки, ни рассылки.
    assert message.answers == [] and message.edits == []
    assert notifier.broadcasts == []
    assert callback.answered == ["Ученик не найден"]


async def test_open_card_sends_snapshot_to_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"student:{student.id}")

    await my_students.open_card(callback, subs)

    # Подписчику показали сохранённый снимок баллов (правкой сообщения, без проверки источника).
    assert any("Русский язык" in a for a in message.edits)


async def test_open_card_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"student:{student.id}")

    await my_students.open_card(callback, subs)

    # Не подписан → результаты чужого ученика не утекают.
    assert message.answers == [] and message.edits == []
    assert callback.answered == ["Ученик не найден"]


async def test_check_now_no_changes_does_not_broadcast(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(callback, subs, FakeResults([]), notifier, SETTINGS)

    assert notifier.broadcasts == []
    assert any("Новых результатов" in a for a in message.edits)


async def test_check_now_throttled_tells_user_to_wait(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2, 3])
    notifier = FakeNotifier()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"check:{student.id}")

    await my_students.check_now(
        callback, subs, FakeResultsThrottled(), notifier, SETTINGS
    )

    # Кулдаун: сайт не дёргаем, инициатору — «подождите», рассылки/админа нет.
    assert any("Обновить" in a for a in message.edits)
    assert notifier.broadcasts == []
    assert notifier.admin == []


# --- share_student ------------------------------------------------------------


async def test_share_student_sends_link_to_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)

    async def fake_link(bot, token):
        return f"https://t.me/bot?start={token}"

    monkeypatch.setattr(my_students, "create_start_link", fake_link)
    student = _student()
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"share:{student.id}")

    await my_students.share_student(callback, subs, SETTINGS)

    # Подписчику пришла ссылка-приглашение с токеном (правкой сообщения).
    assert any("start=tok123" in a for a in message.edits)


async def test_share_student_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student()
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"share:{student.id}")

    await my_students.share_student(callback, subs, SETTINGS)

    # Не подписан → ссылку не выдаём.
    assert message.answers == [] and message.edits == []
    assert callback.answered == ["Ученик не найден"]
