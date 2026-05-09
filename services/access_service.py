from datetime import datetime, timezone

from services.user_service import get_user

DEFAULT_FREE_TRAFFIC_LIMIT_MB = 3072


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_access_status(telegram_id: int) -> dict:
    user = await get_user(telegram_id)

    if not user:
        return {
            "exists": False,
            "has_access": False,
            "is_free": False,
            "is_paid": False,
            "access_type": None,
            "expiry": None,
            "reason": "user_not_found",
        }

    access_type = user.access_type
    expiry = user.subscription_expiry

    if access_type == "free":
        traffic_used = max(int(user.traffic_used or 0), 0)
        traffic_limit = int(user.traffic_limit or DEFAULT_FREE_TRAFFIC_LIMIT_MB)

        if traffic_used >= traffic_limit:
            return {
                "exists": True,
                "has_access": False,
                "is_free": True,
                "is_paid": False,
                "access_type": "free",
                "expiry": None,
                "reason": "free_traffic_limit",
            }

        if not user.is_active:
            return {
                "exists": True,
                "has_access": False,
                "is_free": True,
                "is_paid": False,
                "access_type": "free",
                "expiry": None,
                "reason": "free_inactive",
            }

        return {
            "exists": True,
            "has_access": True,
            "is_free": True,
            "is_paid": False,
            "access_type": "free",
            "expiry": None,
            "reason": None,
        }

    if access_type == "paid":
        if expiry and expiry > _utcnow_naive():
            return {
                "exists": True,
                "has_access": True,
                "is_free": False,
                "is_paid": True,
                "access_type": "paid",
                "expiry": expiry,
                "reason": None,
            }

        return {
            "exists": True,
            "has_access": False,
            "is_free": False,
            "is_paid": False,
            "access_type": "paid",
            "expiry": expiry,
            "reason": "paid_expired",
        }

    return {
        "exists": True,
        "has_access": False,
        "is_free": False,
        "is_paid": False,
        "access_type": access_type,
        "expiry": expiry,
        "reason": "no_subscription",
    }


async def has_active_access(telegram_id: int) -> bool:
    access = await get_access_status(telegram_id)
    return access["has_access"]


async def get_access_message_key(telegram_id: int) -> str:
    access = await get_access_status(telegram_id)

    if access["access_type"] == "paid" and access["has_access"]:
        return "access_paid"

    if access["access_type"] == "free":
        return "access_free"

    if access["reason"] == "paid_expired":
        return "access_expired"

    return access["reason"]
