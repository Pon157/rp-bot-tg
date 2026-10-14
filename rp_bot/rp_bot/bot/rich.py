"""Rich Messages (Bot API 10.1, 11.06.2026): нативные таблицы и структурированный текст.

В aiogram 3.15 метода sendRichMessage ещё нет (он появился в 3.31), поэтому здесь свой
класс метода — он работает на любой версии aiogram, обновлять библиотеку не нужно.

Принцип «никогда не терять сообщение» — лестница отката:
  1) sendRichMessage (нативные таблицы);
  2) если Telegram отверг (BadRequest) — обычное HTML-сообщение (fallback);
  3) если и оно не разобралось — то же самое простым текстом без тегов.
Если сервер вообще не знает метод (404, например локальный Bot API постарше) — rich
отключается на 10 минут, чтобы не долбить его на каждом сообщении.
Выключить совсем: RICH_MESSAGES=0 в .env.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.methods.base import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters

from bot import repo
from bot.config import settings
from bot.utils.formatting import esc

logger = logging.getLogger("rp_bot.rich")

RICH_LIMIT = 30000          # у rich-сообщения лимит 32 768 символов, берём с запасом
_disabled_until = 0.0


class SendRichMessage(TelegramMethod[Message]):
    """https://core.telegram.org/bots/api#sendrichmessage (Bot API 10.1)."""

    __returning__ = Message
    __api_method__ = "sendRichMessage"

    chat_id: int | str
    rich_message: dict[str, Any]            # {"html": "..."} или {"markdown": "..."}
    message_thread_id: int | None = None
    disable_notification: bool | None = None
    reply_parameters: ReplyParameters | None = None
    reply_markup: InlineKeyboardMarkup | None = None


def strip_tags(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text))


def to_classic(html: str) -> str:
    """Rich HTML -> максимально близкий обычный HTML: таблица превращается в строки
    «ячейка │ ячейка», заголовки — в жирный; остальные теги (b, i, a, blockquote, ...) остаются."""
    t = re.sub(r"</t[hd]>\s*<t[hd][^>]*>", " │ ", html)
    t = re.sub(r"</?t[hd][^>]*>", "", t)
    t = re.sub(r"</tr>", "\n", t)
    t = re.sub(r"<caption>.*?</caption>", "", t, flags=re.S)
    t = re.sub(r"</?(?:table|tr)[^>]*>", "", t)
    t = re.sub(r"<h[1-6][^>]*>", "<b>", t)
    t = re.sub(r"</h[1-6]>", "</b>\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


async def send_rich(bot: Bot, chat_id: int, html: str, fallback: str | None = None, *,
                    reply_to: int | None = None, thread_id: int | None = None,
                    reply_markup: InlineKeyboardMarkup | None = None, rich: bool = True) -> Message:
    """rich=False — «старая версия»: сразу обычное сообщение, без попытки sendRichMessage."""
    global _disabled_until
    reply_params = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None

    if rich and settings.rich_messages and time.monotonic() >= _disabled_until and len(html) <= RICH_LIMIT:
        try:
            return await bot(SendRichMessage(
                chat_id=chat_id, rich_message={"html": html}, message_thread_id=thread_id,
                reply_parameters=reply_params, reply_markup=reply_markup,
            ))
        except TelegramNotFound:
            _disabled_until = time.monotonic() + 600
            logger.warning("Сервер не знает sendRichMessage — rich-сообщения отключены на 10 минут")
        except TelegramBadRequest as exc:
            logger.warning("sendRichMessage отклонён (%s) — отправляю обычным сообщением", exc.message)

    text = fallback if fallback is not None else to_classic(html)
    kwargs = dict(chat_id=chat_id, message_thread_id=thread_id, reply_parameters=reply_params, reply_markup=reply_markup)
    try:
        return await bot.send_message(text=text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("HTML не разобрался (%s) — отправляю простым текстом", exc.message)
        return await bot.send_message(text=strip_tags(text)[:4096], parse_mode=None, **kwargs)


def _thread(message: Message) -> int | None:
    return message.message_thread_id if getattr(message, "is_topic_message", False) else None


async def wants_rich(message: Message) -> bool:
    """Выбрал ли автор сообщения «старую версию» (команда стараяверсия)."""
    if message.from_user is None:
        return True
    return await repo.get_rich_pref(message.from_user.id)


async def answer_rich(message: Message, html: str, fallback: str | None = None, **kw) -> Message:
    return await send_rich(message.bot, message.chat.id, html, fallback, thread_id=_thread(message),
                           rich=await wants_rich(message), **kw)


async def reply_rich(message: Message, html: str, fallback: str | None = None, **kw) -> Message:
    return await send_rich(message.bot, message.chat.id, html, fallback, reply_to=message.message_id,
                           thread_id=_thread(message), rich=await wants_rich(message), **kw)


# ----------------------------------------------------------- построители ----

def rtable(headers: list[str], rows: list[list[str]], *, align: list[str] | None = None,
           caption: str | None = None) -> str:
    """Нативная таблица Rich HTML. headers экранируются здесь; ячейки rows — УЖЕ готовый
    безопасный HTML (ники-ссылки, <code>, esc(...)). align: left|center|right на колонку."""
    align = align or ["left"] * len(headers)
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f'<td align="{align[i]}">{cell}</td>' for i, cell in enumerate(row)) + "</tr>"
        for row in rows
    )
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f"<table bordered striped>{cap}<tr>{head}</tr>{body}</table>"
