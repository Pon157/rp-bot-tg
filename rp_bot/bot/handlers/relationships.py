from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Router, F, Bot
from aiogram.filters import BaseFilter
from bot.rich import reply_rich, send_rich
from bot.utils.buttons import ibtn
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.rich import answer_rich, rtable
from bot.utils.formatting import bar, esc, fit_lines, fmt_date, mention, nick, nicks, quote
from bot.utils.reserved import RESERVED
from bot.utils.targets import Person, target_and_rest

router = Router(name="relationships")
logger = logging.getLogger("rp_bot.relationships")

REL_LABEL = {
    "relationship": "отношения",
    "marriage": "брак",
    "marriage_of_convenience": "брак по расчету",
}
MARRIAGE_TYPES = ["marriage", "marriage_of_convenience"]

USAGE = f"{e('info')} Ответь командой на сообщение человека или укажи @ник (он должен был хоть раз писать в чат)."


def _args(message: Message, word_pattern: str) -> str:
    import re
    return re.sub(word_pattern, "", message.text or "", count=1, flags=re.I).strip()


# ------------------------------------------------------------ запросы ----

async def _send_request(message: Message, rel_type: str, word_pattern: str) -> None:
    sender = message.from_user
    target, _ = await target_and_rest(message, _args(message, word_pattern))
    if target is None:
        await message.reply(USAGE)
        return
    if target.id == sender.id:
        await message.reply("С самим собой отношения не построишь 🙂")
        return
    if target.is_bot:
        await message.reply("С ботами отношения не строим 🙂")
        return
    if await repo.find_active_relationship(sender.id, target.id, rel_type):
        await reply_rich(message, f"У вас уже есть активные «{REL_LABEL[rel_type]}» с этим человеком.")
        return

    req_id = await repo.create_request(sender.id, target.id, rel_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("Принять", "check", callback_data=f"rel:accept:{req_id}"),
        ibtn("Отклонить", "alert", callback_data=f"rel:decline:{req_id}"),
    ]])
    verb = "предлагает отношения" if rel_type == "relationship" else "предлагает заключить брак по расчету"
    await message.answer(f"{e('heart')} {mention(sender)} {verb} {mention(target)}!", reply_markup=kb)


@router.message(F.text.regexp(r"(?i)^мутки\b"))
async def request_relationship(message: Message) -> None:
    await _send_request(message, "relationship", r"(?i)^мутки")


@router.message(F.text.regexp(r"(?i)^брак\b"))
async def request_marriage(message: Message) -> None:
    await _send_request(message, "marriage_of_convenience", r"(?i)^брак")


@router.callback_query(F.data.startswith("rel:accept:"))
async def accept_request(call: CallbackQuery) -> None:
    req = await repo.get_request(int(call.data.split(":")[2]))
    if req is None or req["status"] != "pending":
        await call.answer("Заявка больше не действительна.", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это предложение не для вас.", show_alert=True)
        return
    await repo.set_request_status(req["id"], "accepted")
    await repo.create_relationship(req["from_id"], req["to_id"], req["rel_type"])
    names = await nicks([req["from_id"], req["to_id"]])
    await call.message.edit_text(
        f"{e('heart')} {names[req['from_id']]} и {names[req['to_id']]} теперь вместе: "
        f"<b>{REL_LABEL[req['rel_type']]}</b>! {e('gift')}"
    )
    await call.answer("Принято!")


@router.callback_query(F.data.startswith("rel:decline:"))
async def decline_request(call: CallbackQuery) -> None:
    req = await repo.get_request(int(call.data.split(":")[2]))
    if req is None or req["status"] != "pending":
        await call.answer("Заявка больше не действительна.", show_alert=True)
        return
    if call.from_user.id != req["to_id"]:
        await call.answer("Это предложение не для вас.", show_alert=True)
        return
    await repo.set_request_status(req["id"], "declined")
    await call.message.edit_text(f"{e('alert')} Предложение отклонено.")
    await call.answer("Отклонено")


# --------------------------------------------------------- расторжение ----

@router.message(F.text.regexp(r"(?i)^(расторжение|развод)\b"))
async def dissolve(message: Message) -> None:
    target, _ = await target_and_rest(message, _args(message, r"(?i)^(расторжение|развод)"))
    if target is None:
        await message.reply(USAGE)
        return
    rels = [r for r in await repo.list_relationships(message.from_user.id)
            if target.id in (r["user1_id"], r["user2_id"])]
    if not rels:
        await message.reply("У вас нет активных отношений с этим человеком.")
        return
    if len(rels) == 1:
        await repo.end_relationship(rels[0]["id"], "by_user")
        await message.reply(
            f"{e('alert')} «{REL_LABEL[rels[0]['rel_type']]}» {mention(message.from_user)} и {mention(target)} расторгнуты."
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn(REL_LABEL[r["rel_type"]], "heart", callback_data=f"rel:end:{r['id']}:{message.from_user.id}")]
        for r in rels
    ])
    await message.reply("У вас с этим человеком несколько связей, что расторгнуть?", reply_markup=kb)


@router.callback_query(F.data.startswith("rel:end:"))
async def dissolve_pick(call: CallbackQuery) -> None:
    _, _, rel_id, requester_id = call.data.split(":")
    if call.from_user.id != int(requester_id):
        await call.answer("Не твоя кнопка.", show_alert=True)
        return
    await repo.end_relationship(int(rel_id), "by_user")
    await call.message.edit_text(f"{e('alert')} Связь расторгнута.")
    await call.answer()


# ------------------------------------------------------------- списки ----

async def _my_lines(user_id: int) -> list[str]:
    rels = await repo.list_relationships(user_id)
    names = await nicks([x for r in rels for x in (r["user1_id"], r["user2_id"])])
    lines = []
    for r in rels:
        partner = r["user2_id"] if r["user1_id"] == user_id else r["user1_id"]
        extra = ""
        if r["rel_type"] == "relationship":
            extra = f" — {bar(r['blood_drops'], settings.max_blood_drops)} {r['blood_drops']}/{settings.max_blood_drops}"
        lines.append(f"{REL_LABEL[r['rel_type']].capitalize()}: {names[partner]}{extra}")
    return lines


@router.message(F.text.casefold() == "мои отношения")
async def my_relationships(message: Message) -> None:
    uid = message.from_user.id
    rels = await repo.list_relationships(uid)
    if not rels:
        await message.reply("У вас пока нет активных отношений или браков.")
        return
    names = await nicks([x for r in rels for x in (r["user1_id"], r["user2_id"])])
    rows, lines = [], []
    for r in rels:
        partner = r["user2_id"] if r["user1_id"] == uid else r["user1_id"]
        label = REL_LABEL[r["rel_type"]].capitalize()
        drops = f"{r['blood_drops']}/{settings.max_blood_drops}" if r["rel_type"] == "relationship" else "—"
        rows.append([label, names[partner], drops])
        extra = f" — {bar(r['blood_drops'], settings.max_blood_drops)} {drops}" if drops != "—" else ""
        lines.append(f"{label}: {names[partner]}{extra}")
    head = f"{e('heart')} <b>Ваши связи</b>\n"
    await answer_rich(message, head + rtable(["Тип", "Партнёр", "Капли"], rows, align=["left", "left", "right"]),
                      fallback=head + quote("\n".join(lines)))


async def _pair_list(message: Message, rows, title: str, with_drops: bool) -> None:
    if not rows:
        await reply_rich(message, f"{e('info')} {title}: пока никого.")
        return
    total = len(rows)
    rows = rows[:150]                      # в rich-таблице помещается много, но не бесконечно
    names = await nicks([x for r in rows for x in (r["user1_id"], r["user2_id"])])
    table_rows, lines = [], []
    for i, r in enumerate(rows, 1):
        pair = f"{names[r['user1_id']]} ♥ {names[r['user2_id']]}"
        last = f"{r['blood_drops']}/{settings.max_blood_drops}" if with_drops else fmt_date(r["started_at"])
        table_rows.append([str(i), pair, last])
        lines.append(f"{i}. {pair} — {last if with_drops else 'с ' + last}")
    more = f"\n…и ещё {total - len(rows)}" if total > len(rows) else ""
    head = f"{e('heart')} <b>{title}</b> · {total}\n"
    shown, hidden = fit_lines(lines)
    tail = f"\n…и ещё {hidden + total - len(rows)}" if (hidden or total > len(rows)) else ""
    await answer_rich(
        message,
        head + rtable(["№", "Пара", "Капли" if with_drops else "Вместе с"], table_rows, align=["right", "left", "right"]) + more,
        fallback=head + quote("\n".join(shown) + tail, expandable=total > 8),
    )


@router.message(F.text.casefold() == "браки")
async def all_marriages(message: Message) -> None:
    await _pair_list(message, await repo.list_active_by_types(MARRIAGE_TYPES), "Браки", with_drops=False)


@router.message(F.text.casefold() == "отношения")
async def all_relationships(message: Message) -> None:
    await _pair_list(message, await repo.list_active_by_types(["relationship"], order_by_drops=True),
                     "Отношения (по каплям крови)", with_drops=True)


# --------------------------------------------- команды пополнения капель ----

_blood_cache: dict = {"at": 0.0, "map": {}}


async def _blood_commands() -> dict:
    if time.monotonic() - _blood_cache["at"] > 15:
        _blood_cache["map"] = {r["trigger"].casefold(): dict(r) for r in await repo.list_blood_commands()}
        _blood_cache["at"] = time.monotonic()
    return _blood_cache["map"]


class BloodCommandFilter(BaseFilter):
    """Срабатывает ТОЛЬКО если первое слово — настроенная в админ-панели команда отношений."""

    async def __call__(self, message: Message) -> bool | dict:
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return False
        first = text.split(None, 1)[0].casefold()
        if first in RESERVED:
            return False
        cmd = (await _blood_commands()).get(first)
        return {"blood_command": cmd, "blood_args": text.partition(" ")[2]} if cmd else False


@router.message(BloodCommandFilter())
async def blood_command_handler(message: Message, blood_command: dict, blood_args: str) -> None:
    target, _ = await target_and_rest(message, blood_args)
    if target is None or target.id == message.from_user.id:
        return
    ok = await repo.check_and_set_command_cooldown(
        blood_command["id"], message.from_user.id, target.id, blood_command["cooldown_sec"]
    )
    if not ok:
        await reply_rich(message, f"{e('clock')} Эту команду с этим человеком пока рано использовать снова.")
        return
    rel = await repo.find_active_relationship(message.from_user.id, target.id, "relationship")
    if rel is None:
        await message.reply("У вас нет отношений с этим человеком, чтобы прокачивать их этой командой.")
        return
    new_val = await repo.add_blood_drops(rel["id"], blood_command["amount"], settings.max_blood_drops)
    template = esc(blood_command["template"] or "{1} и {2} провели время вместе")
    out = template.replace("{1}", mention(message.from_user)).replace("{2}", mention(target))
    await message.answer(
        f"{out}\n{e('heart')} Капли крови: <b>{new_val}/{settings.max_blood_drops}</b> {bar(new_val, settings.max_blood_drops)}"
    )


# ------------------------------------------------------------ фоновые задачи ----

async def auto_dissolve_loop(bot: Bot, poll_seconds: int = 3600) -> None:
    """Раз в час: расторгает отношения с 0 капель крови и связи, неактивные дольше
    RELATIONSHIP_INACTIVITY_DAYS."""
    while True:
        try:
            for rel in await repo.zero_blood_relationships():
                await repo.end_relationship(rel["id"], "zero_blood")
                names = await nicks([rel["user1_id"], rel["user2_id"]])
                await bot.send_message(
                    settings.allowed_chat_id,
                    f"{e('alert')} Отношения {names[rel['user1_id']]} и {names[rel['user2_id']]} "
                    f"закончились — закончились капли крови.",
                )
            for rel_type in ("relationship", "marriage_of_convenience"):
                for rel in await repo.stale_relationships(rel_type, settings.relationship_inactivity_days):
                    await repo.end_relationship(rel["id"], "inactivity")
                    names = await nicks([rel["user1_id"], rel["user2_id"]])
                    await bot.send_message(
                        settings.allowed_chat_id,
                        f"{e('alert')} «{REL_LABEL[rel_type]}» {names[rel['user1_id']]} и {names[rel['user2_id']]} "
                        f"автоматически расторгнуты из-за неактива.",
                    )
        except Exception:
            logger.exception("Ошибка в auto_dissolve_loop")
        await asyncio.sleep(poll_seconds)
