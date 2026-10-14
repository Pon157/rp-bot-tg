"""Автомут за спам: если участник написал слишком много сообщений за короткое время, бот мутит его.
Настройки — в админ-панели (раздел «Настройки»), хранятся в таблице meta:
  spam_enabled (0/1), spam_max_messages, spam_window_sec, spam_mute_minutes.
Модераторы и админы чата не наказываются."""
from __future__ import annotations

import collections
import time

from aiogram import Bot
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.moderation import apply_action, is_protected
from bot.rich import send_rich

_hits: dict[int, collections.deque] = collections.defaultdict(collections.deque)
_cfg_cache: dict = {"at": 0.0, "cfg": None}


async def get_config() -> dict:
    if _cfg_cache["cfg"] is None or time.monotonic() - _cfg_cache["at"] > 15:
        _cfg_cache["cfg"] = {
            "enabled": (await repo.get_meta("spam_enabled", "0")) == "1",
            "max": max(2, int(await repo.get_meta("spam_max_messages", "6") or 6)),
            "window": max(1, int(await repo.get_meta("spam_window_sec", "10") or 10)),
            "mute_min": max(1, int(await repo.get_meta("spam_mute_minutes", "10") or 10)),
        }
        _cfg_cache["at"] = time.monotonic()
    return _cfg_cache["cfg"]


async def check_spam(bot: Bot, message: Message) -> bool:
    """Вызывается на каждое сообщение. True — если участник только что замучен за спам."""
    if message.chat.id != settings.allowed_chat_id or not message.from_user or message.from_user.is_bot:
        return False
    cfg = await get_config()
    if not cfg["enabled"]:
        return False

    now = time.monotonic()
    dq = _hits[message.from_user.id]
    dq.append(now)
    while dq and now - dq[0] > cfg["window"]:
        dq.popleft()
    if len(dq) < cfg["max"]:
        return False

    dq.clear()
    uid = message.from_user.id
    if await is_protected(bot, settings.allowed_chat_id, uid):
        return False  # админов и модераторов не мутим
    _, text = await apply_action(
        bot, "mute", uid, duration_sec=cfg["mute_min"] * 60,
        reason=f"автоматически: спам ({cfg['max']}+ сообщений за {cfg['window']} сек)",
    )
    await send_rich(bot, settings.allowed_chat_id, text)
    return True
