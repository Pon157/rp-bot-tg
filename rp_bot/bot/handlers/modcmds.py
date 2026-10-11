"""Команды модерации в чате. Работают ответом на сообщение нарушителя
или с указанием @ника / ID. Обычным участникам молча не отвечают (кроме `варны`)."""
from __future__ import annotations

import datetime as dt
import re

from aiogram import Router, F
from aiogram.types import Message

from bot import repo
from bot.emojis import e
from bot.moderation import apply_action, can_moderate
from bot.utils.formatting import (
    FOREVER, esc, fit_lines, fmt_dt, nicks, parse_duration, quote, table,
)
from bot.utils.targets import Person, target_and_rest

router = Router(name="modcmds")

HINT = f"{e('info')} Ответь командой на сообщение человека или укажи @ник / ID."


async def _moderator(message: Message) -> tuple[bool, int | None]:
    """(является ли модератором, id для лога). Админ, пишущий анонимно, тоже модератор."""
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True, None
    if not message.from_user:
        return False, None
    ok = await can_moderate(message.bot, message.chat.id, message.from_user.id)
    return ok, message.from_user.id


async def _prepare(message: Message, pattern: str):
    """Проверка прав + разбор цели. None = дальше не идём (ответ уже отправлен или игнор)."""
    is_mod, actor = await _moderator(message)
    if not is_mod:
        return None
    text = message.text or ""
    m = re.match(pattern, text, flags=re.I)
    args = text[m.end():].strip() if m else ""
    target, rest = await target_and_rest(message, args)
    if target is None:
        await message.reply(HINT)
        return None
    if actor is not None and target.id == actor:
        await message.reply(f"{e('warn')} На себя такое не направить.")
        return None
    if target.is_bot:
        await message.reply(f"{e('warn')} С ботами не связываемся.")
        return None
    return actor, target, rest


@router.message(F.text.regexp(r"(?i)^варн\b"))
async def cmd_warn(message: Message) -> None:
    prep = await _prepare(message, r"(?i)^варн\b")
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "warn", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^(снять\s+варн|унварн)\b"))
async def cmd_unwarn(message: Message) -> None:
    pat = r"(?i)^(снять\s+варн|унварн)\b"
    prep = await _prepare(message, pat)
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "unwarn", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^мут\b"))
async def cmd_mute(message: Message) -> None:
    prep = await _prepare(message, r"(?i)^мут\b")
    if not prep:
        return
    actor, target, rest = prep
    seconds, reason = parse_duration(rest)
    if seconds is None:
        seconds, reason = 3600, rest          # без срока — час
    duration = None if seconds == FOREVER else seconds
    _, text = await apply_action(message.bot, "mute", target.id, duration_sec=duration, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^(размут|анмут)\b"))
async def cmd_unmute(message: Message) -> None:
    pat = r"(?i)^(размут|анмут)\b"
    prep = await _prepare(message, pat)
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "unmute", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^бан\b"))
async def cmd_ban(message: Message) -> None:
    prep = await _prepare(message, r"(?i)^бан\b")
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "ban", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^(разбан|анбан)\b"))
async def cmd_unban(message: Message) -> None:
    pat = r"(?i)^(разбан|анбан)\b"
    prep = await _prepare(message, pat)
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "unban", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


@router.message(F.text.regexp(r"(?i)^кик\b"))
async def cmd_kick(message: Message) -> None:
    prep = await _prepare(message, r"(?i)^кик\b")
    if not prep:
        return
    actor, target, reason = prep
    _, text = await apply_action(message.bot, "kick", target.id, reason=reason, by_admin=actor)
    await message.reply(text)


# ------------------------------------------------------------ просмотр ----

@router.message(F.text.regexp(r"(?i)^варны\b"))
async def cmd_warns(message: Message) -> None:
    """Доступна всем: свои варны или (ответом/@ником) чужие."""
    args = (message.text or "")[len("варны"):].strip()
    target, _ = await target_and_rest(message, args)
    target = target or Person.from_user(message.from_user)

    row = await repo.get_user(target.id)
    if row is None:
        await message.reply(f"{e('info')} Этого человека нет в базе — нарушений нет.")
        return
    name = (await nicks([target.id]))[target.id]
    muted = row["muted_until"] and row["muted_until"] > dt.datetime.utcnow().isoformat()
    mute_text = "нет" if not muted else ("навсегда" if row["muted_until"].startswith("9999") else f"до {fmt_dt(row['muted_until'])} UTC")
    head = (
        f"{e('warn')} <b>Нарушения</b> · {name}\n"
        + quote(f"Варнов: <b>{row['warns']}</b>\nМут: {mute_text}\nБан: {'да' if row['banned'] else 'нет'}")
    )
    log = await repo.user_mod_log(target.id, 8)
    if log:
        rows = [(fmt_dt(r["created_at"])[:5] + " " + fmt_dt(r["created_at"])[11:], r["action"], r["reason"] or "—") for r in log]
        head += "\n" + table(["Когда", "Что", "Причина"], rows, max_widths=[11, 7, 16])
    await message.reply(head)


async def _list_users(message: Message, rows, title: str, emoji: str, extra) -> None:
    is_mod, _ = await _moderator(message)
    if not is_mod:
        return
    if not rows:
        await message.reply(f"{e('check')} {title}: никого нет.")
        return
    names = await nicks([r["user_id"] for r in rows])
    lines = [f"{i}. {names[r['user_id']]}{extra(r)}" for i, r in enumerate(rows, 1)]
    shown, hidden = fit_lines(lines)
    tail = f"\n…и ещё {hidden}" if hidden else ""
    await message.reply(f"{e(emoji)} <b>{title}</b> · {len(rows)}\n" + quote("\n".join(shown) + tail, expandable=len(rows) > 8))


@router.message(F.text.casefold() == "муты")
async def cmd_mutes(message: Message) -> None:
    rows = await repo.list_muted()
    await _list_users(message, rows, "В муте", "chain",
                      lambda r: " — навсегда" if r["muted_until"].startswith("9999") else f" — до {fmt_dt(r['muted_until'])[:16]}")


@router.message(F.text.casefold() == "баны")
async def cmd_bans(message: Message) -> None:
    rows = await repo.list_banned()
    await _list_users(message, rows, "Забанены", "skull", lambda r: "")
