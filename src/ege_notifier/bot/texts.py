from __future__ import annotations

from ege_notifier.models import Student
from ege_notifier.services.diff import ChangeType, ResultChange

WELCOME = (
    "👋 Привет! Я слежу за публикацией результатов ЕГЭ на <b>ege.spb.ru</b> и пришлю "
    "уведомление, как только появятся новые баллы у отслеживаемых учеников.\n\n"
    "Чтобы добавить ученика, понадобятся <b>фамилия</b>, <b>серия</b> и <b>номер "
    "паспорта</b>. Один аккаунт может отслеживать несколько учеников.\n\n"
    "Выберите действие:"
)

HELP = (
    "ℹ️ <b>Как пользоваться</b>\n\n"
    "• <b>Добавить ученика</b> — пошагово введите фамилию и паспорт.\n"
    "• <b>Мои ученики</b> — список отслеживаемых, проверка вручную и удаление.\n\n"
    "Как только у ученика появится новый результат, я пришлю уведомление всем, "
    "кто на него подписан.\n\n"
    "Команды: /start, /help, /cancel (отменить ввод)."
)

ASK_LAST_NAME = "✍️ Введите <b>фамилию</b> ученика (как в паспорте):"
ASK_SERIES = "🔢 Введите <b>серию</b> паспорта (4 цифры):"
ASK_NUMBER = "🔢 Введите <b>номер</b> паспорта (6 цифр):"

BAD_LAST_NAME = "⚠️ Похоже на ошибку. Фамилия — это кириллица (можно с дефисом). Попробуйте ещё раз:"
BAD_SERIES = "⚠️ Серия паспорта — ровно 4 цифры. Попробуйте ещё раз:"
BAD_NUMBER = "⚠️ Номер паспорта — ровно 6 цифр. Попробуйте ещё раз:"

CANCELLED = "❌ Действие отменено."
NOTHING_TO_CANCEL = "Нечего отменять."

NO_STUDENTS = "У вас пока нет отслеживаемых учеников. Добавьте первого 👇"

SUBSCRIBED = "✅ Готово! Теперь отслеживаю результаты: <b>{label}</b>."
ALREADY_SUBSCRIBED = "ℹ️ Вы уже отслеживаете этого ученика: <b>{label}</b>."

PROVIDER_NOT_READY = (
    "⏳ Источник ege.spb.ru ещё не настроен в этой сборке — проверка по реальному "
    "сайту будет доступна после подключения запроса. Подписка сохранена."
)

NO_CHANGES = "🔁 Новых результатов пока нет: <b>{label}</b>."
UNSUBSCRIBED = "🗑 Удалено из отслеживаемых: <b>{label}</b>."


def confirm_text(data: dict) -> str:
    return (
        "Проверьте данные ученика:\n\n"
        f"👤 Фамилия: <b>{data['last_name']}</b>\n"
        f"🪪 Паспорт: <b>{data['passport_series']} {data['passport_number']}</b>\n\n"
        "Сохранить и подписаться на уведомления?"
    )


def _student_status(student: Student) -> str:
    if student.last_error:
        return "ошибка проверки"
    if student.results:
        return f"известно результатов: {len(student.results)}"
    if student.last_checked_at:
        return "результатов пока нет"
    return "ещё не проверялся"


def students_overview(students: list[Student]) -> str:
    lines = ["📋 <b>Ваши ученики:</b>", ""]
    for st in students:
        lines.append(f"• <b>{st.last_name}</b> ({st.passport_masked}) — {_student_status(st)}")
    lines.append("")
    lines.append("🔄 — проверить сейчас, 🗑 — удалить.")
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
    lines = [
        f"📊 Текущие результаты ЕГЭ: <b>{student.last_name}</b> ({student.passport_masked})",
        "",
    ]
    for item in student.results:
        title = item.subject_title or item.subject
        value = _display(item.value, item.score)
        status = f" · {item.status}" if item.status else ""
        lines.append(f"• <b>{title}</b>: {value}{status}")
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
