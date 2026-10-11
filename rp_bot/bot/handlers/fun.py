from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.utils.formatting import esc, quote, user_link

router = Router(name="fun")


@router.message(F.text.casefold() == "кто админ")
async def who_admin(message: Message) -> None:
    await message.reply("а тебя это ебать не должно")


@router.message(F.text.regexp(r"(?i)^кто\s+(?P<q>.+)$"))
async def who_random(message: Message) -> None:
    q = message.text.split(None, 1)[1].strip()
    if q.casefold() in ("я", "админ"):
        return  # обрабатывается другими хэндлерами
    rows = await repo.recent_users(30)
    if not rows:
        await message.reply("В чате пока некого выбрать 🤷")
        return
    chosen = random.choice(rows)
    await message.reply(f"{esc(q.capitalize())} — {user_link(chosen['user_id'], chosen['first_name'], chosen['username'])}")


@router.message(F.text.regexp(r"^шанс\s+(?P<q>.+)$", flags=0))
async def chance(message: Message) -> None:
    q = message.text.split(" ", 1)[1].strip()
    percent = random.randint(0, 100)
    await message.reply(f"{e('search')} {esc(q)} — <b>{percent}%</b>")


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    text = (
        f"{e('info')} <b>Команды бота</b>\n"
        "<i>Кого-то указываем ответом на его сообщение или через @ник (человек должен хоть раз писать в чат).</i>\n\n"
        f"{e('person')} <b>Профиль</b>\n"
        + quote(
            "<code>кто я</code> — карточка профиля\n"
            "<code>+описание текст</code> — описание в профиль"
        )
        + f"\n{e('heart')} <b>Отношения</b>\n"
        + quote(
            "<code>мутки</code> — предложить отношения (капли крови)\n"
            "<code>брак</code> — предложить брак по расчёту\n"
            "<code>расторжение</code> — расторгнуть связь\n"
            "<code>мои отношения</code> · <code>отношения</code> · <code>браки</code> — списки\n"
            "Принять/отклонить — кнопками под предложением"
        )
        + f"\n{e('fire')} <b>RP-действия</b>\n"
        + quote("<code>ударить</code>, <code>обнять</code>, <code>поцеловать</code> … — полный набор задаёт администрация")
        + f"\n{e('coin')} <b>Монеты и игры</b>\n"
        + quote(
            "<code>фарма</code> / <code>ферма</code> — монеты раз в 4 часа, <code>баланс</code>\n"
            "<code>кости</code> · <code>дуэль</code> · <code>монеточка</code> · <code>пианино</code>\n"
            "добавь <code>ставка 50</code> — играть на монеты, иначе на наказание"
        )
        + f"\n{e('megaphone')} <b>Репорты</b>\n"
        + quote("<code>репорт причина</code> — ответом на сообщение нарушителя")
        + f"\n{e('book')} <b>Прочее</b>\n"
        + quote(
            "<code>правила</code> · <code>варны</code> · <code>кто &lt;вопрос&gt;</code> · "
            "<code>шанс &lt;событие&gt;</code> · /links"
        )
        + f"\n{e('chain')} <b>Модераторам</b>\n"
        + quote(
            "<code>варн</code> · <code>снять варн</code> · <code>мут 2ч причина</code> · <code>размут</code>\n"
            "<code>бан</code> · <code>разбан</code> · <code>кик</code> · <code>муты</code> · <code>баны</code>"
        )
    )
    await message.answer(text)


@router.message(Command("links"))
async def links_cmd(message: Message) -> None:
    text = (
        f"{e('link')} <b>Ссылки</b>\n\n"
        f"{e('info')} Наш бот: @{settings.bot_username}\n"
        f"{e('megaphone')} Наш тгк: {settings.bot_channel_url}"
    )
    await message.answer(text, parse_mode="HTML")
