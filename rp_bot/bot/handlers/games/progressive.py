"""Монеточка и пианино — одна и та же механика, отличаются словом команды и кнопкой."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.emojis import e
from bot.utils.formatting import mention
from .common import (
    drop_challenge, get_challenge, handle_progressive_press, new_challenge, parse_game_command,
    progressive_keyboard, stake_text, take_both_stakes,
)


def build_router(*, name: str, word: str, prefix: str, button_label: str, title: str) -> Router:
    router = Router(name=f"game_{name}")

    @router.message(F.text.regexp(rf"(?i)^{word}\b"))
    async def challenge(message: Message) -> None:
        opponent, stake, _, error = await parse_game_command(message, word)
        if error:
            await message.reply(error)
            return
        ch = new_challenge(name, message.from_user, opponent, message.chat.id, stake_coins=stake,
                           punishment=None if stake else "mute_1h")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✔️ Принять", callback_data=f"{prefix}:accept:{ch.id}"),
            InlineKeyboardButton(text="✖️ Отклонить", callback_data=f"{prefix}:decline:{ch.id}"),
        ]])
        await message.answer(
            f"{e('fire')} {mention(message.from_user)} вызывает {mention(opponent)} на {title}, "
            f"{stake_text(stake)}!", reply_markup=kb,
        )

    @router.callback_query(F.data.startswith(f"{prefix}:decline:"))
    async def decline(call: CallbackQuery) -> None:
        ch = get_challenge(int(call.data.split(":")[2]))
        if ch is None or call.from_user.id != ch.opponent.id:
            await call.answer("Это не тебе.", show_alert=True)
            return
        drop_challenge(ch.id)
        await call.message.edit_text(f"{e('alert')} Вызов отклонён.")
        await call.answer()

    @router.callback_query(F.data.startswith(f"{prefix}:accept:"))
    async def accept(call: CallbackQuery) -> None:
        ch = get_challenge(int(call.data.split(":")[2]))
        if ch is None or call.from_user.id != ch.opponent.id:
            await call.answer("Это не тебе.", show_alert=True)
            return
        if not await take_both_stakes(ch, call.message):
            drop_challenge(ch.id)
            return
        ch.progress["turn_id"] = ch.challenger.id
        await call.message.edit_text(
            f"{e('fire')} Игра началась! Ход: {mention(ch.challenger)}",
            reply_markup=progressive_keyboard(ch.id, prefix, button_label),
        )
        await call.answer()

    @router.callback_query(F.data.startswith(f"{prefix}:press:"))
    async def press(call: CallbackQuery) -> None:
        await handle_progressive_press(prefix, call, button_label)

    return router
