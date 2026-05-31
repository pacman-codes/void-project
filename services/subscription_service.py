from datetime import datetime, timedelta

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User
from services.vpn_service import VPNService, VPNServiceError
from services.audit_log_service import log_user_event


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

        user.device_limit = max(user.device_limit or 0, 2)

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0

        if user.first_paid_at is None:
            user.first_paid_at = now

        if user.partner_offer_code and not user.partner_offer_used:
            user.partner_offer_used = True

        if promo_code:
            user.promo_applied = True
            user.promo_type = promo_code

        await session.commit()

    # Legacy raw-key provisioning is disabled.
    # Subscription access is prepared when the user opens the subscription link screen.

    await log_user_event(
        event_type="subscription_paid_activated",
        target_telegram_id=user_id,
        source="subscription_service",
        status="ok",
        message="Paid subscription activated",
        details={
            "duration_days": duration_days,
            "promo_code": promo_code,
        },
    )

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

        new_limit = user.device_limit

        await session.commit()

    await log_user_event(
        event_type="extra_device_activated",
        target_telegram_id=user_id,
        source="subscription_service",
        status="ok",
        message="Extra device activated",
        details={
            "devices_to_add": devices_to_add,
            "new_device_limit": new_limit,
        },
    )

    return True, "OK"
