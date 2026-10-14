from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.rich import answer_rich, rtable
from bot.utils.formatting import esc, fmt_date, mention, nicks, quote, table

router = Router(name="profile")

AUTO_ROLES = {"senior": "старший админ", "admin": "админ"}


@router.message(F.text.casefold() == "кто я")
async def who_am_i(message: Message) -> None:
    user = message.from_user
    row = await repo.get_user(user.id)
    if row is None:
        await repo.touch_user(user.id, user.username, user.first_name)
        row = await repo.get_user(user.id)

    who = f"@{user.username}" if user.username else mention(user)
    level = await repo.is_admin(user.id)
    role = row["role"] or AUTO_ROLES.get(level, "участник")

    stats = table(
        ["Всего", "Месяц", "Неделя", "День"],
        [[row["messages_total"], row["messages_month"], row["messages_week"], row["messages_day"]]],
        align=["r", "r", "r", "r"],
    )

    parts = [
        f"{e('person')} {who} является <b>{esc(role)}</b>",
        f"{e('warn')} Нарушения: <b>{row['warns']}</b>",
        f"{e('calendar')} В чате с: <b>{fmt_date(row['joined_at'])}</b>",
    ]

    rels = await repo.list_relationships(user.id)
    if rels:
        partners = list(dict.fromkeys(r["user2_id"] if r["user1_id"] == user.id else r["user1_id"] for r in rels))[:3]
        names = await nicks(partners)
        parts.append(f"{e('heart')} Вместе с: " + ", ".join(names[p] for p in partners))

    parts.append(f"{e('chat')} Сообщения:")
    stats_rich = rtable(
        ["Всего", "Месяц", "Неделя", "День"],
        [[str(row["messages_total"]), str(row["messages_month"]), str(row["messages_week"]), str(row["messages_day"])]],
        align=["right"] * 4,
    )
    parts.append(stats)
    if row["bio"]:
        parts.append(f"{e('note')} О себе:\n" + quote(esc(row["bio"])))
    parts.append(f"{e('info')} Наш бот: @{settings.bot_username}\n{e('link')} Наш тгк: {settings.bot_channel_url}")
    caption = "\n".join(parts)
    rich_text = caption.replace(stats, stats_rich)

    try:
        photos = await message.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            await message.answer_photo(photos.photos[0][-1].file_id, caption=caption)
            return
    except TelegramBadRequest:
        pass
    # без аватарки подпись к фото не нужна — шлём нативной таблицей (с откатом на <pre>)
    await answer_rich(message, rich_text, fallback=caption)


@router.message(F.text.regexp(r"^\+описание\b"))
async def set_description(message: Message) -> None:
    bio = (message.text or "").partition(" ")[2].strip()
    if not bio:
        await message.reply(f"Напиши описание после команды, например:\n<code>+описание люблю рп и чай</code>")
        return
    if len(bio) > 300:
        await message.reply("Слишком длинно, максимум 300 символов.")
        return
    await repo.set_bio(message.from_user.id, bio)
    await message.reply(f"{e('check')} Описание профиля обновлено.")
