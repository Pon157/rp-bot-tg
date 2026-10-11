"""Система репортов: участник жалуется ответом на сообщение нарушителя, модераторы
получают карточку с кнопками (варн / мут на час / бан / удалить сообщение / отклонить)."""
from __future__ import annotations

import datetime as dt
import re

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import repo
from bot.config import reports_chat, settings
from bot.emojis import e
from bot.moderation import apply_action, can_moderate
from bot.utils.formatting import esc, nick, nicks, quote, user_link
from bot.utils.targets import Person, target_and_rest

router = Router(name="reports")

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
    def b(text, act):
        return InlineKeyboardButton(text=text, callback_data=f"rep:{act}:{report_id}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [b("⚠️ Варн", "warn"), b("🔇 Мут 1ч", "mute"), b("⛔ Бан", "ban")],
        [b("🗑 Удалить сообщение", "del")],
        [b("✔️ Решено", "ok"), b("✖️ Отклонить", "no")],
    ])


def render_report(r, reporter: str, target: str, status_line: str | None = None, mods: str | None = None) -> str:
    body = [f"На: {target}", f"От: {reporter}", f"Причина: {esc(r['reason'] or 'не указана')}"]
    if r["snippet"]:
        body.append(f"Сообщение: «{esc(r['snippet'])}»")
    text = f"{e('megaphone')} <b>Репорт #{r['id']}</b>\n" + quote("\n".join(body))
    link = _msg_link(r["chat_id"], r["message_id"])
    if link:
        text += f'\n<a href="{link}">Перейти к сообщению</a>'
    if mods:
        text += f"\n{e('bell')} Модераторы: {mods}"
    if status_line:
        text += f"\n{e('check')} {status_line}"
    return text


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
    snippet = ""
    msg_id = None
    if rm and rm.from_user and rm.from_user.id == target.id:
        msg_id = rm.message_id
        snippet = (rm.text or rm.caption or "[медиа без подписи]")[:200]

    report_id = await repo.create_report(me.id, target.id, message.chat.id, msg_id, reason, snippet)
    row = await repo.get_report(report_id)

    mods = ""
    try:
        admins = await message.bot.get_chat_administrators(reports_chat())
        mods = ", ".join(user_link(a.user.id, a.user.first_name, a.user.username) for a in admins if not a.user.is_bot)
    except TelegramAPIError:
        pass

    post = await message.bot.send_message(
        reports_chat(),
        render_report(row, user_link(me.id, me.first_name, me.username),
                      user_link(target.id, target.first_name, target.username), mods=mods or None),
        reply_markup=_keyboard(report_id),
        disable_web_page_preview=True,
    )
    await repo.set_report_post(report_id, post.chat.id, post.message_id)
    await message.reply(f"{e('check')} Репорт <b>#{report_id}</b> отправлен модераторам.")


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
    await call.message.edit_text(
        render_report(report, names[report["reporter_id"]], names[report["target_id"]], status_line=done),
        disable_web_page_preview=True,
    )
    if chat_text:
        await bot.send_message(settings.allowed_chat_id, chat_text)
    await call.answer("Готово")
