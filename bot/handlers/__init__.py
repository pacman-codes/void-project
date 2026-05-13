from aiogram import Dispatcher

from config.runtime import DEV_MODE

from bot.handlers.start import router as start_router
from bot.handlers.language import router as language_router
from bot.handlers.subscription import router as subscription_router
from bot.handlers.account import router as account_router
from bot.handlers.instruction import router as instruction_router
from bot.handlers.support import router as support_router
from bot.handlers.referral import router as referral_router
from bot.handlers.admin_tools import router as admin_tools_router


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start_router)
    dp.include_router(admin_tools_router)
    dp.include_router(language_router)
    dp.include_router(subscription_router)
    dp.include_router(account_router)
    dp.include_router(instruction_router)
    dp.include_router(support_router)
    dp.include_router(referral_router)

    if DEV_MODE:
        from bot.handlers.dev_tools import router as dev_tools_router

        dp.include_router(dev_tools_router)
