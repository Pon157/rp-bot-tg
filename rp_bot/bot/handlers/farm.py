from __future__ import annotations

import datetime as dt
import random

from aiogram import Router, F
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.utils.formatting import fmt_timedelta

router = Router(name="farm")


@router.message(F.text.casefold().in_({"фарма", "ферма"}))
async def farm(message: Message) -> None:
    user_id = message.from_user.id
    last = await repo.get_last_farm_at(user_id)
    if last is not None:
        elapsed = (dt.datetime.utcnow() - last).total_seconds()
        remaining = settings.farm_cooldown_sec - elapsed
        if remaining > 0:
            await message.reply(
                f"{e('clock')} Следующая фарма через {fmt_timedelta(remaining)}.", parse_mode="HTML"
            )
            return

    amount = random.randint(settings.farm_min_coins, settings.farm_max_coins)
    new_balance = await repo.add_coins(user_id, amount)
    await repo.set_last_farm_now(user_id)
    await message.reply(
        f"{e('coin')} Вы нафармили <b>{amount}</b> красных монет! Баланс: <b>{new_balance}</b>.",
        parse_mode="HTML",
    )


@router.message(F.text.casefold() == "баланс")
async def balance(message: Message) -> None:
    bal = await repo.get_balance(message.from_user.id)
    await message.reply(f"{e('coin')} Ваш баланс: <b>{bal}</b> красных монет.", parse_mode="HTML")
