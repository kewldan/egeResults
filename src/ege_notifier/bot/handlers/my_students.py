from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InputFile,
    InputMediaDocument,
    Message,
)
from aiogram.utils.deep_linking import create_start_link
from beanie import PydanticObjectId

from ege_notifier.bot import texts
from ege_notifier.bot.keyboards import (
    back_to_card_keyboard,
    back_to_list_keyboard,
    results_card_keyboard,
    results_link_keyboard,
    student_card_keyboard,
    students_keyboard,
)
from ege_notifier.bot.ui import edit_message
from ege_notifier.config import Settings
from ege_notifier.models import Student
from ege_notifier.providers.base import StudentNotFoundError
from ege_notifier.services.blanks import (
    BlankDownloadError,
    BlankDownloader,
    blank_filename,
)
from ege_notifier.services.cards import CardRenderer, CardRenderError
from ege_notifier.services.notifier import Notifier
from ege_notifier.services.results import RefreshThrottled, ResultsService
from ege_notifier.services.subscriptions import SubscriptionService

# Не шлём за раз бесконечно много файлов в один чат (анти-флуд + здравый смысл).
_MAX_BLANKS = 20
# Telegram-альбом (media group) — максимум 10 элементов в одном сообщении.
_ALBUM_LIMIT = 10
# Небольшая пауза между сообщениями, чтобы не упереться в лимит Telegram (~1 msg/с в чат).
_BLANK_SEND_DELAY = 0.3

logger = logging.getLogger(__name__)

router = Router(name="my_students")


def _parse_id(data: str) -> PydanticObjectId | None:
    try:
        return PydanticObjectId(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _can_card(settings: Settings, student: Student) -> bool:
    """Показывать ли кнопку картинки: рендерер включён и есть что рисовать (баллы)."""
    return settings.card_renderer_enabled and bool(student.results)


async def _show_list(
    message: Message, subscriptions: SubscriptionService, telegram_id: int
) -> None:
    students = await subscriptions.list_subscriptions(telegram_id)
    await edit_message(
        message, texts.students_list_text(students), students_keyboard(students)
    )


@router.callback_query(F.data == "my_students")
async def list_students(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    if isinstance(callback.message, Message):
        await _show_list(callback.message, subscriptions, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"))
async def open_card(
    callback: CallbackQuery, subscriptions: SubscriptionService, settings: Settings
) -> None:
    """Карточка ученика: текущие результаты + действия (обновить/поделиться/удалить)."""
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    # Авторизация: карточку (PII-баллы) показываем только подписчикам — иначе
    # подделанный callback дал бы доступ к результатам чужого ученика.
    if callback.from_user.id not in await subscriptions.subscribers_for(student_id):
        await callback.answer("Ученик не найден", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await edit_message(
            callback.message,
            texts.format_current_results(student),
            student_card_keyboard(student, with_card=_can_card(settings, student)),
        )


async def _authorized_student(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> Student | None:
    """Парсит id, проверяет, что запросивший — подписчик, и грузит ученика.

    Доступ к данным ученика (расписание/детали/бланки) — только подписчику: иначе
    подделанный callback вытянул бы чужие данные. На любой сбой шлёт алерт и → None."""
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return None
    if callback.from_user.id not in await subscriptions.subscribers_for(student_id):
        await callback.answer("Ученик не найден", show_alert=True)
        return None
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
    return student


@router.callback_query(F.data.startswith("schedule:"))
async def show_schedule(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    """Расписание экзаменов ученика (даты/предметы/пункты проведения)."""
    student = await _authorized_student(callback, subscriptions)
    if student is None:
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await edit_message(
            callback.message,
            texts.format_schedule(student),
            back_to_card_keyboard(student.id),
        )


@router.callback_query(F.data.startswith("details:"))
async def show_details(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    """Подробности по предметам: критерии, первичный балл, распознанные ответы."""
    student = await _authorized_student(callback, subscriptions)
    if student is None:
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await edit_message(
            callback.message,
            texts.format_details(student),
            back_to_card_keyboard(student.id),
        )


async def _blank_file(
    blank, blanks: BlankDownloader | None, blanks_dir: str
) -> InputFile | None:
    """Готовит файл бланка: сначала с диска (скачан при проверке), иначе — «на лету».

    Файл на диске не зависит от протухания ссылки download.php (его уже скачали).
    Если файла нет (свежий ученик до первой проверки / том очищен) — пробуем
    докачать по ссылке. ``None`` — отдать нечего."""
    if blank.path:
        full = Path(blanks_dir) / blank.path
        if full.exists():
            return FSInputFile(full, filename=full.name)
    if blanks is None:
        return None
    try:
        content, content_type = await blanks.download(blank.url)
    except BlankDownloadError as exc:
        logger.info("Бланк не скачался (%s): %s", blank.url, exc)
        return None
    return BufferedInputFile(content, filename=blank_filename(blank.title, content_type))


async def _send_with_retry(send: Callable[[], Awaitable[object]], label: str) -> bool:
    """Шлёт бланк(и) одним вызовом API; ``True`` — ушло. Сбой доставки по одному
    предмету не должен прерывать отправку остальных: один повтор после
    ``TelegramRetryAfter``, а любую другую ошибку API (битый/большой файл, бот
    заблокирован) или повторный флуд-контроль глотаем и → ``False`` (иначе исключение
    оборвало бы цикл и часть бланков пропала бы)."""
    for attempt in range(2):
        try:
            await send()
            return True
        except TelegramRetryAfter as exc:
            if attempt == 0:
                await asyncio.sleep(exc.retry_after)
                continue
            logger.info("Бланк не отправлен (повторный flood-control): %s", label)
            return False
        except TelegramAPIError as exc:
            logger.info("Бланк не отправлен (%s): %s", label, exc)
            return False
    return False


async def _send_blank_document(message: Message, file: InputFile, caption: str) -> bool:
    """Один файл-бланк отдельным сообщением (предмет с единственным листом)."""
    return await _send_with_retry(
        lambda: message.answer_document(file, caption=caption), caption
    )


async def _send_blank_group(message: Message, media: list[InputMediaDocument]) -> bool:
    """Несколько бланков одного предмета — одним сообщением-альбомом (media group)."""
    return await _send_with_retry(
        lambda: message.answer_media_group(media), "альбом бланков"
    )


def _chunked(items: list, size: int):
    """Бьёт список на куски ≤ ``size`` (для лимита альбома Telegram)."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def _send_subject_blanks(
    message: Message, subject_title: str, files: list[tuple[InputFile, str]]
) -> int:
    """Шлёт бланки ОДНОГО предмета одним сообщением (альбом; 1 файл — документом).

    Возвращает число дошедших файлов. Альбом Telegram ограничен 10 элементами,
    поэтому редкий случай >10 листов бьём на несколько сообщений. Между сообщениями —
    пауза (анти-флуд). Подпись каждого файла — «предмет — лист» (как раньше), чтобы он
    оставался самодостаточным при пересылке."""
    sent = 0
    for chunk in _chunked(files, _ALBUM_LIMIT):
        if len(chunk) == 1:
            file, title = chunk[0]
            if await _send_blank_document(
                message, file, texts.blank_caption(subject_title, title)
            ):
                sent += 1
        else:
            media = [
                InputMediaDocument(
                    media=file, caption=texts.blank_caption(subject_title, title)
                )
                for file, title in chunk
            ]
            if await _send_blank_group(message, media):
                sent += len(chunk)
        await asyncio.sleep(_BLANK_SEND_DELAY)
    return sent


@router.callback_query(F.data.startswith("blanks:"))
async def send_blanks(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    blanks: BlankDownloader | None,
    settings: Settings,
) -> None:
    """Шлёт сканы бланков ответов в чат (с диска, скачанного при проверке).

    Бланки одного предмета уходят ОДНИМ сообщением-альбомом (media group), у разных
    предметов — разными сообщениями. Бланки — новый контент, поэтому это новые
    сообщения (не правка карточки). Спиннер на кнопке держим до первого ответа;
    недоступный файл пропускаем, чтобы остальные дошли. Заголовок шлём лениво —
    только когда есть реальный файл, иначе при полном провале вышло бы «заголовок +
    не удалось»."""
    student = await _authorized_student(callback, subscriptions)
    if student is None:
        return
    # Группируем бланки по предмету, сохраняя порядок предметов (как в results).
    groups: list[tuple[str, list]] = []
    position: dict[str, int] = {}
    total = 0
    for r in student.results:
        for blank in r.blanks:
            subject_title = r.subject_title or r.subject
            if subject_title not in position:
                position[subject_title] = len(groups)
                groups.append((subject_title, []))
            groups[position[subject_title]][1].append(blank)
            total += 1
    if total == 0:
        await callback.answer(texts.BLANKS_NONE, show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    if total > _MAX_BLANKS:
        logger.info(
            "У ученика id=%s бланков больше лимита (%d > %d) — шлём первые %d",
            student.id, total, _MAX_BLANKS, _MAX_BLANKS,
        )

    await callback.answer(texts.BLANKS_SENDING)

    sent = 0
    header_sent = False
    budget = _MAX_BLANKS  # общий потолок файлов на одну отправку
    for subject_title, subject_blanks in groups:
        if budget <= 0:
            break
        files: list[tuple[InputFile, str]] = []
        for blank in subject_blanks:
            if budget <= 0:
                break
            file = await _blank_file(blank, blanks, settings.blanks_dir)
            if file is None:
                continue
            files.append((file, blank.title))
            budget -= 1
        if not files:
            continue
        if not header_sent:  # заголовок — только когда есть что показать
            await callback.message.answer(texts.blanks_header(student))
            header_sent = True
        sent += await _send_subject_blanks(callback.message, subject_title, files)

    if sent == 0:
        await callback.message.answer(texts.BLANKS_FAILED)


@router.callback_query(F.data.startswith("share:"))
async def share_student(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    settings: Settings,
) -> None:
    """Выдаёт одноразовую ссылку-приглашение (получатель не узнает паспорт)."""
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    # Авторизация (подписчик?) — внутри create_share_token: вернёт None, если нет.
    token = await subscriptions.create_share_token(student_id, callback.from_user.id)
    if token is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return
    await callback.answer()
    if not isinstance(callback.message, Message) or callback.bot is None:
        return
    link = await create_start_link(callback.bot, token)
    ttl = texts.human_duration(settings.share_link_ttl_seconds)
    await edit_message(
        callback.message,
        texts.SHARE_LINK.format(link=link, ttl=ttl),
        back_to_list_keyboard(),
    )


@router.callback_query(F.data.startswith("del:"))
async def delete_student(
    callback: CallbackQuery, subscriptions: SubscriptionService
) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    await subscriptions.unsubscribe(callback.from_user.id, student_id)
    await callback.answer("🗑 Удалено")
    # Карточку правим обратно в список (без отдельного сообщения «Удалено»).
    if isinstance(callback.message, Message):
        await _show_list(callback.message, subscriptions, callback.from_user.id)


@router.callback_query(F.data.startswith("check:"))
async def check_now(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    results: ResultsService,
    notifier: Notifier,
    settings: Settings,
) -> None:
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return

    # Авторизация: запускать проверку и видеть результаты может только подписчик —
    # иначе подделанный callback вытянул бы баллы чужого ученика инлайном. Этот же
    # список нужен ниже для рассылки остальным подписчикам, поэтому берём один раз.
    assert student.id is not None  # student получен через Student.get выше
    subscriber_ids = await subscriptions.subscribers_for(student.id)
    if callback.from_user.id not in subscriber_ids:
        await callback.answer("Ученик не найден", show_alert=True)
        return

    await callback.answer("Проверяю…")
    if not isinstance(callback.message, Message):
        return

    card = student_card_keyboard(student, with_card=_can_card(settings, student))
    try:
        changes = await results.check_student(student, manual=True)
    except StudentNotFoundError:
        await edit_message(
            callback.message,
            texts.STUDENT_NOT_FOUND.format(label=texts.student_label(student)),
            card,
        )
        return
    except RefreshThrottled as exc:
        # Источник опрашивали слишком недавно (общий лимит на ученика) — не дёргаем сайт.
        await edit_message(
            callback.message, texts.refresh_throttled(exc.retry_after), card
        )
        return

    if changes:
        text = texts.format_results_update(student, changes)
        # Инициатору правим карточку в результат (кнопки: сайт + назад к списку).
        await edit_message(
            callback.message, text, results_card_keyboard(settings.results_site_url)
        )
        # check_student уже записал снимок в БД → плановая проверка эти изменения
        # больше не увидит; уведомляем остальных подписчиков, иначе они пропустят.
        others = [tid for tid in subscriber_ids if tid != callback.from_user.id]
        await notifier.broadcast(
            others, text, results_link_keyboard(settings.results_site_url)
        )
        await notifier.notify_admin(texts.admin_new_results(student, changes))
    else:
        await edit_message(
            callback.message,
            texts.NO_CHANGES.format(label=texts.student_label(student)),
            card,
        )


@router.callback_query(F.data.startswith("card:"))
async def make_card(
    callback: CallbackQuery,
    subscriptions: SubscriptionService,
    cards: CardRenderer | None,
    settings: Settings,
) -> None:
    """Генерирует PNG-карточку с результатами и шлёт картинку (можно в сторис).

    Картинку с баллами отдаём только подписчику; перед рендером проверяем, что есть
    что рисовать. Сетевые/HTTP-сбои рендерера (``CardRenderError``) не роняют бота —
    показываем алерт. Спиннер на кнопке висит до финального ``answer`` (рендер быстрый),
    поэтому единственный ответ даём в конце — иначе алерт об ошибке не показался бы.
    """
    student_id = _parse_id(callback.data or "")
    if student_id is None:
        await callback.answer("Некорректный идентификатор", show_alert=True)
        return
    if callback.from_user.id not in await subscriptions.subscribers_for(student_id):
        await callback.answer("Ученик не найден", show_alert=True)
        return
    student = await Student.get(student_id)
    if student is None:
        await callback.answer("Ученик не найден", show_alert=True)
        return
    if cards is None or not settings.card_renderer_enabled:
        await callback.answer(texts.CARD_FAILED, show_alert=True)
        return
    if not student.results:
        await callback.answer(texts.CARD_NO_RESULTS, show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    try:
        png = await cards.render_student(student, exam=settings.exam_label)
    except CardRenderError as exc:
        logger.warning("Не удалось отрендерить карточку %s: %s", student_id, exc)
        await callback.answer(texts.CARD_FAILED, show_alert=True)
        return

    photo = BufferedInputFile(png, filename=f"ege_{student_id}.png")
    await callback.message.answer_photo(
        photo,
        caption=texts.card_caption(student),
        reply_markup=back_to_list_keyboard(),
    )
    await callback.answer()
