"""Запуск админ-панели (FastAPI + uvicorn) в том же процессе и том же event loop, что и бот.

Отдельно запускать `uvicorn admin_panel.app:app` больше не нужно — `python -m bot.main`
поднимает и бота, и панель. Выключить панель: ADMIN_PANEL_ENABLED=0 в .env.
Панель никогда не роняет бота: если порт занят или что-то пошло не так — в логе ошибка,
бот продолжает работать.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn

from bot.config import settings

logger = logging.getLogger("rp_bot.panel")


class _PanelServer(uvicorn.Server):
    """uvicorn не должен перехватывать SIGINT/SIGTERM — ими управляет aiogram,
    иначе Ctrl+C / `pm2 stop` остановят только что-то одно."""

    def install_signal_handlers(self) -> None:      # старые версии uvicorn
        pass

    @contextlib.contextmanager
    def capture_signals(self):                      # новые версии uvicorn
        yield


async def start_panel() -> tuple[_PanelServer, asyncio.Task] | None:
    if not settings.admin_panel_enabled:
        logger.info("Админ-панель выключена (ADMIN_PANEL_ENABLED=0)")
        return None
    try:
        from admin_panel.app import app
    except Exception:
        logger.exception("Не удалось загрузить админ-панель — бот работает без неё")
        return None

    config = uvicorn.Config(app, host=settings.admin_panel_host, port=settings.admin_panel_port,
                            log_level="info", access_log=False)
    server = _PanelServer(config)

    async def runner() -> None:
        try:
            await server.serve()
        except SystemExit:
            # uvicorn делает sys.exit(1), если не смог занять порт — не даём этому убить бота
            logger.error("Админ-панель не запустилась: порт %s занят? (возможно, ещё работает старый "
                         "`uvicorn admin_panel.app:app`). Бот продолжает работать без панели.",
                         settings.admin_panel_port)
        except Exception:
            logger.exception("Админ-панель остановилась с ошибкой")

    task = asyncio.create_task(runner(), name="admin-panel")
    logger.info("Админ-панель: http://%s:%s", settings.admin_panel_host, settings.admin_panel_port)
    return server, task


async def stop_panel(handle: tuple[_PanelServer, asyncio.Task] | None) -> None:
    if handle is None:
        return
    server, task = handle
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
