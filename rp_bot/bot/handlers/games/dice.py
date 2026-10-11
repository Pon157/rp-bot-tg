from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import repo
from bot.emojis import e
from bot.utils.formatting import mention
from .common import (
    drop_challenge, get_challenge, new_challenge, parse_game_command, settle_stakes, stake_text, take_both_stakes,
)

router = Router(name="game_dice")


@router.message(F.text.regexp(r"(?i)^кости\b"))
async def dice_challenge(message: Message) -> None:
    opponent, stake, _, error = await parse_game_command(message, "кости")
    if error:
        await message.reply(error)
        return
    ch = new_challenge("dice", message.from_user, opponent, message.chat.id, stake_coins=stake,
                       punishment=None if stake else "mute_1h")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✔️ Принять", callback_data=f"dice:accept:{ch.id}"),
        InlineKeyboardButton(text="✖️ Отклонить", callback_data=f"dice:decline:{ch.id}"),
    ]])
    await message.answer(
        f"{e('fire')} {mention(message.from_user)} вызывает {mention(opponent)} на кости, {stake_text(stake)}!",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("dice:decline:"))
async def dice_decline(call: CallbackQuery) -> None:
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    drop_challenge(ch.id)
    await call.message.edit_text(f"{e('alert')} Вызов на кости отклонён.")
    await call.answer()


@router.callback_query(F.data.startswith("dice:accept:"))
async def dice_accept(call: CallbackQuery) -> None:
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    if not await take_both_stakes(ch, call.message):
        drop_challenge(ch.id)
        return

    await call.message.edit_text(f"{e('fire')} Бросаем кости!")
    await call.answer()

    d1 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2)
    d2 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2.5)

    v1, v2 = d1.dice.value, d2.dice.value
    drop_challenge(ch.id)
    if v1 == v2:
        if ch.stake_coins:
            await repo.add_coins(ch.challenger.id, ch.stake_coins)
            await repo.add_coins(ch.opponent.id, ch.stake_coins)
        await call.message.answer(f"{e('info')} Ничья ({v1}:{v2})! Ставки возвращены, наказаний нет.")
        return

    winner, loser = (ch.challenger, ch.opponent) if v1 > v2 else (ch.opponent, ch.challenger)
    await call.message.answer(f"{e('fire')} {mention(ch.challenger)}: <b>{v1}</b> · {mention(ch.opponent)}: <b>{v2}</b>")
    await settle_stakes(winner, loser, ch, call.message)
