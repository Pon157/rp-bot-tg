"""Анонимные комментарии под постами канала.

Как это работает:
  1. В админ-панели (Настройки) указывается ID канала с постами.
  2. Когда в канале выходит пост, Telegram сам пересылает его в привязанную
     группу обсуждений (это штатная функция Telegram, настраивается в самом
     канале: Управление каналом -> Обсуждение). Бот должен быть добавлен в эту
     группу администратором (чтобы видеть все сообщения).
  3. Бот видит в группе авто-пересланную копию поста (is_automatic_forward=True,
     forward_from_chat.id == ID канала) и отвечает на неё кнопкой-диплинком
     "Написать анонимный комментарий" -> t.me/<bot>?start=cmt_<токен>.
  4. Пользователь открывает бота в личке, бот просит прислать текст комментария.
  5. Что пришло — публикуется в группе обсуждений ответом на исходный пост,
     от имени бота, без каких-либо указаний на автора ("Аноним").

ID группы обсуждений бот определяет сам через bot.get_chat(channel_id).linked_chat_id
и сохраняет в meta (comments_group_id), чтобы ChatGuardMiddleware пропускал её.
"""
from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError

from bot import repo
from bot.emojis import e
from bot.utils.buttons import ibtn
from bot.utils.formatting import esc

logger = logging.getLogger("rp_bot.comments")
router = Router(name="comments")

# user_id -> токен комментируемого поста, ждём следующее сообщение в личке
_pending: dict[int, str] = {}


async def resolve_comments_group(bot: Bot, channel_id: int) -> int | None:
    """Находит ID группы обсуждений, привязанной к каналу, и сохраняет в meta."""
    try:
        chat = await bot.get_chat(channel_id)
    except TelegramAPIError as exc:
        logger.warning("Не удалось получить канал %s: %s", channel_id, exc.message)
        return None
    group_id = getattr(chat, "linked_chat_id", None)
    if not group_id:
        logger.warning("У канала %s нет привязанной группы обсуждений", channel_id)
        return None
    await repo.set_meta("comments_group_id", str(group_id))
    return group_id


async def comments_resolver_loop(bot: Bot, poll_seconds: int = 60) -> None:
    """Фоновая задача: следит за comments_channel_id из админ-панели и подтягивает
    ID привязанной группы обсуждений (comments_group_id), как только он меняется."""
    last_seen = None
    while True:
        try:
            channel_id_raw = await repo.get_meta("comments_channel_id", "")
            channel_id = int(channel_id_raw) if channel_id_raw and channel_id_raw.lstrip("-").isdigit() else 0
            if channel_id and channel_id != last_seen:
                group_id = await resolve_comments_group(bot, channel_id)
                if group_id:
                    last_seen = channel_id
                    logger.info("Анон-комментарии: канал %s -> группа обсуждений %s", channel_id, group_id)
        except Exception:
            logger.exception("Ошибка в comments_resolver_loop")
        await asyncio.sleep(poll_seconds)


@router.message(F.is_automatic_forward == True)  # noqa: E712
async def on_channel_autoforward(message: Message) -> None:
    """Авто-пересланный пост настроенного канала в группе обсуждений -> кнопка-диплинк."""
    channel_id_raw = await repo.get_meta("comments_channel_id", "0")
    channel_id = int(channel_id_raw or 0)
    if not channel_id or not message.forward_from_chat or message.forward_from_chat.id != channel_id:
        return
    bot_username = (await message.bot.me()).username
    token = secrets.token_urlsafe(8)
    await repo.save_anon_comment_target(token, message.chat.id, message.message_id)
    url = f"https://t.me/{bot_username}?start=cmt_{token}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[ibtn("Написать анонимный комментарий", "chat", url=url)]])
    await message.reply(f"{e('chat')} Оставьте анонимный комментарий к этому посту:", reply_markup=kb)


@router.message(CommandStart(deep_link=True))
async def start_deeplink(message: Message, command: CommandObject) -> None:
    payload = command.args or ""
    if not payload.startswith("cmt_"):
        await message.answer(f"{e('info')} Привет! Я бот чата. Открывайте меня по ссылке под постом канала, "
                              f"чтобы оставить анонимный комментарий.")
        return
    token = payload[len("cmt_"):]
    target = await repo.get_anon_comment_target(token)
    if target is None:
        await message.answer(f"{e('warn')} Ссылка устарела — попробуйте открыть её заново под постом.")
        return
    _pending[message.from_user.id] = token
    await message.answer(
        f"{e('chat')} Напишите текст анонимного комментария одним сообщением — я опубликую его под постом "
        f"без указания вашего имени. Чтобы передумать, напишите /cancel.",
    )


@router.message(CommandStart())
async def start_plain(message: Message) -> None:
    await message.answer(f"{e('info')} Привет! Я бот чата. Открывайте меня по ссылке под постом канала, "
                          f"чтобы оставить анонимный комментарий.")


@router.message(F.chat.type == "private", F.text == "/cancel")
async def cancel_comment(message: Message) -> None:
    if _pending.pop(message.from_user.id, None) is not None:
        await message.answer(f"{e('check')} Отменено.")


@router.message(F.chat.type == "private", F.text, F.from_user.id.func(lambda uid: uid in _pending))
async def receive_comment_text(message: Message) -> None:
    token = _pending.pop(message.from_user.id, None)
    if token is None:
        return
    target = await repo.get_anon_comment_target(token)
    if target is None:
        await message.answer(f"{e('warn')} Ссылка устарела — попробуйте открыть её заново под постом.")
        return
    text = message.text.strip()
    if not text:
        await message.answer(f"{e('warn')} Пустой комментарий не отправлен.")
        return
    try:
        await message.bot.send_message(
            target["group_chat_id"],
            f"{e('person')} <b>Аноним:</b>\n{esc(text)}",
            reply_to_message_id=target["group_message_id"],
            allow_sending_without_reply=True,
        )
    except TelegramAPIError as exc:
        logger.warning("Не удалось опубликовать анон-комментарий: %s", exc.message)
        await message.answer(f"{e('alert')} Не получилось опубликовать комментарий — попробуйте позже.")
        return
    await message.answer(f"{e('check')} Комментарий опубликован анонимно.")
