from datetime import datetime

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User


async def get_terms_status(telegram_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User.terms_accepted).where(User.telegram_id == telegram_id)
        )
        value = result.scalar_one_or_none()
        return bool(value)


async def accept_terms_for_user(telegram_id: int) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден."

        if user.terms_accepted:
            return True, "Условия уже приняты."

        user.terms_accepted = True
        user.terms_accepted_at = datetime.utcnow()

        await session.commit()

        return True, "Условия приняты."
