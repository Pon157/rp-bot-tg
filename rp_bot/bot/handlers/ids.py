"""Команда «. ид»: ID участника и чата. Без аргументов — ваш ID; ответом или @ником — ID другого человека."""
import re

from aiogram import F, Router
from aiogram.types import Message

from bot import repo
from bot.emojis import e
from bot.utils.formatting import esc, quote
from bot.rich import reply_rich
from bot.utils.targets import Person, target_and_rest

router = Router(name="ids")


@router.message(F.text.regexp(r"(?i)^\.\s*ид\b"))
async def show_id(message: Message) -> None:
    args = re.sub(r"(?i)^\.\s*ид", "", message.text or "", count=1).strip()
    target, _ = await target_and_rest(message, args)
    if args and target is None:
        # Указан @ник, которого бот не знает. Раньше тут подставлялся сам отправитель — это было неверно.
        await reply_rich(message, f"{e('warn')} Не знаю такого @ника: он должен хоть раз писать в этот чат. "
                                  "Ответьте командой на его сообщение или укажите числовой ID.")
        return
    person = target or Person.from_user(message.from_user)

    lines = [f"ID: <code>{person.id}</code>"]
    if person.username:
        lines.append(f"Юзернейм: @{person.username}")
    if message.chat.type != "private":
        lines.append(f"ID чата: <code>{message.chat.id}</code>")
    if target is not None and not await repo.get_user(person.id):
        lines.append("В базе бота нет: этот человек ещё не писал в чат")

    name = esc(person.first_name or (f"@{person.username}" if person.username else "участник"))
    await reply_rich(message, f"{e('person')} <b>{name}</b>\n" + quote("\n".join(lines)))
