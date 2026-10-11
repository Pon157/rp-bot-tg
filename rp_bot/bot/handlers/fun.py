from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.rich import answer_rich, rtable
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


HELP = [
    ("person", "Профиль", [
        ("кто я", "карточка профиля"),
        ("+описание текст", "описание в профиль"),
    ]),
    ("heart", "Отношения", [
        ("мутки", "предложить отношения (капли крови)"),
        ("брак", "предложить брак по расчёту"),
        ("расторжение", "расторгнуть связь"),
        ("мои отношения", "ваши связи"),
        ("отношения", "список всех отношений"),
        ("браки", "список всех браков"),
    ]),
    ("fire", "RP-действия", [
        ("ударить, обнять, поцеловать …", "полный набор задаёт администрация"),
    ]),
    ("coin", "Монеты и игры", [
        ("фарма / ферма", "монеты раз в 4 часа"),
        ("баланс", "ваши монеты"),
        ("кости, дуэль, монеточка, пианино", "игры; добавьте «ставка 50» — на монеты, иначе на наказание"),
    ]),
    ("megaphone", "Репорты", [
        ("репорт причина", "ответом на сообщение нарушителя"),
    ]),
    ("book", "Прочее", [
        ("правила", "правила чата"),
        ("варны", "ваши нарушения"),
        ("кто <вопрос>", "случайный участник"),
        ("шанс <событие>", "случайный процент"),
        ("/links", "ссылки"),
        ("стараяверсия · новаяверсия", "ответы мне без таблиц (для старого Telegram) · с таблицами"),
    ]),
    ("chain", "Модераторам", [
        ("варн · снять варн", "предупреждение"),
        ("мут 2ч причина · размут", "срок: 30м, 2ч, 1д, навсегда"),
        ("бан · разбан · кик", "блокировка"),
        ("муты · баны", "списки"),
    ]),
]


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    intro = (f"{e('info')} <b>Команды бота</b>\n"
             "<i>Кого-то указываем ответом на его сообщение или через @ник (человек должен хоть раз писать в чат).</i>\n")
    rich, classic = [intro], [intro]
    for emoji, title, items in HELP:
        head = f"\n{e(emoji)} <b>{title}</b>\n"
        rich.append(head + rtable(["Команда", "Что делает"], [[f"<code>{esc(c)}</code>", esc(d)] for c, d in items]))
        classic.append(head + quote("\n".join(f"<code>{esc(c)}</code> — {esc(d)}" for c, d in items)))
    await answer_rich(message, "".join(rich), fallback="".join(classic))


@router.message(Command("links"))
async def links_cmd(message: Message) -> None:
    text = (
        f"{e('link')} <b>Ссылки</b>\n\n"
        f"{e('info')} Наш бот: @{settings.bot_username}\n"
        f"{e('megaphone')} Наш тгк: {settings.bot_channel_url}"
    )
    await message.answer(text, parse_mode="HTML")
