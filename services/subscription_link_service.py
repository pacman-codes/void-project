from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserSubscriptionLink, VPNAccess
from urllib.parse import quote, urlsplit, urlunsplit
import re


RAW_KEY_GRACE_DAYS = 5
DEFAULT_FREE_TRAFFIC_LIMIT_MB = 3072


class SubscriptionLinkError(Exception):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _user_has_active_access(user: User) -> bool:
    if user.access_type == "free":
        traffic_used = max(int(user.traffic_used or 0), 0)
        traffic_limit = int(user.traffic_limit or DEFAULT_FREE_TRAFFIC_LIMIT_MB)
        return bool(user.is_active) and traffic_used < traffic_limit

    if user.access_type == "paid":
        return bool(user.subscription_expiry and user.subscription_expiry > _now())

    return False



def build_public_happ_import_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088").rstrip("/")
    return f"{base_url}/happ/{token}"


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


def _build_subscription_profile_name(user) -> str:
    username = getattr(user, "username", None)
    telegram_id = getattr(user, "telegram_id", None)

    if username:
        raw = str(username).strip().lstrip("@")
    elif telegram_id:
        raw = f"id{telegram_id}"
    else:
        raw = "user"

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-_.")
    if not safe:
        safe = "user"

    return f"void-{safe}"


def _with_subscription_profile_name(config_url: str, profile_name: str) -> str:
    if not config_url.startswith("vless://"):
        return config_url

    parts = urlsplit(config_url)
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        parts.query,
        quote(profile_name, safe="-_."),
    ))


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
            raise SubscriptionLinkError("Подключение не найдена или отключена")

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
                VPNAccess.config_url.is_not(None),
            )
            .order_by(VPNAccess.id.asc())
        )
        rows = list(access_result.scalars().all())

        migration_urls = [
            row.config_url
            for row in rows
            if row.config_url and ":8449" in row.config_url
        ]

        legacy_urls = [
            row.config_url
            for row in rows
            if row.config_url and ":8449" not in row.config_url
        ]

        # Soft migration rule:
        # if the user has a rescue 8449 access, subscription returns only that.
        # old 443 access stays active in DB/panel until a later cleanup step.
        config_urls = migration_urls or legacy_urls
        profile_name = _build_subscription_profile_name(user)
        config_urls = [
            _with_subscription_profile_name(config_url, profile_name)
            for config_url in config_urls
        ]

        if not config_urls:
            raise SubscriptionLinkError("Активные ключи не найдены")

        now = _now()
        link.last_used_at = now

        if link.migrated_at is None:
            link.migrated_at = now
            link.raw_disable_after = now + timedelta(days=RAW_KEY_GRACE_DAYS)

        await session.commit()

        header_lines = [
            "#profile-title: VOID",
            "#subscription-auto-update-enable: 1",
            "#subscription-auto-update-open-enable: 1",
            "#subscription-autoconnect: 1",
            "#subscription-autoconnect-type: lowestdelay",
            "#subscription-ping-onopen-enabled: 1",
            "#subscriptions-expand-now: 1",
            "#ping-result: icon",
        ]

        return "\n".join(header_lines + config_urls) + "\n"


def build_public_subscription_url(token: str) -> str:
    base_url = os.getenv("SUBSCRIPTION_PUBLIC_BASE_URL", "http://127.0.0.1:8088")
    return f"{base_url.rstrip('/')}/sub/{token}"
