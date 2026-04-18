from aiogram import Dispatcher

from bot.handlers.start import router as start_router
from bot.handlers.language import router as language_router
from bot.handlers.subscription import router as subscription_router
from bot.handlers.access_demo import router as access_demo_router
from bot.handlers.instruction import router as instruction_router
from bot.handlers.support import router as support_router
from bot.handlers.debug import router as debug_router


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(language_router)
    dp.include_router(subscription_router)
    dp.include_router(access_demo_router)
    dp.include_router(instruction_router)
    dp.include_router(support_router)
    dp.include_router(debug_router)
