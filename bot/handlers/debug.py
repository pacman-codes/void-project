from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import delete, select

from db.database import async_session_maker
from db.models import User, VPNAccess

router = Router()

DEBUG_ALLOWED_IDS = {
    1600207976,
    7596501812,
}


@router.message(Command("reset_profile"))
async def reset_profile(message: Message) -> None:
    if message.from_user.id not in DEBUG_ALLOWED_IDS:
        await message.answer("Эта команда недоступна.")
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            await message.answer(
                "Профиль уже пустой ✅\n\n"
                "Теперь отправьте /start."
            )
            return

        await session.execute(
            delete(VPNAccess).where(VPNAccess.user_id == user.id)
        )

        await session.delete(user)
        await session.commit()

    await message.answer(
        "Профиль удалён ✅\n\n"
        "Теперь отправьте /start и бот покажет себя как для нового пользователя."
    )
