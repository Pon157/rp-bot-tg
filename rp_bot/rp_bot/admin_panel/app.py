"""
Веб-панель для старшей администрации.

Запуск отдельно от бота (использует ту же базу sqlite):
    uvicorn admin_panel.app:app --host 0.0.0.0 --port 8080

Доступ:
- по желанию ограничивается списком IP (ADMIN_PANEL_ALLOWED_IPS в .env) —
  тогда «просто подключаться по IP сервера» и есть контроль доступа;
- плюс отдельный секретный код входа (ADMIN_PANEL_SECRET), чтобы страницу
  нельзя было дёргать вслепую, даже если она открыта в интернет.

Технически это самый обычный сайт (Jinja2 + формы), а не Telegram Mini App —
как и предполагалось в ТЗ ("можно даже не мини аппой"). При желании его легко
завернуть в Telegram WebApp позже, подключив telegram-web-app.js и проверку
initData — в коде оставлен соответствующий комментарий в login().
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from bot import repo
from bot.config import settings

BASE_DIR = Path(__file__).resolve().parent
MOD_ACTIONS = {"warn", "unwarn", "mute", "unmute", "ban", "unban", "kick"}

app = FastAPI(title="RP Bot — Админ-панель")
app.add_middleware(SessionMiddleware, secret_key=settings.admin_panel_secret)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.middleware("http")
async def ip_allowlist(request: Request, call_next):
    if settings.admin_panel_allowed_ips:
        client_ip = request.client.host if request.client else ""
        if client_ip not in settings.admin_panel_allowed_ips:
            raise HTTPException(status_code=403, detail="IP не в белом списке")
    return await call_next(request)


def require_login(request: Request) -> RedirectResponse | None:
    if not request.session.get("authed"):
        return RedirectResponse("/login", status_code=303)
    return None


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, secret: str = Form(...)):
    # Примечание: если панель встраивается как Telegram Mini App, здесь вместо
    # секретного кода стоит проверять initData (hash) и user.id из Telegram,
    # сверяя его со списком в таблице admins.
    if secret != settings.admin_panel_secret:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный код доступа"})
    request.session["authed"] = True
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if (r := require_login(request)):
        return r
    log = await repo.recent_mod_log(30)
    open_reports = await repo.count_open_reports()
    return templates.TemplateResponse("dashboard.html", {"request": request, "log": log, "open_reports": open_reports})


@app.get("/user", response_class=HTMLResponse)
async def user_search(request: Request, q: str = ""):
    if (r := require_login(request)):
        return r
    row = None
    if q:
        row = await repo.get_user_by_username(q) if not q.lstrip("-").isdigit() else await repo.get_user(int(q))
    history = await repo.user_mod_log(row["user_id"], 100) if row else []
    return templates.TemplateResponse("user.html", {"request": request, "q": q, "user": row, "history": history})


@app.post("/user/{user_id}/action")
async def user_action(request: Request, user_id: int, action: str = Form(...),
                       reason: str = Form(""), duration_hours: float = Form(1.0)):
    if (r := require_login(request)):
        return r
    if action not in MOD_ACTIONS:
        raise HTTPException(status_code=400, detail="Неизвестное действие")
    # для мута: 0 часов = навсегда (None); для остальных действий срок не нужен
    duration_sec = int(duration_hours * 3600) if action == "mute" and duration_hours > 0 else None
    await repo.enqueue_mod_action(user_id, action, duration_sec, reason, by_admin=None)
    return RedirectResponse(f"/user?q={user_id}", status_code=303)


@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    if (r := require_login(request)):
        return r
    rules = await repo.get_rules()
    return templates.TemplateResponse("rules.html", {"request": request, "rules": rules})


@app.post("/rules")
async def rules_update(request: Request, text: str = Form(...)):
    if (r := require_login(request)):
        return r
    await repo.set_rules(text)
    return RedirectResponse("/rules", status_code=303)


@app.get("/commands", response_class=HTMLResponse)
async def commands_page(request: Request, edit: int = 0):
    if (r := require_login(request)):
        return r
    cmds = await repo.list_all_blood_commands()
    edit_cmd = await repo.get_blood_command_by_id(edit) if edit else None
    return templates.TemplateResponse("commands.html", {"request": request, "commands": cmds, "edit_cmd": edit_cmd})


@app.post("/commands")
async def commands_upsert(
    request: Request, trigger: str = Form(...), template: str = Form(""),
    amount: int = Form(10), cooldown_sec: int = Form(0), enabled: str = Form(""), command_id: str = Form(""),
):
    if (r := require_login(request)):
        return r
    trigger = trigger.strip().casefold()
    if not trigger or " " in trigger:
        raise HTTPException(status_code=400, detail="Триггер — одно слово без пробелов")
    try:
        if command_id.strip():
            await repo.update_blood_command(int(command_id), trigger, template, amount, cooldown_sec, enabled == "on")
        else:
            if any(c["trigger"] == trigger for c in await repo.list_all_blood_commands()):
                raise HTTPException(status_code=400, detail=f"Команда «{trigger}» уже есть — откройте её и нажмите «изменить»")
            await repo.upsert_blood_command(trigger, template, amount, cooldown_sec, enabled == "on")
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Команда с таким триггером уже есть")
    return RedirectResponse("/commands", status_code=303)


@app.post("/commands/{command_id}/delete")
async def commands_delete(request: Request, command_id: int):
    if (r := require_login(request)):
        return r
    await repo.delete_blood_command(command_id)
    return RedirectResponse("/commands", status_code=303)


@app.get("/admins", response_class=HTMLResponse)
async def admins_page(request: Request):
    if (r := require_login(request)):
        return r
    admins = await repo.list_admins()
    return templates.TemplateResponse("admins.html", {"request": request, "admins": admins})


@app.post("/admins")
async def admins_add(request: Request, user_id: int = Form(...), level: str = Form("admin")):
    if (r := require_login(request)):
        return r
    await repo.set_admin(user_id, level)
    return RedirectResponse("/admins", status_code=303)


@app.post("/admins/{user_id}/delete")
async def admins_remove(request: Request, user_id: int):
    if (r := require_login(request)):
        return r
    await repo.remove_admin(user_id)
    return RedirectResponse("/admins", status_code=303)


# ------------------------------------------------------------- репорты ----

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, status: str = "open"):
    if (r := require_login(request)):
        return r
    if status not in ("open", "resolved", "rejected", "all"):
        status = "open"
    reports = await repo.list_reports(status)
    return templates.TemplateResponse("reports.html", {"request": request, "reports": reports, "status": status})


@app.post("/reports/{report_id}/action")
async def report_action(request: Request, report_id: int, action: str = Form(...)):
    """warn / mute / ban — ставят наказание в очередь бота и закрывают репорт;
    resolve — закрыть без наказания; reject — отклонить."""
    if (r := require_login(request)):
        return r
    report = await repo.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Репорт не найден")
    if action in ("warn", "mute", "ban"):
        reason = f"репорт #{report_id}: {report['reason'] or '—'}"
        await repo.enqueue_mod_action(report["target_id"], action, 3600 if action == "mute" else None, reason, None)
        await repo.close_report(report_id, "resolved", action, None)
    elif action == "resolve":
        await repo.close_report(report_id, "resolved", "ok", None)
    elif action == "reject":
        await repo.close_report(report_id, "rejected", "no", None)
    else:
        raise HTTPException(status_code=400, detail="Неизвестное действие")
    return RedirectResponse("/reports", status_code=303)


# ------------------------------------------------ свободные RP-команды ----

@app.get("/rp", response_class=HTMLResponse)
async def rp_page(request: Request, edit: int = 0):
    if (r := require_login(request)):
        return r
    cmds = await repo.list_rp_commands(enabled_only=False)
    edit_cmd = await repo.get_rp_command(edit) if edit else None
    return templates.TemplateResponse("rp.html", {"request": request, "commands": cmds, "edit_cmd": edit_cmd})


@app.post("/rp")
async def rp_upsert(request: Request, trigger: str = Form(...), template: str = Form(""),
                    variants: str = Form(""), enabled: str = Form(""), command_id: str = Form("")):
    if (r := require_login(request)):
        return r
    trigger = " ".join(trigger.strip().casefold().split())
    opts = [v.strip() for v in variants.splitlines() if v.strip()]
    if not opts and template.strip():
        opts = [template.strip()]
    if not trigger or not opts:
        raise HTTPException(status_code=400, detail="Нужен триггер и хотя бы один вариант (шаблон или список)")
    for o in opts:
        if "{1}" not in o or "{2}" not in o:
            raise HTTPException(status_code=400, detail=f"В варианте должны быть {{1}} и {{2}}: «{o}»")
    variants_value = "\n".join(opts) if len(opts) > 1 else ""
    try:
        if command_id.strip():
            await repo.update_rp_command(int(command_id), trigger, template.strip(), variants_value, enabled == "on")
        else:
            if any(c["trigger"] == trigger for c in await repo.list_rp_commands(enabled_only=False)):
                raise HTTPException(status_code=400, detail=f"Команда «{trigger}» уже есть — откройте её и нажмите «изменить»")
            await repo.upsert_rp_command(trigger, template.strip(), enabled == "on", variants_value)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Команда с таким триггером уже есть")
    return RedirectResponse("/rp", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str = ""):
    if (r := require_login(request)):
        return r
    values = {
        "amount": await repo.get_meta("blood_decay_amount", "0"),
        "hours": await repo.get_meta("blood_decay_hours", "24"),
        "spam_enabled": (await repo.get_meta("spam_enabled", "0")) == "1",
        "spam_max": await repo.get_meta("spam_max_messages", "6"),
        "spam_window": await repo.get_meta("spam_window_sec", "10"),
        "spam_mute": await repo.get_meta("spam_mute_minutes", "10"),
    }
    return templates.TemplateResponse("settings.html", {"request": request, "values": values, "saved": saved})


@app.post("/settings/spam")
async def spam_save(request: Request, spam_enabled: str = Form(""), spam_max_messages: int = Form(6),
                    spam_window_sec: int = Form(10), spam_mute_minutes: int = Form(10)):
    if (r := require_login(request)):
        return r
    if spam_max_messages < 2 or spam_window_sec < 1 or spam_mute_minutes < 1:
        raise HTTPException(status_code=400,
                            detail="Сообщений — от 2, окно — от 1 сек, мут — от 1 мин")
    await repo.set_meta("spam_enabled", "1" if spam_enabled == "on" else "0")
    await repo.set_meta("spam_max_messages", str(spam_max_messages))
    await repo.set_meta("spam_window_sec", str(spam_window_sec))
    await repo.set_meta("spam_mute_minutes", str(spam_mute_minutes))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings")
async def settings_save(request: Request, blood_decay_amount: int = Form(0), blood_decay_hours: float = Form(24)):
    if (r := require_login(request)):
        return r
    if blood_decay_amount < 0 or blood_decay_hours <= 0:
        raise HTTPException(status_code=400, detail="Капли не могут быть отрицательными, период больше нуля")
    await repo.set_meta("blood_decay_amount", str(blood_decay_amount))
    await repo.set_meta("blood_decay_hours", str(blood_decay_hours))
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/rp/{command_id}/delete")
async def rp_delete(request: Request, command_id: int):
    if (r := require_login(request)):
        return r
    await repo.delete_rp_command(command_id)
    return RedirectResponse("/rp", status_code=303)
