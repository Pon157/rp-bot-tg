"""Репорты: участник жалуется ответом на сообщение нарушителя. Карточка с кнопками уходит
МОДЕРАТОРАМ В ЛИЧКУ (админы чата в Telegram + назначенные в панели). Бот может писать только
тем, кто хотя бы раз нажал /start у бота — поэтому /start в личке регистрирует модератора.
Если никому не удалось написать и задан REPORTS_CHAT_ID — карточка уходит туда."""
from __future__ import annotations

import datetime as dt
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import repo
from bot.config import reports_chat, settings
from bot.emojis import e
from bot.rich import reply_rich, send_rich
from bot.moderation import apply_action, can_moderate
from bot.utils.buttons import ibtn
from bot.utils.formatting import esc, nick, nicks, quote, user_link
from bot.utils.targets import target_and_rest
from aiogram.types import InlineKeyboardMarkup

router = Router(name="reports")
logger = logging.getLogger("rp_bot.reports")

COOLDOWN_SEC = 60
ACTION_LABELS = {
    "warn": "выдан варн", "mute": "мут на 1 час", "ban": "бан",
    "del": "сообщение удалено", "ok": "решено без наказания", "no": "отклонён",
}


def _msg_link(chat_id: int | None, message_id: int | None) -> str | None:
    if not chat_id or not message_id or not str(chat_id).startswith("-100"):
        return None
    return f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"


def _keyboard(report_id: int) -> InlineKeyboardMarkup:
    def b(text, icon, act):
        return ibtn(text, icon, callback_data=f"rep:{act}:{report_id}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("Варн", "warn", "warn"), b("Мут 1ч", "chain", "mute"), b("Бан", "skull", "ban")],
        [b("Удалить сообщение", "trash", "del")],
        [b("Решено", "check", "ok"), b("Отклонить", "alert", "no")],
    ])


def render_report(r, reporter: str, target: str, status_line: str | None = None) -> str:
    body = [f"На: {target}", f"От: {reporter}", f"Причина: {esc(r['reason'] or 'не указана')}"]
    if r["snippet"]:
        body.append(f"Сообщение: «{esc(r['snippet'])}»")
    text = f"{e('megaphone')} <b>Репорт #{r['id']}</b>\n" + quote("\n".join(body))
    link = _msg_link(r["chat_id"], r["message_id"])
    if link:
        text += f'\n<a href="{link}">Перейти к сообщению</a>'
    if status_line:
        text += f"\n{e('check')} {status_line}"
    return text


async def _moderator_ids(bot, exclude: set[int]) -> list[int]:
    """Кому слать репорт: админы чата в Telegram + назначенные в панели модераторы."""
    ids: set[int] = set()
    try:
        admins = await bot.get_chat_administrators(settings.allowed_chat_id)
        ids |= {a.user.id for a in admins if not a.user.is_bot}
    except TelegramAPIError:
        logger.warning("Не удалось получить список админов чата")
    ids |= set(await repo.admin_user_ids())
    return sorted(ids - exclude)


@router.message(Command("start"), F.chat.type == "private")
async def start_private(message: Message) -> None:
    await repo.touch_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(
        f"{e('check')} Готово. Если вы модератор чата, сюда будут приходить репорты с кнопками.\n"
        "Модератором считается админ чата в Telegram или человек, назначенный в админ-панели."
    )


@router.message(Command("report"))
@router.message(F.text.regexp(r"(?i)^(репорт|жалоба)\b"))
async def create_report(message: Message) -> None:
    text = message.text or ""
    args = re.sub(r"(?i)^(/report(@\w+)?|репорт|жалоба)", "", text, count=1).strip()
    target, reason = await target_and_rest(message, args)
    if target is None:
        await message.reply(f"{e('info')} Ответь на сообщение нарушителя: <code>репорт причина</code> (или укажи @ник).")
        return
    me = message.from_user
    if target.id == me.id:
        await message.reply(f"{e('warn')} На себя жаловаться нельзя.")
        return
    if target.is_bot or target.id == (await message.bot.me()).id:
        await message.reply(f"{e('warn')} На ботов репорты не принимаются.")
        return

    last = await repo.last_report_time(me.id)
    if last and (dt.datetime.utcnow() - last).total_seconds() < COOLDOWN_SEC:
        await message.reply(f"{e('clock')} Репорты можно отправлять не чаще раза в минуту.")
        return

    rm = message.reply_to_message
    snippet, msg_id = "", None
    if rm and rm.from_user and rm.from_user.id == target.id:
        msg_id = rm.message_id
        snippet = (rm.text or rm.caption or "[медиа без подписи]")[:200]

    report_id = await repo.create_report(me.id, target.id, message.chat.id, msg_id, reason, snippet)
    row = await repo.get_report(report_id)
    names = await nicks([me.id, target.id])
    card = render_report(row, names[me.id], names[target.id])

    delivered = 0
    recipients = await _moderator_ids(message.bot, exclude={me.id, target.id})
    for uid in recipients:
        try:
            sent = await message.bot.send_message(uid, card, reply_markup=_keyboard(report_id),
                                                  disable_web_page_preview=True)
            await repo.add_report_delivery(report_id, sent.chat.id, sent.message_id)
            delivered += 1
        except TelegramAPIError:
            # модератор не нажимал /start у бота, заблокировал его или сам вышел — это не ошибка
            logger.info("Репорт #%s: не удалось написать модератору %s (нужен /start боту)", report_id, uid)

    fallback_note = ""
    if delivered == 0 and reports_chat() != settings.allowed_chat_id:
        sent = await message.bot.send_message(reports_chat(), card, reply_markup=_keyboard(report_id),
                                              disable_web_page_preview=True)
        await repo.add_report_delivery(report_id, sent.chat.id, sent.message_id)
        delivered, fallback_note = 1, " (в чат модераторов)"
    elif delivered == 0:
        fallback_note = ""
        logger.warning("Репорт #%s: ни одному модератору не удалось написать", report_id)

    if delivered:
        await reply_rich(message, f"{e('check')} Репорт <b>#{report_id}</b> отправлен модераторам{fallback_note}.")
    else:
        await reply_rich(
            message, f"{e('warn')} Репорт <b>#{report_id}</b> сохранён, но модераторам сейчас не удалось написать. "
            "Пусть модераторы нажмут /start у бота, чтобы получать репорты."
        )


async def _refresh_deliveries(bot, report_id: int, text: str) -> None:
    """Убирает кнопки и пишет итог во всех копиях репорта."""
    for d in await repo.list_report_deliveries(report_id):
        try:
            await bot.edit_message_text(text=text, chat_id=d["chat_id"], message_id=d["message_id"],
                                        disable_web_page_preview=True)
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("rep:"))
async def handle_report_button(call: CallbackQuery) -> None:
    _, act, rid = call.data.split(":")
    report = await repo.get_report(int(rid))
    if report is None:
        await call.answer("Репорт не найден.", show_alert=True)
        return
    if not await can_moderate(call.bot, settings.allowed_chat_id, call.from_user.id):
        await call.answer("Это кнопки для модераторов.", show_alert=True)
        return
    if report["status"] != "open":
        await call.answer("Репорт уже обработан.", show_alert=True)
        return

    bot = call.bot
    chat_text = None
    if act in ("warn", "mute", "ban"):
        kw = {"duration_sec": 3600} if act == "mute" else {}
        ok, chat_text = await apply_action(
            bot, act, report["target_id"], reason=f"репорт #{report['id']}: {report['reason'] or '—'}",
            by_admin=call.from_user.id, **kw,
        )
        if not ok:
            await call.answer("Не вышло: цель — админ или у бота нет прав.", show_alert=True)
            return
    elif act == "del":
        try:
            await bot.delete_message(report["chat_id"], report["message_id"])
        except (TelegramAPIError, TypeError):
            await call.answer("Не получилось удалить сообщение (нет прав или оно уже удалено).", show_alert=True)
            return

    status = "rejected" if act == "no" else "resolved"
    if not await repo.close_report(report["id"], status, act, call.from_user.id):
        await call.answer("Репорт уже обработан.", show_alert=True)
        return

    names = await nicks([report["reporter_id"], report["target_id"]])
    done = f"{ACTION_LABELS[act].capitalize()} · {await nick(call.from_user.id)}"
    await _refresh_deliveries(bot, report["id"], render_report(
        report, names[report["reporter_id"]], names[report["target_id"]], status_line=done))
    if chat_text:
        await send_rich(bot, settings.allowed_chat_id, chat_text)
    await call.answer("Готово")
