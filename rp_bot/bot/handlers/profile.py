from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.utils.formatting import fmt_date

router = Router(name="profile")


@router.message(F.text.casefold() == "кто я")
async def who_am_i(message: Message) -> None:
    user = message.from_user
    row = await repo.get_user(user.id)
    if row is None:
        await repo.touch_user(user.id, user.username, user.first_name)
        row = await repo.get_user(user.id)

    display = f"@{user.username}" if user.username else f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    role = row["role"] or "участник"
    bio = row["bio"] or "—"

    caption = (
        f"{e('person')} {display}\n"
        f"{e('trophy')} Роль: <b>{role}</b>\n"
        f"{e('warn')} Нарушения: <b>{row['warns']}</b>\n"
        f"{e('calendar')} В чате с: <b>{fmt_date(row['joined_at'])}</b>\n"
        f"{e('chat')} Сообщений: всего <b>{row['messages_total']}</b> / "
        f"за месяц <b>{row['messages_month']}</b> / за неделю <b>{row['messages_week']}</b> / "
        f"за день <b>{row['messages_day']}</b>\n"
        f"{e('note')} О себе: {bio}\n\n"
        f"{e('info')} Наш бот: @{settings.bot_username}\n"
        f"{e('link')} Наш тгк: {settings.bot_channel_url}"
    )

    try:
        photos = await message.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            await message.answer_photo(file_id, caption=caption, parse_mode="HTML")
            return
    except TelegramBadRequest:
        pass

    await message.answer(caption, parse_mode="HTML")


@router.message(F.text.regexp(r"^\+описание(\s+(?P<bio>.+))?$", flags=0))
async def set_description(message: Message) -> None:
    text = message.text or ""
    bio = text.partition(" ")[2].strip()
    if not bio:
        await message.reply("Напиши описание после команды, например:\n<code>+описание люблю рп и чай</code>", parse_mode="HTML")
        return
    if len(bio) > 300:
        await message.reply("Слишком длинно, максимум 300 символов.")
        return
    await repo.set_bio(message.from_user.id, bio)
    await message.reply(f"{e('check')} Описание профиля обновлено.", parse_mode="HTML")
