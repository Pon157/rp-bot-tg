"""Кнопки с премиум-эмодзи: иконка идёт через icon_custom_emoji_id, подпись — без юникода."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from bot.emojis import EMOJI


def ibtn(text: str, icon: str | None = None, *, callback_data: str | None = None,
         url: str | None = None) -> InlineKeyboardButton:
    """icon — имя из bot/emojis.py (например 'check'), None — кнопка без иконки."""
    kw = {}
    if icon:
        kw["icon_custom_emoji_id"] = EMOJI[icon][0]
    return InlineKeyboardButton(text=text, callback_data=callback_data, url=url, **kw)
