"""Слой доступа к данным. Все функции открывают своё короткое соединение aiosqlite —
для бота такого масштаба это проще и надёжнее, чем держать один общий connection
и гонять его между хэндлерами/задачами."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import aiosqlite

from bot.config import settings

DB_PATH = settings.db_path


def _now() -> str:
    return dt.datetime.utcnow().isoformat()


def _conn():
    """Асинхронный context manager, открывающий соединение и сразу выставляющий
    row_factory. Использование: `async with _conn() as db:` (без await перед _conn()!)."""
    return _ConnCtx()


class _ConnCtx:
    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        # timeout: ждём освобождения базы до 10 с (бот и панель пишут в один файл)
        self._db = await aiosqlite.connect(DB_PATH, timeout=10)
        self._db.row_factory = aiosqlite.Row
        return self._db

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._db.close()


# ---------------------------------------------------------------- users ----

async def touch_user(user_id: int, username: str | None, first_name: str) -> None:
    """Регистрирует пользователя при первом сообщении и обновляет статистику сообщений."""
    now = dt.datetime.utcnow()
    day = now.strftime("%Y-%m-%d")
    week = now.strftime("%Y-%W")
    month = now.strftime("%Y-%m")
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            await db.execute(
                """INSERT INTO users
                (user_id, username, first_name, joined_at, messages_total, messages_month,
                 messages_week, messages_day, day_stamp, week_stamp, month_stamp, last_activity_at)
                VALUES (?, ?, ?, ?, 1, 1, 1, 1, ?, ?, ?, ?)""",
                (user_id, username, first_name, _now(), day, week, month, _now()),
            )
            await db.execute("INSERT OR IGNORE INTO coins (user_id, red_coins) VALUES (?, 0)", (user_id,))
        else:
            day_total = row["messages_day"] + 1 if row["day_stamp"] == day else 1
            week_total = row["messages_week"] + 1 if row["week_stamp"] == week else 1
            month_total = row["messages_month"] + 1 if row["month_stamp"] == month else 1
            await db.execute(
                """UPDATE users SET username=?, first_name=?, messages_total=messages_total+1,
                   messages_day=?, messages_week=?, messages_month=?,
                   day_stamp=?, week_stamp=?, month_stamp=?, last_activity_at=?
                   WHERE user_id=?""",
                (username, first_name, day_total, week_total, month_total, day, week, month, _now(), user_id),
            )
        await db.commit()


async def get_user(user_id: int) -> aiosqlite.Row | None:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()


async def get_user_by_username(username: str) -> aiosqlite.Row | None:
    username = username.lstrip("@")
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,))
        return await cur.fetchone()


async def set_bio(user_id: int, bio: str) -> None:
    async with _conn() as db:
        await db.execute("UPDATE users SET bio=? WHERE user_id=?", (bio, user_id))
        await db.commit()


# ---------------------------------------------------------------- coins ----

async def get_balance(user_id: int) -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT red_coins FROM coins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row["red_coins"] if row else 0


async def add_coins(user_id: int, amount: int) -> int:
    async with _conn() as db:
        await db.execute("INSERT OR IGNORE INTO coins (user_id, red_coins) VALUES (?, 0)", (user_id,))
        await db.execute("UPDATE coins SET red_coins = MAX(0, red_coins + ?) WHERE user_id=?", (amount, user_id))
        cur = await db.execute("SELECT red_coins FROM coins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await db.commit()
        return row["red_coins"]


async def try_take_coins(user_id: int, amount: int) -> bool:
    """Атомарно списывает ставку, если хватает средств."""
    async with _conn() as db:
        cur = await db.execute("SELECT red_coins FROM coins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        balance = row["red_coins"] if row else 0
        if balance < amount:
            return False
        await db.execute("UPDATE coins SET red_coins = red_coins - ? WHERE user_id=?", (amount, user_id))
        await db.commit()
        return True


async def get_last_farm_at(user_id: int) -> dt.datetime | None:
    async with _conn() as db:
        cur = await db.execute("SELECT last_farm_at FROM coins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row["last_farm_at"]:
            return dt.datetime.fromisoformat(row["last_farm_at"])
        return None


async def set_last_farm_now(user_id: int) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO coins (user_id, red_coins, last_farm_at) VALUES (?, 0, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_farm_at=excluded.last_farm_at",
            (user_id, _now()),
        )
        await db.commit()


# --------------------------------------------------------- relationships ----

REL_TYPES = {
    "relationship": "отношения",
    "marriage": "брак",
    "marriage_of_convenience": "брак по расчету",
}


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


async def find_active_relationship(user_a: int, user_b: int, rel_type: str) -> aiosqlite.Row | None:
    a, b = _pair(user_a, user_b)
    async with _conn() as db:
        cur = await db.execute(
            """SELECT * FROM relationships WHERE status='active' AND rel_type=?
               AND ((user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?))""",
            (rel_type, a, b, b, a),
        )
        return await cur.fetchone()


async def list_relationships(user_id: int) -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM relationships WHERE status='active' AND (user1_id=? OR user2_id=?) ORDER BY id",
            (user_id, user_id),
        )
        return await cur.fetchall()


async def create_relationship(user_a: int, user_b: int, rel_type: str) -> int:
    async with _conn() as db:
        cur = await db.execute(
            """INSERT INTO relationships (user1_id, user2_id, rel_type, blood_drops, status, started_at, last_activity_at)
               VALUES (?, ?, ?, 0, 'active', ?, ?)""",
            (user_a, user_b, rel_type, _now(), _now()),
        )
        await db.commit()
        return cur.lastrowid


async def end_relationship(rel_id: int, reason: str) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE relationships SET status='ended', ended_at=?, ended_reason=? WHERE id=?",
            (_now(), reason, rel_id),
        )
        await db.commit()


async def add_blood_drops(rel_id: int, amount: int, max_cap: int) -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT blood_drops FROM relationships WHERE id=?", (rel_id,))
        row = await cur.fetchone()
        new_val = max(0, min(max_cap, row["blood_drops"] + amount))
        await db.execute(
            "UPDATE relationships SET blood_drops=?, last_activity_at=? WHERE id=?", (new_val, _now(), rel_id)
        )
        await db.commit()
        return new_val


async def stale_relationships(rel_type: str, days: int) -> list[aiosqlite.Row]:
    """Пары, у которых хотя бы один участник не писал в чат дольше `days` дней."""
    threshold = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
    async with _conn() as db:
        cur = await db.execute(
            """SELECT r.* FROM relationships r
               LEFT JOIN users u1 ON u1.user_id = r.user1_id
               LEFT JOIN users u2 ON u2.user_id = r.user2_id
               WHERE r.status='active' AND r.rel_type=?
                 AND (COALESCE(u1.last_activity_at, r.started_at) < ?
                      OR COALESCE(u2.last_activity_at, r.started_at) < ?)""",
            (rel_type, threshold, threshold),
        )
        return await cur.fetchall()


async def zero_blood_relationships() -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM relationships WHERE status='active' AND rel_type='relationship' AND blood_drops<=0"
        )
        return await cur.fetchall()


# --------------------------------------------------------- rel. requests ----

async def create_request(from_id: int, to_id: int, rel_type: str) -> int:
    async with _conn() as db:
        cur = await db.execute(
            "INSERT INTO relationship_requests (from_id, to_id, rel_type, created_at, status) VALUES (?, ?, ?, ?, 'pending')",
            (from_id, to_id, rel_type, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_request(req_id: int) -> aiosqlite.Row | None:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM relationship_requests WHERE id=?", (req_id,))
        return await cur.fetchone()


async def set_request_status(req_id: int, status: str) -> None:
    async with _conn() as db:
        await db.execute("UPDATE relationship_requests SET status=? WHERE id=?", (status, req_id))
        await db.commit()


# --------------------------------------------------------- blood commands ----

async def list_blood_commands() -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM blood_commands WHERE enabled=1")
        return await cur.fetchall()


async def get_blood_command(trigger: str) -> aiosqlite.Row | None:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM blood_commands WHERE trigger=? COLLATE NOCASE AND enabled=1", (trigger,)
        )
        return await cur.fetchone()


async def check_and_set_command_cooldown(command_id: int, user_a: int, user_b: int, cooldown_sec: int) -> bool:
    """True если можно использовать (кд прошёл), заодно обновляет отметку времени."""
    a, b = _pair(user_a, user_b)
    key = f"{a}:{b}"
    async with _conn() as db:
        cur = await db.execute(
            "SELECT last_used_at FROM blood_command_cooldowns WHERE command_id=? AND pair_key=?", (command_id, key)
        )
        row = await cur.fetchone()
        if row and cooldown_sec > 0:
            last = dt.datetime.fromisoformat(row["last_used_at"])
            if (dt.datetime.utcnow() - last).total_seconds() < cooldown_sec:
                return False
        await db.execute(
            "INSERT INTO blood_command_cooldowns (command_id, pair_key, last_used_at) VALUES (?, ?, ?) "
            "ON CONFLICT(command_id, pair_key) DO UPDATE SET last_used_at=excluded.last_used_at",
            (command_id, key, _now()),
        )
        await db.commit()
        return True


# --------------------------------------------------------------- rules ----

async def get_rules() -> aiosqlite.Row:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM rules WHERE id=1")
        return await cur.fetchone()


async def mark_rules_broadcasted() -> None:
    async with _conn() as db:
        await db.execute("UPDATE rules SET broadcasted=1 WHERE id=1")
        await db.commit()


# -------------------------------------------------------------- admins ----

async def is_admin(user_id: int) -> str | None:
    async with _conn() as db:
        cur = await db.execute("SELECT level FROM admins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row["level"] if row else None


async def list_admins() -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute(
            """SELECT admins.user_id, admins.level, users.username, users.first_name
               FROM admins LEFT JOIN users ON users.user_id = admins.user_id
               ORDER BY admins.level DESC"""
        )
        return await cur.fetchall()


async def set_admin(user_id: int, level: str) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO admins (user_id, level) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET level=excluded.level",
            (user_id, level),
        )
        await db.commit()


async def remove_admin(user_id: int) -> None:
    async with _conn() as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()


# --------------------------------------------------------------- rules ----

async def set_rules(text: str) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE rules SET text=?, updated_at=?, broadcasted=0 WHERE id=1", (text, _now())
        )
        await db.commit()


# ------------------------------------------------------- blood commands ----

async def list_all_blood_commands() -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM blood_commands ORDER BY id")
        return await cur.fetchall()


async def upsert_blood_command(trigger: str, template: str, amount: int, cooldown_sec: int, enabled: bool) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO blood_commands (trigger, template, amount, cooldown_sec, enabled) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(trigger) DO UPDATE SET template=excluded.template, amount=excluded.amount, "
            "cooldown_sec=excluded.cooldown_sec, enabled=excluded.enabled",
            (trigger, template, amount, cooldown_sec, int(enabled)),
        )
        await db.commit()


async def delete_blood_command(command_id: int) -> None:
    async with _conn() as db:
        await db.execute("DELETE FROM blood_commands WHERE id=?", (command_id,))
        await db.commit()


# --------------------------------------------------------------- search ----

async def recent_mod_log(limit: int = 30) -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM mod_log ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()


# ------------------------------------------------------------- mod log ----

async def add_mod_log(user_id: int, action: str, reason: str, by_admin: int | None) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO mod_log (user_id, action, reason, by_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, reason, by_admin, _now()),
        )
        await db.commit()


async def apply_warn(user_id: int, expires_in_days: int | None = None) -> int:
    async with _conn() as db:
        await db.execute("UPDATE users SET warns = warns + 1 WHERE user_id=?", (user_id,))
        if expires_in_days:
            expires_at = (dt.datetime.utcnow() + dt.timedelta(days=expires_in_days)).isoformat()
            await db.execute(
                "INSERT INTO warn_expiries (user_id, expires_at, processed) VALUES (?, ?, 0)",
                (user_id, expires_at),
            )
        cur = await db.execute("SELECT warns FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await db.commit()
        return row["warns"] if row else 0


async def process_expired_warns() -> list[int]:
    """Снимает по одному варну за каждый истёкший warn_expiries. Возвращает user_id, с кого сняли."""
    now = _now()
    affected: list[int] = []
    async with _conn() as db:
        cur = await db.execute(
            "SELECT id, user_id FROM warn_expiries WHERE processed=0 AND expires_at <= ?", (now,)
        )
        rows = await cur.fetchall()
        for row in rows:
            await db.execute("UPDATE users SET warns = MAX(0, warns - 1) WHERE user_id=?", (row["user_id"],))
            await db.execute("UPDATE warn_expiries SET processed=1 WHERE id=?", (row["id"],))
            affected.append(row["user_id"])
        await db.commit()
    return affected


async def apply_mute(user_id: int, until: dt.datetime) -> None:
    async with _conn() as db:
        await db.execute("UPDATE users SET muted_until=? WHERE user_id=?", (until.isoformat(), user_id))
        await db.commit()


async def apply_ban(user_id: int) -> None:
    async with _conn() as db:
        await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def enqueue_mod_action(user_id: int, action: str, duration_sec: int | None, reason: str, by_admin: int | None) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO mod_queue (user_id, action, duration_sec, reason, by_admin, created_at, processed) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (user_id, action, duration_sec, reason, by_admin, _now()),
        )
        await db.commit()


async def fetch_mod_queue() -> list[aiosqlite.Row]:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM mod_queue WHERE processed=0 ORDER BY id")
        return await cur.fetchall()


async def mark_mod_queue_done(item_id: int) -> None:
    async with _conn() as db:
        await db.execute("UPDATE mod_queue SET processed=1 WHERE id=?", (item_id,))
        await db.commit()


# ======================================================================
#  Добавлено: модерация, репорты, свободные RP-команды, списки
# ======================================================================

FOREVER_ISO = "9999-12-31T00:00:00"


async def get_users_map(ids) -> dict:
    ids = list(set(ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    async with _conn() as db:
        cur = await db.execute(f"SELECT * FROM users WHERE user_id IN ({marks})", ids)
        return {r["user_id"]: r for r in await cur.fetchall()}


async def ensure_user(user_id: int) -> None:
    """Гарантирует строку в users (для наказания человека, который ещё не писал в чат)."""
    # Не ставим joined_at/last_activity_at: человек ещё не писал в чат, и выбирать его в «кто ...» нельзя
    async with _conn() as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute("INSERT OR IGNORE INTO coins (user_id, red_coins) VALUES (?, 0)", (user_id,))
        await db.commit()


async def apply_unwarn(user_id: int) -> int:
    async with _conn() as db:
        await db.execute("UPDATE users SET warns = MAX(0, warns - 1) WHERE user_id=?", (user_id,))
        # снятый вручную варн не должен потом «истечь» ещё раз и съесть чужой варн
        await db.execute(
            "UPDATE warn_expiries SET processed=1 WHERE id = "
            "(SELECT id FROM warn_expiries WHERE user_id=? AND processed=0 ORDER BY expires_at LIMIT 1)",
            (user_id,),
        )
        cur = await db.execute("SELECT warns FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await db.commit()
        return row["warns"] if row else 0


async def clear_mute(user_id: int) -> None:
    async with _conn() as db:
        await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?", (user_id,))
        await db.commit()


async def clear_ban(user_id: int) -> None:
    async with _conn() as db:
        await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
        await db.commit()


async def list_muted() -> list:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM users WHERE muted_until IS NOT NULL AND muted_until > ? ORDER BY muted_until", (_now(),)
        )
        return await cur.fetchall()


async def list_banned() -> list:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM users WHERE banned=1 ORDER BY user_id")
        return await cur.fetchall()


async def user_mod_log(user_id: int, limit: int = 10) -> list:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM mod_log WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return await cur.fetchall()


# ---------------------------------------------------------------- репорты ----

async def create_report(reporter_id: int, target_id: int, chat_id: int, message_id: int | None,
                        reason: str, snippet: str) -> int:
    async with _conn() as db:
        cur = await db.execute(
            """INSERT INTO reports (reporter_id, target_id, chat_id, message_id, reason, snippet, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (reporter_id, target_id, chat_id, message_id, reason, snippet, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def set_report_post(report_id: int, post_chat_id: int, post_message_id: int) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE reports SET post_chat_id=?, post_message_id=? WHERE id=?", (post_chat_id, post_message_id, report_id)
        )
        await db.commit()


async def get_report(report_id: int):
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM reports WHERE id=?", (report_id,))
        return await cur.fetchone()


async def close_report(report_id: int, status: str, action: str, handled_by: int | None) -> bool:
    """Закрывает репорт, только если он ещё открыт (защита от двойной обработки)."""
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE reports SET status=?, action=?, handled_by=?, handled_at=? WHERE id=? AND status='open'",
            (status, action, handled_by, _now(), report_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def last_report_time(reporter_id: int):
    async with _conn() as db:
        cur = await db.execute(
            "SELECT created_at FROM reports WHERE reporter_id=? ORDER BY id DESC LIMIT 1", (reporter_id,)
        )
        row = await cur.fetchone()
        return dt.datetime.fromisoformat(row["created_at"]) if row else None


async def list_reports(status: str = "open", limit: int = 100) -> list:
    async with _conn() as db:
        cur = await db.execute(
            """SELECT r.*, tu.username AS target_username, tu.first_name AS target_name,
                      ru.username AS reporter_username, ru.first_name AS reporter_name
               FROM reports r
               LEFT JOIN users tu ON tu.user_id = r.target_id
               LEFT JOIN users ru ON ru.user_id = r.reporter_id
               WHERE (? = 'all' OR r.status = ?)
               ORDER BY r.id DESC LIMIT ?""",
            (status, status, limit),
        )
        return await cur.fetchall()


async def count_open_reports() -> int:
    async with _conn() as db:
        cur = await db.execute("SELECT COUNT(*) AS c FROM reports WHERE status='open'")
        return (await cur.fetchone())["c"]


# ------------------------------------------------- свободные RP-команды ----

async def list_rp_commands(enabled_only: bool = True) -> list:
    async with _conn() as db:
        sql = "SELECT * FROM rp_commands" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY LENGTH(trigger) DESC, id"
        cur = await db.execute(sql)
        return await cur.fetchall()


async def upsert_rp_command(trigger: str, template: str, enabled: bool, variants: str = "") -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO rp_commands (trigger, template, variants, enabled) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(trigger) DO UPDATE SET template=excluded.template, variants=excluded.variants, "
            "enabled=excluded.enabled",
            (trigger, template, variants, int(enabled)),
        )
        await db.commit()


async def delete_rp_command(command_id: int) -> None:
    async with _conn() as db:
        await db.execute("DELETE FROM rp_commands WHERE id=?", (command_id,))
        await db.commit()


# --------------------------------------------------------- списки пар ----

async def list_active_by_types(types: list[str], order_by_drops: bool = False) -> list:
    marks = ",".join("?" * len(types))
    order = "blood_drops DESC, id" if order_by_drops else "started_at, id"
    async with _conn() as db:
        cur = await db.execute(
            f"SELECT * FROM relationships WHERE status='active' AND rel_type IN ({marks}) ORDER BY {order}", types
        )
        return await cur.fetchall()


async def recent_users(limit: int = 30) -> list:
    """Недавно писавшие в чат — Bot API не отдаёт список всех участников группы."""
    async with _conn() as db:
        cur = await db.execute(
            "SELECT user_id, username, first_name FROM users WHERE banned=0 AND messages_total > 0 "
            "ORDER BY last_activity_at DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()


# ------------------------------------------------- «старая/новая версия» ----

async def get_rich_pref(user_id: int) -> bool:
    """True — отвечать этому человеку Rich-сообщениями (по умолчанию)."""
    async with _conn() as db:
        cur = await db.execute("SELECT rich FROM user_prefs WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return bool(row["rich"]) if row else True


async def set_rich_pref(user_id: int, value: bool) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO user_prefs (user_id, rich) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET rich=excluded.rich",
            (user_id, int(value)),
        )
        await db.commit()


# ------------------------------------------------ доставка репортов модераторам ----

async def admin_user_ids() -> list[int]:
    """Назначенные в панели модераторы (таблица admins)."""
    async with _conn() as db:
        cur = await db.execute("SELECT user_id FROM admins")
        return [r["user_id"] for r in await cur.fetchall()]


async def add_report_delivery(report_id: int, chat_id: int, message_id: int) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT OR IGNORE INTO report_deliveries (report_id, chat_id, message_id) VALUES (?, ?, ?)",
            (report_id, chat_id, message_id),
        )
        await db.commit()


async def list_report_deliveries(report_id: int) -> list:
    async with _conn() as db:
        cur = await db.execute("SELECT chat_id, message_id FROM report_deliveries WHERE report_id=?", (report_id,))
        return await cur.fetchall()


async def last_reasons(user_ids, action: str) -> dict[int, str]:
    """Причина последнего наказания указанного типа (mute/ban) для каждого пользователя."""
    ids = list(set(user_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    async with _conn() as db:
        cur = await db.execute(
            f"SELECT user_id, reason FROM mod_log WHERE action=? AND user_id IN ({marks}) ORDER BY id DESC",
            [action, *ids],
        )
        out: dict[int, str] = {}
        for r in await cur.fetchall():
            out.setdefault(r["user_id"], r["reason"] or "")  # первая строка = самая свежая
        return out


# ------------------------------------------------ настройки (таблица meta) ----

async def get_meta(key: str, default: str | None = None) -> str | None:
    async with _conn() as db:
        cur = await db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default


async def set_meta(key: str, value: str) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        await db.commit()


async def decay_blood(amount: int) -> int:
    """Списывает amount капель со всех активных отношений (не браков). Возвращает число затронутых пар."""
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE relationships SET blood_drops = MAX(0, blood_drops - ?) "
            "WHERE status='active' AND rel_type='relationship'",
            (amount,),
        )
        await db.commit()
        return cur.rowcount


# --------------------------------------------- отложенные баны (по ID) ----

async def add_pending_ban(user_id: int, reason: str, by_admin: int | None) -> None:
    async with _conn() as db:
        await db.execute(
            "INSERT INTO pending_bans (user_id, reason, by_admin, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason, by_admin=excluded.by_admin",
            (user_id, reason, by_admin, _now()),
        )
        await db.commit()


async def pop_pending_ban(user_id: int):
    """Достаёт и удаляет отложенный бан. None, если его нет."""
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM pending_bans WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        await db.execute("DELETE FROM pending_bans WHERE user_id=?", (user_id,))
        await db.commit()
        return row


async def list_pending_bans() -> list:
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM pending_bans ORDER BY created_at")
        return await cur.fetchall()


# --------------------------------------------- редактирование команд ----

async def get_rp_command(command_id: int):
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM rp_commands WHERE id=?", (command_id,))
        return await cur.fetchone()


async def update_rp_command(command_id: int, trigger: str, template: str, variants: str, enabled: bool) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE rp_commands SET trigger=?, template=?, variants=?, enabled=? WHERE id=?",
            (trigger, template, variants, int(enabled), command_id),
        )
        await db.commit()


async def get_blood_command_by_id(command_id: int):
    async with _conn() as db:
        cur = await db.execute("SELECT * FROM blood_commands WHERE id=?", (command_id,))
        return await cur.fetchone()


async def update_blood_command(command_id: int, trigger: str, template: str, amount: int,
                               cooldown_sec: int, enabled: bool) -> None:
    async with _conn() as db:
        await db.execute(
            "UPDATE blood_commands SET trigger=?, template=?, amount=?, cooldown_sec=?, enabled=? WHERE id=?",
            (trigger, template, amount, cooldown_sec, int(enabled), command_id),
        )
        await db.commit()
