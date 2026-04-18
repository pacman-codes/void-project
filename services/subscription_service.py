from datetime import datetime, timedelta

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User


async def activate_paid_for_user(
    user_id: int,
    duration_days: int,
    promo_code: str | None = None,
) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден"

        now = datetime.utcnow()
        current_expiry = user.subscription_expiry

        if current_expiry and current_expiry > now:
            base_date = current_expiry
        else:
            base_date = now

        user.subscription_expiry = base_date + timedelta(days=duration_days)
        user.is_active = True
        user.access_type = "paid"

        if user.device_limit is None or user.device_limit < 2:
            user.device_limit = 2

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0

        if promo_code:
            user.promo_applied = True
            user.promo_type = promo_code

        await session.commit()

    return True, "OK"


async def activate_extra_device_for_user(user_id: int, devices_to_add: int = 1) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден"

        if user.access_type != "paid":
            return False, "Дополнительные устройства доступны только на полном доступе"

        if devices_to_add <= 0:
            return False, "Некорректное количество устройств"

        current_limit = user.device_limit or 2
        user.device_limit = current_limit + devices_to_add

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0

        await session.commit()

    return True, "OK"
