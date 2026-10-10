from __future__ import annotations

import datetime as dt

from aiogram.types import User


def mention(user: User) -> str:
    name = user.first_name or (f"@{user.username}" if user.username else str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_by_id(user_id: int, display: str) -> str:
    return f'<a href="tg://user?id={user_id}">{display}</a>'


def fmt_timedelta(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин {s} сек"
    return f"{s} сек"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "неизвестно"
    return dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y")
