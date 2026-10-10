from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, ChatMemberUpdated

from bot import repo
from bot.config import settings


class ChatGuardMiddleware(BaseMiddleware):
    """Бот работает только в одном разрешённом чате. Если его добавили ещё куда-то —
    он сразу об этом сообщает и не выполняет никаких команд там."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        if chat is None and hasattr(event, "message") and event.message:
            chat = event.message.chat

        if chat is not None and chat.type != "private" and chat.id != settings.allowed_chat_id:
            if isinstance(event, Message):
                await event.answer(
                    f"Я блять не в этой хуйне рожден. Верни меня в @{settings.bot_username}"
                )
            return None
        return await handler(event, data)


class MyChatMemberGuard(BaseMiddleware):
    """Ловит момент добавления бота в чужой чат и сразу пишет туда предупреждение,
    даже до того, как кто-то успеет написать команду."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: ChatMemberUpdated,
        data: dict[str, Any],
    ) -> Any:
        if event.chat.id != settings.allowed_chat_id and event.new_chat_member.status in ("member", "administrator"):
            bot = data["bot"]
            try:
                await bot.send_message(
                    event.chat.id,
                    f"Я блять не в этой хуйне рожден. Верни меня в @{settings.bot_username}",
                )
                await bot.leave_chat(event.chat.id)
            except Exception:
                pass
            return None
        return await handler(event, data)


class ActivityMiddleware(BaseMiddleware):
    """Регистрирует пользователя и считает статистику сообщений для команды 'кто я'."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            await repo.touch_user(event.from_user.id, event.from_user.username, event.from_user.first_name)
        return await handler(event, data)
