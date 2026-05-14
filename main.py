import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config.config import settings
from db.database import init_db
from bot.handlers import register_handlers
from services.expiry_scheduler import maybe_start_paid_expiry_scheduler
from services.traffic_scheduler import maybe_start_traffic_sync_scheduler


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
    traffic_scheduler_task = maybe_start_traffic_sync_scheduler()

    print("Бот запущен 🚀")

    try:
        await dp.start_polling(bot)
    finally:
        tasks = [
            task
            for task in (expiry_scheduler_task, traffic_scheduler_task)
            if task is not None
        ]

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
