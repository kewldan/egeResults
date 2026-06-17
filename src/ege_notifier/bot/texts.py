from __future__ import annotations

import math
from html import escape
from typing import TYPE_CHECKING

from ege_notifier.models import Student, User
from ege_notifier.services.diff import ChangeType, ResultChange

if TYPE_CHECKING:
    from ege_notifier.providers.ege_spb_overview import PublishedSubject
    from ege_notifier.services.ranking import RankEntry, SubjectCount
    from ege_notifier.services.results import StudentUpdate


def _esc(value: str) -> str:
    """Экранирует HTML-спецсимволы (``&``, ``<``, ``>``).

    Все сообщения уходят с ``parse_mode=HTML``, а подставляемые значения приходят
    извне: ``subject``/``status``/``value`` — со стороннего сайта, ``full_name`` —
    из Telegram. Без экранирования любой ``<`` или ``&`` сломал бы разметку.
    """
    return escape(value, quote=False)


def _spoiler(text: str) -> str:
    """Прячет результат экзамена под спойлер Telegram (тап, чтобы раскрыть)."""
    return f"<tg-spoiler>{text}</tg-spoiler>"


def student_label(student: Student) -> str:
    """Экранированная подпись ученика «Фамилия · ●●●● ●●●●NN» для HTML-шаблонов."""
    return f"{_esc(student.last_name)} · {_esc(student.passport_masked)}"

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
    "паспорта</b>. Один аккаунт может отслеживать несколько учеников.\n\n"
    "Кнопки управления — снизу 👇"
)

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
    "• Убрать ученика из отслеживания можно в любой момент (🗑) — вы перестанете "
    "получать о нём уведомления.\n\n"
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
    "<b>Почему не «официальный» сайт checkege?</b>\n"
    "Федеральный портал проверки результатов (checkege.rustest.ru) я не использую по "
    "двум причинам: на нём стоит <b>капча</b> (автоматически её не пройти), и это "
    "<b>федеральная</b> база — результаты из региона попадают туда <b>с задержкой</b>. "
    "<b>ege.spb.ru</b> — официальный сайт по Санкт-Петербургу, баллы появляются на нём "
    "раньше, поэтому слежу именно за ним.\n\n"
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

ASK_LAST_NAME = (
    "✍️ Введите <b>только фамилию</b> ученика — без имени и отчества, "
    "одним словом (как в паспорте):"
)
ASK_SERIES = "🔢 Введите <b>серию</b> паспорта (4 цифры):"
ASK_NUMBER = "🔢 Введите <b>номер</b> паспорта (6 цифр):"

BAD_LAST_NAME = (
    "⚠️ Нужна <b>только фамилия</b> — без имени и отчества!\n"
    "Одним словом, кириллицей, без пробелов. "
    "Двойную фамилию пишите через дефис: «Петров-Водкин».\n"
    "Попробуйте ещё раз:"
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


def _group_digits(n: int) -> str:
    """Разбивает число на разряды: 41144 → «41 144».

    Разделитель — неразрывный пробел (U+00A0), как на сайте: число не переносится
    по строкам."""
    return f"{n:,}".replace(",", " ")


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
        f"👤 Фамилия: <b>{_esc(data['last_name'])}</b>\n"
        f"🪪 Паспорт: <b>{_esc(data['passport_series'])} {_esc(data['passport_number'])}</b>\n\n"
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
            f"• <b>{_esc(st.last_name)}</b> ({_esc(st.passport_masked)}) — "
            f"{_student_status(st)}"
        )
    lines.append("")
    lines.append("Нажмите на ученика — откроется карточка с результатами и действиями.")
    return "\n".join(lines)


def students_list_text(students: list[Student]) -> str:
    """Текст экрана «Мои ученики»: обзор списка или приглашение добавить первого."""
    return students_overview(students) if students else NO_STUDENTS


def _display(value: str | None, score: int | None) -> str:
    if value:
        return value
    if score is not None:
        return str(score)
    return "—"


def format_current_results(student: Student) -> str:
    """Снимок всех известных результатов ученика — для нового подписчика, который
    подписался на уже отслеживаемого ученика (diff будет пуст, но баллы есть)."""
    header = (
        f"📊 Текущие результаты ЕГЭ: <b>{_esc(student.last_name)}</b> "
        f"({_esc(student.passport_masked)})"
    )
    if not student.results:
        # Защита от заголовка без строк, если вызвать с пустым снимком.
        return f"{header}\n\nРезультатов пока нет."
    lines = [header, ""]
    for item in student.results:
        title = _esc(item.subject_title or item.subject)
        value = _spoiler(_esc(_display(item.value, item.score)))
        status = f" · {_esc(item.status)}" if item.status else ""
        lines.append(f"• <b>{title}</b>: {value}{status}")
    return "\n".join(lines)


def admin_new_results(student: Student, changes: list[ResultChange]) -> str:
    """Служебное уведомление админу о новых результатах у любого ученика."""
    return "🛎 <b>[админ]</b>\n\n" + format_results_update(student, changes)


def admin_new_user(user: User) -> str:
    """Служебное уведомление админу о новом пользователе бота."""
    parts = [f"id <code>{user.telegram_id}</code>"]
    if user.username:
        parts.append(f"@{_esc(user.username)}")
    if user.full_name:
        parts.append(_esc(user.full_name))
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
            f"• <b>{_esc(st.last_name)}</b> ({_esc(st.passport_masked)}) — "
            f"изменений: {len(upd.changes)}"
        )
    if len(updates) > limit:
        lines.append(f"… и ещё {len(updates) - limit}")
    return "\n".join(lines)


def results_published_announcement(
    subjects: list[PublishedSubject], delta: int | None, total: int | None
) -> str:
    """Анонс «результаты выложили» для тех, кто без паспортных данных.

    Перечисляет новые предметы основного периода и (если счётчик распарсился)
    оценивает, сколько человек в СПб сдавали — по приросту «результатов в базе».
    """
    one = len(subjects) == 1
    names = "\n".join(f"• <b>{_esc(s.title)}</b>" for s in subjects)
    lines = [
        "🎓 <b>На ege.spb.ru опубликованы результаты ЕГЭ!</b>",
        "",
        f"Появились баллы по предмет{'у' if one else 'ам'} (основной период):",
        names,
    ]
    if delta and delta > 0:
        who = "этот предмет" if one else "эти предметы"
        results_word = _plural(delta, "результат", "результата", "результатов")
        lines += [
            "",
            f"📈 В базу добавилось <b>{_group_digits(delta)}</b> {results_word} — "
            f"примерно столько человек в СПб сдавали {who}.",
        ]
    if total is not None:
        lines += [f"Всего результатов в базе СПб: <b>{_group_digits(total)}</b>."]
    lines += [
        "",
        "Хотите узнать свой балл? Добавьте ученика (фамилия + серия и номер "
        "паспорта) — пришлю уведомление сразу, как появится результат. "
        "Нажмите «📋 Мои ученики» → «➕ Добавить ученика».",
    ]
    return "\n".join(lines)


def admin_subjects_published(
    subjects: list[PublishedSubject], delta: int | None
) -> str:
    """Служебное уведомление админу о новых опубликованных предметах (#w2)."""
    names = ", ".join(_esc(s.title) for s in subjects)
    extra = f" (Δ {delta})" if delta is not None else ""
    return f"🛎 <b>[админ]</b> Опубликованы предметы #w2: {names}{extra}"


# --- админ-команды (топ по предмету, ручной запуск проверки) ------------------

ADMIN_TOP_NO_DATA = (
    "📊 Пока нет ни одного результата у отслеживаемых учеников — топ составить не из чего."
)


def admin_subjects_overview(subjects: list[SubjectCount]) -> str:
    """Подсказка для /top без аргумента: какие предметы доступны и сколько учеников."""
    if not subjects:
        return ADMIN_TOP_NO_DATA
    lines = [
        "📊 <b>Доступные предметы</b> — укажите один: <code>/top предмет</code>",
        "",
    ]
    for s in subjects:
        word = _plural(s.count, "ученик", "ученика", "учеников")
        lines.append(f"• <b>{_esc(s.title)}</b> — {s.count} {word}")
    lines += ["", "Например: <code>/top математика профильная</code>"]
    return "\n".join(lines)


def admin_top_empty(subject: str, notes_filter: str | None = None) -> str:
    """Запрошенного предмета (с учётом фильтра по заметке) нет ни у одного ученика."""
    if notes_filter:
        return (
            f"🤷 По предмету «<b>{_esc(subject)}</b>» с заметкой, содержащей "
            f"«<b>{_esc(notes_filter)}</b>», нет ни одного ученика с результатом. "
            "Уберите фильтр или измените его — <code>/top предмет | заметка</code>."
        )
    return (
        f"🤷 По предмету «<b>{_esc(subject)}</b>» пока нет результатов ни у одного "
        "ученика. Посмотреть доступные предметы — <code>/top</code> без аргумента."
    )


def _rank_line(entry: RankEntry, display: str) -> str:
    """Строка топа: фамилия + 2 цифры паспорта (на случай однофамильцев) + балл."""
    tail = entry.passport_masked[-2:]
    note = f" <i>{_esc(entry.notes)}</i>" if entry.notes else ""
    return f"<b>{_esc(entry.last_name)}</b> (…{_esc(tail)}){note} — {display}"


def admin_subject_ranking(
    title: str, entries: list[RankEntry], notes_filter: str | None = None
) -> str:
    """Топ учеников по предмету: числовые баллы по убыванию + средний балл.

    Это админ-инструмент: баллы показываем открыто (без спойлера), чтобы список
    читался сразу. Результаты без числового балла («Зачёт») выносятся в конец.
    ``notes_filter`` (если задан) показываем в шапке — топ сужен по заметке."""
    numeric = [e for e in entries if e.score is not None]
    other = [e for e in entries if e.score is None]

    header = f"🏆 <b>Топ по предмету: {_esc(title)}</b>"
    if notes_filter:
        header += f"\n🔎 фильтр по заметке: «<b>{_esc(notes_filter)}</b>»"
    summary = f"Учеников с результатом: <b>{len(entries)}</b>"
    if numeric:
        avg = sum(e.score or 0 for e in numeric) / len(numeric)
        best = numeric[0].score
        worst = numeric[-1].score
        summary += (
            f" · средний балл: <b>{avg:.1f}</b> · "
            f"макс/мин: <b>{best}</b>/<b>{worst}</b>"
        )
    lines = [header, summary, ""]

    limit = 100  # защитный предел на длину сообщения Telegram (4096 символов)
    for i, e in enumerate(numeric[:limit], 1):
        lines.append(f"{i}. {_rank_line(e, f'<b>{e.score}</b>')}")
    if len(numeric) > limit:
        lines.append(f"… и ещё {len(numeric) - limit}")

    if other:
        lines += ["", "Без числового балла:"]
        for e in other[:limit]:
            lines.append(f"• {_rank_line(e, _esc(_display(e.value, e.score)))}")
    return "\n".join(lines)


ADMIN_CHECK_STARTED = (
    "🚀 Запускаю проверку личных результатов всех отслеживаемых учеников…\n"
    "Это может занять некоторое время — пришлю сводку, когда закончу."
)
ADMIN_CHECK_ALREADY_RUNNING = (
    "⏳ Проверка уже идёт. Дождитесь её завершения — пришлю сводку."
)


def admin_check_done(updated: int) -> str:
    """Сводка администратору по завершении ручного запуска проверки."""
    if updated == 0:
        return "✅ Проверка завершена. Новых результатов ни у кого не появилось."
    word = _plural(updated, "ученика", "учеников", "учеников")
    return f"✅ Проверка завершена. Новые результаты у <b>{updated}</b> {word}."


def format_results_update(student: Student, changes: list[ResultChange]) -> str:
    lines = [
        f"🔔 Обновление результатов ЕГЭ: <b>{_esc(student.last_name)}</b> "
        f"({_esc(student.passport_masked)})",
        "",
    ]
    for c in changes:
        title = _esc(c.subject_title or c.subject)
        if c.type == ChangeType.NEW:
            value = _spoiler(_esc(_display(c.new_value, c.new_score)))
            status = f" · {_esc(c.new_status)}" if c.new_status else ""
            lines.append(f"🆕 <b>{title}</b>: {value}{status}")
        else:
            old = _spoiler(_esc(_display(c.old_value, c.old_score)))
            new = _spoiler(_esc(_display(c.new_value, c.new_score)))
            lines.append(f"✏️ <b>{title}</b>: {old} → {new}")
    return "\n".join(lines)
