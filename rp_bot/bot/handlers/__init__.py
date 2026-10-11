from aiogram import Router

from . import farm, fun, modcmds, profile, relationships, reports, richmode, rpfree, rules
from .games import games_router

root_router = Router(name="root")

# Порядок важен: точные команды раньше, «широкие» фильтры (команды отношений и
# свободные RP-команды из админ-панели) — в самом конце.
root_router.include_router(profile.router)
root_router.include_router(rules.router)
root_router.include_router(farm.router)
root_router.include_router(games_router)
root_router.include_router(modcmds.router)
root_router.include_router(reports.router)
root_router.include_router(richmode.router)
root_router.include_router(fun.router)
root_router.include_router(relationships.router)
root_router.include_router(rpfree.router)
