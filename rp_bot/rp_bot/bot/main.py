from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.db import init_db
from bot.handlers import root_router
from bot.middlewares import ChatGuardMiddleware, ActivityMiddleware, MyChatMemberGuard
from bot.handlers.rules import rules_broadcast_loop
from bot.handlers.relationships import auto_dissolve_loop, blood_decay_loop
from bot.moderation import mod_queue_loop, warn_expiry_loop
from bot.panel import start_panel, stop_panel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rp_bot")


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.outer_middleware(ChatGuardMiddleware())
    dp.message.outer_middleware(ActivityMiddleware())
    dp.my_chat_member.outer_middleware(MyChatMemberGuard())

    dp.include_router(root_router)

    me = await bot.get_me()
    logger.info("Бот @%s (id=%s). Разрешённый чат: %s", me.username, me.id, settings.allowed_chat_id)
    if not me.can_read_all_group_messages:
        logger.warning(
            "ПРИВАТНОСТЬ ВКЛЮЧЕНА: бот в группах видит только /команды. "
            "Отключите в @BotFather: /setprivacy -> Disable, затем удалите бота из чата и добавьте заново."
        )

    background_tasks = [
        asyncio.create_task(rules_broadcast_loop(bot)),
        asyncio.create_task(auto_dissolve_loop(bot)),
        asyncio.create_task(blood_decay_loop(bot)),
        asyncio.create_task(mod_queue_loop(bot)),
        asyncio.create_task(warn_expiry_loop(bot)),
    ]

    panel = await start_panel()      # админ-панель стартует вместе с ботом

    try:
        logger.info("Бот запущен, поллинг...")
        await dp.start_polling(bot)
    finally:
        for t in background_tasks:
            t.cancel()
        await stop_panel(panel)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
