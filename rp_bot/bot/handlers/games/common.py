from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field

from aiogram.types import Message, User

from bot import repo
from bot.emojis import e

_challenge_ids = itertools.count(1)

PUNISHMENTS = {
    "mute_1h": "мут на 1 час",
    "warn_1w": "варн на неделю (истекает автоматически)",
}


@dataclass
class Challenge:
    id: int
    game: str                       # 'dice' | 'coinflip' | 'piano' | 'duel'
    challenger: User
    opponent: User
    chat_id: int
    stake_coins: int = 0            # 0, если игра на наказание
    punishment: str | None = None   # 'mute_1h' | 'warn_1w', если игра на наказание
    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)
    # состояние для игр с "прогрессивным шансом" (монеточка/пианино/дуэль)
    progress: dict = field(default_factory=lambda: {"a": 0, "b": 0})


CHALLENGES: dict[int, Challenge] = {}


def new_challenge(game: str, challenger: User, opponent: User, chat_id: int,
                   stake_coins: int = 0, punishment: str | None = None) -> Challenge:
    cid = next(_challenge_ids)
    ch = Challenge(id=cid, game=game, challenger=challenger, opponent=opponent,
                    chat_id=chat_id, stake_coins=stake_coins, punishment=punishment)
    CHALLENGES[cid] = ch
    return ch


def get_challenge(cid: int) -> Challenge | None:
    return CHALLENGES.get(cid)


def drop_challenge(cid: int) -> None:
    CHALLENGES.pop(cid, None)


async def settle_stakes(winner: User, loser: User, ch: Challenge, message: Message) -> None:
    """Начисляет монеты победителю (ставка уже списана с обоих при старте) или
    объявляет наказание — сам мут/варн администратор применяет вручную или через
    модуль модерации бота (apply_mute/apply_warn), здесь только фиксируем результат."""
    if ch.stake_coins > 0:
        total = ch.stake_coins * 2
        await repo.add_coins(winner.id, total)
        await message.answer(
            f"{e('trophy')} Победитель: {_disp(winner)}! Забирает <b>{total}</b> монет.",
            parse_mode="HTML",
        )
    elif ch.punishment:
        until = None
        if ch.punishment == "mute_1h":
            until = dt.datetime.utcnow() + dt.timedelta(hours=1)
            await repo.apply_mute(loser.id, until)
            await repo.add_mod_log(loser.id, "mute", "проигрыш в игре", None)
            punish_text = "получает мут на 1 час"
        else:
            warns = await repo.apply_warn(loser.id, expires_in_days=7)
            await repo.add_mod_log(loser.id, "warn", "проигрыш в игре (снимается через неделю)", None)
            punish_text = f"получает варн (всего варнов: {warns}, этот снимется через неделю)"
        await message.answer(
            f"{e('trophy')} Победитель: {_disp(winner)}!\n{e('chain')} {_disp(loser)} {punish_text}.",
            parse_mode="HTML",
        )
    else:
        await message.answer(f"{e('trophy')} Победитель: {_disp(winner)}!", parse_mode="HTML")


def _disp(u: User) -> str:
    name = u.first_name or (f"@{u.username}" if u.username else str(u.id))
    return f'<a href="tg://user?id={u.id}">{name}</a>'


import random

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def progressive_keyboard(cid: int, prefix: str, button_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=button_label, callback_data=f"{prefix}:press:{cid}")
    ]])


async def handle_progressive_press(prefix: str, call, button_label: str) -> None:
    """Общая логика для игр 'монеточка' и 'пианино': ходят по очереди, каждое
    нажатие поднимает шанс, что соперник сдастся именно сейчас."""
    cid = int(call.data.split(":")[2])
    ch = get_challenge(cid)
    if ch is None:
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    turn_user_id = ch.progress.get("turn_id", ch.challenger.id)
    if call.from_user.id != turn_user_id:
        await call.answer("Сейчас не твой ход.", show_alert=True)
        return

    presser = ch.challenger if call.from_user.id == ch.challenger.id else ch.opponent
    opponent = ch.opponent if presser.id == ch.challenger.id else ch.challenger

    presses = ch.progress.get("presses", 0) + 1
    ch.progress["presses"] = presses
    # шанс, что соперник сдастся в этот раз: растёт с каждым нажатием, максимум ~95%
    give_up_chance = min(95, 15 + presses * 12)

    if random.randint(1, 100) <= give_up_chance:
        await call.message.edit_text(
            f"{e('trophy')} {opponent.first_name} не выдержал! Победитель: {presser.first_name} 🎉",
            parse_mode="HTML",
        )
        await settle_stakes(presser, opponent, ch, call.message)
        drop_challenge(cid)
        await call.answer()
        return

    ch.progress["turn_id"] = opponent.id
    await call.message.edit_text(
        f"{e('fire')} {presser.first_name} жмёт «{button_label}»... {opponent.first_name} держится! "
        f"({presses} попытка, шанс сдаться уже {give_up_chance}%)\nХод: {opponent.first_name}",
        parse_mode="HTML",
        reply_markup=progressive_keyboard(cid, prefix, button_label),
    )
    await call.answer()


async def deduct_stake_or_fail(user: User, amount: int, message: Message) -> bool:
    if amount <= 0:
        return True
    ok = await repo.try_take_coins(user.id, amount)
    if not ok:
        await message.answer(f"{e('coin')} У {_disp(user)} не хватает монет на такую ставку.", parse_mode="HTML")
    return ok
