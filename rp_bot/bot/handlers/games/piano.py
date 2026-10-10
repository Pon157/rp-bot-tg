from __future__ import annotations

import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot import repo
from bot.emojis import e, btn
from .common import (
    new_challenge, get_challenge, drop_challenge, deduct_stake_or_fail,
    progressive_keyboard, handle_progressive_press,
)

router = Router(name="game_piano")
BUTTON_LABEL = "🎹 Ударить"


@router.message(F.text.regexp(r"(?i)^пианино(\s+(?P<mode>ставка\s+\d+|наказание))?$"))
async def piano_challenge(message: Message) -> None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответь этой командой на сообщение соперника, чтобы вызвать его на пианино.")
        return
    opponent = message.reply_to_message.from_user
    challenger = message.from_user
    if opponent.id == challenger.id:
        await message.reply("Нельзя играть с самим собой 🙂")
        return

    text = message.text or ""
    stake_match = re.search(r"ставка\s+(\d+)", text, flags=re.I)
    stake = int(stake_match.group(1)) if stake_match else 0
    punishment = "mute_1h" if not stake else None

    ch = new_challenge("piano", challenger, opponent, message.chat.id, stake_coins=stake, punishment=punishment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{btn('check')} Принять", callback_data=f"pn:accept:{ch.id}"),
        InlineKeyboardButton(text=f"{btn('alert')} Отклонить", callback_data=f"pn:decline:{ch.id}"),
    ]])
    stake_text = f"на ставку {stake} монет" if stake else "на наказание (мут на 1 час проигравшему)"
    await message.answer(
        f"{e('fire')} {challenger.first_name} вызывает {opponent.first_name} на пианино, {stake_text}!",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("pn:decline:"))
async def pn_decline(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    drop_challenge(cid)
    await call.message.edit_text(f"{e('alert')} Вызов отклонён.", parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("pn:accept:"))
async def pn_accept(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return

    if ch.stake_coins:
        if not await deduct_stake_or_fail(ch.challenger, ch.stake_coins, call.message):
            drop_challenge(cid); return
        if not await deduct_stake_or_fail(ch.opponent, ch.stake_coins, call.message):
            await repo.add_coins(ch.challenger.id, ch.stake_coins)
            drop_challenge(cid); return

    ch.progress["turn_id"] = ch.challenger.id
    await call.message.edit_text(
        f"{e('fire')} Игра началась! Ход: {ch.challenger.first_name}",
        parse_mode="HTML",
        reply_markup=progressive_keyboard(cid, "pn", BUTTON_LABEL),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pn:press:"))
async def pn_press(call: CallbackQuery) -> None:
    await handle_progressive_press("pn", call, BUTTON_LABEL)
