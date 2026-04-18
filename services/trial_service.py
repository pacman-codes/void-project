from sqlalchemy import select

from db.database import async_session_maker
from db.models import User


FREE_TRAFFIC_LIMIT_GB = 3
FREE_DEVICE_LIMIT = 1


async def activate_trial_for_user(telegram_id: int) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден."

        user.trial_used = False
        user.subscription_expiry = None
        user.is_active = True
        user.access_type = "free"
        user.traffic_limit = FREE_TRAFFIC_LIMIT_GB * 1024
        user.traffic_used = 0

        await session.commit()

        return True, "Бесплатный доступ активирован."
