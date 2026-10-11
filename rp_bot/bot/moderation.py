"""Единое ядро модерации. Им пользуются:
 - команды в чате (handlers/modcmds.py),
 - репорты (handlers/reports.py),
 - наказания за проигрыш в играх,
 - очередь действий из админ-панели (mod_queue_loop).
Везде реально вызывается Telegram API, а в чат уходит правда: если не вышло —
бот так и пишет, а не «забанен».
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.rich import send_rich
from bot.utils.formatting import esc, fmt_dt, nick, quote

logger = logging.getLogger("rp_bot.moderation")

UTC = dt.timezone.utc
FOREVER_DT = dt.datetime(9999, 12, 31)


# --------------------------------------------------------------- права ----

async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    return member.status in ("creator", "administrator")


async def can_moderate(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Модератор = админ чата в Telegram ИЛИ человек, назначенный в админ-панели."""
    if await repo.is_admin(user_id):
        return True
    return await is_chat_admin(bot, chat_id, user_id)


async def is_protected(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Кого наказывать нельзя: сам бот, админы чата и назначенные модераторы."""
    me = await bot.me()
    if user_id == me.id:
        return True
    if await repo.is_admin(user_id):
        return True
    return await is_chat_admin(bot, chat_id, user_id)


# ---------------------------------------------------------------- ядро ----

def _fail(text: str) -> tuple[bool, str]:
    return False, f"{e('alert')} {text}"


async def apply_action(bot: Bot, action: str, user_id: int, *, duration_sec: int | None = None,
                       reason: str = "", by_admin: int | None = None,
                       warn_expires_days: int | None = None) -> tuple[bool, str]:
    """action: warn | unwarn | mute | unmute | ban | unban | kick.
    duration_sec для mute: None = навсегда. Возвращает (получилось, HTML-текст для чата)."""
    chat_id = settings.allowed_chat_id
    target = await nick(user_id)
    actor = await nick(by_admin) if by_admin else None
    reason_line = f"Причина: {esc(reason)}" if reason else "Причина: не указана"

    def card(title_emoji: str, title: str, *lines: str) -> str:
        extra = list(lines) + [reason_line] if action in ("warn", "mute", "ban", "kick") else list(lines)
        if actor:
            extra.append(f"Выдал: {actor}")
        return f"{e(title_emoji)} <b>{title}</b> · {target}\n" + quote("\n".join(extra))

    if action in ("warn", "mute", "ban", "kick") and await is_protected(bot, chat_id, user_id):
        return _fail(f"{target} — админ или бот, наказать нельзя.")

    try:
        if action == "warn":
            await repo.ensure_user(user_id)
            warns = await repo.apply_warn(user_id, warn_expires_days)
            await repo.add_mod_log(user_id, "warn", reason, by_admin)
            lines = [f"Варнов: <b>{warns}</b>"]
            if warn_expires_days:
                lines.append(f"Снимется через {warn_expires_days} дн.")
            return True, card("warn", "Варн", *lines)

        if action == "unwarn":
            warns = await repo.apply_unwarn(user_id)
            await repo.add_mod_log(user_id, "unwarn", reason, by_admin)
            return True, card("check", "Варн снят", f"Осталось варнов: <b>{warns}</b>")

        if action == "mute":
            await repo.ensure_user(user_id)
            until = None if duration_sec is None else dt.datetime.now(UTC) + dt.timedelta(seconds=duration_sec)
            await bot.restrict_chat_member(
                chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until
            )
            await repo.apply_mute(user_id, FOREVER_DT if until is None else until.replace(tzinfo=None))
            await repo.add_mod_log(user_id, "mute", reason, by_admin)
            when = "навсегда" if until is None else f"до {fmt_dt(until.replace(tzinfo=None).isoformat())} UTC"
            return True, card("chain", "Мут", f"Срок: <b>{when}</b>")

        if action == "unmute":
            chat = await bot.get_chat(chat_id)
            perms = chat.permissions or ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
                can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True,
                can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True,
            )
            await bot.restrict_chat_member(chat_id, user_id, permissions=perms)
            await repo.clear_mute(user_id)
            await repo.add_mod_log(user_id, "unmute", reason, by_admin)
            return True, card("check", "Мут снят")

        if action == "ban":
            await repo.ensure_user(user_id)
            await bot.ban_chat_member(chat_id, user_id)
            await repo.apply_ban(user_id)
            await repo.add_mod_log(user_id, "ban", reason, by_admin)
            return True, card("skull", "Бан")

        if action == "unban":
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            await repo.clear_ban(user_id)
            await repo.add_mod_log(user_id, "unban", reason, by_admin)
            return True, card("check", "Разбан")

        if action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            await repo.add_mod_log(user_id, "kick", reason, by_admin)
            return True, card("flag", "Кик")

    except TelegramAPIError as exc:
        logger.warning("Действие %s для %s не удалось: %s", action, user_id, exc)
        return _fail(
            f"Не получилось ({esc(action)}): {esc(getattr(exc, 'message', str(exc)))}.\n"
            "Проверьте, что бот — админ чата с правом блокировать участников."
        )
    return _fail(f"Неизвестное действие: {esc(action)}")


# --------------------------------------------------------- фоновые задачи ----

async def mod_queue_loop(bot: Bot, poll_seconds: int = 5) -> None:
    """Исполняет действия, поставленные из админ-панели."""
    while True:
        try:
            for item in await repo.fetch_mod_queue():
                ok, text = await apply_action(
                    bot, item["action"], item["user_id"], duration_sec=item["duration_sec"],
                    reason=item["reason"] or "", by_admin=item["by_admin"],
                )
                await repo.mark_mod_queue_done(item["id"])
                try:
                    await send_rich(bot, settings.allowed_chat_id, text)
                except TelegramAPIError:
                    logger.exception("Не удалось отправить итог модерации в чат")
        except Exception:
            logger.exception("Ошибка в mod_queue_loop")
        await asyncio.sleep(poll_seconds)


async def warn_expiry_loop(bot: Bot, poll_seconds: int = 3600) -> None:
    """Снимает варны, срок которых истёк (например варн на неделю за проигрыш в игре)."""
    while True:
        try:
            for user_id in await repo.process_expired_warns():
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"{e('check')} {await nick(user_id)} — один варн истёк и снят.",
                )
        except Exception:
            logger.exception("Ошибка в warn_expiry_loop")
        await asyncio.sleep(poll_seconds)
