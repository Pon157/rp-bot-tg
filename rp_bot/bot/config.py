"""Загрузка настроек бота из переменных окружения / .env"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Переменная окружения {name} обязательна, но не задана (см. .env.example)")
    return val or ""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_chat_id: int
    bot_username: str
    bot_channel_url: str
    db_path: str
    admin_panel_secret: str
    admin_panel_allowed_ips: list[str]
    admin_panel_port: int
    relationship_inactivity_days: int
    max_blood_drops: int = 1000
    farm_cooldown_sec: int = 4 * 60 * 60
    farm_min_coins: int = 1
    farm_max_coins: int = 30
    reports_chat_id: int = 0
    rich_messages: bool = True
    userbot_api_id: int = 0
    userbot_api_hash: str = ""
    admin_panel_enabled: bool = True
    admin_panel_host: str = "0.0.0.0"


def load_settings() -> Settings:
    ips_raw = _env("ADMIN_PANEL_ALLOWED_IPS", "")
    return Settings(
        bot_token=_env("BOT_TOKEN", required=True),
        allowed_chat_id=int(_env("ALLOWED_CHAT_ID", required=True)),
        bot_username=_env("BOT_USERNAME", "my_rp_bot"),
        bot_channel_url=_env("BOT_CHANNEL_URL", "https://t.me/"),
        db_path=_env("DB_PATH", str(ROOT_DIR / "data" / "bot.db")),
        admin_panel_secret=_env("ADMIN_PANEL_SECRET", required=True),
        admin_panel_allowed_ips=[ip.strip() for ip in ips_raw.split(",") if ip.strip()],
        admin_panel_port=int(_env("ADMIN_PANEL_PORT", "8080")),
        relationship_inactivity_days=int(_env("RELATIONSHIP_INACTIVITY_DAYS", "14")),
        reports_chat_id=int(_env("REPORTS_CHAT_ID", "0") or 0),
        userbot_api_id=int(_env("USERBOT_API_ID", "0") or 0),
        userbot_api_hash=_env("USERBOT_API_HASH", ""),
        rich_messages=_env("RICH_MESSAGES", "1").strip().lower() not in ("0", "false", "no", "off"),
        admin_panel_enabled=_env("ADMIN_PANEL_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off"),
        admin_panel_host=_env("ADMIN_PANEL_HOST", "0.0.0.0"),
    )


settings = load_settings()


def reports_chat() -> int:
    """Куда слать репорты: отдельный чат модераторов или основной чат."""
    return settings.reports_chat_id or settings.allowed_chat_id
