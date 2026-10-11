from __future__ import annotations

import random

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.emojis import e
from bot.utils.formatting import mention
from bot.utils.targets import Person
from .common import (
    drop_challenge, get_challenge, new_challenge, parse_game_command, settle_stakes, stake_text, take_both_stakes,
)

router = Router(name="game_duel")

BASE_HIT_CHANCE = 40   # %
AIM_BONUS = 15         # % за каждый стак прицела
MAX_STACKS = 3


def _duel_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎯 Прицелиться", callback_data=f"duel:aim:{cid}"),
        InlineKeyboardButton(text="🔫 Выстрелить", callback_data=f"duel:shoot:{cid}"),
        InlineKeyboardButton(text="💨 Сбить прицел", callback_data=f"duel:knock:{cid}"),
    ]])


@router.message(F.text.regexp(r"(?i)^дуэль\b"))
async def duel_start(message: Message) -> None:
    opponent, stake, _, error = await parse_game_command(message, "дуэль")
    if error:
        await message.reply(error)
        return
    if stake:
        await _announce_duel(message, message.from_user, opponent, stake_coins=stake, punishment=None)
        return
    # дуэль без ставки — на наказание; сначала вызывающий выбирает какое
    me = message.from_user.id
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔇 Мут на час", callback_data=f"duel:pick_mute:{opponent.id}:{me}"),
        InlineKeyboardButton(text="⚠️ Варн на неделю", callback_data=f"duel:pick_warn:{opponent.id}:{me}"),
    ]])
    await message.reply("Выбери наказание для проигравшего (решает тот, кто вызывает на дуэль):", reply_markup=kb)


async def _punishment_picked(call: CallbackQuery, punishment: str) -> None:
    _, _, opponent_id, challenger_id = call.data.split(":")
    if call.from_user.id != int(challenger_id):
        await call.answer("Наказание выбирает вызывающий.", show_alert=True)
        return
    opponent = Person(int(opponent_id))
    try:
        user = (await call.bot.get_chat_member(call.message.chat.id, int(opponent_id))).user
        opponent = Person.from_user(user)
    except TelegramAPIError:
        pass
    await call.message.delete()
    await _announce_duel(call.message, call.from_user, opponent, stake_coins=0, punishment=punishment)
    await call.answer()


@router.callback_query(F.data.startswith("duel:pick_mute:"))
async def duel_pick_mute(call: CallbackQuery) -> None:
    await _punishment_picked(call, "mute_1h")


@router.callback_query(F.data.startswith("duel:pick_warn:"))
async def duel_pick_warn(call: CallbackQuery) -> None:
    await _punishment_picked(call, "warn_1w")


async def _announce_duel(message: Message, challenger, opponent, stake_coins: int, punishment: str | None) -> None:
    ch = new_challenge("duel", challenger, opponent, message.chat.id, stake_coins=stake_coins, punishment=punishment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✔️ Принять", callback_data=f"duel:accept:{ch.id}"),
        InlineKeyboardButton(text="✖️ Отклонить", callback_data=f"duel:decline:{ch.id}"),
    ]])
    await message.answer(
        f"{e('gun')} {mention(challenger)} вызывает {mention(opponent)} на дуэль, {stake_text(stake_coins, punishment)}!",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("duel:decline:"))
async def duel_decline(call: CallbackQuery) -> None:
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    drop_challenge(ch.id)
    await call.message.edit_text(f"{e('alert')} Дуэль отклонена.")
    await call.answer()


@router.callback_query(F.data.startswith("duel:accept:"))
async def duel_accept(call: CallbackQuery) -> None:
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    if not await take_both_stakes(ch, call.message):
        drop_challenge(ch.id)
        return
    ch.progress = {"aim_a": 0, "aim_b": 0, "turn_id": ch.challenger.id}
    await call.message.edit_text(
        f"{e('gun')} Дуэль началась! Ход: {mention(ch.challenger)}", reply_markup=_duel_kb(ch.id)
    )
    await call.answer()


def _side(ch, user_id: int) -> str:
    return "a" if user_id == ch.challenger.id else "b"


async def _turn_guard(call: CallbackQuery):
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None:
        await call.answer("Дуэль уже завершена.", show_alert=True)
        return None
    if call.from_user.id != ch.progress["turn_id"]:
        await call.answer("Сейчас не твой ход.", show_alert=True)
        return None
    return ch


@router.callback_query(F.data.startswith("duel:aim:"))
async def duel_aim(call: CallbackQuery) -> None:
    ch = await _turn_guard(call)
    if ch is None:
        return
    side = _side(ch, call.from_user.id)
    key = f"aim_{side}"
    ch.progress[key] = min(MAX_STACKS, ch.progress[key] + 1)
    other = ch.opponent if side == "a" else ch.challenger
    ch.progress["turn_id"] = other.id
    await call.message.edit_text(
        f"{e('info')} {mention(call.from_user)} прицеливается ({ch.progress[key]} стак.).\nХод: {mention(other)}",
        reply_markup=_duel_kb(ch.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("duel:knock:"))
async def duel_knock(call: CallbackQuery) -> None:
    ch = await _turn_guard(call)
    if ch is None:
        return
    side = _side(ch, call.from_user.id)
    ch.progress["aim_b" if side == "a" else "aim_a"] = 0
    other = ch.opponent if side == "a" else ch.challenger
    ch.progress["turn_id"] = other.id
    await call.message.edit_text(
        f"{e('warn')} {mention(call.from_user)} сбивает прицел противника!\nХод: {mention(other)}",
        reply_markup=_duel_kb(ch.id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("duel:shoot:"))
async def duel_shoot(call: CallbackQuery) -> None:
    ch = await _turn_guard(call)
    if ch is None:
        return
    side = _side(ch, call.from_user.id)
    hit_chance = min(95, BASE_HIT_CHANCE + ch.progress[f"aim_{side}"] * AIM_BONUS)
    shooter = ch.challenger if side == "a" else ch.opponent
    target = ch.opponent if side == "a" else ch.challenger

    if random.randint(1, 100) <= hit_chance:
        await call.message.edit_text(f"{e('gun')} {mention(shooter)} стреляет и попадает! ({hit_chance}% шанс)")
        await call.answer()
        drop_challenge(ch.id)
        await settle_stakes(shooter, target, ch, call.message)
        return

    ch.progress["turn_id"] = target.id
    await call.message.edit_text(
        f"{e('warn')} {mention(shooter)} стреляет и промахивается! ({hit_chance}% шанс)\nХод: {mention(target)}",
        reply_markup=_duel_kb(ch.id),
    )
    await call.answer()
