"""Аккаунт-помощник (пользовательская сессия Pyrogram).

Нужен только там, где Bot API не справляется:
  • узнать ID по @нику, если человека нет в базе бота (публичный юзернейм);
  • забанить человека, которого Telegram не видит боту по ID.

Включается, если заданы USERBOT_API_ID / USERBOT_API_HASH и есть файл data/userbot.session
(создаётся один раз командой: python -m bot.userbot_login). Без этого бот работает как раньше.
Аккаунт должен быть отдельным, а админом чата — с правом блокировки участников.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from pyrogram import Client
from pyrogram.errors import FloodWait, PeerIdInvalid, RPCError, UsernameInvalid, UsernameNotOccupied

from bot.config import settings

logger = logging.getLogger("rp_bot.userbot")

SESSION_NAME = "userbot"
CACHE_TTL = 600  # сек: ник не дёргаем у Telegram чаще раза в 10 минут

_client: Client | None = None
_lock = asyncio.Lock()
_name_cache: dict[str, tuple[float, dict | None]] = {}


def data_dir() -> Path:
    return Path(settings.db_path).resolve().parent


def session_file() -> Path:
    return data_dir() / f"{SESSION_NAME}.session"


def enabled() -> bool:
    return bool(settings.userbot_api_id and settings.userbot_api_hash and session_file().exists())


async def _get() -> Client | None:
    """Ленивый запуск клиента; один клиент на процесс."""
    global _client
    if not enabled():
        return None
    async with _lock:
        if _client is None:
            _client = Client(SESSION_NAME, api_id=settings.userbot_api_id, api_hash=settings.userbot_api_hash,
                             workdir=str(data_dir()), no_updates=True)
            await _client.start()
            logger.info("Аккаунт-помощник запущен")
    return _client


async def resolve_username(name: str) -> dict | None:
    """По @нику вернуть {'id', 'first_name', 'username', 'is_bot'} или None."""
    key = name.lstrip("@").casefold()
    if not key:
        return None
    hit = _name_cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]

    result: dict | None = None
    try:
        client = await _get()
        if client is not None:
            user = await client.get_users(key)
            result = {"id": user.id, "first_name": user.first_name, "username": user.username,
                      "is_bot": bool(user.is_bot)}
    except (UsernameInvalid, UsernameNotOccupied, PeerIdInvalid):
        result = None
    except FloodWait as exc:
        logger.warning("Аккаунт-помощник: FloodWait %s сек при резолве @%s", exc.value, key)
        return None  # не кэшируем: попробуем позже
    except RPCError:
        logger.exception("Аккаунт-помощник: ошибка при резолве @%s", key)
        return None
    _name_cache[key] = (time.monotonic(), result)
    return result


async def ban(chat_id: int, user_id: int) -> tuple[bool, str]:
    """Бан через аккаунт-помощник. Возвращает (получилось, текст ошибки)."""
    try:
        client = await _get()
        if client is None:
            return False, "аккаунт-помощник не настроен"
        # Pyrogram должен знать участника (access hash). Для этого сначала просим его у Telegram.
        await client.get_users(user_id)
        await client.ban_chat_member(chat_id, user_id)
        return True, ""
    except FloodWait as exc:
        return False, f"лимит Telegram, подождите {exc.value} сек"
    except (PeerIdInvalid, UsernameInvalid, UsernameNotOccupied) as exc:
        return False, f"Telegram не видит этого человека ({exc.__class__.__name__})"
    except RPCError as exc:
        return False, str(exc)
