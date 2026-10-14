"""Одноразовый вход аккаунта-помощника. Запускается на сервере вручную:
    cd ~/rp-bot-tg/rp_bot && source venv/bin/activate && python -m bot.userbot_login
Спросит номер телефона, код из Telegram и (если включён) пароль 2FA.
Результат — файл data/userbot.session. Его не коммитьте: это доступ к аккаунту."""
import asyncio


async def main() -> None:
    # Импорт Pyrogram внутри работающего цикла событий: при импорте на верхнем уровне
    # с uvloop (его ставит uvicorn[standard]) Pyrogram 2.0.x падает.
    from pyrogram import Client

    from bot.config import settings
    from bot.userbot import SESSION_NAME, data_dir, session_file

    if not (settings.userbot_api_id and settings.userbot_api_hash):
        print("Сначала укажите USERBOT_API_ID и USERBOT_API_HASH в .env (берутся на my.telegram.org)")
        return
    data_dir().mkdir(parents=True, exist_ok=True)
    app = Client(SESSION_NAME, api_id=settings.userbot_api_id, api_hash=settings.userbot_api_hash,
                 workdir=str(data_dir()), no_updates=True)
    await app.start()
    me = await app.get_me()
    await app.stop()
    print(f"Готово: вошли как {me.first_name} (id {me.id}). Сессия: {session_file()}")


if __name__ == "__main__":
    asyncio.run(main())
