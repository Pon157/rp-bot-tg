"""Система питомцев.

Яйцо стоит 500 красных монет (настраивается в meta: pet_egg_cost), из него
вылупляется случайный питомец. За питомцем нужно ухаживать: кормить, играть,
гулять — иначе его характеристики (сытость/счастье/энергия) со временем падают.
На пользователя — один питомец одновременно.
"""
from __future__ import annotations

import datetime as dt
import random

from aiogram import Router, F
from aiogram.types import Message

from bot import repo
from bot.rich import reply_rich
from bot.emojis import e
from bot.utils.formatting import esc, fmt_timedelta

router = Router(name="pets")

DEFAULT_EGG_COST = 500

# вид -> (эмодзи, имя по умолчанию в падеже "твой ...")
SPECIES = {
    "кот": "🐱",
    "пёс": "🐶",
    "лис": "🦊",
    "дракончик": "🐲",
    "панда": "🐼",
    "хомяк": "🐹",
    "пингвин": "🐧",
    "кролик": "🐰",
}

# упадок характеристик со временем (в пунктах в час)
DECAY_PER_HOUR = {"hunger": 4, "happiness": 2, "energy": 3}

FEED_COOLDOWN_SEC = 2 * 60 * 60
PLAY_COOLDOWN_SEC = 2 * 60 * 60
WALK_COOLDOWN_SEC = 3 * 60 * 60


async def _egg_cost() -> int:
    raw = await repo.get_meta("pet_egg_cost", str(DEFAULT_EGG_COST))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_EGG_COST


def _bar(value: int) -> str:
    value = max(0, min(100, value))
    filled = round(value / 10)
    return "█" * filled + "░" * (10 - filled) + f" {value}%"


async def _ticked_pet(user_id: int):
    """Отдаёт питомца с пересчитанными по времени характеристиками (и сохраняет пересчёт)."""
    pet = await repo.get_pet(user_id)
    if pet is None:
        return None
    last_tick = dt.datetime.fromisoformat(pet["last_tick_at"])
    hours = max(0.0, (dt.datetime.utcnow() - last_tick).total_seconds() / 3600)
    if hours <= 0:
        return pet
    hunger = max(0, pet["hunger"] - round(DECAY_PER_HOUR["hunger"] * hours))
    happiness = max(0, pet["happiness"] - round(DECAY_PER_HOUR["happiness"] * hours))
    energy = max(0, pet["energy"] - round(DECAY_PER_HOUR["energy"] * hours))
    if (hunger, happiness, energy) != (pet["hunger"], pet["happiness"], pet["energy"]):
        await repo.apply_pet_tick(user_id, hunger, happiness, energy)
        pet = await repo.get_pet(user_id)
    return pet


def _status_line(pet) -> str:
    icon = SPECIES.get(pet["species"], "🐾")
    return (
        f"{icon} <b>{esc(pet['name'])}</b> ({pet['species']}), уровень {pet['level']}\n"
        f"{e('coin')} Опыт: {pet['xp']}/{pet['level'] * 100}\n"
        f"🍖 Сытость: {_bar(pet['hunger'])}\n"
        f"💖 Счастье: {_bar(pet['happiness'])}\n"
        f"⚡ Энергия: {_bar(pet['energy'])}"
    )


@router.message(F.text.casefold().in_({"купить яйцо", "яйцо", "купить питомца"}))
async def buy_egg(message: Message) -> None:
    user_id = message.from_user.id
    existing = await repo.get_pet(user_id)
    if existing is not None:
        await reply_rich(message,
            f"{e('warn')} У вас уже есть питомец — {esc(existing['name'])}. "
            f"Одновременно можно держать только одного.")
        return

    cost = await _egg_cost()
    if not await repo.try_take_coins(user_id, cost):
        balance = await repo.get_balance(user_id)
        await reply_rich(message,
            f"{e('coin')} Яйцо стоит <b>{cost}</b> монет, у вас только <b>{balance}</b>. "
            f"Фармите командой «фарма».")
        return

    species = random.choice(list(SPECIES.keys()))
    name = species.capitalize()
    await repo.create_pet(user_id, name, species)
    icon = SPECIES[species]
    await reply_rich(message,
        f"{e('gift')} Яйцо треснуло — вылупился {icon} <b>{species}</b>!\n"
        f"Назовите его командой «назвать питомца &lt;имя&gt;», а пока его зовут просто «{esc(name)}».\n"
        f"Ухаживайте: «покормить», «играть», «гулять».",
    )


@router.message(F.text.casefold().startswith("назвать питомца "))
async def rename(message: Message) -> None:
    pet = await repo.get_pet(message.from_user.id)
    if pet is None:
        await reply_rich(message, f"{e('warn')} У вас пока нет питомца — купите яйцо.")
        return
    new_name = message.text.split(" ", 2)[2].strip()[:32]
    if not new_name:
        await reply_rich(message, f"{e('warn')} Укажите имя: «назвать питомца Рекс».")
        return
    await repo.rename_pet(message.from_user.id, new_name)
    await reply_rich(message, f"{e('check')} Теперь питомца зовут <b>{esc(new_name)}</b>.")


@router.message(F.text.casefold().in_({"питомец", "мой питомец", "питомцы"}))
async def status(message: Message) -> None:
    pet = await _ticked_pet(message.from_user.id)
    if pet is None:
        cost = await _egg_cost()
        await reply_rich(message,
            f"{e('info')} У вас ещё нет питомца. Купите яйцо за <b>{cost}</b> монет: «купить яйцо».")
        return
    await reply_rich(message, _status_line(pet))


def _cooldown_left(stamp: str | None, cooldown_sec: int) -> float:
    if not stamp:
        return 0.0
    elapsed = (dt.datetime.utcnow() - dt.datetime.fromisoformat(stamp)).total_seconds()
    return max(0.0, cooldown_sec - elapsed)


@router.message(F.text.casefold().in_({"покормить", "кормить", "покормить питомца"}))
async def feed(message: Message) -> None:
    pet = await _ticked_pet(message.from_user.id)
    if pet is None:
        await reply_rich(message, f"{e('warn')} У вас пока нет питомца — купите яйцо.")
        return
    left = _cooldown_left(pet["last_fed_at"], FEED_COOLDOWN_SEC)
    if left > 0:
        await reply_rich(message, f"{e('clock')} {esc(pet['name'])} ещё не проголодался: через {fmt_timedelta(left)}.")
        return
    pet = await repo.pet_action(message.from_user.id, {"hunger": 35}, xp_gain=5,
                                stamp_field="last_fed_at")
    await reply_rich(message, f"🍖 Вы покормили {esc(pet['name'])}!\n\n{_status_line(pet)}")


@router.message(F.text.casefold().in_({"играть", "играть с питомцем", "поиграть"}))
async def play(message: Message) -> None:
    pet = await _ticked_pet(message.from_user.id)
    if pet is None:
        await reply_rich(message, f"{e('warn')} У вас пока нет питомца — купите яйцо.")
        return
    left = _cooldown_left(pet["last_played_at"], PLAY_COOLDOWN_SEC)
    if left > 0:
        await reply_rich(message, f"{e('clock')} {esc(pet['name'])} устал играть: через {fmt_timedelta(left)}.")
        return
    if pet["energy"] < 10:
        await reply_rich(message, f"{e('warn')} {esc(pet['name'])} слишком без сил для игры — дайте ему отдохнуть.")
        return
    pet = await repo.pet_action(message.from_user.id, {"happiness": 25, "energy": -15},
                                xp_gain=8, stamp_field="last_played_at")
    await reply_rich(message, f"🎾 Вы поиграли с {esc(pet['name'])}!\n\n{_status_line(pet)}")


@router.message(F.text.casefold().in_({"гулять", "погулять", "гулять с питомцем", "выгулять питомца"}))
async def walk(message: Message) -> None:
    pet = await _ticked_pet(message.from_user.id)
    if pet is None:
        await reply_rich(message, f"{e('warn')} У вас пока нет питомца — купите яйцо.")
        return
    left = _cooldown_left(pet["last_walked_at"], WALK_COOLDOWN_SEC)
    if left > 0:
        await reply_rich(message, f"{e('clock')} {esc(pet['name'])} ещё не хочет гулять: через {fmt_timedelta(left)}.")
        return
    pet = await repo.pet_action(message.from_user.id, {"happiness": 15, "energy": 20, "hunger": -10},
                                xp_gain=10, stamp_field="last_walked_at")
    await reply_rich(message, f"🚶 Вы погуляли с {esc(pet['name'])}!\n\n{_status_line(pet)}")
