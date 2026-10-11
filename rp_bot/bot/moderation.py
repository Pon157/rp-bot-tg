from __future__ import annotations

import asyncio
import datetime as dt

from aiogram import Bot
from aiogram.types import ChatPermissions

from bot import repo
from bot.config import settings
from bot.emojis import e


async def mod_queue_loop(bot: Bot, poll_seconds: int = 5) -> None:
    """Раз в несколько секунд исполняет действия модерации, поставленные из админ-панели:
    реально мутит/банит человека в разрешённом чате и уведомляет чат."""
    while True:
        try:
            for item in await repo.fetch_mod_queue():
                await _apply(bot, item)
                await repo.mark_mod_queue_done(item["id"])
        except Exception:
            pass
        await asyncio.sleep(poll_seconds)


async def warn_expiry_loop(bot: Bot, poll_seconds: int = 3600) -> None:
    """Снимает варны, срок действия которых истёк (например варны за проигрыш в играх,
    которые по правилам держатся неделю)."""
    while True:
        try:
            for user_id in await repo.process_expired_warns():
                await bot.send_message(
                    settings.allowed_chat_id,
                    f'{e("check")} <a href="tg://user?id={user_id}">Пользователь</a> — один варн истёк и снят.',
                    parse_mode="HTML",
                )
        except Exception:
            pass
        await asyncio.sleep(poll_seconds)


async def _apply(bot: Bot, item) -> None:
    user_id = item["user_id"]
    action = item["action"]
    chat_id = settings.allowed_chat_id

    if action == "warn":
        warns = await repo.apply_warn(user_id)
        await repo.add_mod_log(user_id, "warn", item["reason"], item["by_admin"])
        await bot.send_message(
            chat_id, f'{e("warn")} <a href="tg://user?id={user_id}">Пользователь</a> получает варн '
                     f'(всего: {warns}). Причина: {item["reason"] or "не указана"}',
            parse_mode="HTML",
        )
    elif action == "mute":
        seconds = item["duration_sec"] or 3600
        until = dt.datetime.utcnow() + dt.timedelta(seconds=seconds)
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except Exception:
            pass
        await repo.apply_mute(user_id, until)
        await repo.add_mod_log(user_id, "mute", item["reason"], item["by_admin"])
        await bot.send_message(
            chat_id, f'{e("chain")} <a href="tg://user?id={user_id}">Пользователь</a> получает мут до '
                     f'{until.strftime("%d.%m.%Y %H:%M")} UTC. Причина: {item["reason"] or "не указана"}',
            parse_mode="HTML",
        )
    elif action == "unmute":
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_photos=True, can_send_videos=True,
                    can_send_other_messages=True,
                ),
            )
        except Exception:
            pass
    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id, user_id)
        except Exception:
            pass
        await repo.apply_ban(user_id)
        await repo.add_mod_log(user_id, "ban", item["reason"], item["by_admin"])
        await bot.send_message(
            chat_id, f'{e("skull")} <a href="tg://user?id={user_id}">Пользователь</a> забанен. '
                     f'Причина: {item["reason"] or "не указана"}',
            parse_mode="HTML",
        )
    elif action == "unban":
        try:
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        except Exception:
            pass
