from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess


RAW_KEY_GRACE_DAYS = 5


class SubscriptionLinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _user_has_active_access(user: User) -> bool:
    if user.access_type == "free":
        return True

    if user.access_type == "paid":
        return bool(user.subscription_expiry and user.subscription_expiry > _now())

    return False


async def get_or_create_subscription_link(telegram_id: int) -> UserSubscriptionLink:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            raise SubscriptionLinkError("Пользователь не найден")

        link_result = await session.execute(
            select(UserSubscriptionLink).where(
                UserSubscriptionLink.user_id == user.id,
                UserSubscriptionLink.is_active.is_(True),
            )
        )
        link = link_result.scalar_one_or_none()

        if link is not None:
            return link

        for _ in range(5):
            token = _make_token()
            existing_result = await session.execute(
                select(UserSubscriptionLink).where(UserSubscriptionLink.token == token)
            )
            if existing_result.scalar_one_or_none() is None:
                link = UserSubscriptionLink(
                    user_id=user.id,
                    token=token,
                    is_active=True,
                    created_at=_now(),
                )
                session.add(link)
                await session.commit()
                await session.refresh(link)
                return link

        raise SubscriptionLinkError("Не удалось создать уникальную ссылку подписки")


async def build_subscription_by_token(token: str) -> str:
    async with async_session_maker() as session:
        link_result = await session.execute(
            select(UserSubscriptionLink).where(
                UserSubscriptionLink.token == token,
                UserSubscriptionLink.is_active.is_(True),
            )
        )
        link = link_result.scalar_one_or_none()

        if link is None:
            raise SubscriptionLinkError("Подписочная ссылка не найдена или отключена")

        user_result = await session.execute(
            select(User).where(User.id == link.user_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            raise SubscriptionLinkError("Пользователь не найден")

        if not _user_has_active_access(user):
            raise SubscriptionLinkError("Доступ не активен")

        access_result = await session.execute(
            select(VPNAccess)
            .where(
                VPNAccess.user_id == user.id,
                VPNAccess.is_active.is_(True),
            )
            .order_by(VPNAccess.device_number.asc(), VPNAccess.id.asc())
        )
        rows = access_result.scalars().all()
        config_urls = [row.config_url for row in rows if row.config_url]

        if not config_urls:
            raise SubscriptionLinkError("Активные ключи не найдены")

        now = _now()
        link.last_used_at = now

        if link.migrated_at is None:
            link.migrated_at = now
            link.raw_disable_after = now + timedelta(days=RAW_KEY_GRACE_DAYS)

        await session.commit()

        return "\n".join(config_urls) + "\n"


def build_public_subscription_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088")
    return f"{base_url.rstrip('/')}/sub/{token}"
