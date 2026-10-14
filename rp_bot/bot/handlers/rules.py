from __future__ import annotations

import asyncio

from aiogram import Router, F, Bot
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e

router = Router(name="rules")


@router.message(F.text.casefold() == "правила")
async def show_rules(message: Message) -> None:
    rules = await repo.get_rules()
    await message.answer(f"{e('book')} <b>Правила чата</b>\n\n{rules['text']}", parse_mode="HTML")


async def rules_broadcast_loop(bot: Bot, poll_seconds: int = 15) -> None:
    """Фоновая задача: раз в poll_seconds секунд проверяет, не обновили ли правила
    через админ-панель (флаг broadcasted=0), и если да — постит их в чат."""
    while True:
        try:
            rules = await repo.get_rules()
            if not rules["broadcasted"]:
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"{e('megaphone')} <b>Правила чата обновлены:</b>\n\n{rules['text']}",
                    parse_mode="HTML",
                )
                await repo.mark_rules_broadcasted()
        except Exception:
            pass
        await asyncio.sleep(poll_seconds)
