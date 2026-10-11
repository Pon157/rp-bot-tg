"""Свободные RP-команды («ударить», «обнять» …): работают между кем угодно, без отношений,
ничего не начисляют. Список и тексты настраиваются в админ-панели (раздел «RP-команды»).
Шаблон: {1} — автор, {2} — цель, {e:fire} — премиум-эмодзи из emojis.py."""
from __future__ import annotations

import re
import time

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot import repo
from bot.emojis import EMOJI, e
from bot.utils.formatting import esc, mention
from bot.utils.reserved import RESERVED
from bot.utils.targets import Person, target_and_rest

router = Router(name="rpfree")

_cache: dict = {"at": 0.0, "rows": []}
CACHE_TTL = 15  # панель — отдельный процесс, поэтому подтягиваем изменения раз в 15 сек


async def _commands():
    if time.monotonic() - _cache["at"] > CACHE_TTL:
        _cache["rows"] = [dict(r) for r in await repo.list_rp_commands()]
        _cache["at"] = time.monotonic()
    return _cache["rows"]


class RpFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool | dict:
        text = (message.text or "").strip()
        low = text.casefold()
        if not low or low.startswith("/"):
            return False
        for cmd in await _commands():          # длинные триггеры идут первыми
            trig = cmd["trigger"]
            if trig.split()[0] in RESERVED:
                continue
            if low == trig or low.startswith(trig + " ") or low.startswith(trig + "\n"):
                return {"rp_command": cmd, "rp_args": text[len(trig):].strip()}
        return False


def render_template(template: str, actor: str, target: str) -> str:
    text = esc(template)
    text = re.sub(r"\{e:(\w+)\}", lambda m: e(m.group(1)) if m.group(1) in EMOJI else "", text)
    return text.replace("{1}", actor).replace("{2}", target)


@router.message(RpFilter())
async def rp_command(message: Message, rp_command: dict, rp_args: str) -> None:
    target, _ = await target_and_rest(message, rp_args)
    if target is None:
        if not rp_args:  # просто «ударить» без цели — подсказка; «ударить всех» — молча игнор
            await message.reply(
                f"{e('info')} Ответь на сообщение человека или укажи @ник: "
                f"<code>{esc(rp_command['trigger'])} @ник</code>"
            )
        return
    if target.id == message.from_user.id:
        await message.reply(f"{e('warn')} На себя такое не направить.")
        return
    await message.answer(render_template(rp_command["template"], mention(message.from_user), mention(target)))
