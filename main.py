import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config.config import settings
from db.database import init_db
from bot.handlers import register_handlers
from services.expiry_scheduler import maybe_start_paid_expiry_scheduler


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    register_handlers(dp)

    expiry_scheduler_task = maybe_start_paid_expiry_scheduler()

    print("Бот запущен 🚀")

    try:
        await dp.start_polling(bot)
    finally:
        if expiry_scheduler_task is not None:
            expiry_scheduler_task.cancel()
            await asyncio.gather(expiry_scheduler_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
