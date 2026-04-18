from datetime import datetime

from sqlalchemy import select

from db.database import async_session
from db.models import User

DEFAULT_LANGUAGE = "ru"
DEFAULT_TRAFFIC_LIMIT_MB = 3072
DEFAULT_FREE_DEVICE_LIMIT = 1


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def create_user(telegram_id: int, username: str | None) -> User:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user:
            return user

        new_user = User(
            telegram_id=telegram_id,
            username=username,
            language=DEFAULT_LANGUAGE,
            created_at=datetime.utcnow(),
            subscription_expiry=None,
            traffic_used=0,
            traffic_limit=DEFAULT_TRAFFIC_LIMIT_MB,
            trial_used=False,
            is_active=False,
            access_type=None,
            terms_accepted=False,
            terms_accepted_at=None,
            payment_status=None,
            payment_id=None,
            device_limit=DEFAULT_FREE_DEVICE_LIMIT,
            used_devices=0,
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        return new_user


async def get_or_create_user(telegram_id: int, username: str | None) -> User:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                language=DEFAULT_LANGUAGE,
                created_at=datetime.utcnow(),
                subscription_expiry=None,
                traffic_used=0,
                traffic_limit=DEFAULT_TRAFFIC_LIMIT_MB,
                trial_used=False,
                is_active=False,
                access_type=None,
                terms_accepted=False,
                terms_accepted_at=None,
                payment_status=None,
                payment_id=None,
                device_limit=DEFAULT_FREE_DEVICE_LIMIT,
                used_devices=0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

        changed = False

        if user.username != username:
            user.username = username
            changed = True

        if not user.language:
            user.language = DEFAULT_LANGUAGE
            changed = True

        if user.traffic_used is None:
            user.traffic_used = 0
            changed = True

        if user.traffic_limit is None:
            user.traffic_limit = DEFAULT_TRAFFIC_LIMIT_MB
            changed = True

        if user.access_type not in {"free", "paid", None}:
            user.access_type = None
            changed = True

        if user.device_limit is None or user.device_limit <= 0:
            user.device_limit = DEFAULT_FREE_DEVICE_LIMIT
            changed = True

        if user.used_devices is None or user.used_devices < 0:
            user.used_devices = 0
            changed = True

        if changed:
            await session.commit()
            await session.refresh(user)

        return user


async def set_language(telegram_id: int, language: str) -> User | None:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return None

        user.language = language
        await session.commit()
        await session.refresh(user)

        return user


async def get_user_info(telegram_id: int) -> dict | None:
    user = await get_user(telegram_id)

    if not user:
        return None

    return {
        "expiry": user.subscription_expiry,
        "traffic_used": user.traffic_used,
        "traffic_limit": user.traffic_limit,
        "trial_used": user.trial_used,
        "is_active": user.is_active,
        "language": user.language,
        "access_type": user.access_type,
        "terms_accepted": user.terms_accepted,
        "payment_status": user.payment_status,
        "payment_id": user.payment_id,
        "device_limit": user.device_limit,
        "used_devices": user.used_devices,
    }


async def is_subscription_active(telegram_id: int) -> bool:
    user = await get_user(telegram_id)

    if not user:
        return False

    if not user.subscription_expiry:
        return False

    return user.subscription_expiry > datetime.utcnow()
