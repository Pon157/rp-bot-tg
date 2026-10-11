from __future__ import annotations

import datetime as dt
import itertools
import random
import re
from dataclasses import dataclass, field

from bot.utils.buttons import ibtn
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import repo
from bot.emojis import e
from bot.moderation import apply_action
from bot.utils.formatting import mention
from bot.utils.targets import Person, target_and_rest

_challenge_ids = itertools.count(1)


@dataclass
class Challenge:
    id: int
    game: str                       # 'dice' | 'coinflip' | 'piano' | 'duel'
    challenger: object              # aiogram User или Person — главное id/first_name/username
    opponent: object
    chat_id: int
    stake_coins: int = 0            # 0, если игра на наказание
    punishment: str | None = None   # 'mute_1h' | 'warn_1w', если игра на наказание
    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)
    progress: dict = field(default_factory=dict)


CHALLENGES: dict[int, Challenge] = {}


def new_challenge(game: str, challenger, opponent, chat_id: int,
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


async def parse_game_command(message: Message, word: str):
    """Разбирает «кости @ник ставка 50» / ответ на сообщение.
    Возвращает (соперник | None, ставка, остаток, ошибка | None)."""
    args = re.sub(rf"(?i)^{word}", "", message.text or "", count=1).strip()
    opponent, rest = await target_and_rest(message, args)
    if opponent is None:
        return None, 0, rest, (f"{e('info')} Ответь командой на сообщение соперника "
                               f"или укажи @ник: <code>{word} @ник</code>")
    if opponent.id == message.from_user.id:
        return None, 0, rest, "Нельзя играть с самим собой 🙂"
    if opponent.is_bot:
        return None, 0, rest, "С ботами не играем 🙂"
    stake = 0
    m = re.search(r"(?i)ставка\s+(\d+)", rest)
    if m:
        stake = int(m.group(1))
        if stake <= 0:
            return None, 0, rest, "Ставка должна быть больше нуля."
        if await repo.get_balance(message.from_user.id) < stake:
            return None, 0, rest, f"{e('coin')} У вас не хватает монет на такую ставку."
    return opponent, stake, rest, None


def stake_text(stake: int, punishment: str | None = "mute_1h") -> str:
    if stake:
        return f"на ставку {stake} монет"
    return "на мут на 1 час" if punishment == "mute_1h" else "на варн на неделю"


async def settle_stakes(winner, loser, ch: Challenge, message: Message) -> None:
    """Выплачивает монеты победителю либо реально применяет наказание проигравшему."""
    head = f"{e('trophy')} Победитель: {mention(winner)}!"
    if ch.stake_coins > 0:
        total = ch.stake_coins * 2
        await repo.add_coins(winner.id, total)
        await message.answer(f"{head} Забирает <b>{total}</b> монет.")
    elif ch.punishment == "mute_1h":
        _, text = await apply_action(message.bot, "mute", loser.id, duration_sec=3600, reason="проигрыш в игре")
        await message.answer(f"{head}\n{text}")
    elif ch.punishment == "warn_1w":
        _, text = await apply_action(message.bot, "warn", loser.id, reason="проигрыш в игре", warn_expires_days=7)
        await message.answer(f"{head}\n{text}")
    else:
        await message.answer(head)


async def deduct_stake_or_fail(user, amount: int, message: Message) -> bool:
    if amount <= 0:
        return True
    ok = await repo.try_take_coins(user.id, amount)
    if not ok:
        await message.answer(f"{e('coin')} У {mention(user)} не хватает монет на такую ставку.")
    return ok


async def take_both_stakes(ch: Challenge, message: Message) -> bool:
    """Списывает ставки с обоих; если у кого-то не хватило — возвращает уже списанное."""
    if not ch.stake_coins:
        return True
    if not await deduct_stake_or_fail(ch.challenger, ch.stake_coins, message):
        return False
    if not await deduct_stake_or_fail(ch.opponent, ch.stake_coins, message):
        await repo.add_coins(ch.challenger.id, ch.stake_coins)
        return False
    return True


# ---------------- «прогрессивные» игры: монеточка и пианино ----------------

def progressive_keyboard(cid: int, prefix: str, button_label: str, icon: str = "fire") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        ibtn(button_label, icon, callback_data=f"{prefix}:press:{cid}")
    ]])


async def handle_progressive_press(prefix: str, call, button_label: str, icon: str = "fire") -> None:
    """Ходят по очереди; каждое нажатие поднимает шанс, что соперник сдастся прямо сейчас."""
    ch = get_challenge(int(call.data.split(":")[2]))
    if ch is None:
        await call.answer("Игра уже завершена.", show_alert=True)
        return
    if call.from_user.id != ch.progress.get("turn_id", ch.challenger.id):
        await call.answer("Сейчас не твой ход.", show_alert=True)
        return

    presser = ch.challenger if call.from_user.id == ch.challenger.id else ch.opponent
    other = ch.opponent if presser.id == ch.challenger.id else ch.challenger

    presses = ch.progress.get("presses", 0) + 1
    ch.progress["presses"] = presses
    give_up_chance = min(95, 15 + presses * 12)

    if random.randint(1, 100) <= give_up_chance:
        await call.message.edit_text(
            f"{e('trophy')} {mention(other)} не выдержал! Победитель: {mention(presser)} 🎉"
        )
        await settle_stakes(presser, other, ch, call.message)
        drop_challenge(ch.id)
        await call.answer()
        return

    ch.progress["turn_id"] = other.id
    await call.message.edit_text(
        f"{e('fire')} {mention(presser)} жмёт «{button_label}»... {mention(other)} держится! "
        f"({presses} попытка, шанс сдаться уже {give_up_chance}%)\nХод: {mention(other)}",
        reply_markup=progressive_keyboard(ch.id, prefix, button_label, icon),
    )
    await call.answer()
