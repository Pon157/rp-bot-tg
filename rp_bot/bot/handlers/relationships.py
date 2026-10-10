from __future__ import annotations

import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, User

from bot import repo
from bot.config import settings
from bot.emojis import e, btn
from bot.utils.formatting import mention, mention_by_id

router = Router(name="relationships")

# слова, зарезервированные другими командами бота — их нельзя перекрыть rp-командой из панели
RESERVED_WORDS = {
    "фарма", "ферма", "баланс", "кости", "дуэль", "монеточка", "пианино", "правила",
    "мутки", "брак", "расторжение", "принять", "отклонить", "кто", "шанс",
}


class BloodCommandFilter(BaseFilter):
    """Срабатывает ТОЛЬКО если первое слово сообщения — реально настроенная в
    админ-панели rp/пополняющая команда. Так catch-all не перехватывает чужие команды."""

    async def __call__(self, message: Message) -> bool | dict:
        text = (message.text or "").strip()
        if not text:
            return False
        trigger = text.split(" ", 1)[0].casefold()
        if trigger in RESERVED_WORDS or trigger.startswith("/"):
            return False
        cmd = await repo.get_blood_command(trigger)
        if cmd is None:
            return False
        return {"blood_command": cmd}

REL_LABEL = {
    "relationship": "отношения",
    "marriage": "брак",
    "marriage_of_convenience": "брак по расчету",
}


def _resolve_target(message: Message) -> User | None:
    """Ищем упомянутого пользователя: через reply или через text_mention entity."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user
    return None


# ------------------------------------------------------------ запросы ----

async def _send_request(message: Message, rel_type: str) -> None:
    from_user = message.from_user
    to_user = _resolve_target(message)
    if to_user is None:
        await message.reply(
            "Ответь этой командой на сообщение человека, которому хочешь сделать предложение "
            "(или упомяни его так, чтобы получилась text-mention ссылка)."
        )
        return
    if to_user.id == from_user.id:
        await message.reply("С самим собой отношения не построишь 🙂")
        return

    existing = await repo.find_active_relationship(from_user.id, to_user.id, rel_type)
    if existing:
        await message.reply(f"У вас уже есть активные «{REL_LABEL[rel_type]}» с этим человеком.")
        return

    req_id = await repo.create_request(from_user.id, to_user.id, rel_type)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"{btn('check')} Принять", callback_data=f"rel:accept:{req_id}"),
            InlineKeyboardButton(text=f"{btn('alert')} Отклонить", callback_data=f"rel:decline:{req_id}"),
        ]]
    )
    verb = "предлагает отношения" if rel_type == "relationship" else "предлагает заключить брак по расчету"
    await message.answer(
        f"{e('heart')} {mention(from_user)} {verb} {mention(to_user)}!",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(F.text.regexp(r"(?i)^мутки\b"))
async def request_relationship(message: Message) -> None:
    await _send_request(message, "relationship")


@router.message(F.text.regexp(r"(?i)^брак\b"))
async def request_marriage(message: Message) -> None:
    await _send_request(message, "marriage_of_convenience")


@router.callback_query(F.data.startswith("rel:accept:"))
async def accept_request(call: CallbackQuery) -> None:
    req_id = int(call.data.split(":")[2])
    req = await repo.get_request(req_id)
    if req is None or req["status"] != "pending":
        await call.answer("Заявка больше не действительна.", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это предложение не для вас.", show_alert=True)
        return

    await repo.set_request_status(req_id, "accepted")
    await repo.create_relationship(req["from_id"], req["to_id"], req["rel_type"])
    label = REL_LABEL[req["rel_type"]]
    await call.message.edit_text(
        f"{e('heart')} {mention_by_id(req['from_id'], 'Пользователь')} и "
        f"{mention_by_id(req['to_id'], 'пользователь')} теперь в отношениях: <b>{label}</b>! {e('gift')}",
        parse_mode="HTML",
    )
    await call.answer("Принято!")


@router.callback_query(F.data.startswith("rel:decline:"))
async def decline_request(call: CallbackQuery) -> None:
    req_id = int(call.data.split(":")[2])
    req = await repo.get_request(req_id)
    if req is None or req["status"] != "pending":
        await call.answer("Заявка больше не действительна.", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это предложение не для вас.", show_alert=True)
        return
    await repo.set_request_status(req_id, "declined")
    await call.message.edit_text(f"{e('alert')} Предложение отклонено.", parse_mode="HTML")
    await call.answer("Отклонено")


# --------------------------------------------------------- расторжение ----

@router.message(F.text.regexp(r"(?i)^расторжение\b"))
async def dissolve(message: Message) -> None:
    target = _resolve_target(message)
    if target is None:
        await message.reply("Ответь этой командой на сообщение партнёра, чтобы разорвать отношения/брак.")
        return

    rels = [r for r in await repo.list_relationships(message.from_user.id)
            if target.id in (r["user1_id"], r["user2_id"])]
    if not rels:
        await message.reply("У вас нет активных отношений с этим человеком.")
        return

    if len(rels) == 1:
        await repo.end_relationship(rels[0]["id"], "by_user")
        label = REL_LABEL[rels[0]["rel_type"]]
        await message.reply(f"{e('alert')} «{label}» с {mention(target)} расторгнуты.", parse_mode="HTML")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=REL_LABEL[r["rel_type"]], callback_data=f"rel:end:{r['id']}:{message.from_user.id}")]
            for r in rels
        ]
    )
    await message.reply("У вас с этим человеком несколько связей, что расторгнуть?", reply_markup=kb)


@router.callback_query(F.data.startswith("rel:end:"))
async def dissolve_pick(call: CallbackQuery) -> None:
    _, _, rel_id, requester_id = call.data.split(":")
    if call.from_user.id != int(requester_id):
        await call.answer("Не твоя кнопка.", show_alert=True)
        return
    await repo.end_relationship(int(rel_id), "by_user")
    await call.message.edit_text(f"{e('alert')} Связь расторгнута.", parse_mode="HTML")
    await call.answer()


# ------------------------------------------------------------ список ----

@router.message(F.text.casefold() == "мои отношения")
async def my_relationships(message: Message) -> None:
    rels = await repo.list_relationships(message.from_user.id)
    if not rels:
        await message.reply("У вас пока нет активных отношений или браков.")
        return
    lines = [f"{e('heart')} <b>Ваши связи</b>\n"]
    for r in rels:
        partner_id = r["user2_id"] if r["user1_id"] == message.from_user.id else r["user1_id"]
        label = REL_LABEL[r["rel_type"]]
        extra = f" — {r['blood_drops']}/{settings.max_blood_drops} {e('heart')}" if r["rel_type"] == "relationship" else ""
        lines.append(f"• {label} с {mention_by_id(partner_id, 'пользователем')}{extra}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# --------------------------------------------- команды пополнения капель ----

@router.message(BloodCommandFilter())
async def maybe_blood_command(message: Message, blood_command) -> None:
    """Обрабатывает настроенную через админ-панель rp/пополняющую команду
    (например "свидание" -> +N капель крови). Благодаря BloodCommandFilter
    сюда попадают только реальные, включённые в панели триггеры."""
    cmd = blood_command
    target = _resolve_target(message)
    if target is None or target.id == message.from_user.id:
        return

    ok = await repo.check_and_set_command_cooldown(cmd["id"], message.from_user.id, target.id, cmd["cooldown_sec"])
    if not ok:
        await message.reply(f"{e('clock')} Эту команду с этим человеком пока рано использовать снова.", parse_mode="HTML")
        return

    rel = await repo.find_active_relationship(message.from_user.id, target.id, "relationship")
    if rel is None:
        await message.reply("У вас нет отношений с этим человеком, чтобы прокачивать их этой командой.")
        return

    new_val = await repo.add_blood_drops(rel["id"], cmd["amount"], settings.max_blood_drops)
    template = cmd["template"] or "{1} и {2} провели время вместе"
    text_out = template.replace("{1}", mention(message.from_user)).replace("{2}", mention(target))
    await message.answer(
        f"{text_out}\n{e('heart')} Капли крови: <b>{new_val}/{settings.max_blood_drops}</b>",
        parse_mode="HTML",
    )


# ------------------------------------------------------------ фоновые задачи ----

async def auto_dissolve_loop(bot: Bot, poll_seconds: int = 3600) -> None:
    """Раз в час: 1) расторгает отношения с нулевым балансом капель крови,
    2) расторгает связи, неактивные дольше settings.relationship_inactivity_days."""
    while True:
        try:
            for rel in await repo.zero_blood_relationships():
                await repo.end_relationship(rel["id"], "zero_blood")
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"{e('alert')} Отношения {mention_by_id(rel['user1_id'], 'пользователя')} и "
                    f"{mention_by_id(rel['user2_id'], 'пользователя')} закончились — закончились капли крови.",
                    parse_mode="HTML",
                )
            for rel_type in ("relationship", "marriage_of_convenience"):
                for rel in await repo.stale_relationships(rel_type, settings.relationship_inactivity_days):
                    await repo.end_relationship(rel["id"], "inactivity")
                    await bot.send_message(
                        settings.allowed_chat_id,
                        f"{e('alert')} «{REL_LABEL[rel_type]}» {mention_by_id(rel['user1_id'], 'пользователя')} и "
                        f"{mention_by_id(rel['user2_id'], 'пользователя')} автоматически расторгнуты из-за неактива.",
                        parse_mode="HTML",
                    )
        except Exception:
            pass
        await asyncio.sleep(poll_seconds)
