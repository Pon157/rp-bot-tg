from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.emojis import e, btn
from .common import new_challenge, get_challenge, drop_challenge, settle_stakes, deduct_stake_or_fail

router = Router(name="game_dice")


@router.message(F.text.regexp(r"(?i)^кости(\s+ставка\s+(?P<amount>\d+))?$"))
async def dice_challenge(message: Message) -> None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответь этой командой на сообщение того, кого хочешь вызвать на кости 🎲")
        return
    opponent = message.reply_to_message.from_user
    challenger = message.from_user
    if opponent.id == challenger.id:
        await message.reply("Нельзя играть с самим собой 🙂")
        return

    m = message.text or ""
    stake = 0
    punishment = None
    if "ставка" in m.casefold():
        import re
        match = re.search(r"ставка\s+(\d+)", m, flags=re.I)
        stake = int(match.group(1)) if match else 0
        punishment = None
    else:
        punishment = "mute_1h"  # дефолтное наказание за кости без ставки, настраивается по желанию

    ch = new_challenge("dice", challenger, opponent, message.chat.id, stake_coins=stake, punishment=punishment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{btn('check')} Принять", callback_data=f"dice:accept:{ch.id}"),
        InlineKeyboardButton(text=f"{btn('alert')} Отклонить", callback_data=f"dice:decline:{ch.id}"),
    ]])
    stake_text = f"на ставку {stake} монет" if stake else "на наказание (мут на 1 час проигравшему)"
    await message.answer(
        f"{e('fire')} {challenger.first_name} вызывает {opponent.first_name} на игру в кости, {stake_text}!",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("dice:decline:"))
async def dice_decline(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    drop_challenge(cid)
    await call.message.edit_text(f"{e('alert')} Вызов на кости отклонён.", parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("dice:accept:"))
async def dice_accept(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return

    if ch.stake_coins:
        if not await deduct_stake_or_fail(ch.challenger, ch.stake_coins, call.message):
            drop_challenge(cid)
            return
        if not await deduct_stake_or_fail(ch.opponent, ch.stake_coins, call.message):
            from bot import repo
            await repo.add_coins(ch.challenger.id, ch.stake_coins)  # возврат
            drop_challenge(cid)
            return

    await call.message.edit_text(f"{e('fire')} Бросаем кости!", parse_mode="HTML")
    await call.answer()

    d1 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2)
    d2 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2.5)

    v1, v2 = d1.dice.value, d2.dice.value
    if v1 == v2:
        if ch.stake_coins:
            from bot import repo
            await repo.add_coins(ch.challenger.id, ch.stake_coins)
            await repo.add_coins(ch.opponent.id, ch.stake_coins)
        await call.message.answer(f"{e('info')} Ничья ({v1}:{v2})! Ставки возвращены, наказаний нет.", parse_mode="HTML")
        drop_challenge(cid)
        return

    winner, loser = (ch.challenger, ch.opponent) if v1 > v2 else (ch.opponent, ch.challenger)
    await call.message.answer(f"{e('fire')} Результат: {v1} vs {v2}", parse_mode="HTML")
    await settle_stakes(winner, loser, ch, call.message)
    drop_challenge(cid)
