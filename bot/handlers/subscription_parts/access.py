from sqlalchemy import select

from config.pricing import PARTNER_OFFER_CODE
from db.database import async_session_maker
from db.models import User
from services.access_service import get_access_status
from services.payment_service import (
    get_launch_offer_used_count,
    is_launch_offer_available,
)
from services.vpn_service import VPNService, VPNServiceError

DEFAULT_TRAFFIC_LIMIT_MB = 3072


def get_duration_days(plan_code: str) -> int:
    duration_map = {
        "plan_1m": 30,
        "plan_6m": 180,
        "plan_12m": 365,
    }
    return duration_map.get(plan_code, 30)


async def user_has_any_access(user_id: int) -> tuple[bool, str | None]:
    access = await get_access_status(user_id)
    return access.get("has_access", False), access.get("access_type")


async def get_offer_state() -> tuple[bool, int]:
    used_count = await get_launch_offer_used_count()
    use_launch_offer = await is_launch_offer_available()
    return use_launch_offer, used_count


async def get_partner_offer_state(user_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False

        return bool(
            user.partner_offer_code == PARTNER_OFFER_CODE
            and not user.partner_offer_used
            and user.first_paid_at is None
        )


async def activate_free_for_user(user_id: int) -> tuple[bool, str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False, "Пользователь не найден."

        user.access_type = "free"
        user.is_active = True

        if user.traffic_limit is None:
            user.traffic_limit = DEFAULT_TRAFFIC_LIMIT_MB

        if user.traffic_used is None:
            user.traffic_used = 0

        if user.device_limit is None or user.device_limit <= 0:
            user.device_limit = 1

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0

        await session.commit()

    try:
        service = VPNService()
        await service.ensure_vpn_access_record(
            telegram_id=user_id,
            device_number=1,
            device_name="Устройство 1",
        )
    except VPNServiceError:
        return False, "Не удалось создать ключ. Попробуйте ещё раз позже."
    except Exception:
        return False, "Не удалось создать ключ. Попробуйте ещё раз позже."

    return True, "ok"
