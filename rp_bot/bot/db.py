"""
Общая SQLite база для бота и админ-панели (они читают/пишут один и тот же файл).
Используем aiosqlite в боте (asyncio) и sqlite3 в FastAPI (синхронно, запросы короткие).
"""
from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

from bot.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    role TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    warns INTEGER NOT NULL DEFAULT 0,
    banned INTEGER NOT NULL DEFAULT 0,
    muted_until TEXT,
    joined_at TEXT,
    messages_total INTEGER NOT NULL DEFAULT 0,
    messages_month INTEGER NOT NULL DEFAULT 0,
    messages_week INTEGER NOT NULL DEFAULT 0,
    messages_day INTEGER NOT NULL DEFAULT 0,
    day_stamp TEXT,
    week_stamp TEXT,
    month_stamp TEXT,
    last_activity_at TEXT
);

CREATE TABLE IF NOT EXISTS coins (
    user_id INTEGER PRIMARY KEY,
    red_coins INTEGER NOT NULL DEFAULT 0,
    last_farm_at TEXT
);

-- отношения / брак / брак по расчету между двумя пользователями чата
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id INTEGER NOT NULL,
    user2_id INTEGER NOT NULL,
    rel_type TEXT NOT NULL,              -- 'relationship' | 'marriage' | 'marriage_of_convenience'
    blood_drops INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'ended'
    started_at TEXT,
    ended_at TEXT,
    ended_reason TEXT,
    last_activity_at TEXT
);

-- заявки на отношения/брак ("мутки")
CREATE TABLE IF NOT EXISTS relationship_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    rel_type TEXT NOT NULL,
    created_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' -- 'pending'|'accepted'|'declined'|'cancelled'
);

-- админ-настраиваемые команды пополнения капель крови / прокачки отношений
-- (напр. "пригласить на свидание" -> +40 капель, кд 2ч; "привет" -> rp-шаблон "{1} поприветствовал {2}")
CREATE TABLE IF NOT EXISTS blood_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL UNIQUE,     -- текст команды, напр. "свидание"
    template TEXT NOT NULL DEFAULT '', -- rp-текст, {1} и {2} заменяются на упоминания
    amount INTEGER NOT NULL DEFAULT 10,
    cooldown_sec INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS blood_command_cooldowns (
    command_id INTEGER NOT NULL,
    pair_key TEXT NOT NULL,   -- "min_id:max_id"
    last_used_at TEXT NOT NULL,
    PRIMARY KEY (command_id, pair_key)
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    text TEXT NOT NULL DEFAULT 'Правила ещё не заданы.',
    updated_at TEXT,
    broadcasted INTEGER NOT NULL DEFAULT 1  -- 0 = ждёт автопостинга в чат
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    level TEXT NOT NULL DEFAULT 'admin'  -- 'admin' | 'senior'
);

-- отдельные "тающие" варны (снимаются автоматически по истечении срока)
CREATE TABLE IF NOT EXISTS warn_expiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);

-- очередь действий модерации, поставленных из админ-панели (панель не может сама
-- дёргать Telegram Bot API, поэтому только пишет намерение сюда, а бот исполняет)
CREATE TABLE IF NOT EXISTS mod_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,      -- 'warn' | 'mute' | 'ban' | 'unmute' | 'unban'
    duration_sec INTEGER,      -- для mute
    reason TEXT,
    by_admin INTEGER,
    created_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0
);

-- персональные настройки: rich=0 — «старая версия» (отвечать этому человеку без Rich Messages)
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY,
    rich INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- свободные RP-команды: работают вне отношений, ничего не начисляют ("ударить" -> "{1} ударил {2}")
CREATE TABLE IF NOT EXISTS rp_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL UNIQUE,
    template TEXT NOT NULL DEFAULT '',
    variants TEXT NOT NULL DEFAULT '',   -- несколько вариантов, по одному на строку: выбирается случайный
    enabled INTEGER NOT NULL DEFAULT 1
);

-- репорты (жалобы) участников на других участников
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    chat_id INTEGER,
    message_id INTEGER,            -- сообщение, на которое пожаловались
    reason TEXT,
    snippet TEXT,                  -- начало текста сообщения-нарушения
    status TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'resolved' | 'rejected'
    action TEXT,                   -- что сделали: warn/mute/ban/delete/none
    handled_by INTEGER,
    created_at TEXT,
    handled_at TEXT,
    post_chat_id INTEGER,          -- где опубликован репорт для модераторов
    post_message_id INTEGER
);

-- где лежит копия репорта у каждого модератора (личка) — нужно, чтобы обновить их все после решения
CREATE TABLE IF NOT EXISTS report_deliveries (
    report_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (report_id, chat_id, message_id)
);

-- баны по ID, которых Telegram пока не видит (человек ещё не писал в чат и не заходил);
-- применяются при первом появлении в чате
CREATE TABLE IF NOT EXISTS pending_bans (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    by_admin INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS mod_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,   -- 'warn'|'mute'|'ban'|'unmute'|'unban'
    reason TEXT,
    by_admin INTEGER,
    created_at TEXT
);
"""


DEFAULT_RP = [
    ("ударить", "{1} ударил {2}"),
    ("обнять", "{1} обнял {2}"),
    ("поцеловать", "{1} поцеловал {2}"),
    ("погладить", "{1} погладил {2} по голове"),
    ("пнуть", "{1} пнул {2}"),
    ("укусить", "{1} укусил {2}"),
    ("шлёпнуть", "{1} шлёпнул {2}"),
    ("пожать руку", "{1} пожал руку {2}"),
    ("дать пять", "{1} дал пять {2}"),
    ("подмигнуть", "{1} подмигнул {2}"),
]


async def init_db() -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(SCHEMA)
        await db.execute(
            "INSERT OR IGNORE INTO rules (id, text, broadcasted) VALUES (1, 'Правила ещё не заданы.', 1)"
        )
        # миграция: старые базы получают колонку variants
        cur = await db.execute("PRAGMA table_info(rp_commands)")
        if "variants" not in [r[1] for r in await cur.fetchall()]:
            await db.execute("ALTER TABLE rp_commands ADD COLUMN variants TEXT NOT NULL DEFAULT ''")
        # стартовый набор свободных RP-команд — один раз; удалённые потом не возвращаются
        cur = await db.execute("SELECT value FROM meta WHERE key='rp_seeded'")
        if await cur.fetchone() is None:
            await db.executemany(
                "INSERT OR IGNORE INTO rp_commands (trigger, template, enabled) VALUES (?, ?, 1)", DEFAULT_RP
            )
            await db.execute("INSERT INTO meta (key, value) VALUES ('rp_seeded', '1')")
        await db.commit()


def sync_db_path() -> str:
    return settings.db_path
