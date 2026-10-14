from __future__ import annotations

import random
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot import repo
from bot.emojis import e, btn
from .common import new_challenge, get_challenge, drop_challenge, deduct_stake_or_fail, settle_stakes

router = Router(name="game_duel")

BASE_HIT_CHANCE = 40   # %
AIM_BONUS = 15         # % за каждый стак прицела, максимум учитываем 3 стака
MAX_STACKS = 3

# временное хранилище выбора наказания, пока challenger не подтвердил вызов
_pending_punishment_choice: dict[int, int] = {}  # user_id -> будет использовано при следующем вызове


def _duel_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎯 Прицелиться", callback_data=f"duel:aim:{cid}"),
        InlineKeyboardButton(text="🔫 Выстрелить", callback_data=f"duel:shoot:{cid}"),
        InlineKeyboardButton(text="💨 Сбить прицел", callback_data=f"duel:knock:{cid}"),
    ]])


@router.message(F.text.regexp(r"(?i)^дуэль(\s+ставка\s+(?P<amount>\d+))?$"))
async def duel_start(message: Message) -> None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответь этой командой на сообщение соперника, чтобы вызвать его на дуэль.")
        return
    opponent = message.reply_to_message.from_user
    challenger = message.from_user
    if opponent.id == challenger.id:
        await message.reply("Нельзя дуэлиться с самим собой 🙂")
        return

    text = message.text or ""
    match = re.search(r"ставка\s+(\d+)", text, flags=re.I)

    if match:
        stake = int(match.group(1))
        await _announce_duel(message, challenger, opponent, stake_coins=stake, punishment=None)
        return

    # дуэль без ставки — на наказание, сперва спрашиваем у вызывающего какое наказание
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{btn('chain')} Мут на час", callback_data=f"duel:pick_mute:{opponent.id}"),
        InlineKeyboardButton(text=f"{btn('warn')} Варн на неделю", callback_data=f"duel:pick_warn:{opponent.id}"),
    ]])
    await message.reply(
        "Выбери наказание для проигравшего (решает тот, кто вызывает на дуэль):",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("duel:pick_mute:"))
async def duel_pick_mute(call: CallbackQuery) -> None:
    await _duel_punishment_picked(call, "mute_1h")


@router.callback_query(F.data.startswith("duel:pick_warn:"))
async def duel_pick_warn(call: CallbackQuery) -> None:
    await _duel_punishment_picked(call, "warn_1w")


async def _duel_punishment_picked(call: CallbackQuery, punishment: str) -> None:
    opponent_id = int(call.data.split(":")[2])
    challenger = call.from_user
    bot = call.bot
    try:
        opponent = (await bot.get_chat_member(call.message.chat.id, opponent_id)).user
    except Exception:
        await call.answer("Не удалось найти соперника.", show_alert=True)
        return
    await call.message.delete()
    await _announce_duel(call.message, challenger, opponent, stake_coins=0, punishment=punishment)
    await call.answer()


async def _announce_duel(message: Message, challenger, opponent, stake_coins: int, punishment: str | None) -> None:
    ch = new_challenge("duel", challenger, opponent, message.chat.id, stake_coins=stake_coins, punishment=punishment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{btn('check')} Принять", callback_data=f"duel:accept:{ch.id}"),
        InlineKeyboardButton(text=f"{btn('alert')} Отклонить", callback_data=f"duel:decline:{ch.id}"),
    ]])
    if stake_coins:
        stake_text = f"на ставку {stake_coins} монет"
    else:
        stake_text = "на мут на 1 час" if punishment == "mute_1h" else "на варн на неделю"
    await message.answer(
        f"{e('gun')} {challenger.first_name} вызывает {opponent.first_name} на дуэль, {stake_text}!",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("duel:decline:"))
async def duel_decline(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None or call.from_user.id != ch.opponent.id:
        await call.answer("Это не тебе.", show_alert=True)
        return
    drop_challenge(cid)
    await call.message.edit_text(f"{e('alert')} Дуэль отклонена.", parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("duel:accept:"))
async def duel_accept(call: CallbackQuery) -> None:
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

    ch.progress = {"aim_a": 0, "aim_b": 0, "turn_id": ch.challenger.id}
    await call.message.edit_text(
        f"{e('gun')} Дуэль началась! Ход: {ch.challenger.first_name}",
        parse_mode="HTML",
        reply_markup=_duel_kb(cid),
    )
    await call.answer()


def _side(ch, user_id: int) -> str:
    return "a" if user_id == ch.challenger.id else "b"


@router.callback_query(F.data.startswith("duel:aim:"))
async def duel_aim(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None:
        await call.answer("Дуэль уже завершена.", show_alert=True); return
    if call.from_user.id != ch.progress["turn_id"]:
        await call.answer("Сейчас не твой ход.", show_alert=True); return

    side = _side(ch, call.from_user.id)
    key = f"aim_{side}"
    ch.progress[key] = min(MAX_STACKS, ch.progress[key] + 1)
    other = ch.opponent if side == "a" else ch.challenger
    ch.progress["turn_id"] = other.id
    await call.message.edit_text(
        f"{e('info')} {call.from_user.first_name} прицеливается ({ch.progress[key]} стак(ов)).\nХод: {other.first_name}",
        parse_mode="HTML",
        reply_markup=_duel_kb(cid),
    )
    await call.answer()


@router.callback_query(F.data.startswith("duel:knock:"))
async def duel_knock(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None:
        await call.answer("Дуэль уже завершена.", show_alert=True); return
    if call.from_user.id != ch.progress["turn_id"]:
        await call.answer("Сейчас не твой ход.", show_alert=True); return

    side = _side(ch, call.from_user.id)
    other_key = "aim_b" if side == "a" else "aim_a"
    ch.progress[other_key] = 0
    other = ch.opponent if side == "a" else ch.challenger
    ch.progress["turn_id"] = other.id
    await call.message.edit_text(
        f"{e('warn')} {call.from_user.first_name} сбивает прицел противника!\nХод: {other.first_name}",
        parse_mode="HTML",
        reply_markup=_duel_kb(cid),
    )
    await call.answer()


@router.callback_query(F.data.startswith("duel:shoot:"))
async def duel_shoot(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None:
        await call.answer("Дуэль уже завершена.", show_alert=True); return
    if call.from_user.id != ch.progress["turn_id"]:
        await call.answer("Сейчас не твой ход.", show_alert=True); return

    side = _side(ch, call.from_user.id)
    stacks = ch.progress[f"aim_{side}"]
    hit_chance = min(95, BASE_HIT_CHANCE + stacks * AIM_BONUS)
    shooter = ch.challenger if side == "a" else ch.opponent
    target = ch.opponent if side == "a" else ch.challenger

    if random.randint(1, 100) <= hit_chance:
        await call.message.edit_text(
            f"{e('gun')} {shooter.first_name} стреляет и попадает! ({hit_chance}% шанс)",
            parse_mode="HTML",
        )
        await call.answer()
        await settle_stakes(shooter, target, ch, call.message)
        drop_challenge(cid)
        return

    ch.progress["turn_id"] = target.id
    await call.message.edit_text(
        f"{e('warn')} {shooter.first_name} стреляет и промахивается! ({hit_chance}% шанс)\nХод: {target.first_name}",
        parse_mode="HTML",
        reply_markup=_duel_kb(cid),
    )
    await call.answer()
