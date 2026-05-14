from aiogram import Router

from bot.handlers.subscription_parts.menu import router as menu_router
from bot.handlers.subscription_parts.payments import router as payments_router

router = Router()

router.include_router(menu_router)
router.include_router(payments_router)
