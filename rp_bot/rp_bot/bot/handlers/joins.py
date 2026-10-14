"""Вход участника в чат: если на него стоит отложенный бан (см. moderation.apply_action), баним сразу.
Работает, только если бот — админ чата (Telegram присылает chat_member только администраторам)."""
from aiogram import Router
from aiogram.types import ChatMemberUpdated

from bot.config import settings
from bot.middlewares import apply_pending_ban

router = Router(name="joins")


@router.chat_member()
async def on_member_change(event: ChatMemberUpdated) -> None:
    if event.chat.id != settings.allowed_chat_id:
        return
    if event.new_chat_member.status not in ("member", "restricted"):
        return
    await apply_pending_ban(event.bot, event.new_chat_member.user.id)
