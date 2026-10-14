"""Переключатель оформления для конкретного человека.

стараяверсия — на сообщения этого человека бот отвечает обычным форматированием (без таблиц
Rich Messages) — на случай, если у него старый клиент Telegram и таблицы не отображаются.
новаяверсия  — снова Rich-оформление (нативные таблицы).
Настройка хранится в базе и переживает перезапуск бота. Действует на ответы бота
ЕМУ (его командам); чужие команды остаются в оформлении, выбранном их авторами.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot import repo
from bot.config import settings
from bot.emojis import e
from bot.rich import answer_rich, rtable

router = Router(name="richmode")


@router.message(F.text.regexp(r"(?i)^старая\s*версия\s*$"))
async def old_version(message: Message) -> None:
    await repo.set_rich_pref(message.from_user.id, False)
    await message.reply(
        f"{e('check')} <b>Старая версия</b>: на ваши сообщения я отвечаю обычным форматированием, "
        f"без таблиц Rich Messages.\nВернуть новое оформление: <code>новаяверсия</code>"
    )


@router.message(F.text.regexp(r"(?i)^новая\s*версия\s*$"))
async def new_version(message: Message) -> None:
    await repo.set_rich_pref(message.from_user.id, True)
    if not settings.rich_messages:
        await message.reply(
            f"{e('warn')} Режим сохранён, но Rich-сообщения сейчас выключены администратором бота "
            f"(<code>RICH_MESSAGES=0</code>) — пока отвечаю обычным форматированием."
        )
        return
    intro = (
        f"{e('check')} <b>Новая версия</b>: отвечаю Rich-форматированием.\n"
        "Если ниже вы видите таблицу — всё работает. Если вместо неё что-то странное, "
        "обновите Telegram или напишите <code>стараяверсия</code>.\n"
    )
    demo = [["<code>стараяверсия</code>", "обычное оформление"], ["<code>новаяверсия</code>", "таблицы и Rich-текст"]]
    await answer_rich(
        message, intro + rtable(["Команда", "Режим"], demo),
        fallback=intro + "<code>стараяверсия</code> — обычное оформление\n<code>новаяверсия</code> — таблицы и Rich-текст",
    )
