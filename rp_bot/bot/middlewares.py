from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import ChatMemberUpdated, Message, TelegramObject

from bot import repo
from bot.moderation import apply_action
from bot.config import reports_chat, settings

STRANGER = "Я блять не в этой хуйне рожден. Верни меня в @{username}"


def _known_chats() -> set[int]:
    return {settings.allowed_chat_id, reports_chat()}


class ChatGuardMiddleware(BaseMiddleware):
    """Бот работает только в своём чате (и, если задан, в чате модераторов для репортов).
    В любом другом чате отвечает фирменной фразой и молчит."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        chat = getattr(event, "chat", None)
        if chat is not None and chat.type != "private" and chat.id not in _known_chats():
            if isinstance(event, Message):
                await event.answer(STRANGER.format(username=settings.bot_username))
            return None
        if chat is not None and chat.type != "private" and chat.id != settings.allowed_chat_id:
            return None  # чат модераторов: только кнопки репортов, команды не исполняем
        return await handler(event, data)


class MyChatMemberGuard(BaseMiddleware):
    """Добавили бота в чужой чат — он сразу предупреждает и выходит."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: ChatMemberUpdated, data: dict[str, Any]) -> Any:
        if event.chat.id not in _known_chats() and event.new_chat_member.status in ("member", "administrator"):
            bot = data["bot"]
            try:
                await bot.send_message(event.chat.id, STRANGER.format(username=settings.bot_username))
                await bot.leave_chat(event.chat.id)
            except Exception:
                pass
            return None
        return await handler(event, data)


class ActivityMiddleware(BaseMiddleware):
    """Регистрирует пользователя и считает статистику сообщений для «кто я»."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            await repo.touch_user(event.from_user.id, event.from_user.username, event.from_user.first_name)
            await apply_pending_ban(event.bot, event.from_user.id)
        return await handler(event, data)


async def apply_pending_ban(bot, user_id: int) -> None:
    """Если на этого человека стоит отложенный бан, применяем его теперь, когда Telegram его видит."""
    if not user_id:
        return
    pending = await repo.pop_pending_ban(user_id)
    if pending is None:
        return
    _, text = await apply_action(bot, "ban", user_id, reason=pending["reason"] or "",
                                 by_admin=pending["by_admin"])
    await bot.send_message(settings.allowed_chat_id, text)
