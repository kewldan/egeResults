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

from ege_notifier.bot import texts
from ege_notifier.bot.handlers import add_student, common, my_students
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.cards import CardRenderError
from ege_notifier.services.diff import ChangeType, ResultChange
from ege_notifier.services.results import RefreshThrottled


# --- двойники Telegram --------------------------------------------------------


class FakeMessage:
    def __init__(self, user_id=None):
        self.answers: list[str] = []
        self.edits: list[str] = []
        self.photos: list[tuple] = []  # (photo, caption) отправленных answer_photo
        self.documents: list[tuple] = []  # (document, caption) отправленных answer_document
        self.markups: list = []  # клавиатуры последних answer/edit/photo/document
        self.from_user = (
            SimpleNamespace(id=user_id, username=None, full_name=None)
            if user_id is not None
            else None
        )

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)
        self.markups.append(reply_markup)

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)
        self.markups.append(reply_markup)

    async def answer_photo(self, photo, caption=None, reply_markup=None):
        self.photos.append((photo, caption))
        self.markups.append(reply_markup)

    async def answer_document(self, document, caption=None, reply_markup=None):
        self.documents.append((document, caption))
        self.markups.append(reply_markup)


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


# Заглушка настроек: хендлерам нужны URL сайта, TTL ссылки и параметры карточки.
SETTINGS = SimpleNamespace(
    results_site_url="https://www.ege.spb.ru/result/index.php?mode=ege2026&wave=1",
    share_link_ttl_seconds=86400,
    card_renderer_enabled=True,
    exam_label="ЕГЭ · 2026",
    blanks_dir="data/blanks",  # для send_blanks; в тестах файлов там нет → fallback
)


class FakeCardRenderer:
    """Двойник рендерера карточек: отдаёт фиксированные байты или бросает ошибку."""

    def __init__(self, png=b"PNGDATA", error=None):
        self._png = png
        self._error = error
        self.calls: list[tuple] = []

    async def render_student(self, student, *, exam):
        self.calls.append((student, exam))
        if self._error is not None:
            raise self._error
        return self._png


# --- двойники сервисов --------------------------------------------------------


class FakeSubscriptions:
    def __init__(
        self, student, created, subscribers, share_token="tok123", students=None
    ):
        self._student = student
        self._created = created
        self._subscribers = subscribers
        self._share_token = share_token
        self._students = students or []

    async def subscribe(self, telegram_id, last_name, series, number):
        return self._student, self._created

    async def subscribers_for(self, student_id):
        return list(self._subscribers)

    async def list_subscriptions(self, telegram_id):
        return list(self._students)

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


def _student(results=None, registrations=None):
    sid = PydanticObjectId()
    return SimpleNamespace(
        id=sid,
        label="Иванов · ●●●● ●●●●74",
        last_name="Иванов",
        passport_masked="●●●● ●●●●74",
        results=results or [],
        registrations=registrations or [],
        last_error=None,
        last_checked_at=None,
        not_found=False,
    )


def _result_item():
    return SimpleNamespace(
        subject="русский язык",
        subject_title="Русский язык",
        value="88",
        score=88,
        status="Действующий результат",
        criteria=[],
        primary_score=None,
        recognition=[],
        blanks=[],
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

    await my_students.open_card(callback, subs, SETTINGS)

    # Подписчику показали сохранённый снимок баллов (правкой сообщения, без проверки источника).
    assert any("Русский язык" in a for a in message.edits)


async def test_open_card_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"student:{student.id}")

    await my_students.open_card(callback, subs, SETTINGS)

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


# --- расписание / детали / бланки --------------------------------------------


def _reg(subject, *, title=None, date=None, place=None, address=None):
    return SimpleNamespace(
        subject=subject, subject_title=title, exam_date=date, place=place, address=address
    )


def _blank(title, url, path=None):
    return SimpleNamespace(title=title, url=url, path=path)


def _detailed_item():
    return SimpleNamespace(
        subject="сочинение",
        subject_title="Сочинение",
        value="Зачёт",
        score=None,
        status="Действующий результат",
        criteria=[SimpleNamespace(name="Крит. К1", value="Зачёт")],
        primary_score=37,
        recognition=[SimpleNamespace(task="1", answer="АБВ")],
        blanks=[_blank("Бланк 1", "https://x/d?f=1"), _blank("Бланк 2", "https://x/d?f=2")],
    )


class FakeBlanks:
    def __init__(self, content=b"%PDF", ctype="application/pdf", error=None):
        self._content = content
        self._ctype = ctype
        self._error = error
        self.urls: list[str] = []

    async def download(self, url):
        self.urls.append(url)
        if self._error is not None:
            raise self._error
        return self._content, self._ctype


async def test_show_schedule_edits_for_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(registrations=[_reg("сочинение", title="Сочинение", date="3 декабря 2025", place="ГБОУ СОШ №669")])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"schedule:{student.id}")

    await my_students.show_schedule(callback, subs)

    assert any("3 декабря 2025" in e and "ГБОУ СОШ №669" in e for e in message.edits)


async def test_show_schedule_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(registrations=[_reg("x", title="X", date="1 июня")])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"schedule:{student.id}")

    await my_students.show_schedule(callback, subs)

    assert message.edits == [] and message.answers == []
    assert callback.answered == ["Ученик не найден"]


async def test_show_details_edits_for_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_detailed_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"details:{student.id}")

    await my_students.show_details(callback, subs)

    assert any("Первичный балл" in e and "Крит. К1" in e for e in message.edits)


async def test_send_blanks_falls_back_to_download_when_no_local_file(monkeypatch):
    # path=None и файла на диске нет → качаем «на лету» по ссылке.
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    monkeypatch.setattr(my_students, "_BLANK_SEND_DELAY", 0)
    student = _student(results=[_detailed_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    blanks = FakeBlanks()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"blanks:{student.id}")

    await my_students.send_blanks(callback, subs, blanks, SETTINGS)

    # оба бланка скачаны и отправлены файлами; первым — заголовок-сообщение
    assert blanks.urls == ["https://x/d?f=1", "https://x/d?f=2"]
    assert len(message.documents) == 2
    assert any("Бланки ответов" in a for a in message.answers)
    assert callback.answered == [texts.BLANKS_SENDING]


async def test_send_blanks_serves_from_disk_without_download(monkeypatch, tmp_path):
    # path задан и файл существует → отдаём с диска, по сети НЕ ходим.
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    monkeypatch.setattr(my_students, "_BLANK_SEND_DELAY", 0)
    blank_file = tmp_path / "HASH" / "Сочинение__Бланк 1.pdf"
    blank_file.parent.mkdir(parents=True)
    blank_file.write_bytes(b"%PDF-1.4")
    item = SimpleNamespace(
        subject="сочинение", subject_title="Сочинение", value="Зачёт", score=None,
        status=None, criteria=[], primary_score=None, recognition=[],
        blanks=[_blank("Бланк 1", "https://x/d?f=1", path="HASH/Сочинение__Бланк 1.pdf")],
    )
    student = _student(results=[item])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    blanks = FakeBlanks()
    settings = SimpleNamespace(blanks_dir=str(tmp_path))
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"blanks:{student.id}")

    await my_students.send_blanks(callback, subs, blanks, settings)

    assert blanks.urls == []  # по сети не ходили
    assert len(message.documents) == 1


async def test_send_blanks_none_alerts(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])  # результат без бланков
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    blanks = FakeBlanks()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"blanks:{student.id}")

    await my_students.send_blanks(callback, subs, blanks, SETTINGS)

    assert message.documents == [] and blanks.urls == []
    assert callback.answered == [texts.BLANKS_NONE]


async def test_send_blanks_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_detailed_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    blanks = FakeBlanks()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"blanks:{student.id}")

    await my_students.send_blanks(callback, subs, blanks, SETTINGS)

    assert message.documents == [] and blanks.urls == []
    assert callback.answered == ["Ученик не найден"]


async def test_send_blank_document_swallows_api_error():
    """Любая ошибка API (кроме одного повтора RetryAfter) → False, без проброса."""
    from aiogram.exceptions import TelegramAPIError

    message = FakeMessage()

    async def boom(document, caption=None, reply_markup=None):
        raise TelegramAPIError(method=None, message="too big")

    message.answer_document = boom
    ok = await my_students._send_blank_document(message, object(), "подпись")
    assert ok is False


async def test_send_blanks_continues_after_one_failure(monkeypatch):
    """Сбой отправки одного бланка (не RetryAfter) не обрывает остальные.

    Регрессия: раньше ловился только TelegramRetryAfter, любая другая ошибка
    answer_document пробрасывалась и роняла цикл — остальные бланки не уходили."""
    from aiogram.exceptions import TelegramAPIError

    monkeypatch.setattr(my_students, "Message", FakeMessage)
    monkeypatch.setattr(my_students, "_BLANK_SEND_DELAY", 0)
    student = _student(results=[_detailed_item()])  # 2 бланка
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    blanks = FakeBlanks()
    message = FakeMessage()

    real_answer_document = message.answer_document
    state = {"n": 0}

    async def flaky(document, caption=None, reply_markup=None):
        state["n"] += 1
        if state["n"] == 1:
            raise TelegramAPIError(method=None, message="boom")
        await real_answer_document(document, caption=caption, reply_markup=reply_markup)

    message.answer_document = flaky
    callback = FakeCallback(message, user_id=1, data=f"blanks:{student.id}")

    await my_students.send_blanks(callback, subs, blanks, SETTINGS)

    assert len(message.documents) == 1  # первый упал, второй всё равно дошёл


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


# --- make_card (картинка для сторис) -----------------------------------------


async def test_make_card_sends_photo_to_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1, 2])
    cards = FakeCardRenderer(png=b"PNGBYTES")
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"card:{student.id}")

    await my_students.make_card(callback, subs, cards, SETTINGS)

    # Подписчику ушла картинка с подписью-приглашением в сторис; рендер позвали с меткой ЕГЭ.
    assert len(message.photos) == 1
    photo, caption = message.photos[0]
    assert "Иванов" in caption
    assert cards.calls == [(student, "ЕГЭ · 2026")]
    assert callback.answered == [None]  # финальный «пустой» ответ снимает спиннер


async def test_make_card_rejects_non_subscriber(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[2, 3])
    cards = FakeCardRenderer()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"card:{student.id}")

    await my_students.make_card(callback, subs, cards, SETTINGS)

    # Не подписан → картинку с баллами не отдаём и рендер не дёргаем.
    assert message.photos == []
    assert cards.calls == []
    assert callback.answered == ["Ученик не найден"]


async def test_make_card_no_results_alerts(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[])  # баллов ещё нет — рисовать нечего
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    cards = FakeCardRenderer()
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"card:{student.id}")

    await my_students.make_card(callback, subs, cards, SETTINGS)

    assert message.photos == []
    assert cards.calls == []
    assert callback.answered == [texts.CARD_NO_RESULTS]


async def test_make_card_handles_render_error(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    cards = FakeCardRenderer(error=CardRenderError("renderer down"))
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"card:{student.id}")

    await my_students.make_card(callback, subs, cards, SETTINGS)

    # Сбой рендерера не роняет бота: фото нет, пользователю — понятный алерт.
    assert message.photos == []
    assert callback.answered == [texts.CARD_FAILED]


async def test_make_card_when_renderer_unavailable(monkeypatch):
    monkeypatch.setattr(my_students, "Message", FakeMessage)
    student = _student(results=[_result_item()])
    _patch_student_get(monkeypatch, student)
    subs = FakeSubscriptions(student, created=False, subscribers=[1])
    message = FakeMessage()
    callback = FakeCallback(message, user_id=1, data=f"card:{student.id}")

    # cards=None (рендерер выключен в конфиге) → алерт, без падения.
    await my_students.make_card(callback, subs, None, SETTINGS)

    assert message.photos == []
    assert callback.answered == [texts.CARD_FAILED]


# --- нижняя ReplyKeyboard (common) -------------------------------------------


def _kb_labels(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


async def test_btn_my_students_lists_students_with_add_button():
    student = _student()
    subs = FakeSubscriptions(
        student, created=False, subscribers=[1], students=[student]
    )
    message = FakeMessage(user_id=1)
    state = FakeState({})

    await common.btn_my_students(message, state, subs)

    # Одно сообщение со списком; в клавиатуре — ученик и кнопка добавления.
    assert any("Иванов" in a for a in message.answers)
    labels = _kb_labels(message.markups[-1])
    assert any("Иванов" in t for t in labels)
    assert any("Добавить ученика" in t for t in labels)


async def test_btn_my_students_empty_shows_only_add_button():
    subs = FakeSubscriptions(_student(), created=False, subscribers=[], students=[])
    message = FakeMessage(user_id=1)
    state = FakeState({})

    await common.btn_my_students(message, state, subs)

    labels = _kb_labels(message.markups[-1])
    assert labels == ["➕ Добавить ученика"]


async def test_btn_security_and_about_send_texts():
    sec = FakeMessage(user_id=1)
    await common.btn_security(sec)
    assert any("Безопасность" in a for a in sec.answers)

    about = FakeMessage(user_id=1)
    await common.btn_about(about)
    assert any("@kewldan" in a for a in about.answers)
