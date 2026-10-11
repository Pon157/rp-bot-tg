from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.types import Message

from bot.config import settings
from bot.emojis import e

router = Router(name="fun")


@router.message(F.text.casefold() == "кто админ")
async def who_admin(message: Message) -> None:
    await message.reply("а тебя это ебать не должно")


@router.message(F.text.regexp(r"^кто\s+(?P<q>.+)$", flags=0))
async def who_random(message: Message) -> None:
    q = message.text.split(" ", 1)[1].strip()
    if q.casefold() in ("я", "админ"):
        return  # обрабатывается другими хэндлерами
    member_ids = await _chat_member_sample(message)
    if not member_ids:
        await message.reply("В чате пока некого выбрать 🤷")
        return
    chosen = random.choice(member_ids)
    display = f"@{chosen.username}" if chosen.username else chosen.first_name
    await message.reply(f"{q.capitalize()} — {display}")


@router.message(F.text.regexp(r"^шанс\s+(?P<q>.+)$", flags=0))
async def chance(message: Message) -> None:
    q = message.text.split(" ", 1)[1].strip()
    percent = random.randint(0, 100)
    await message.reply(f"{e('search')} {q} — {percent}%", parse_mode="HTML")


@router.message(F.text == "/help")
async def help_cmd(message: Message) -> None:
    text = (
        f"{e('info')} <b>Список команд</b>\n\n"
        "<b>Профиль</b>\n"
        "• кто я — карточка профиля\n"
        "• +описание [текст] — задать описание профиля\n\n"
        "<b>Отношения</b>\n"
        "• мутки @юзер — предложить отношения\n"
        "• брак @юзер — предложить брак по расчету\n"
        "• принять / отклонить — ответ на предложение\n"
        "• расторжение @юзер — разорвать отношения/брак\n"
        "• мои отношения — список ваших отношений и браков\n\n"
        "<b>Экономика</b>\n"
        "• фарма / ферма — получить монеты (раз в 4 часа)\n"
        "• баланс — ваш баланс монет\n\n"
        "<b>Игры</b>\n"
        "• кости [ставка] — игра в кости\n"
        "• дуэль ставка [число] — дуэль на монеты\n"
        "• дуэль — дуэль на наказание\n"
        "• монеточка [ставка|наказание] — игра монеточка\n"
        "• пианино [ставка|наказание] — игра пианино\n\n"
        "<b>Разное</b>\n"
        "• правила — показать правила чата\n"
        "• кто &lt;вопрос&gt; — бот выбирает случайного участника\n"
        "• шанс &lt;действие&gt; — случайный процент\n"
        "• /links — полезные ссылки"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "/links")
async def links_cmd(message: Message) -> None:
    text = (
        f"{e('link')} <b>Ссылки</b>\n\n"
        f"{e('info')} Наш бот: @{settings.bot_username}\n"
        f"{e('megaphone')} Наш тгк: {settings.bot_channel_url}"
    )
    await message.answer(text, parse_mode="HTML")


async def _chat_member_sample(message: Message, limit: int = 30):
    """aiogram/Bot API не даёт списка всех участников чата, поэтому берём тех,
    кто уже писал в чат (зарегистрированы в БД через ActivityMiddleware)."""
    from bot import repo
    import aiosqlite

    async with aiosqlite.connect(repo.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT user_id, username, first_name FROM users ORDER BY last_activity_at DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()

    class _U:
        def __init__(self, r):
            self.username = r["username"]
            self.first_name = r["first_name"]

    return [_U(r) for r in rows]
