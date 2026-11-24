"""Команда whois — только для модераторов/админов.

Показывает карточку пользователя: ID, ник, роль, варны, мут, дата в чате,
баланс монет, питомец. Поддерживает те же способы указать цель, что и другие
команды модерации: ответом на сообщение, @ник, ID.

Отдельно: если ответить командой whois на опубликованный ботом анонимный
комментарий (под постом канала), бот деанонимизирует автора и покажет, кто
его реально написал — это и есть «посмотреть, кто написал».
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message

from bot import repo
from bot.emojis import e
from bot.rich import reply_rich
from bot.moderation import can_moderate
from bot.utils.formatting import esc, fmt_date, mention
from bot.utils.targets import Person, target_and_rest

router = Router(name="whois")


async def _is_anon_comment(message: Message) -> bool:
    rm = message.reply_to_message
    return bool(rm and rm.from_user and rm.from_user.is_bot)


def _who_line(person: Person) -> str:
    if person.username:
        return f"@{esc(person.username)}"
    return mention(person)


async def _card(person: Person) -> str:
    row = await repo.get_user(person.id)
    lines = [f"{e('person')} <b>Whois</b> {_who_line(person)}"]
    lines.append(f"{e('info')} ID: <code>{person.id}</code>")

    if row is None:
        lines.append(f"{e('warn')} Этот пользователь ещё не писал в чате (данных нет).")
        return "\n".join(lines)

    role = row["role"] or ("админ" if await repo.is_admin(person.id) else "участник")
    lines.append(f"{e('trophy')} Роль: <b>{esc(role)}</b>")
    lines.append(f"{e('warn')} Варны: <b>{row['warns']}</b>")
    if row["banned"]:
        lines.append("🚫 В бане")
    if row["muted_until"]:
        lines.append(f"🔇 Мут до: <b>{fmt_date(row['muted_until'])}</b>")
    lines.append(f"{e('calendar')} В чате с: <b>{fmt_date(row['joined_at'])}</b>")
    lines.append(f"{e('chat')} Сообщений всего: <b>{row['messages_total']}</b>")

    balance = await repo.get_balance(person.id)
    lines.append(f"{e('coin')} Баланс: <b>{balance}</b>")

    pet = await repo.get_pet(person.id)
    if pet:
        lines.append(f"🐾 Питомец: <b>{esc(pet['name'])}</b> ({pet['species']}, ур. {pet['level']})")

    return "\n".join(lines)


@router.message(F.text.regexp(r"(?i)^whois\b"))
async def cmd_whois(message: Message) -> None:
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        is_mod = True
    elif not message.from_user:
        is_mod = False
    else:
        is_mod = await can_moderate(message.bot, message.chat.id, message.from_user.id)
    if not is_mod:
        return  # обычным участникам молча не отвечаем, как и остальные команды модерации

    # ответ на анонимный комментарий бота -> деанонимизация автора
    if await _is_anon_comment(message):
        rm = message.reply_to_message
        author = await repo.get_anon_comment_author(rm.chat.id, rm.message_id)
        if author is not None:
            person = Person(author["author_user_id"])
            row = await repo.get_user(person.id)
            if row:
                person = Person(row["user_id"], row["first_name"], row["username"])
            card = await _card(person)
            await reply_rich(message, "👁 Этот анонимный комментарий написал:\n\n" + card)
            return
        # это не наш анонимный комментарий (или запись не найдена) — продолжаем как обычный whois

    text = message.text or ""
    args = text[len("whois"):].strip()
    target, _ = await target_and_rest(message, args)
    if target is None:
        await reply_rich(
            message,
            f"{e('info')} Не понял, о ком речь. Варианты:\n"
            "• ответом на сообщение: <code>whois</code>\n"
            "• по нику: <code>whois @nick</code>\n"
            "• по ID: <code>whois 123456789</code>",
        )
        return
    await reply_rich(message, await _card(target))
