from aiogram import Router

from . import dice, duel, coinflip, piano

games_router = Router(name="games")
games_router.include_router(dice.router)
games_router.include_router(duel.router)
games_router.include_router(coinflip.router)
games_router.include_router(piano.router)
