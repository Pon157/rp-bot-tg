from aiogram import Router

from . import profile, rules, farm, fun, relationships
from .games import games_router

root_router = Router(name="root")

# порядок важен: сначала все "точные" команды, каталог rp-команд (relationships)
# регистрируем последним, т.к. в нём есть широкий (но безопасный, см. BloodCommandFilter) хэндлер
root_router.include_router(profile.router)
root_router.include_router(rules.router)
root_router.include_router(farm.router)
root_router.include_router(games_router)
root_router.include_router(fun.router)
root_router.include_router(relationships.router)
