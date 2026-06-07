from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ege_notifier.models import Student, User
from ege_notifier.services.diff import ChangeType, ResultChange

if TYPE_CHECKING:
    from ege_notifier.services.results import StudentUpdate

# Подписи кнопок постоянной нижней клавиатуры (см. keyboards.main_reply_keyboard).
# По ним же хендлеры в common.py ловят нажатия (F.text == ...), поэтому держим
# здесь единым источником правды.
BTN_MY_STUDENTS = "📋 Мои ученики"
BTN_SECURITY = "🛡 Безопасность"
BTN_ABOUT = "ℹ️ О боте"

WELCOME = (
    "👋 Привет! Я слежу за публикацией результатов ЕГЭ на <b>ege.spb.ru</b> и пришлю "
    "уведомление, как только появятся новые баллы у отслеживаемых учеников.\n\n"
    "Чтобы добавить ученика, понадобятся <b>фамилия</b>, <b>серия</b> и <b>номер "
    "паспорта</b>. Один аккаунт может отслеживать несколько учеников."
)

CHOOSE_ACTION = "Выберите действие 👇"

SECURITY = (
    "🛡 <b>Безопасность и данные</b>\n\n"
    "Я обрабатываю паспортные данные ученика только чтобы проверять результаты на "
    "<b>ege.spb.ru</b> (как если бы вы вводили их на сайте сами). Никаких логинов и "
    "паролей от Госуслуг я не прошу.\n\n"
    "<b>Как защищены данные:</b>\n"
    "• Паспорт хранится <b>в зашифрованном виде</b> (Fernet/AES) — в базе нет "
    "открытых серии и номера.\n"
    "• Для поиска и объединения дублей используется необратимый <b>хэш</b> (HMAC) — "
    "сам паспорт при этом не расшифровывается.\n"
    "• В сообщениях паспорт всегда <b>маскируется</b> (видны лишь 2 последние цифры).\n"
    "• Результаты ученика видят <b>только его подписчики</b>.\n"
    "• <b>Ссылки-приглашения</b> одноразовые: получатель видит результаты, но "
    "<b>не</b> паспортные данные.\n"
    "• Когда ученика перестаёт отслеживать <b>последний</b> подписчик, его данные "
    "<b>удаляются</b>.\n\n"
    "Если хотите убрать ученика — откройте его карточку и нажмите 🗑."
)

ABOUT = (
    "ℹ️ <b>О боте</b>\n\n"
    "Бот следит за публикацией результатов ЕГЭ на <b>ege.spb.ru</b> и присылает "
    "уведомление, как только у отслеживаемого ученика появляются или меняются баллы. "
    "Один аккаунт может отслеживать нескольких учеников, а на одного ученика — "
    "подписаться несколько человек.\n\n"
    "Проверки идут автоматически по расписанию; можно проверить и вручную из карточки "
    "ученика.\n\n"
    "Автор: @kewldan"
)

HELP = (
    "ℹ️ <b>Как пользоваться</b>\n\n"
    "• <b>Добавить ученика</b> — пошагово введите фамилию и паспорт.\n"
    "• <b>Мои ученики</b> — список, текущие результаты, проверка вручную и удаление.\n\n"
    "Как только у ученика появится новый результат, я пришлю уведомление всем, "
    "кто на него подписан.\n\n"
    "Команды: /start, /help, /cancel (отменить ввод)."
)

ASK_LAST_NAME = "✍️ Введите <b>фамилию</b> ученика (как в паспорте):"
ASK_SERIES = "🔢 Введите <b>серию</b> паспорта (4 цифры):"
ASK_NUMBER = "🔢 Введите <b>номер</b> паспорта (6 цифр):"

BAD_LAST_NAME = (
    "⚠️ Похоже на ошибку. Фамилия — это кириллица (можно с дефисом). Попробуйте ещё раз:"
)
BAD_SERIES = "⚠️ Серия паспорта — ровно 4 цифры. Попробуйте ещё раз:"
BAD_NUMBER = "⚠️ Номер паспорта — ровно 6 цифр. Попробуйте ещё раз:"

CANCELLED = "❌ Действие отменено."
NOTHING_TO_CANCEL = "Нечего отменять."

NO_STUDENTS = "У вас пока нет отслеживаемых учеников. Добавьте первого 👇"

SUBSCRIBED = "✅ Готово! Теперь отслеживаю результаты: <b>{label}</b>."
ALREADY_SUBSCRIBED = "ℹ️ Вы уже отслеживаете этого ученика: <b>{label}</b>."

NO_CHANGES = "🔁 Новых результатов пока нет: <b>{label}</b>."
UNSUBSCRIBED = "🗑 Удалено из отслеживаемых: <b>{label}</b>."

STUDENT_NOT_FOUND = (
    "🔎 На <b>ege.spb.ru</b> не нашлось ученика по этим данным: <b>{label}</b>.\n\n"
    "Чаще всего это опечатка в фамилии, серии или номере паспорта. Фамилия должна "
    "быть точно как в паспорте. Удалите ученика (🗑) и добавьте заново с верными "
    "данными.\n\nЕсли данные точно верны — возможно, ученика ещё нет в базе сайта; "
    "я продолжу проверять автоматически."
)

SHARE_LINK = (
    "🔗 <b>Одноразовая ссылка-приглашение</b>\n\n"
    "Перешлите её тому, с кем хотите поделиться отслеживанием. Перейдя по ссылке, "
    "человек начнёт получать уведомления о результатах этого ученика, но "
    "<b>не увидит паспортных данных</b>.\n\n"
    "Ссылка сработает <b>только один раз</b> и действует {ttl}:\n\n{link}"
)

SHARE_REDEEMED = (
    "✅ Готово! По приглашению вы теперь отслеживаете результаты: <b>{label}</b>."
)

SHARE_INVALID = (
    "⚠️ Ссылка-приглашение недействительна: она уже использована, истекла или указана "
    "с ошибкой. Попросите отправителя сгенерировать новую."
)


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение существительного после числа (1 час, 2 часа, 5 часов)."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def human_duration(seconds: float) -> str:
    """Человекочитаемая длительность с округлением ВВЕРХ (для «осталось ждать N»)."""
    total = max(math.ceil(seconds), 1)
    if total < 60:
        return f"{total} {_plural(total, 'секунду', 'секунды', 'секунд')}"
    if total < 3600:
        m = math.ceil(total / 60)
        return f"{m} {_plural(m, 'минуту', 'минуты', 'минут')}"
    h = math.ceil(total / 3600)
    return f"{h} {_plural(h, 'час', 'часа', 'часов')}"


def refresh_throttled(retry_after: float) -> str:
    return (
        "⏳ Этого ученика недавно уже проверяли. Обновить вручную можно через "
        f"{human_duration(retry_after)} — чтобы не нагружать сайт лишними запросами "
        "(лимит общий на всех подписчиков). Новые результаты придут автоматически."
    )


def confirm_text(data: dict) -> str:
    return (
        "Проверьте данные ученика:\n\n"
        f"👤 Фамилия: <b>{data['last_name']}</b>\n"
        f"🪪 Паспорт: <b>{data['passport_series']} {data['passport_number']}</b>\n\n"
        "Сохранить и подписаться на уведомления?"
    )


def _student_status(student: Student) -> str:
    if student.results:
        return f"известно результатов: {len(student.results)}"
    # «Не найден» показываем только когда баллов ещё нет: иначе разовый сбой сайта
    # не должен прятать уже известные результаты.
    if getattr(student, "not_found", False):
        return "не найден — проверьте данные"
    if student.last_error:
        return "ошибка проверки"
    if student.last_checked_at:
        return "результатов пока нет"
    return "ещё не проверялся"


def students_overview(students: list[Student]) -> str:
    lines = ["📋 <b>Ваши ученики:</b>", ""]
    for st in students:
        lines.append(
            f"• <b>{st.last_name}</b> ({st.passport_masked}) — {_student_status(st)}"
        )
    return "\n".join(lines)


def _display(value: str | None, score: int | None) -> str:
    if value:
        return value
    if score is not None:
        return str(score)
    return "—"


def format_current_results(student: Student) -> str:
    """Снимок всех известных результатов ученика — для нового подписчика, который
    подписался на уже отслеживаемого ученика (diff будет пуст, но баллы есть)."""
    header = f"📊 Текущие результаты ЕГЭ: <b>{student.last_name}</b> ({student.passport_masked})"
    if not student.results:
        # Защита от заголовка без строк, если вызвать с пустым снимком.
        return f"{header}\n\nРезультатов пока нет."
    lines = [header, ""]
    for item in student.results:
        title = item.subject_title or item.subject
        value = _display(item.value, item.score)
        status = f" · {item.status}" if item.status else ""
        lines.append(f"• <b>{title}</b>: {value}{status}")
    return "\n".join(lines)


def admin_new_results(student: Student, changes: list[ResultChange]) -> str:
    """Служебное уведомление админу о новых результатах у любого ученика."""
    return "🛎 <b>[админ]</b>\n\n" + format_results_update(student, changes)


def admin_new_user(user: User) -> str:
    """Служебное уведомление админу о новом пользователе бота."""
    parts = [f"id <code>{user.telegram_id}</code>"]
    if user.username:
        parts.append(f"@{user.username}")
    if user.full_name:
        parts.append(user.full_name)
    return "🆕 <b>[админ]</b> Новый пользователь: " + ", ".join(parts)


def admin_results_digest(updates: list[StudentUpdate]) -> str:
    """Сводка по новым результатам за плановый цикл — ОДНИМ сообщением.

    Шлём админу одно сообщение на цикл (а не по одному на ученика), иначе при
    массовом появлении баллов получили бы пачку сообщений в один чат и поймали
    бы ``TelegramRetryAfter`` (лимит ~1 сообщение/с на чат). Список усечён, чтобы
    влезть в лимит длины сообщения Telegram (4096 символов)."""
    limit = 50
    lines = [f"🛎 <b>[админ]</b> Новые результаты у {len(updates)} ученик(ов):", ""]
    for upd in updates[:limit]:
        st = upd.student
        lines.append(
            f"• <b>{st.last_name}</b> ({st.passport_masked}) — "
            f"изменений: {len(upd.changes)}"
        )
    if len(updates) > limit:
        lines.append(f"… и ещё {len(updates) - limit}")
    return "\n".join(lines)


def format_results_update(student: Student, changes: list[ResultChange]) -> str:
    lines = [
        f"🔔 Обновление результатов ЕГЭ: <b>{student.last_name}</b> ({student.passport_masked})",
        "",
    ]
    for c in changes:
        title = c.subject_title or c.subject
        if c.type == ChangeType.NEW:
            value = _display(c.new_value, c.new_score)
            status = f" · {c.new_status}" if c.new_status else ""
            lines.append(f"🆕 <b>{title}</b>: {value}{status}")
        else:
            old = _display(c.old_value, c.old_score)
            new = _display(c.new_value, c.new_score)
            lines.append(f"✏️ <b>{title}</b>: {old} → {new}")
    return "\n".join(lines)
