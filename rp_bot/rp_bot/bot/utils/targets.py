"""Как бот понимает, К КОМУ относится команда: ответ на сообщение, @ник или ID."""
from __future__ import annotations

import re
from dataclasses import dataclass

from aiogram.types import Message, User

from bot import repo

# служебные «пользователи» Telegram: анонимный админ и пересланные из канала
_FAKE_IDS = {1087968824, 777000}


@dataclass
class Person:
    id: int
    first_name: str | None = None
    username: str | None = None
    is_bot: bool = False

    @classmethod
    def from_user(cls, u: User) -> "Person":
        return cls(u.id, u.first_name, u.username, bool(u.is_bot))

    @classmethod
    def from_row(cls, row) -> "Person":
        return cls(row["user_id"], row["first_name"], row["username"], False)


async def target_and_rest(message: Message, args: str) -> tuple[Person | None, str]:
    """Разбирает «хвост» команды (всё после первого слова/слов команды).

    Порядок: явный @ник или ID в начале хвоста -> text-mention -> ответ на сообщение.
    Возвращает (человек или None, остаток текста — причина/ставка/время).
    Для @ника человек должен хотя бы раз писать в чат (бот узнаёт его из базы);
    по ID можно указать кого угодно.
    """
    args = args.strip()
    first, _, tail = args.partition(" ")

    if first.startswith("@") and len(first) > 1:
        row = await repo.get_user_by_username(first[1:])
        return (Person.from_row(row) if row else None), tail.strip()

    if re.fullmatch(r"\d{7,}", first):
        uid = int(first)
        row = await repo.get_user(uid)
        return (Person.from_row(row) if row else Person(uid)), tail.strip()

    text = message.text or ""
    for ent in message.entities or []:
        if ent.type == "text_mention" and ent.user:
            name = ent.extract_from(text)
            rest = args[len(name):].strip() if args.startswith(name) else args
            return Person.from_user(ent.user), rest

    rm = message.reply_to_message
    if rm and rm.from_user and rm.from_user.id not in _FAKE_IDS and not getattr(rm, "forum_topic_created", None):
        return Person.from_user(rm.from_user), args
    return None, args
