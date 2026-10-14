"""Форматирование сообщений: ники-ссылки, таблицы, цитаты, длительности.

Про «таблицы» в Telegram: настоящих таблиц в сообщениях нет. Есть моноширинный
блок <pre> — в нём колонки выравниваются пробелами, это и есть «красивая
табличка». Внутри <pre> нельзя ссылки и премиум-эмодзи, поэтому там, где нужны
кликабельные ники, используется <blockquote> со строками, а <pre>-таблицы — для
чисел и истории.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Sequence

from bot import repo


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def display_name(first_name: str | None, username: str | None, user_id: int) -> str:
    name = (first_name or "").strip()
    if not name:
        name = f"@{username}" if username else f"id{user_id}"
    return name


def user_link(user_id: int, first_name: str | None = None, username: str | None = None) -> str:
    """Ник, по нажатию на который открывается профиль человека."""
    return f'<a href="tg://user?id={user_id}">{esc(display_name(first_name, username, user_id))}</a>'


def mention(user) -> str:
    """Принимает aiogram.types.User или utils.targets.Person."""
    return user_link(user.id, getattr(user, "first_name", None), getattr(user, "username", None))


async def nick(user_id: int | None) -> str:
    if user_id is None:
        return "администрация"
    row = await repo.get_user(user_id)
    if row:
        return user_link(user_id, row["first_name"], row["username"])
    return user_link(user_id)


async def nicks(user_ids) -> dict[int, str]:
    """Ники-ссылки сразу для нескольких людей одним запросом."""
    rows = await repo.get_users_map(list(user_ids))
    return {
        uid: user_link(uid, rows[uid]["first_name"], rows[uid]["username"]) if uid in rows else user_link(uid)
        for uid in set(user_ids)
    }


# ------------------------------------------------------------ время ----

def fmt_timedelta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d} д {h} ч"
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин {s} сек" if not s == 0 else f"{m} мин"
    return f"{s} сек"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "неизвестно"
    return dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y")


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    return dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")


FOREVER = -1
_FOREVER_WORDS = {"навсегда", "forever", "вечно"}
_UNITS = (("мес", 30 * 86400), ("мин", 60), ("м", 60), ("m", 60), ("ч", 3600), ("h", 3600),
          ("д", 86400), ("d", 86400), ("н", 7 * 86400), ("w", 7 * 86400))


def parse_duration(args: str) -> tuple[int | None, str]:
    """'2ч спам' -> (7200, 'спам'); 'навсегда' -> (FOREVER, ''); 'спам' -> (None, 'спам').
    Число без единицы считается минутами. Диапазон: от 1 минуты до 365 дней."""
    args = args.strip()
    if not args:
        return None, ""
    first, _, rest = args.partition(" ")
    low = first.casefold()
    if low in _FOREVER_WORDS:
        return FOREVER, rest.strip()
    m = re.fullmatch(r"(\d{1,6})([a-zа-яё]*)", low)
    if not m:
        return None, args
    n, unit = int(m.group(1)), m.group(2)
    mult = 60
    if unit:
        for prefix, k in _UNITS:
            if unit.startswith(prefix):
                mult = k
                break
        else:
            return None, args
    return max(60, min(n * mult, 365 * 86400)), rest.strip()


# ------------------------------------------------------- оформление ----

def quote(text: str, expandable: bool = False) -> str:
    tag = "blockquote expandable" if expandable else "blockquote"
    return f"<{tag}>{text}</blockquote>"


def bar(value: int, maximum: int, width: int = 10) -> str:
    filled = 0 if maximum <= 0 else round(width * max(0, min(value, maximum)) / maximum)
    if value > 0 and filled == 0:
        filled = 1  # хоть одна заполненная клетка, пока капли есть
    return "█" * filled + "░" * (width - filled)


def table(headers: Sequence[str], rows: Sequence[Sequence], *, max_widths: Sequence[int] | None = None,
          align: Sequence[str] | None = None) -> str:
    """Моноширинная таблица в <pre>. align: 'l' или 'r' для каждой колонки."""
    cols = len(headers)
    max_widths = list(max_widths or [24] * cols)
    align = list(align or ["l"] * cols)

    def cell(text, i) -> str:
        s = str(text).replace("\n", " ")
        return s if len(s) <= max_widths[i] else s[: max_widths[i] - 1] + "…"

    data = [[cell(h, i) for i, h in enumerate(headers)]] + [[cell(c, i) for i, c in enumerate(r)] for r in rows]
    widths = [max(len(r[i]) for r in data) for i in range(cols)]

    def line(r) -> str:
        parts = [r[i].rjust(widths[i]) if align[i] == "r" else r[i].ljust(widths[i]) for i in range(cols)]
        return " │ ".join(parts).rstrip()

    sep = "─┼─".join("─" * w for w in widths)
    body = [line(data[0]), sep] + [line(r) for r in data[1:]]
    return "<pre>" + esc("\n".join(body)) + "</pre>"


def fit_lines(lines: list[str], limit: int = 3300) -> tuple[list[str], int]:
    """Обрезает список строк под лимит Telegram (4096). Возвращает (строки, сколько не влезло)."""
    out: list[str] = []
    size = 0
    for i, line in enumerate(lines):
        if size + len(line) + 1 > limit:
            return out, len(lines) - i
        out.append(line)
        size += len(line) + 1
    return out, 0
